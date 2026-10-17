"""考勤记录：点名结果落库、明细修改、导出

和请假的联动只有一处：点名时前端把「当前时刻落在已批准请假区间内」的人自动
记成 leave。判定在前端做，用的是现成的 GET /api/leaves?status=approved
（api/leaves.py），不在这里另开一个「查谁在请假」的接口 —— 那要和请假列表
各写一份区间比较，两份迟早走散；而班委本来就看得见请假列表，权限也对得上。
"""

import io
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AttendanceItem, AttendanceRecord, User
from ..schemas import (
    AttendanceCreate,
    AttendanceItemUpdate,
    AttendanceListResponse,
    AttendanceRecordResponse,
    AttendanceRemarkUpdate,
)
from ..services import display_name, log_operation
from ..services.list_filters import keyword_like
from .deps import committee_required, get_client_ip

router = APIRouter(prefix="/api/attendance", tags=["考勤记录"])

# 状态的中文名。库里存的是英文枚举（present/absent/leave），页面和导出都显示中文
STATUS_LABELS = {"present": "到", "absent": "无应答", "leave": "请假"}

# 导出时写在列上的顺序。备注是这次点名上的一句话，同一批明细的每一行都带同一个值
EXPORT_COLUMNS = ["日期", "范围", "点名时刻", "操作人", "学号", "姓名", "状态", "备注"]


def _counts(items: list[AttendanceItem]) -> dict[str, int]:
    """从明细聚合出各状态人数。

    表里没有计数列，一律现算 —— 改某人状态时不需要再去同步第二份数据。
    """
    result = {"total": len(items), "present": 0, "leave": 0, "absent": 0}
    for item in items:
        if item.status in result:
            result[item.status] += 1
    return result


def _to_response(
    record: AttendanceRecord, items: list[AttendanceItem] | None = None
) -> AttendanceRecordResponse:
    """组装一条记录。列表接口不传 items（只给聚合计数），详情接口才传"""
    data = _counts(items or [])
    return AttendanceRecordResponse(
        id=record.id,
        call_date=record.call_date,
        scope=record.scope or "",
        called_at=record.called_at,
        operator_no=record.operator_no or "",
        operator_name=record.operator_name or "",
        remark=record.remark or "",
        total=data["total"],
        present=data["present"],
        leave=data["leave"],
        absent=data["absent"],
        items=[
            {
                "student_no": i.student_no,
                "student_name": i.student_name or "",
                "status": i.status,
            }
            for i in (items or [])
        ],
    )


def _date_range(query, start: date | None, end: date | None):
    if start:
        query = query.filter(AttendanceRecord.call_date >= start)
    if end:
        query = query.filter(AttendanceRecord.call_date <= end)
    return query


def _summary_detail(scope: str, items: list[AttendanceItem]) -> str:
    """操作日志里那句话。无应答的名字列出来才是可用的信息，其余只报数字"""
    data = _counts(items)
    absent_names = "、".join(
        f"{i.student_name}({i.student_no})" for i in items if i.status == "absent"
    )
    return (
        f"共 {data['total']} 人，实到 {data['present']} 人，"
        f"请假 {data['leave']} 人，无应答 {data['absent']} 人"
        + (f"：{absent_names}" if absent_names else "（全部到齐）")
    )


# ---------- 固定路径必须定义在 /{record_id} 之前 ----------
# 否则 /export 会先撞上 /{record_id} 被当成 record_id 解析，直接 422（本项目已踩过）
@router.get("/export", summary="导出考勤记录（班委及以上）")
def export_attendance(
    start: date | None = Query(None, description="起始日期，含当天"),
    end: date | None = Query(None, description="结束日期，含当天"),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """一个明细一行（某人某次点名的状态），要统计自己在 Excel 里透视"""
    query = _date_range(db.query(AttendanceRecord), start, end)
    records = query.order_by(AttendanceRecord.call_date.desc(), AttendanceRecord.id.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "考勤记录"

    # 表头样式与 generate_excel 保持一致，导出文件看起来是同一套东西
    header_font = Font(bold=True)
    header_fill = PatternFill(start_color="E8F0FE", end_color="E8F0FE", fill_type="solid")
    for col_idx, label in enumerate(EXPORT_COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    row_idx = 2
    for record in records:
        items = (
            db.query(AttendanceItem)
            .filter(AttendanceItem.record_id == record.id)
            .order_by(AttendanceItem.student_no)
            .all()
        )
        for item in items:
            values = [
                record.call_date.strftime("%Y-%m-%d") if record.call_date else "",
                record.scope or "",
                record.called_at.strftime("%Y-%m-%d %H:%M") if record.called_at else "",
                record.operator_name or "",
                item.student_no,
                item.student_name or "",
                STATUS_LABELS.get(item.status, item.status),
                record.remark or "",
            ]
            for col_idx, value in enumerate(values, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.alignment = Alignment(vertical="center")
            row_idx += 1

    # 列宽按表头估就够了：内容是学号/姓名/日期这类定长
    for col_idx, label in enumerate(EXPORT_COLUMNS, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = min(len(label) * 2 + 6, 24)
    # 除了备注 —— 它是唯一的长文本列，按表头估出来的宽度只够显示两三个字
    ws.column_dimensions[get_column_letter(len(EXPORT_COLUMNS))].width = 30
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)

    filename = f"考勤记录_{start or '全部'}_{end or '全部'}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            # HTTP 头只能装 latin-1，中文文件名必须按 RFC 5987 百分号编码，
            # 否则 Starlette 编码响应头时直接抛 UnicodeEncodeError（已踩过）
            "Content-Disposition": "attachment; filename*=utf-8''" + quote(filename),
            "Cache-Control": "no-store",
        },
    )


@router.get("", response_model=AttendanceListResponse, summary="考勤记录列表（班委及以上）")
def list_attendance(
    start: date | None = Query(None, description="起始日期，含当天"),
    end: date | None = Query(None, description="结束日期，含当天"),
    keyword: str | None = Query(None, description="按备注模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """列表只带聚合计数，不带明细（明细走 GET /{record_id}）"""
    query = _date_range(db.query(AttendanceRecord), start, end)
    remark_match = keyword_like(keyword, AttendanceRecord.remark)
    if remark_match is not None:
        query = query.filter(remark_match)
    total = query.count()
    records = (
        query.order_by(AttendanceRecord.call_date.desc(), AttendanceRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 一次分组查询把本页所有记录的计数拿回来，不要每条记录各查一遍
    ids = [r.id for r in records]
    by_record: dict[int, dict[str, int]] = {}
    if ids:
        rows = (
            db.query(AttendanceItem.record_id, AttendanceItem.status, func.count())
            .filter(AttendanceItem.record_id.in_(ids))
            .group_by(AttendanceItem.record_id, AttendanceItem.status)
            .all()
        )
        for record_id, status, count in rows:
            by_record.setdefault(record_id, {})[status] = count

    items = []
    for record in records:
        counts = by_record.get(record.id, {})
        items.append(
            AttendanceRecordResponse(
                id=record.id,
                call_date=record.call_date,
                scope=record.scope or "",
                called_at=record.called_at,
                operator_no=record.operator_no or "",
                operator_name=record.operator_name or "",
                remark=record.remark or "",
                total=sum(counts.values()),
                present=counts.get("present", 0),
                leave=counts.get("leave", 0),
                absent=counts.get("absent", 0),
            )
        )
    return {"total": total, "items": items}


@router.post("", response_model=AttendanceRecordResponse, summary="上报一次点名（班委及以上）")
def create_attendance(
    data: AttendanceCreate,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """点名结束后把每个人的状态落库

    权限沿用列表接口的 committee_required：看得到名单的人才点得了名。
    同时写一条操作日志（action=点名）—— 「谁在什么时候点了谁的名」这件事
    仍然是操作日志的价值所在，只是现在明细也有地方存了。
    """
    seen: set[str] = set()
    for row in data.records:
        if row.student_no in seen:
            raise HTTPException(status_code=400, detail=f"学号 {row.student_no} 重复上报")
        seen.add(row.student_no)

    record = AttendanceRecord(
        call_date=date.today(),
        scope=data.scope,
        called_at=datetime.now(),
        operator_no=user.student_no,
        operator_name=display_name(db, user),
    )
    db.add(record)
    # 先 flush 拿到自增 id，明细要用
    db.flush()

    items = [
        AttendanceItem(
            record_id=record.id,
            student_no=row.student_no,
            student_name=row.name,
            status=row.status,
        )
        for row in data.records
    ]
    db.add_all(items)

    log_operation(
        db,
        user,
        action="点名",
        target=data.scope,
        # log_operation 内部会把 detail 截断到 500 字，这里不用自己处理
        detail=_summary_detail(data.scope, items),
        ip=get_client_ip(request),
        target_student_nos=[row.student_no for row in data.records],
    )
    db.commit()
    db.refresh(record)
    return _to_response(record, items)


@router.get("/{record_id}", response_model=AttendanceRecordResponse, summary="考勤详情（班委及以上）")
def get_attendance(
    record_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """带明细，供「查看明细 / 改状态」的对话框用"""
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="考勤记录不存在")
    items = (
        db.query(AttendanceItem)
        .filter(AttendanceItem.record_id == record_id)
        .order_by(AttendanceItem.student_no)
        .all()
    )
    return _to_response(record, items)


@router.patch(
    "/{record_id}/items/{student_no}",
    response_model=AttendanceRecordResponse,
    summary="改某人状态（班委及以上）",
)
def update_item(
    record_id: int,
    student_no: str,
    data: AttendanceItemUpdate,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """当场点名难免点错，事后要能改回来"""
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="考勤记录不存在")

    item = (
        db.query(AttendanceItem)
        .filter(
            AttendanceItem.record_id == record_id,
            AttendanceItem.student_no == student_no,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="该学生不在这条考勤记录里")
    if item.status == data.status:
        # 没变就不写日志，免得日志里全是「张三：到 → 到」
        return _to_response(record, _items_of(db, record_id))

    before = STATUS_LABELS.get(item.status, item.status)
    after = STATUS_LABELS.get(data.status, data.status)
    item.status = data.status
    log_operation(
        db,
        user,
        action="修改考勤",
        target=f"{record.call_date} {record.scope}",
        detail=f"{item.student_name or ''}({student_no})：{before} → {after}",
        ip=get_client_ip(request),
        target_student_nos=[student_no],
    )
    db.commit()
    return _to_response(record, _items_of(db, record_id))


@router.patch("/{record_id}", response_model=AttendanceRecordResponse, summary="写某次点名的备注（班委及以上）")
def update_remark(
    record_id: int,
    data: AttendanceRemarkUpdate,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """给这一次点名补一句话说明，例如「学院临时集合，迟到 5 人」。

    整条替换、传空即清掉，所以不另开「删除备注」的接口。
    """
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="考勤记录不存在")

    remark = data.remark.strip()
    before = record.remark or ""
    if remark == before:
        # 没变就不写日志，免得日志里全是一模一样的两句话
        return _to_response(record, _items_of(db, record_id))

    if not remark:
        detail = f"清掉「{before}」"
    elif before:
        detail = f"「{before}」→「{remark}」"
    else:
        detail = f"写上「{remark}」"

    record.remark = remark
    log_operation(
        db,
        user,
        action="考勤备注",
        target=f"{record.call_date} {record.scope}",
        detail=detail,
        ip=get_client_ip(request),
        # 不挂 target_student_nos：备注是记在这次点名上的，不属于任何一个学生，
        # 挂上去会让每个人的「被操作记录」里凭空多一条和他无关的事
    )
    db.commit()
    return _to_response(record, _items_of(db, record_id))


@router.delete("/{record_id}", summary="删除一条考勤记录（班委及以上）")
def delete_attendance(
    record_id: int,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """整条删掉（含明细）。点错范围、重复上报时用"""
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="考勤记录不存在")

    items = _items_of(db, record_id)
    log_operation(
        db,
        user,
        action="删除考勤",
        target=f"{record.call_date} {record.scope}",
        detail=_summary_detail(record.scope or "", items),
        ip=get_client_ip(request),
        target_student_nos=[i.student_no for i in items],
    )
    # 先删明细再删主记录：SQLite 默认不开外键约束，靠这里的顺序保证不留孤儿行
    db.query(AttendanceItem).filter(AttendanceItem.record_id == record_id).delete()
    db.delete(record)
    db.commit()
    return {"message": "已删除"}


def _items_of(db: Session, record_id: int) -> list[AttendanceItem]:
    """取一条记录的明细，按学号排（各处返回给前端前都走这个，顺序才一致）"""
    return (
        db.query(AttendanceItem)
        .filter(AttendanceItem.record_id == record_id)
        .order_by(AttendanceItem.student_no)
        .all()
    )
