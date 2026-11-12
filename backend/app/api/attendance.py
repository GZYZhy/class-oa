"""考勤记录：点名结果落库、明细修改、导出

和请假的联动只有一处：点名时前端把「当前时刻落在已批准请假区间内」的人自动
记成 leave。判定在前端做，用的是现成的 GET /api/leaves?status=approved
（api/leaves.py），不在这里另开一个「查谁在请假」的接口 —— 那要和请假列表
各写一份区间比较，两份迟早走散；而班委本来就看得见请假列表，权限也对得上。
"""

import io
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AttendanceImportBatch,
    AttendanceItem,
    AttendanceRecord,
    Checkin,
    CheckinTarget,
    Student,
    User,
)
from ..schemas import (
    AttendanceBatchDelete,
    AttendanceCreate,
    AttendanceImportConfirm,
    AttendanceImportPreviewResponse,
    AttendanceImportResult,
    AttendanceItemUpdate,
    AttendanceListResponse,
    AttendanceOverviewItem,
    AttendanceOverviewResponse,
    AttendanceRecordResponse,
    AttendanceRemarkUpdate,
    FullAttendanceResponse,
    MyAttendanceItem,
    MyAttendanceListResponse,
)
from ..services import display_name, log_operation
from ..services import attendance_import_service as ais
from ..services.checkin_service import (
    CHECKIN_DIR,
    CHECKIN_ENDED,
    CHECKIN_PAUSED,
    CHECKIN_PENDING,
    approved_leave_nos,
    checkin_status,
    finalize_due,
    remove_checkin,
    remove_photos,
)
from ..services.attendance_permission import (
    ensure_manage_attendance,
    ensure_manage_checkin,
)
from ..services.list_filters import keyword_like
from ..services.share_service import share_path
from ..utils.links import full_url
from .deps import committee_required, get_client_ip, get_current_student

router = APIRouter(prefix="/api/attendance", tags=["考勤记录"])

# 状态的中文名。库里存的是英文枚举（present/absent/leave/late），页面和导出都显示中文。
# 注意 late 只在「改某人状态」时才会出现，点名的创建接口不收它。
STATUS_LABELS = {"present": "到", "absent": "无应答", "leave": "请假", "late": "迟到"}

# 导出时写在列上的顺序。最后一列是这次点名上的一句话（库里仍叫 remark），
# 列表里统一叫「标题」，导出也跟着叫标题；同一批明细的每一行都带同一个值
EXPORT_COLUMNS = ["日期", "范围", "点名时刻", "操作人", "学号", "姓名", "状态", "标题"]

# 签到页签的列。「签到情况」是本人签没签，「出勤状态」是结算后考勤明细里的结果。
# 最后一列是发布时填的「说明」，不叫备注，免得和个人说明混在一起
CHECKIN_EXPORT_COLUMNS = [
    "截止日期", "标题", "发布人", "截止时间", "签到状态",
    "学号", "姓名", "签到情况", "签到时间", "距离(米)", "出勤状态", "说明",
]


def _write_header(ws, columns: list[str], row: int = 1) -> None:
    """两个页签共用一套表头样式，导出文件看起来是同一套东西

    row 可传：单次明细导出上面还有一段抬头摘要，表头要落在它下面
    """
    font = Font(bold=True)
    fill = PatternFill(start_color="E8F0FE", end_color="E8F0FE", fill_type="solid")
    for col_idx, label in enumerate(columns, 1):
        cell = ws.cell(row=row, column=col_idx, value=label)
        cell.font = font
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _fit_columns(ws, columns: list[str], last_wide: bool = True) -> None:
    """列宽按表头估就够了：内容是学号/姓名/日期这类定长。

    除了最后一列 —— 列表导出里它总是标题 / 说明这类长文本，按表头估只够显示
    两三个字；单次明细导出没有这一列，last_wide=False 别把「状态」撑成 30。
    """
    for col_idx, label in enumerate(columns, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = min(len(label) * 2 + 6, 24)
    if last_wide:
        ws.column_dimensions[get_column_letter(len(columns))].width = 30
    ws.freeze_panes = "A2"


def _write_detail_block(ws, title: str, meta: list[str], columns: list[str]) -> int:
    """单次明细的抬头：大字标题 + 几行摘要 + 空一行 + 表头

    返回第一行数据的行号。抬头整段合并到列宽，长标题不会被截在 A 列里。
    """
    span = f"A1:{get_column_letter(len(columns))}1"
    ws.merge_cells(span)
    cell = ws.cell(row=1, column=1, value=title)
    cell.font = Font(bold=True, size=14)
    cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24

    row = 2
    for line in meta:
        if not line:
            continue
        ws.merge_cells(f"A{row}:{get_column_letter(len(columns))}{row}")
        meta_cell = ws.cell(row=row, column=1, value=line)
        meta_cell.alignment = Alignment(horizontal="left", vertical="center")
        row += 1

    row += 1  # 摘要和表之间留一行空白
    _write_header(ws, columns, row=row)
    _fit_columns(ws, columns, last_wide=False)
    ws.freeze_panes = f"A{row + 1}"
    return row + 1


def _counts(items: list[AttendanceItem]) -> dict[str, int]:
    """从明细聚合出各状态人数。

    表里没有计数列，一律现算 —— 改某人状态时不需要再去同步第二份数据。
    """
    result = {"total": len(items), "present": 0, "late": 0, "leave": 0, "absent": 0}
    for item in items:
        if item.status in result:
            result[item.status] += 1
    return result


def _to_response(
    record: AttendanceRecord, items: list[AttendanceItem] | None = None
) -> AttendanceRecordResponse:
    """组装一条记录。列表接口不传 items（只给聚合计数），详情接口才传"""
    data = _counts(items or [])
    label = "导入" if record.import_batch_id else _manual_scope_label(
        record.scope, len(items or [])
    )
    return AttendanceRecordResponse(
        id=record.id,
        call_date=record.call_date,
        scope=record.scope or "",
        scope_label=label,
        called_at=record.called_at,
        operator_no=record.operator_no or "",
        operator_name=record.operator_name or "",
        remark=record.remark or "",
        total=data["total"],
        present=data["present"],
        late=data["late"],
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
    # 实到包含迟到（迟到的人确实到了），迟到再单独括起来；这样各计数之和还是应到
    attended = data["present"] + data["late"]
    late_text = f"（含迟到 {data['late']} 人）" if data["late"] else ""
    return (
        f"共 {data['total']} 人，实到 {attended} 人{late_text}，"
        f"请假 {data['leave']} 人，无应答 {data['absent']} 人"
        + (f"：{absent_names}" if absent_names else "（全部到齐）")
    )


# ---------- 固定路径必须定义在 /{record_id} 之前 ----------
# 否则 /export 会先撞上 /{record_id} 被当成 record_id 解析，直接 422（本项目已踩过）
@router.get(
    "/full-attendance",
    response_model=FullAttendanceResponse,
    summary="统计周期内全勤名单（班委及以上）",
)
def full_attendance(
    start: date | None = Query(None, description="起始日期，含当天"),
    end: date | None = Query(None, description="结束日期，含当天"),
    late_counts: bool = Query(True, description="迟到是否算全勤"),
    leave_counts: bool = Query(False, description="请假是否算全勤"),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """按周期汇总全勤人员

    只统计已经落在考勤明细里的记录；签到在结算后同样会生成考勤明细，
    未结算的签到不参与。一个人只要在周期内被点到过，且每次状态都在
    「到 / 迟到（可选）/ 请假（可选）」范围内，就算全勤。
    """
    if start and end and end < start:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    finalize_due(db)
    records = _date_range(db.query(AttendanceRecord), start, end).all()
    record_ids = [record.id for record in records]
    if not record_ids:
        return {
            "start_date": start,
            "end_date": end,
            "total_records": 0,
            "checked_students": 0,
            "items": [],
        }

    rows = (
        db.query(AttendanceItem)
        .filter(AttendanceItem.record_id.in_(record_ids))
        .all()
    )
    statuses: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for item in rows:
        number = item.student_no or ""
        if not number:
            continue
        statuses.setdefault(number, []).append(item.status or "")
        if item.student_name:
            names[number] = item.student_name

    student_names = dict(
        db.query(Student.student_no, Student.name)
        .filter(Student.student_no.in_(statuses.keys()))
        .all()
    )
    names.update({number: name for number, name in student_names.items() if name})

    items = []
    for number, values in statuses.items():
        allowed = all(
            value == "present"
            or (late_counts and value == "late")
            or (leave_counts and value == "leave")
            for value in values
        )
        if not allowed:
            continue
        items.append(
            {
                "student_no": number,
                "name": names.get(number, number),
                "late_count": values.count("late"),
                "leave_count": values.count("leave"),
            }
        )
    items.sort(key=lambda item: item["student_no"])

    return {
        "start_date": start,
        "end_date": end,
        "total_records": len(records),
        "checked_students": len(statuses),
        "items": items,
    }


@router.post(
    "/import/preview",
    response_model=AttendanceImportPreviewResponse,
    summary="解析考勤 Excel（班委及以上）",
)
async def preview_attendance_import(
    file: UploadFile = File(...),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    filename = file.filename or "考勤.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 文件")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 5MB")

    try:
        parsed = ais.parse_excel(content, filename)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Excel 解析失败：{error}")

    students = db.query(Student).all()
    by_no = {student.student_no: student for student in students}
    by_name: dict[str, list[Student]] = {}
    for student in students:
        if student.name:
            by_name.setdefault(student.name, []).append(student)

    warnings = list(parsed["warnings"])
    matched = []
    for row in parsed["rows"]:
        number = row["student_no"].strip()
        name = row["name"].strip()
        student = by_no.get(number) if number else None
        if not student and not number and name:
            candidates = by_name.get(name, [])
            if len(candidates) == 1:
                student = candidates[0]
            elif len(candidates) > 1:
                warnings.append(f"第 {row['row']} 行姓名「{name}」重名，已跳过")
        if not student:
            warnings.append(
                f"第 {row['row']} 行「{name or number}」不在学生名单里，已跳过"
            )
            continue
        matched.append({
            "row": row["row"],
            "student_no": student.student_no,
            "name": student.name or student.student_no,
            "values": row["values"],
        })

    if not matched:
        raise HTTPException(status_code=400, detail="没有匹配到任何学生")

    token = ais.save_preview({
        "filename": filename,
        "sheet_name": parsed["sheet_name"],
        "sessions": parsed["sessions"],
        "rows": matched,
        "warnings": warnings,
    })
    return {
        "token": token,
        "filename": filename,
        "sheet_name": parsed["sheet_name"],
        "sessions": parsed["sessions"],
        "rows": matched,
        "warnings": warnings,
    }


@router.post(
    "/import/confirm",
    response_model=AttendanceImportResult,
    summary="确认导入考勤（班委及以上）",
)
def confirm_attendance_import(
    data: AttendanceImportConfirm,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    preview = ais.load_preview(data.token)
    if not preview:
        raise HTTPException(status_code=400, detail="预览已过期，请重新上传文件")
    times = {item.key: item.occurred_at for item in data.sessions}
    missing = [s["title"] for s in preview["sessions"] if not times.get(s["key"])]
    if missing:
        raise HTTPException(status_code=400, detail=f"还没有选择发生时间：{'、'.join(missing)}")

    operator_name = display_name(db, user)
    batch = AttendanceImportBatch(
        filename=preview["filename"],
        operator_no=user.student_no,
        operator_name=operator_name,
        record_count=0,
        item_count=0,
    )
    db.add(batch)
    db.flush()

    records_created = 0
    items_created = 0
    skipped_sessions = 0
    for session in preview["sessions"]:
        occurred_at = times[session["key"]]
        rows = [
            row for row in preview["rows"]
            if row["values"].get(session["key"])
        ]
        if not rows:
            skipped_sessions += 1
            continue
        record = AttendanceRecord(
            call_date=occurred_at.date(),
            called_at=occurred_at,
            scope="导入",
            remark=session["title"],
            operator_no=user.student_no,
            operator_name=operator_name,
            import_batch_id=batch.id,
        )
        db.add(record)
        db.flush()
        records_created += 1
        for row in rows:
            db.add(AttendanceItem(
                record_id=record.id,
                student_no=row["student_no"],
                student_name=row["name"],
                status=row["values"][session["key"]],
            ))
            items_created += 1

    if not records_created:
        db.rollback()
        raise HTTPException(status_code=400, detail="所有场次都没有范围内的学生，未导入")

    batch.record_count = records_created
    batch.item_count = items_created
    log_operation(
        db,
        user,
        action="导入考勤",
        target=preview["filename"],
        detail=f"导入 {records_created} 场、{items_created} 条明细",
        ip=get_client_ip(request),
    )
    db.commit()
    ais.drop_preview(data.token)
    return {
        "records_created": records_created,
        "items_created": items_created,
        "skipped_sessions": skipped_sessions,
    }


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
                # 签到结算生成的那条保留「签到·N人」，导出文件里没有类型列，
                # 去掉前缀就分不出它是签到还是手动点名；手动点名的自定义范围
                # （男生 / 临时集合…）统一写成标准简语「N人」
                (record.scope or "")
                if (record.scope or "").startswith("签到·")
                else _manual_scope_label(record.scope, len(items)),
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


def _file_part(text: str, limit: int = 40) -> str:
    """文件名里的一段：去掉路径分隔符等非法字符

    点名范围、签到标题都是人写的，可能带斜杠或冒号，原样进 Content-Disposition
    会被解成路径，下载下来文件名也乱
    """
    cleaned = "".join(
        "_" if char in '/\\:*?"<>|\r\n\t' else char for char in (text or "")
    ).strip("._ ")
    return cleaned[:limit] or "明细"


def _xlsx_response(content: bytes, filename: str) -> Response:
    """单次明细导出共用的响应：中文文件名按 RFC 5987 编码，禁止缓存"""
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename*=utf-8''" + quote(filename),
            "Cache-Control": "no-store",
        },
    )


@router.get("/{record_id}/export", summary="导出单次点名明细（班委及以上）")
def export_attendance_detail(
    record_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """只导这一次点名：抬头说明这场是谁点的、应到多少、各状态几人，下面是逐人明细

    列表页那个 `/export` 是「一次导出很多条、两个页签」；核对单场时用这个，
    打开就是一张能直接发出去的表。
    """
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="考勤记录不存在")
    items = (
        db.query(AttendanceItem)
        .filter(AttendanceItem.record_id == record.id)
        .order_by(AttendanceItem.student_no)
        .all()
    )
    counts = _counts(items)
    scope = _manual_scope_label(record.scope, len(items))
    day = record.call_date.strftime("%Y-%m-%d") if record.call_date else ""
    meta = [
        f"点名时刻：{record.called_at:%Y-%m-%d %H:%M}　发起人：{record.operator_name or '—'}"
        if record.called_at
        else f"发起人：{record.operator_name or '—'}",
        f"应到 {counts['total']} 人 · 实到 {counts['present'] + counts['late']} 人"
        f"（含迟到 {counts['late']} 人）· 请假 {counts['leave']} 人"
        f" · 无应答 {counts['absent']} 人",
    ]
    if record.remark:
        meta.append(f"标题：{record.remark}")

    columns = ["学号", "姓名", "状态"]
    wb = Workbook()
    ws = wb.active
    ws.title = "点名明细"
    row = _write_detail_block(ws, f"{day} {scope} 点名明细", meta, columns)
    for item in items:
        values = [
            item.student_no,
            item.student_name or "",
            STATUS_LABELS.get(item.status, item.status or ""),
        ]
        for col_idx, value in enumerate(values, 1):
            ws.cell(row=row, column=col_idx, value=value).alignment = Alignment(vertical="center")
        row += 1

    buf = io.BytesIO()
    wb.save(buf)
    return _xlsx_response(
        buf.getvalue(),
        f"点名明细_{day or '未记录'}_{_file_part(scope)}.xlsx",
    )


@router.get("/checkin/{checkin_id}/export", summary="导出单次签到明细（班委及以上）")
def export_checkin_detail(
    checkin_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """只导这一次签到：谁签了、几点签的、离地点多远、最终算出什么出勤状态

    有照片时返回 **zip**（`签到明细.xlsx` + `照片/学号_姓名.后缀`），和收集
    「导出含文件」是同一套做法：表格单元格写包内相对路径，解开就对得上。
    照片一张都没有时仍是裸 xlsx，照片列退回「有 / 空」，不逼人去解压。
    """
    finalize_due(db)
    checkin = db.query(Checkin).filter(Checkin.id == checkin_id).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="签到不存在")
    targets = (
        db.query(CheckinTarget)
        .filter(CheckinTarget.checkin_id == checkin.id)
        .order_by(CheckinTarget.student_no)
        .all()
    )
    reference = checkin.closed_at or checkin.end_at
    leave_nos = approved_leave_nos(db, [t.student_no for t in targets], reference)
    status_by_no = (
        dict(
            db.query(AttendanceItem.student_no, AttendanceItem.status)
            .filter(AttendanceItem.record_id == checkin.attendance_record_id)
            .all()
        )
        if checkin.attendance_record_id
        else {}
    )
    signed = sum(1 for target in targets if target.signed_at)
    status_counts = {"present": 0, "late": 0, "leave": 0, "absent": 0}
    for target in targets:
        status = status_by_no.get(target.student_no, "")
        if status in status_counts:
            status_counts[status] += 1

    day = reference.strftime("%Y-%m-%d") if reference else ""
    meta = [
        f"截止：{reference:%Y-%m-%d %H:%M}　发起人：{checkin.created_by_name or '—'}"
        if reference
        else f"发起人：{checkin.created_by_name or '—'}",
        f"应到 {len(targets)} 人 · 已签 {signed} 人 · 未签 {len(targets) - signed} 人",
    ]
    if checkin.finalized_at:
        meta.append(
            f"出勤：到 {status_counts['present']} 人 · 迟到 {status_counts['late']} 人"
            f" · 请假 {status_counts['leave']} 人 · 无应答 {status_counts['absent']} 人"
        )
    if checkin.remark:
        meta.append(f"说明：{checkin.remark}")

    columns = ["学号", "姓名", "签到状态", "签到时间", "距离(米)", "出勤状态", "照片"]
    # 先把能打包的照片收好：表格最后列要写包内路径，所以得在建表之前知道谁有照片
    photo_entries: list[tuple[str, Path]] = []
    photo_arc: dict[str, str] = {}
    for target in targets:
        stored = Path(str(target.photo_file or "")).name
        path = CHECKIN_DIR / stored
        if not (stored and path.is_file()):
            continue
        arcname = (
            f"照片/{target.student_no}_{_file_part(target.student_name or '学生')}"
            f"{path.suffix or '.jpg'}"
        )
        photo_entries.append((arcname, path))
        photo_arc[target.student_no] = arcname

    wb = Workbook()
    ws = wb.active
    ws.title = "签到明细"
    row = _write_detail_block(
        ws, f"{day} {checkin.title or '签到'} 签到明细", meta, columns
    )
    for target in targets:
        status = status_by_no.get(target.student_no, "")
        values = [
            target.student_no,
            target.student_name or "",
            "已签到" if target.signed_at else "未签到",
            target.signed_at.strftime("%Y-%m-%d %H:%M") if target.signed_at else "",
            target.distance_m if target.distance_m is not None else "",
            STATUS_LABELS.get(status, status or ""),
            # 打包了写包内路径（解开直接点开）；没打包退回「有/空」
            photo_arc.get(target.student_no) or ("有" if target.photo_file else ""),
        ]
        for col_idx, value in enumerate(values, 1):
            ws.cell(row=row, column=col_idx, value=value).alignment = Alignment(vertical="center")
        row += 1
    # 请假的人补一句：未签不等于无故缺席，导出的人不用再回去翻请假表
    if leave_nos and targets:
        row += 1
        ws.cell(row=row, column=1, value="注：未签到但已批准请假的同学，出勤状态会是「请假」")
        ws.merge_cells(
            start_row=row, start_column=1, end_row=row, end_column=len(columns)
        )

    buf = io.BytesIO()
    wb.save(buf)
    filename = f"签到明细_{day or '未记录'}_{_file_part(checkin.title or '签到')}"

    # 有照片就打成 zip（表 + 照片），和收集导出同一套：xlsx 里的「照片」列
    # 写的就是包内相对路径。没有照片仍然只给 xlsx，别为一张表逼人解压
    if photo_entries:
        archive = BytesIO()
        with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
            bundle.writestr("签到明细.xlsx", buf.getvalue())
            for arcname, path in photo_entries:
                bundle.write(path, arcname)
        return Response(
            content=archive.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename*=utf-8''"
                + quote(f"{filename}_含照片.zip"),
                "Cache-Control": "no-store",
            },
        )

    return _xlsx_response(buf.getvalue(), f"{filename}.xlsx")


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
        imported = bool(record.import_batch_id)
        items.append(
            AttendanceOverviewItem(
                type="import" if imported else "attendance",
                id=record.id,
                date=record.call_date,
                time=record.called_at,
                title=(record.remark if imported else record.scope) or "",
                scope_label="导入" if imported else _manual_scope_label(
                    record.scope, sum(counts.values())
                ),
                operator_no=record.operator_no or "",
                operator_name=record.operator_name or "",
                remark=record.remark or "",
                total=sum(counts.values()),
                present=counts.get("present", 0),
                late=counts.get("late", 0),
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
                scope_label=_checkin_scope_label(
                    db, checkin.id, targets.get(checkin.id, 0)
                ),
                operator_no=checkin.created_by_no or "",
                operator_name=checkin.created_by_name or "",
                remark=checkin.remark or "",
                # 结算前 total 是 0，前端按 status 显示实时的「已签 x / y」
                total=sum(counts.values()),
                present=counts.get("present", 0),
                late=counts.get("late", 0),
                leave=counts.get("leave", 0),
                absent=counts.get("absent", 0),
                status=checkin_status(checkin),
                start_at=checkin.start_at,
                target_count=targets.get(checkin.id, 0),
                signed_count=signed.get(checkin.id, 0),
                # 分享弹窗重新打开时要显示备注和签到要求
                require_photo=bool(checkin.require_photo),
                location=(
                    {
                        "lat": checkin.lat,
                        "lng": checkin.lng,
                        "radius_m": checkin.radius_m or 0,
                        "name": checkin.location_name or "",
                    }
                    if checkin.lat is not None and checkin.lng is not None
                    else None
                ),
                # 和发布接口、签到列表用同一个分享地址：真实路径，
                # 服务器能按场次写入 meta，微信爬虫读得到卡片信息
                link=full_url(request, share_path("checkin", checkin.code)),
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

    # 批量删也要逐条验权限。签到生成的考勤跟着签到走，校验签到本身即可；
    # 不能因为「勾了一堆」就跳过某一条 —— 那等于给了绕开单条校验的口子
    parent_of_record = {
        c.attendance_record_id: c for c in checkins if c.attendance_record_id
    }
    for checkin in checkins:
        ensure_manage_checkin(checkin, user, "删除这条签到")
    for record in records:
        if record.id not in parent_of_record:
            ensure_manage_attendance(record, user, "删除这条考勤")

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
                scope_label=_manual_scope_label(record.scope, sum(counts.values())),
                called_at=record.called_at,
                operator_no=record.operator_no or "",
                operator_name=record.operator_name or "",
                remark=record.remark or "",
                total=sum(counts.values()),
                present=counts.get("present", 0),
                late=counts.get("late", 0),
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


def _manual_scope_label(scope: str, total: int | None = None) -> str:
    """点名的范围 → 标准简语：全班 / 团员 / 班委 / N人

    原始 scope 是点名时的快捷选项（「男生」「女生」「共青团员」等），
    页面上的「范围」列只认这四个标准说法。给了 total 时，其余范围一律
    写成「N人」；没给 total 的老调用方保持原样（只归一「团员」）。
    """
    if (scope or "").strip() == "导入":
        return "导入"
    value = (scope or "").strip()
    if value == "全班":
        return "全班"
    if value in ("共青团员", "团员"):
        return "团员"
    if value == "班委":
        return "班委"
    if total is not None:
        return f"{total}人"
    return value or "—"


def _checkin_scope_label(db: Session, checkin_id: int, target_count: int) -> str:
    """把签到的目标集合说成「全班 / 团员 / 班委 / N人」

    **必须是「刚好圈了全部团员 / 全部班委」才这么叫**：只圈了一名团员时，
    他本人虽然是团员，但这次范围并不等于「团员」，应该如实显示「1人」。
    """
    total = db.query(Student).count()
    if target_count and total and target_count >= total:
        return "全班"
    nos = [
        no
        for (no,) in db.query(CheckinTarget.student_no).filter(
            CheckinTarget.checkin_id == checkin_id
        )
    ]
    if not nos:
        return "0人"

    league_total = (
        db.query(Student)
        .filter(Student.political_status == "共青团员")
        .count()
    )
    if league_total and len(nos) == league_total:
        league = (
            db.query(Student)
            .filter(
                Student.student_no.in_(nos),
                Student.political_status == "共青团员",
            )
            .count()
        )
        if league == league_total:
            return "团员"

    committee_total = (
        db.query(User)
        .join(Student, Student.student_no == User.student_no)
        .filter(
            User.role.in_(("committee", "admin")),
            User.is_external == False,  # noqa: E712
        )
        .count()
    )
    if committee_total and len(nos) == committee_total:
        committee = (
            db.query(User)
            .join(Student, Student.student_no == User.student_no)
            .filter(
                User.student_no.in_(nos),
                User.role.in_(("committee", "admin")),
                User.is_external == False,  # noqa: E712
            )
            .count()
        )
        if committee == committee_total:
            return "班委"

    return f"{len(nos)}人"


def _student_attendance_items(db: Session, student: Student) -> list[MyAttendanceItem]:
    """某个学生参与的考勤（点名 + 签到），按时间倒序

    只列「有他自己那一行」的记录：点名看 attendance_items，签到看 checkin_targets。
    签到结算后会生成一条普通考勤记录，那条不再单独列出 —— 一次签到始终只占一行。
    """
    finalize_due(db)
    settled_ids = {
        rid
        for (rid,) in db.query(Checkin.attendance_record_id).filter(
            Checkin.attendance_record_id.isnot(None)
        )
    }
    items: list[MyAttendanceItem] = []

    # ---------- 点名 ----------
    rows = (
        db.query(AttendanceItem, AttendanceRecord)
        .join(AttendanceRecord, AttendanceRecord.id == AttendanceItem.record_id)
        .filter(AttendanceItem.student_no == student.student_no)
        .all()
    )
    # 每条记录的应到人数，用来把「男生 / 女生」这类原始范围写成「N人」
    record_ids = [record.id for _, record in rows]
    record_totals = (
        dict(
            db.query(AttendanceItem.record_id, func.count())
            .filter(AttendanceItem.record_id.in_(record_ids))
            .group_by(AttendanceItem.record_id)
            .all()
        )
        if record_ids
        else {}
    )
    for item, record in rows:
        # 签到结算出来的那条考勤归到签到那一行，不重复展示
        if record.id in settled_ids:
            continue
        occurred = record.called_at or datetime.combine(
            record.call_date, datetime.min.time()
        )
        items.append(
            MyAttendanceItem(
                type="attendance",
                id=record.id,
                occurred_at=occurred,
                title=(record.remark or "").strip() or "点名",
                category="点名",
                scope=_manual_scope_label(
                    record.scope, record_totals.get(record.id, 0)
                ),
                status=item.status or "",
                status_label=STATUS_LABELS.get(item.status or "", item.status or ""),
            )
        )

    # ---------- 签到 ----------
    targets = (
        db.query(CheckinTarget, Checkin)
        .join(Checkin, Checkin.id == CheckinTarget.checkin_id)
        .filter(CheckinTarget.student_no == student.student_no)
        .all()
    )
    for target, checkin in targets:
        # 请假判定看截止（含提前结束）那一刻；列表上的「考勤时间」用签到开始的时间
        reference = checkin.closed_at or checkin.end_at
        occurred = checkin.start_at or checkin.created_at or reference
        state = checkin_status(checkin)

        # 已结算的以考勤明细为准（班委可能改过状态），没结算的才按签到事实推
        final_status = None
        if checkin.attendance_record_id:
            final = (
                db.query(AttendanceItem)
                .filter(
                    AttendanceItem.record_id == checkin.attendance_record_id,
                    AttendanceItem.student_no == student.student_no,
                )
                .first()
            )
            final_status = final.status if final else None

        if final_status:
            code = final_status
            label = STATUS_LABELS.get(final_status, final_status)
        elif target.signed_at:
            code, label = "present", "到"
        elif state == CHECKIN_ENDED:
            on_leave = approved_leave_nos(db, [student.student_no], reference)
            code, label = ("leave", "请假") if on_leave else ("absent", "无应答")
        elif state == CHECKIN_PENDING:
            code, label = "pending", "未开始"
        elif state == CHECKIN_PAUSED:
            code, label = "paused", "已暂停"
        else:
            code, label = "unsigned", "未签到"

        target_count = (
            db.query(CheckinTarget)
            .filter(CheckinTarget.checkin_id == checkin.id)
            .count()
        )
        items.append(
            MyAttendanceItem(
                type="checkin",
                id=checkin.id,
                occurred_at=occurred,
                title=(checkin.title or "").strip() or "签到",
                category="签到",
                scope=_checkin_scope_label(db, checkin.id, target_count),
                status=code,
                status_label=label,
            )
        )

    items.sort(key=lambda row: row.occurred_at or datetime.min, reverse=True)
    return items


@router.get(
    "/mine",
    response_model=MyAttendanceListResponse,
    summary="我的考勤情况（学生本人）",
)
def my_attendance(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    items = _student_attendance_items(db, student)
    return MyAttendanceListResponse(total=len(items), items=items)


@router.get(
    "/student/{student_id}",
    response_model=MyAttendanceListResponse,
    summary="某个学生的考勤情况（班委及以上）",
)
def student_attendance(
    student_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """学生详情卡片里的「考勤情况」，内容与学生端自己看到的一致"""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    items = _student_attendance_items(db, student)
    return MyAttendanceListResponse(total=len(items), items=items)


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
    # 改状态是写操作：只有管理员或这场点名的发起者能动（改标题不在此列）
    ensure_manage_attendance(record, user, "修改考勤状态")

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
    ensure_manage_attendance(record, user, "删除这条考勤")

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
