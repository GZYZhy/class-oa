"""学生信息导出申请

班委提交 → 管理员审核 → 通过后生成文件 → 下载。

两种导出类型：
- excel_list：名单 Excel，可选字段
- pdf_individual：个人信息表 PDF（每人一份，打包 zip）

PDF 自动打不可见水印，溯源是谁导出的。
"""

import json
import uuid
from datetime import datetime
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
    log_operation,
    make_watermark_token,
    notify,
    recipients,
)
from ..services.export_service import (
    DEFAULT_FIELDS,
    FIELD_MAP,
    generate_excel,
    generate_individual_pdfs,
    get_default_fields,
    get_field_groups,
    resolve_students,
)
from .deps import admin_required, committee_required, get_current_user

router = APIRouter(prefix="/api/export-requests", tags=["学生信息导出"])

# 导出文件存放目录
EXPORT_DIR = BASE_DIR / "data" / "exports"
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

        # 水印 token：file_id 用导出申请 ID
        token = make_watermark_token(req.id, req.student_no)

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

    # 操作日志的 target 写「被导出的人」：写人数 + 第一个人的学号姓名，
    # 反查被操作记录时能按代表的学号查到这条日志（显示「张三等 N 人」）
    students = resolve_students(db, body.scope_type, body.scope_param)
    if students:
        first = students[0]
        log_target = f"{first.student_no} {first.name}等{len(students)}人"
    else:
        log_target = "无匹配学生"

    log_operation(
        db, user,
        "提交导出申请",
        log_target,
        f"{_display_name_for_type(body.export_type)}，范围：{body.scope_type}",
    )

    # 推送给管理员
    notify(
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

@router.get("", response_model=ExportRequestListResponse, summary="导出申请列表（管理员）")
def list_requests(
    status: str = Query("", description="按状态筛选，空=全部"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(admin_required),
):
    q = db.query(ExportRequest)
    if status:
        q = q.filter(ExportRequest.status == status)
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

    # 操作日志 target：被导出的学生代表
    scope_param = json.loads(req.scope_param) if req.scope_param else None
    students = resolve_students(db, req.scope_type, scope_param)
    if students:
        first = students[0]
        log_target = f"{first.student_no} {first.name}等{len(students)}人"
    else:
        log_target = "无匹配学生"

    log_operation(
        db, user,
        "通过导出申请",
        log_target,
        f"{_display_name_for_type(req.export_type)}",
    )

    # 通知申请人
    notify(
        background,
        recipients(db, only_no=req.student_no),
        "导出申请已通过",
        f"你申请的{_display_name_for_type(req.export_type)}已通过审核，可前往学生信息页下载",
        level="timeSensitive",
        page="/students",
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
    db.commit()
    db.refresh(req)

    # 操作日志 target：被导出的学生代表
    scope_param = json.loads(req.scope_param) if req.scope_param else None
    students = resolve_students(db, req.scope_type, scope_param)
    if students:
        first = students[0]
        log_target = f"{first.student_no} {first.name}等{len(students)}人"
    else:
        log_target = "无匹配学生"

    log_operation(
        db, user,
        "驳回导出申请",
        log_target,
        f"{_display_name_for_type(req.export_type)}，理由：{body.reason}",
    )

    notify(
        background,
        recipients(db, only_no=req.student_no),
        "导出申请被驳回",
        f"你申请的{_display_name_for_type(req.export_type)}被驳回：{body.reason}",
        level="timeSensitive",
        page="/students",
    )

    return _to_response(req)
