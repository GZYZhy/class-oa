"""学生信息导出申请

班委提交 → 管理员审核 → 通过后生成文件 → 下载。

两种导出类型：
- excel_list：名单 Excel，可选字段
- pdf_individual：个人信息表 PDF（每人一份，打包 zip）

PDF 自动打不可见水印，溯源是谁导出的。
"""

import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import ExportRequest, Student, User
from ..schemas.export import (
    ExportRequestCreate,
    ExportRequestListResponse,
    ExportRequestResponse,
    ExportRejectRequest,
)
from ..services import (
    TOKEN_SOURCE_EXPORT,
    log_operation,
    make_watermark_token,
    notify,
    recipients,
    scope_label,
)
from ..services.list_filters import created_between, keyword_like
from ..services.export_service import (
    DEFAULT_FIELDS,
    FIELD_MAP,
    generate_excel,
    generate_individual_pdfs,
    get_default_fields,
    get_field_groups,
    resolve_students,
)
from .deps import admin_required, committee_required, get_client_ip, get_current_user

router = APIRouter(prefix="/api/export-requests", tags=["学生信息导出"])

# 导出文件存放目录
EXPORT_DIR = Path(os.environ.get("EXPORT_DIR") or (BASE_DIR / "data" / "exports"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# 学生照片目录（PDF 里要嵌入照片）
PHOTOS_DIR = BASE_DIR / "data" / "photos"

# 审批人角色：只有管理员能批
APPROVER_ROLES = ["admin"]

# 导出类型常量
TYPE_EXCEL = "excel_list"
TYPE_PDF = "pdf_individual"

# 允许的导出类型
ALLOWED_TYPES = {TYPE_EXCEL, TYPE_PDF}
ALLOWED_SCOPES = {"all", "filtered", "selected", "id_range"}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _to_response(req: ExportRequest) -> ExportRequestResponse:
    """模型转响应 Schema"""
    scope_param = None
    if req.scope_param:
        try:
            scope_param = json.loads(req.scope_param)
        except (json.JSONDecodeError, TypeError):
            scope_param = None

    fields = None
    if req.fields:
        try:
            fields = json.loads(req.fields)
        except (json.JSONDecodeError, TypeError):
            fields = None

    return ExportRequestResponse(
        id=req.id,
        student_id=req.student_id,
        student_no=req.student_no,
        student_name=req.student_name,
        export_type=req.export_type,
        scope_type=req.scope_type,
        scope_param=scope_param,
        fields=fields,
        file_original_name=req.file_original_name or None,
        status=req.status,
        reviewer_name=req.reviewer_name or None,
        reviewer_no=req.reviewer_no or None,
        reject_reason=req.reject_reason or None,
        reviewed_at=req.reviewed_at,
        error_msg=req.error_msg or None,
        created_at=req.created_at,
    )


def _display_name_for_type(export_type: str) -> str:
    return {"excel_list": "学生名单", "pdf_individual": "个人信息表"}.get(export_type, "导出文件")


def _log_target(students: list[Student]) -> tuple[str, list[str]]:
    """操作日志的对象展示名 + 全部学号

    一条日志写「第一人 等N人」，日志列表才不会被几十条同源记录刷屏；
    全部学号另外存进 target_student_nos，每个人查自己的「被操作记录」又都查得到。
    """
    if not students:
        return "无匹配学生", []
    first = students[0]
    return f"{first.student_no} {first.name}等{len(students)}人", [s.student_no for s in students]


def _log_detail(export_type: str, scope_type: str, count: int, fields: list[str] | None) -> str:
    """日志里的「导出了什么」

    学生范围和信息范围分开写：个人信息表每人一份完整信息、没有选字段这一步，
    信息范围恒为「全部」；名单 Excel 就是勾选的那些列。
    """
    parts = [f"学生范围：{scope_label(scope_type, count)}"]
    if export_type == TYPE_PDF:
        parts.append("信息范围：全部")
    else:
        labels = [FIELD_MAP.get(f, {}).get("label", f) for f in (fields or DEFAULT_FIELDS)]
        parts.append("信息范围：" + "、".join(labels))
    return f"{_display_name_for_type(export_type)}，" + "，".join(parts)


def _generate_and_save(req: ExportRequest, db: Session) -> None:
    """生成导出文件并存盘，更新 request 状态。

    审批通过时调用。班级体量小（几十人），同步生成即可，不用异步。
    """
    try:
        scope_param = json.loads(req.scope_param) if req.scope_param else None
        students = resolve_students(db, req.scope_type, scope_param)
        if not students:
            req.status = "failed"
            req.error_msg = "没有符合条件的学生"
            db.commit()
            return

        # 水印 token：file_id 用导出申请 ID，来源标 exp —— 公告和导出申请
        # 的 id 各自编号会撞号，不标来源的话溯源报告会指到别的文件上
        token = make_watermark_token(req.id, req.student_no, source=TOKEN_SOURCE_EXPORT)

        if req.export_type == TYPE_EXCEL:
            fields = json.loads(req.fields) if req.fields else DEFAULT_FIELDS
            # 过滤掉不在白名单里的
            fields = [f for f in fields if f in FIELD_MAP]
            if not fields:
                fields = DEFAULT_FIELDS
            content = generate_excel(students, fields)
            ext = "xlsx"
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        elif req.export_type == TYPE_PDF:
            content = generate_individual_pdfs(students, PHOTOS_DIR, token)
            ext = "zip"
            mime = "application/zip"

        else:
            req.status = "failed"
            req.error_msg = f"未知导出类型：{req.export_type}"
            db.commit()
            return

        # 存盘
        fname = f"{req.export_type}_{req.id}_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}.{ext}"
        (EXPORT_DIR / fname).write_bytes(content)

        # 文件名用中文，下载时用 RFC 5987 编码
        display = f"{_display_name_for_type(req.export_type)}_{datetime.now():%Y%m%d}.{ext}"

        req.file_name = fname
        req.file_original_name = display
        req.status = "generated"
        db.commit()

    except Exception as e:
        req.status = "failed"
        req.error_msg = str(e)[:500]
        db.commit()


# ---------------------------------------------------------------------------
# 字段元信息（前端用来渲染复选框）
# ---------------------------------------------------------------------------

@router.get("/field-groups", summary="导出字段分组（前端渲染用）")
def field_groups(_: User = Depends(committee_required)):
    return {
        "groups": get_field_groups(),
        "default_fields": get_default_fields(),
    }


# ---------------------------------------------------------------------------
# 学生 / 班委侧：提交申请、查我的申请、下载
# ---------------------------------------------------------------------------

@router.post("", response_model=ExportRequestResponse, summary="提交导出申请")
def create_request(
    body: ExportRequestCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(committee_required),
    ip: str = Depends(get_client_ip),
):
    if body.export_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="不支持的导出类型")
    if body.scope_type not in ALLOWED_SCOPES:
        raise HTTPException(status_code=400, detail="不支持的范围类型")

    # 找对应的学生记录（拿名字）
    student = db.query(Student).filter(Student.student_no == user.student_no).first()

    req = ExportRequest(
        student_id=student.id if student else None,
        student_no=user.student_no,
        student_name=student.name if student else user.display_name or user.student_no,
        export_type=body.export_type,
        scope_type=body.scope_type,
        scope_param=json.dumps(body.scope_param or {}, ensure_ascii=False),
        fields=json.dumps(body.fields or [], ensure_ascii=False) if body.export_type == TYPE_EXCEL else "",
        status="pending",
    )
    db.add(req)
    db.flush()

    # 操作日志：记一条，但 target_student_nos 写入全部学号，
    # 这样操作日志列表不刷屏，每个人查被操作记录时又都能查到
    students = resolve_students(db, body.scope_type, body.scope_param)
    log_target, target_nos = _log_target(students)

    log_operation(
        db, user,
        "导出学生信息",
        log_target,
        _log_detail(body.export_type, body.scope_type, len(students), body.fields),
        ip=ip,
        target_student_nos=target_nos,
    )

    # 推送给管理员
    notify(
        db,
        background,
        recipients(db, roles=APPROVER_ROLES),
        "有新的导出申请待审核",
        f"{req.student_name} 申请导出{_display_name_for_type(body.export_type)}",
        level="timeSensitive",
        page="/review?tab=export",
    )

    db.commit()
    db.refresh(req)
    return _to_response(req)


@router.get("/mine", response_model=ExportRequestListResponse, summary="我的导出申请")
def my_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(committee_required),
):
    q = db.query(ExportRequest).filter(ExportRequest.student_no == user.student_no)
    total = q.count()
    items = (
        q.order_by(desc(ExportRequest.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": [_to_response(r) for r in items]}


@router.get("/{req_id}/download", summary="下载已通过的导出文件")
def download_file(
    req_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(committee_required),
):
    req = db.query(ExportRequest).filter(ExportRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")

    # 申请人自己或管理员可以下载
    if req.student_no != user.student_no and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权下载")

    if req.status not in ("generated", "approved"):
        raise HTTPException(status_code=400, detail=f"文件未生成或已被驳回（当前状态：{req.status}）")

    if not req.file_name:
        raise HTTPException(status_code=400, detail="文件不存在")

    fpath = EXPORT_DIR / req.file_name
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="文件已被清理")

    content = fpath.read_bytes()
    display_name = req.file_original_name or fpath.name

    if req.export_type == TYPE_EXCEL:
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        mime = "application/zip"

    return Response(
        content=content,
        media_type=mime,
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(display_name, safe='')}",
            "Content-Length": str(len(content)),
        },
    )


# ---------------------------------------------------------------------------
# 管理员侧：列表、审批
# ---------------------------------------------------------------------------

@router.get("", response_model=ExportRequestListResponse, summary="导出申请列表")
def list_requests(
    status: str = Query("", description="按状态筛选，空=全部"),
    keyword: str | None = Query(None, description="按提交人姓名或学号模糊搜索"),
    start: date | None = Query(None, description="提交日期起始，含当天"),
    end: date | None = Query(None, description="提交日期结束，含当天"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(committee_required),
):
    """班委能看全部申请列表（只读），管理员能审批。

    班委也能看别人的申请（姓名和类型），这样大家知道导出申请的进度，
    但只有自己的能下载（下载接口另外做权限控制）。
    """
    q = db.query(ExportRequest)
    if status:
        q = q.filter(ExportRequest.status == status)
    person_match = keyword_like(keyword, ExportRequest.student_name, ExportRequest.student_no)
    if person_match is not None:
        q = q.filter(person_match)
    q = created_between(q, ExportRequest.created_at, start, end)
    total = q.count()
    items = (
        q.order_by(desc(ExportRequest.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": [_to_response(r) for r in items]}


@router.post("/{req_id}/approve", response_model=ExportRequestResponse, summary="通过导出申请")
def approve_request(
    req_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(admin_required),
    ip: str = Depends(get_client_ip),
):
    req = db.query(ExportRequest).filter(ExportRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态为 {req.status}，无法审批")

    req.status = "approved"
    req.reviewer_name = user.display_name or user.student_no
    req.reviewer_no = user.student_no
    req.reviewed_at = datetime.now()
    db.flush()

    # 同步生成文件（班级体量小，秒级完成）
    _generate_and_save(req, db)

    # 操作日志：记一条，target_student_nos 写入全部学号
    scope_param = json.loads(req.scope_param) if req.scope_param else None
    students = resolve_students(db, req.scope_type, scope_param)
    log_target, target_nos = _log_target(students)
    log_operation(
        db, user,
        "通过导出申请",
        log_target,
        _log_detail(req.export_type, req.scope_type, len(students),
                    json.loads(req.fields) if req.fields else None),
        ip=ip,
        target_student_nos=target_nos,
    )

    # 日志和上面那批改动一起提交。别省这一步：log_operation 只 add 不 commit，
    # 请求结束时 session 直接关掉，日志会被回滚掉（通过/驳回两处的日志曾经就这么丢的）
    db.commit()

    # 通知申请人
    notify(
        db,
        background,
        recipients(db, only_no=req.student_no),
        "导出申请已通过",
        f"你申请的{_display_name_for_type(req.export_type)}已通过审核，可前往学生信息页下载",
        level="timeSensitive",
        page="/my-info?tab=workspace&sub=submitted",
    )

    db.refresh(req)
    return _to_response(req)


@router.post("/{req_id}/reject", response_model=ExportRequestResponse, summary="驳回导出申请")
def reject_request(
    req_id: int,
    body: ExportRejectRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(admin_required),
    ip: str = Depends(get_client_ip),
):
    req = db.query(ExportRequest).filter(ExportRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态为 {req.status}，无法审批")

    req.status = "rejected"
    req.reviewer_name = user.display_name or user.student_no
    req.reviewer_no = user.student_no
    req.reject_reason = body.reason
    req.reviewed_at = datetime.now()

    # 操作日志：记一条，target_student_nos 写入全部学号
    scope_param = json.loads(req.scope_param) if req.scope_param else None
    students = resolve_students(db, req.scope_type, scope_param)
    log_target, target_nos = _log_target(students)
    log_operation(
        db, user,
        "驳回导出申请",
        log_target,
        _log_detail(req.export_type, req.scope_type, len(students),
                    json.loads(req.fields) if req.fields else None)
        + f"，理由：{body.reason}",
        ip=ip,
        target_student_nos=target_nos,
    )
    # 状态改动和日志一起提交（log_operation 只 add 不 commit，见 approve 里的说明）
    db.commit()

    notify(
        db,
        background,
        recipients(db, only_no=req.student_no),
        "导出申请被驳回",
        f"你申请的{_display_name_for_type(req.export_type)}被驳回：{body.reason}",
        level="timeSensitive",
        page="/my-info?tab=workspace&sub=submitted",
    )

    return _to_response(req)
