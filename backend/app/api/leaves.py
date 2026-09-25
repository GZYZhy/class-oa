"""请假申请：学生提交，管理员审核，通过后可生成 Word 请假表"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    Query,
)
from fastapi.responses import FileResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import LeaveRequest, Student, User
from ..schemas import LeaveRequestCreate, LeaveRequestResponse, LeaveRejectRequest
from ..services import clip, display_name, log_operation, notify, recipients
from ..utils.leave_docx import generate_leave_docx
from .deps import (
    admin_required,
    committee_required,
    get_client_ip,
    get_current_student,
    get_current_user,
)

router = APIRouter(prefix="/api/leaves", tags=["请假申请"])

# 请假证明文件存放目录
LEAVE_DIR = BASE_DIR / "data" / "leaves"
LEAVE_DIR.mkdir(parents=True, exist_ok=True)

# 允许的辅助证明文件类型
ALLOWED_PROOF_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
# 单个文件大小上限 20MB
MAX_PROOF_SIZE = 20 * 1024 * 1024

# 可选的请假类型
LEAVE_TYPES = ("病假", "事假", "公假")

# 请假审批只有管理员能做（见 approve_leave），所以「待审核」的推送也只发给管理员
APPROVER_ROLES = ["admin"]


def _safe_name(original: str) -> str:
    """提取后缀，生成安全的存储文件名"""
    ext = Path(original).suffix.lower() if original else ""
    if ext not in ALLOWED_PROOF_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ext}，仅支持 PDF / 图片")
    return f"{uuid.uuid4().hex}{ext}"


def _to_response(leave: LeaveRequest) -> LeaveRequestResponse:
    return LeaveRequestResponse.model_validate(leave)


# ---------- 学生端 ----------

@router.get("/my", response_model=list[LeaveRequestResponse], summary="我的请假记录")
def my_leaves(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """当前登录学生自己的请假申请，按时间倒序"""
    rows = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.student_id == student.id)
        .order_by(desc(LeaveRequest.id))
        .all()
    )
    return [_to_response(r) for r in rows]


@router.post("", response_model=LeaveRequestResponse, summary="提交请假申请")
async def submit_leave(
    # BackgroundTasks 必须放在最前：它没有默认值，排在下面那些带默认值的参数后面会语法报错
    background: BackgroundTasks,
    leave_type: str = Form(..., description="病假/事假/公假"),
    start_at: datetime = Form(..., description="开始时间，精确到小时"),
    end_at: datetime = Form(..., description="结束时间，精确到小时"),
    reason: str = Form(..., description="请假事由"),
    travel_mode: str = Form(""),
    travel_detail: str = Form(""),
    destination: str = Form(""),
    destination_phone: str = Form(""),
    proof: UploadFile = File(..., description="请假辅助证明（图片或 PDF，必填）"),
    user: User = Depends(get_current_user),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    # 基本校验
    if leave_type not in LEAVE_TYPES:
        raise HTTPException(status_code=400, detail=f"请假类型只能是：{'/'.join(LEAVE_TYPES)}")
    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")
    if not reason.strip():
        raise HTTPException(status_code=400, detail="请假事由不能为空")

    # 校验并保存证明文件
    if not proof.filename:
        raise HTTPException(status_code=400, detail="请上传请假辅助证明")
    proof_name = _safe_name(proof.filename)
    content = await proof.read()
    if len(content) > MAX_PROOF_SIZE:
        raise HTTPException(status_code=400, detail="证明文件大小不能超过 20MB")
    save_path = LEAVE_DIR / proof_name
    with open(save_path, "wb") as f:
        f.write(content)

    leave = LeaveRequest(
        student_id=student.id,
        student_no=student.student_no,
        student_name=student.name,
        leave_type=leave_type,
        start_at=start_at,
        end_at=end_at,
        reason=reason.strip(),
        travel_mode=travel_mode.strip(),
        travel_detail=travel_detail.strip(),
        destination=destination.strip(),
        destination_phone=destination_phone.strip(),
        proof_file=proof_name,
        proof_original_name=proof.filename,
        status="pending",
    )
    db.add(leave)
    log_operation(
        db, user, "提交请假申请",
        target=f"{student.student_no} {student.name}",
        detail=f"{leave_type}：{start_at:%Y-%m-%d %H时} ~ {end_at:%Y-%m-%d %H时}",
        ip=ip,
    )
    db.commit()
    db.refresh(leave)

    # 提醒管理员来审。待办性质，用 timeSensitive 让它能穿透专注模式。
    # 跳转必须带 ?tab=leave：审批在「审核中心」页，默认停在信息修改那个 tab，
    # 不带参数的话管理员点进来看到的是「没有修改申请」
    notify(
        background,
        recipients(db, roles=APPROVER_ROLES, exclude_no=user.student_no),
        "有新的请假申请待审核",
        f"{student.name} 提交了{leave_type}，等待你审核",
        level="timeSensitive",
        page="/review?tab=leave",
    )
    return _to_response(leave)


@router.get("/{leave_id}/proof", summary="查看/下载我的请假证明")
def my_proof(
    leave_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """学生只能看自己的证明文件"""
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave or leave.student_id != student.id:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if not leave.proof_file:
        raise HTTPException(status_code=404, detail="没有证明文件")
    file_path = LEAVE_DIR / leave.proof_file
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="证明文件不存在")
    return FileResponse(
        str(file_path),
        filename=leave.proof_original_name or leave.proof_file,
    )


# ---------- 管理员端 ----------

@router.get("", response_model=list[LeaveRequestResponse], summary="请假申请列表（班委及以上可见）")
def list_leaves(
    status: str | None = Query(None, description="pending/approved/rejected，不传为全部"),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """班委可以看列表和详情，但只有管理员能审批（通过/驳回）和生成 Word"""
    query = db.query(LeaveRequest)
    if status:
        query = query.filter(LeaveRequest.status == status)
    rows = query.order_by(desc(LeaveRequest.id)).all()
    return [_to_response(r) for r in rows]


@router.get("/{leave_id}/docx", summary="下载填好的请假审批表 Word（管理员）")
def download_docx(
    leave_id: int,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """只有审核通过的申请才能生成 Word（未通过的拿了也没用）"""
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if leave.status != "approved":
        raise HTTPException(status_code=400, detail="仅审核通过的申请可生成请假表")

    student = db.query(Student).filter(Student.id == leave.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="学生信息不存在")

    docx_bytes = generate_leave_docx(student, leave)
    filename = f"{leave.student_name}_请假审批表_{leave.start_at:%Y%m%d}.docx"

    from fastapi.responses import Response
    return Response(
        content=docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            # HTTP 头只能装 latin-1，中文文件名必须按 RFC 5987 百分号编码，
            # 否则 Starlette 在编码响应头时直接抛 UnicodeEncodeError（已踩过）
            "Content-Disposition": "attachment; filename*=utf-8''" + quote(filename),
            "Cache-Control": "no-store",
        },
    )


@router.get("/{leave_id}/proof/admin", summary="下载请假证明文件（班委及以上）")
def admin_proof(
    leave_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if not leave.proof_file:
        raise HTTPException(status_code=404, detail="没有证明文件")
    file_path = LEAVE_DIR / leave.proof_file
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="证明文件不存在")
    return FileResponse(
        str(file_path),
        filename=leave.proof_original_name or leave.proof_file,
    )


@router.post("/{leave_id}/approve", response_model=LeaveRequestResponse, summary="通过请假申请")
def approve_leave(
    leave_id: int,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if leave.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理过")

    leave.status = "approved"
    leave.reviewed_at = datetime.now()
    leave.reviewer_no = user.student_no
    leave.reviewer_name = display_name(db, user)
    log_operation(
        db, user, "通过请假申请",
        target=f"{leave.student_no} {leave.student_name}",
        detail=f"{leave.leave_type}：{leave.start_at:%Y-%m-%d %H时} ~ {leave.end_at:%Y-%m-%d %H时}",
        ip=ip,
    )
    targets = recipients(db, only_no=leave.student_no)
    db.commit()
    db.refresh(leave)

    notify(
        background, targets, "请假申请已通过",
        f"你的{leave.leave_type}（{leave.start_at:%m-%d %H时} 起）已通过审核",
        level="timeSensitive",
        page="/leave",
    )
    return _to_response(leave)


@router.post("/{leave_id}/reject", response_model=LeaveRequestResponse, summary="驳回请假申请")
def reject_leave(
    leave_id: int,
    payload: LeaveRejectRequest,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if leave.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理过")

    leave.status = "rejected"
    leave.reject_reason = payload.reason.strip()
    leave.reviewed_at = datetime.now()
    leave.reviewer_no = user.student_no
    leave.reviewer_name = display_name(db, user)
    log_operation(
        db, user, "驳回请假申请",
        target=f"{leave.student_no} {leave.student_name}",
        detail=f"理由：{payload.reason.strip()}",
        ip=ip,
    )
    targets = recipients(db, only_no=leave.student_no)
    db.commit()
    db.refresh(leave)

    notify(
        background, targets, "请假申请被驳回",
        f"理由：{clip(leave.reject_reason)}", level="timeSensitive", page="/leave",
    )
    return _to_response(leave)
