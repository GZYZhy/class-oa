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
from ..models import AttendanceItem, AttendanceRecord, Checkin, CheckinTarget, User
from ..schemas import (
    AttendanceBatchDelete,
    AttendanceCreate,
    AttendanceItemUpdate,
    AttendanceListResponse,
    AttendanceOverviewItem,
    AttendanceOverviewResponse,
    AttendanceRecordResponse,
    AttendanceRemarkUpdate,
)
from ..services import display_name, log_operation
from ..services.checkin_service import (
    approved_leave_nos,
    checkin_status,
    finalize_due,
    remove_checkin,
    remove_photos,
)
from ..services.list_filters import keyword_like
from ..utils.links import full_url
from .deps import committee_required, get_client_ip

router = APIRouter(prefix="/api/attendance", tags=["考勤记录"])

# 状态的中文名。库里存的是英文枚举（present/absent/leave），页面和导出都显示中文
STATUS_LABELS = {"present": "到", "absent": "无应答", "leave": "请假"}

# 导出时写在列上的顺序。最后一列是这次点名上的一句话（库里仍叫 remark），
# 列表里统一叫「标题」，导出也跟着叫标题；同一批明细的每一行都带同一个值
EXPORT_COLUMNS = ["日期", "范围", "点名时刻", "操作人", "学号", "姓名", "状态", "标题"]

# 签到页签的列。「签到情况」是本人签没签，「出勤状态」是结算后考勤明细里的结果。
# 最后一列是发布时填的「说明」，不叫备注，免得和个人说明混在一起
CHECKIN_EXPORT_COLUMNS = [
    "截止日期", "标题", "发布人", "截止时间", "签到状态",
    "学号", "姓名", "签到情况", "签到时间", "距离(米)", "出勤状态", "说明",
]


def _write_header(ws, columns: list[str]) -> None:
    """两个页签共用一套表头样式，导出文件看起来是同一套东西"""
    font = Font(bold=True)
    fill = PatternFill(start_color="E8F0FE", end_color="E8F0FE", fill_type="solid")
    for col_idx, label in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.font = font
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _fit_columns(ws, columns: list[str]) -> None:
    """列宽按表头估就够了：内容是学号/姓名/日期这类定长。

    除了最后一列 —— 它总是标题 / 说明这类长文本，按表头估只够显示两三个字。
    """
    for col_idx, label in enumerate(columns, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = min(len(label) * 2 + 6, 24)
    ws.column_dimensions[get_column_letter(len(columns))].width = 30
    ws.freeze_panes = "A2"


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


def _checkin_in_range(checkin: Checkin, start: date | None, end: date | None) -> bool:
    """签到的导出日期取「截止那一刻」，与结算生成的考勤记录日期一致"""
    day = (checkin.closed_at or checkin.end_at).date()
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


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
    keyword: str | None = Query(None, description="按点名备注或签到标题模糊搜索"),
    record_ids: list[int] = Query(default=[], description="只导出选中的点名记录"),
    checkin_ids: list[int] = Query(default=[], description="只导出选中的签到"),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """点开导出必须同时拿到点名与签到两种记录，各占一个工作表。

    两种导出方式：

    - 传了 `record_ids` / `checkin_ids`：只导勾选的记录（另一个页签就空着）；
    - 没传：按日期与关键词导出「当前筛选结果」，关键词对点名查备注、
      对签到查标题，和列表页的口径完全一致。

    签到结算出来的那几条本来就在「考勤记录」里（和点名记录同表），
    这里再单列一张「签到记录」，把本人签到时间、距离和请假情况也带上，
    核对时不用两个页签来回翻。
    """
    # 到点的签到先结算，否则导出里会少掉刚结束的那几条
    finalize_due(db)
    selected = bool(record_ids or checkin_ids)
    if selected:
        # 勾选模式：不再套日期与关键词，勾了什么就导什么
        records = (
            db.query(AttendanceRecord)
            .filter(AttendanceRecord.id.in_(record_ids))
            .order_by(AttendanceRecord.call_date.desc(), AttendanceRecord.id.desc())
            .all()
            if record_ids
            else []
        )
        checkins = (
            db.query(Checkin)
            .filter(Checkin.id.in_(checkin_ids))
            .order_by(Checkin.id.desc())
            .all()
            if checkin_ids
            else []
        )
    else:
        query = _date_range(db.query(AttendanceRecord), start, end)
        att_match = keyword_like(keyword, AttendanceRecord.remark)
        if att_match is not None:
            query = query.filter(att_match)
        records = query.order_by(
            AttendanceRecord.call_date.desc(), AttendanceRecord.id.desc()
        ).all()

        chk_query = db.query(Checkin)
        chk_match = keyword_like(keyword, Checkin.title)
        if chk_match is not None:
            chk_query = chk_query.filter(chk_match)
        # 时间范围按「截止日期」算，和考勤记录的日期（结算参考时刻）是同一个口径
        checkins = [
            c for c in chk_query.order_by(Checkin.id.desc()).all()
            if _checkin_in_range(c, start, end)
        ]

    wb = Workbook()
    ws = wb.active
    ws.title = "考勤记录"
    _write_header(ws, EXPORT_COLUMNS)

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
    _fit_columns(ws, EXPORT_COLUMNS)

    # ---------- 第二个页签：签到 ----------
    ws2 = wb.create_sheet("签到记录")
    _write_header(ws2, CHECKIN_EXPORT_COLUMNS)

    row_idx = 2
    for checkin in checkins:
        targets = (
            db.query(CheckinTarget)
            .filter(CheckinTarget.checkin_id == checkin.id)
            .order_by(CheckinTarget.student_no)
            .all()
        )
        reference = checkin.closed_at or checkin.end_at
        leave_nos = approved_leave_nos(db, [t.student_no for t in targets], reference)
        # 结算后以考勤明细为准：明细里手动改过的状态，导出要跟着变
        status_by_no = (
            dict(
                db.query(AttendanceItem.student_no, AttendanceItem.status)
                .filter(AttendanceItem.record_id == checkin.attendance_record_id)
                .all()
            )
            if checkin.attendance_record_id
            else {}
        )
        for target in targets:
            status = status_by_no.get(target.student_no, "")
            values = [
                reference.strftime("%Y-%m-%d") if reference else "",
                checkin.title or "",
                checkin.created_by_name or "",
                checkin.end_at.strftime("%Y-%m-%d %H:%M") if checkin.end_at else "",
                {
                    "pending": "未开始",
                    "ongoing": "进行中",
                    "ended": "已结束",
                }[checkin_status(checkin)],
                target.student_no,
                target.student_name or "",
                "已签到" if target.signed_at else "未签到",
                target.signed_at.strftime("%Y-%m-%d %H:%M") if target.signed_at else "",
                target.distance_m if target.distance_m is not None else "",
                STATUS_LABELS.get(status, status),
                checkin.remark or "",
            ]
            for col_idx, value in enumerate(values, 1):
                cell = ws2.cell(row=row_idx, column=col_idx, value=value)
                cell.alignment = Alignment(vertical="center")
            row_idx += 1
    _fit_columns(ws2, CHECKIN_EXPORT_COLUMNS)

    buf = io.BytesIO()
    wb.save(buf)

    # 勾选导出时文件名标出条数，避免和「筛选结果」那份同名分不清
    if selected:
        filename = f"考勤与签到_选中{len(records) + len(checkins)}条.xlsx"
    else:
        filename = f"考勤与签到_{start or '全部'}_{end or '全部'}.xlsx"
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


@router.get(
    "/overview",
    response_model=AttendanceOverviewResponse,
    summary="点名与签到记录汇总（班委及以上）",
)
def overview_attendance(
    request: Request,
    start: date | None = Query(None, description="起始日期，含当天"),
    end: date | None = Query(None, description="结束日期，含当天"),
    keyword: str | None = Query(None, description="按点名备注或签到标题模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """点名与签到合成一张列表，按时间倒序排

    关键词对点名查备注、对签到查标题 —— 两边能用来认出这次记录的那句话
    不是同一个字段，但都是用户记得住的那句。两类数据量都是班级级，
    合并后在内存里排序、分页就够了，不必依赖 UNION。

    签到结算后不再新冒出一条「点名」行：这次签到本身那一行直接换成
    标准格式的人数字段，一次签到始终只占一行。
    """
    # 签到到点后要自动生成考勤记录，汇总里才看得到
    finalize_due(db)

    # ---------- 签到 ----------
    chk_query = db.query(Checkin)
    chk_match = keyword_like(keyword, Checkin.title)
    if chk_match is not None:
        chk_query = chk_query.filter(chk_match)
    checkins = [
        c for c in chk_query.all() if _checkin_in_range(c, start, end)
    ]

    # 结算生成的考勤记录不再单独成行 —— 哪怕关键词搜到的是它（它的备注里
    # 也带着标题），也归到上面那次签到那一行，避免一次签到出现两条
    settled_ids = {
        rid
        for (rid,) in db.query(Checkin.attendance_record_id).filter(
            Checkin.attendance_record_id.isnot(None)
        )
    }

    # ---------- 点名记录 ----------
    att_query = _date_range(db.query(AttendanceRecord), start, end)
    att_match = keyword_like(keyword, AttendanceRecord.remark)
    if att_match is not None:
        att_query = att_query.filter(att_match)
    if settled_ids:
        att_query = att_query.filter(AttendanceRecord.id.notin_(settled_ids))
    records = att_query.all()

    # 一次分组查询把两类记录的人数都拿回来，不要每条各查一遍。
    # 签到那行结算后也要显示「应到 / 实到 / 请假 / 无应答」，数就从它
    # 生成的那条考勤明细里取
    count_ids = [r.id for r in records] + [
        c.attendance_record_id for c in checkins if c.attendance_record_id
    ]
    by_record: dict[int, dict[str, int]] = {}
    if count_ids:
        rows = (
            db.query(AttendanceItem.record_id, AttendanceItem.status, func.count())
            .filter(AttendanceItem.record_id.in_(count_ids))
            .group_by(AttendanceItem.record_id, AttendanceItem.status)
            .all()
        )
        for record_id, status, count in rows:
            by_record.setdefault(record_id, {})[status] = count

    items: list[AttendanceOverviewItem] = []
    for record in records:
        counts = by_record.get(record.id, {})
        items.append(
            AttendanceOverviewItem(
                type="attendance",
                id=record.id,
                date=record.call_date,
                time=record.called_at,
                title=record.scope or "",
                operator_name=record.operator_name or "",
                remark=record.remark or "",
                total=sum(counts.values()),
                present=counts.get("present", 0),
                leave=counts.get("leave", 0),
                absent=counts.get("absent", 0),
            )
        )

    ids = [c.id for c in checkins]
    signed: dict[int, int] = {}
    targets: dict[int, int] = {}
    if ids:
        rows = (
            db.query(CheckinTarget.checkin_id, func.count())
            .filter(CheckinTarget.checkin_id.in_(ids))
            .group_by(CheckinTarget.checkin_id)
            .all()
        )
        targets = dict(rows)
        rows = (
            db.query(CheckinTarget.checkin_id, func.count())
            .filter(
                CheckinTarget.checkin_id.in_(ids),
                CheckinTarget.signed_at.isnot(None),
            )
            .group_by(CheckinTarget.checkin_id)
            .all()
        )
        signed = dict(rows)

    for checkin in checkins:
        # 截止那一刻是这条记录的时间，和日期筛选、导出用同一个口径
        reference = checkin.closed_at or checkin.end_at
        # 结算后本行换成标准格式：人数从生成的那条考勤明细里取
        counts = by_record.get(checkin.attendance_record_id or 0, {})
        items.append(
            AttendanceOverviewItem(
                type="checkin",
                id=checkin.id,
                date=reference.date(),
                time=reference,
                title=checkin.title or "",
                operator_name=checkin.created_by_name or "",
                remark=checkin.remark or "",
                # 结算前 total 是 0，前端按 status 显示实时的「已签 x / y」
                total=sum(counts.values()),
                present=counts.get("present", 0),
                leave=counts.get("leave", 0),
                absent=counts.get("absent", 0),
                status=checkin_status(checkin),
                start_at=checkin.start_at,
                target_count=targets.get(checkin.id, 0),
                signed_count=signed.get(checkin.id, 0),
                link=full_url(request, f"/#/checkin?code={checkin.code}"),
            )
        )

    # 时间倒序。同一时刻的按 id 兜底，翻页顺序才稳定
    items.sort(key=lambda x: (x.time or datetime.min, x.id), reverse=True)
    begin = (page - 1) * page_size
    return AttendanceOverviewResponse(
        total=len(items), items=items[begin:begin + page_size]
    )


@router.post(
    "/batch-delete", summary="批量删除点名与签到记录（班委及以上）"
)
def batch_delete_attendance(
    data: AttendanceBatchDelete,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """一次删掉勾选的记录。

    - 签到：连它的 targets、照片、结算生成的考勤一起删，链接随即失效；
    - 点名：连明细一起删；
    - 勾了签到生成的考勤却没勾那次签到：把身后的签到也一起删，
      否则会留下指空的签到，那条考勤也会变成删不得的历史记录。
    """
    if not data.record_ids and not data.checkin_ids:
        raise HTTPException(status_code=400, detail="没有选择要删除的记录")

    selected_checkin_ids = set(data.checkin_ids)
    selected_record_ids = set(data.record_ids)

    checkins = (
        db.query(Checkin).filter(Checkin.id.in_(data.checkin_ids)).all()
        if data.checkin_ids
        else []
    )
    records = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.id.in_(data.record_ids))
        .all()
        if data.record_ids
        else []
    )

    # 选中的考勤若是签到生成的，把那次签到也纳入删除范围
    known_checkin_ids = {c.id for c in checkins}
    for record in records:
        parent = (
            db.query(Checkin)
            .filter(Checkin.attendance_record_id == record.id)
            .first()
        )
        if parent and parent.id not in known_checkin_ids:
            checkins.append(parent)
            known_checkin_ids.add(parent.id)

    photo_files: list[str] = []
    handled = 0
    # 先删签到：它可能带着一条已选中的考勤，先删考勤会撞上「找不到父签到」
    for checkin in checkins:
        targets = (
            db.query(CheckinTarget)
            .filter(CheckinTarget.checkin_id == checkin.id)
            .all()
        )
        log_operation(
            db,
            user,
            action="删除签到",
            target=f"{checkin.end_at:%Y-%m-%d} {checkin.title}",
            detail=f"应到 {len(targets)} 人，已签 "
            f"{sum(1 for t in targets if t.signed_at)} 人，批量删除"
            + ("，结算生成的考勤记录一并删除" if checkin.attendance_record_id else ""),
            ip=get_client_ip(request),
            target_student_nos=[t.student_no for t in targets],
        )
        photo_files += remove_checkin(db, checkin)
        if checkin.id in selected_checkin_ids:
            handled += 1
    db.flush()

    # 签到生成的考勤已经跟着删了，这里只管普通点名
    generated_ids = {
        c.attendance_record_id for c in checkins if c.attendance_record_id
    }
    for record in records:
        if record.id in generated_ids:
            if record.id in selected_record_ids:
                handled += 1
            continue
        items = _items_of(db, record.id)
        log_operation(
            db,
            user,
            action="删除考勤",
            target=f"{record.call_date} {record.scope}",
            detail=_summary_detail(record.scope or "", items) + "，批量删除",
            ip=get_client_ip(request),
            target_student_nos=[i.student_no for i in items],
        )
        db.query(AttendanceItem).filter(
            AttendanceItem.record_id == record.id
        ).delete(synchronize_session=False)
        db.delete(record)
        if record.id in selected_record_ids:
            handled += 1

    db.commit()
    # 事务成功后再删签到照片，回滚时文件还在
    remove_photos(photo_files)
    return {"deleted": handled}


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
    # 签到到点后要自动生成考勤记录。懒结算放在这里，班委不打开签到页也能看到
    finalize_due(db)
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

    # 签到结算出来的记录由 checkins.attendance_record_id 指着。删它等于删那次
    # 签到 —— 单独删会留下一条指空的历史签到；只删签到又会留下这条删不掉的
    # 考勤，所以两边一起删，链接随即失效
    checkin = (
        db.query(Checkin)
        .filter(Checkin.attendance_record_id == record_id)
        .first()
    )

    items = _items_of(db, record_id)
    log_operation(
        db,
        user,
        action="删除考勤",
        target=f"{record.call_date} {record.scope}",
        detail=_summary_detail(record.scope or "", items)
        + ("；这条考勤由签到自动生成，签到记录与链接一并删除" if checkin else ""),
        ip=get_client_ip(request),
        target_student_nos=[i.student_no for i in items],
    )
    if checkin:
        photo_files = remove_checkin(db, checkin)
        db.commit()
        # 事务成功后再删签到照片，回滚时文件还在
        remove_photos(photo_files)
    else:
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
