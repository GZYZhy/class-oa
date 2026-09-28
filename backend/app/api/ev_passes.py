"""电动车通行证补办 API"""
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
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..config import BASE_DIR, settings
from ..database import get_db
from ..models import EvPassRequest, Student, User
from ..schemas import EvPassRequestResponse, EvPassRejectRequest
from ..services import account_name, clip, log_operation, notify, recipients
from .deps import (
    admin_required,
    committee_required,
    get_client_ip,
    get_current_user,
    is_committee,
)
from ..utils.ev_pass_docx import generate_pass_docx, generate_promise_docx
from ..utils.media_type import guess_media_type

router = APIRouter(prefix="/api/ev-passes", tags=["电动车通行证"])

# 通行证只有管理员能审批（班委只读，见下面的 admin_required / committee_required），
# 所以「待审核」的推送也只发给管理员
APPROVER_ROLES = ["admin"]

# 行驶证文件存放目录
LICENSE_DIR = BASE_DIR / "data" / "ev_passes"
LICENSE_DIR.mkdir(parents=True, exist_ok=True)

# 允许的行驶证文件类型（和请假证明一样：图片 + PDF）
ALLOWED_LICENSE_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
}
MAX_LICENSE_SIZE = 20 * 1024 * 1024  # 20MB


def _safe_license_name(original: str) -> str:
    """校验后缀并生成安全存盘名（UUID + 后缀）"""
    ext = Path(original).suffix.lower() if original else ""
    if ext not in ALLOWED_LICENSE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的行驶证文件类型：{ext or '（无后缀）'}，仅支持 PDF / 图片",
        )
    return f"{uuid.uuid4().hex}{ext}"


def _to_response(db: Session, req: EvPassRequest) -> dict:
    """把 ORM 对象转成响应体（补上学生姓名/学号）"""
    student = db.query(Student).filter(Student.id == req.student_id).first()
    return {
        "id": req.id,
        "student_id": req.student_id,
        "student_name": student.name if student else None,
        "student_no": student.student_no if student else None,
        "brand": req.brand,
        "plate_number": req.plate_number,
        "license_original_name": req.license_original_name,
        "status": req.status,
        "created_at": req.created_at,
        "reviewer_name": req.reviewer_name,
        "reviewed_at": req.reviewed_at,
        "reject_reason": req.reject_reason,
    }


# ---------- 学生端 ----------

@router.get("/my", response_model=list[EvPassRequestResponse], summary="我的电动车通行证申请")
def my_applications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前登录学生的所有申请，按时间倒序"""
    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student:
        return []
    rows = (
        db.query(EvPassRequest)
        .filter(EvPassRequest.student_id == student.id)
        .order_by(EvPassRequest.id.desc())
        .all()
    )
    return [_to_response(db, r) for r in rows]


@router.post("", response_model=EvPassRequestResponse, summary="提交电动车通行证申请")
async def submit_application(
    background: BackgroundTasks,
    brand: str = Form(..., min_length=1, max_length=100, description="电动车品牌"),
    plate_number: str = Form(..., min_length=1, max_length=50, description="车牌号"),
    license_file: UploadFile = File(..., description="行驶证照片（图片或 PDF）"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """学生提交补办申请（multipart form）"""
    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student:
        raise HTTPException(status_code=400, detail="未找到学生信息")

    # 校验行驶证
    if not license_file.filename:
        raise HTTPException(status_code=400, detail="请上传行驶证")
    safe_name = _safe_license_name(license_file.filename)
    content = await license_file.read()
    if len(content) > MAX_LICENSE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"行驶证文件超过 {MAX_LICENSE_SIZE // 1024 // 1024}MB",
        )
    save_path = LICENSE_DIR / safe_name
    with open(save_path, "wb") as f:
        f.write(content)

    req = EvPassRequest(
        student_id=student.id,
        brand=brand.strip(),
        plate_number=plate_number.strip(),
        license_file=safe_name,
        license_original_name=license_file.filename,
        status="pending",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # 提醒管理员来审。待办性质，用 timeSensitive 让它能穿透专注模式。
    # 跳转必须带 ?tab=evpass：审批在「审核中心」页，不带参数会停在信息修改那个 tab，
    # 管理员点进来看到的不是这条申请
    notify(
        background,
        recipients(db, roles=APPROVER_ROLES, exclude_no=user.student_no),
        "有新的电动车通行证补办申请",
        f"{student.name} 提交了电动车通行证补办申请，等待你审核",
        level="timeSensitive",
        page="/review?tab=evpass",
    )
    return _to_response(db, req)


@router.get("/{req_id}/license", summary="查看我的行驶证")
def my_license(
    req_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """学生查看自己的行驶证"""
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student or req.student_id != student.id:
        raise HTTPException(status_code=403, detail="无权查看")
    if not req.license_file:
        raise HTTPException(status_code=404, detail="没有行驶证文件")
    file_path = LICENSE_DIR / Path(req.license_file).name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="行驶证文件不存在")
    # 交给 FileResponse 处理文件名：它会按 RFC 5987 编码，中文名才不会炸
    # （别手拼 Content-Disposition，HTTP 头只装得下 latin-1）
    return FileResponse(
        str(file_path),
        # 显式给类型：猜不出来时 Starlette 兜底成 text/plain（见 utils/media_type.py）
        media_type=guess_media_type(req.license_original_name, req.license_file),
        filename=req.license_original_name or req.license_file,
        content_disposition_type="inline",
    )


def _docx_target(db: Session, req_id: int, user: User) -> tuple[EvPassRequest, Student]:
    """取回申请和申请人，并校验「能不能下载生成的文档」

    能下载的是两类人：申请人本人（拿去打印签字），以及班委及以上
    （要留档、要报学院盖章）。其余人一律不行 —— 表里是学生本人的个人信息。
    两份文档的权限完全一样，所以收在一处，免得以后改一个漏一个。
    """
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    student = db.query(Student).filter(Student.id == req.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="申请人信息不存在")
    if not is_committee(user) and student.student_no != user.student_no:
        raise HTTPException(status_code=403, detail="无权下载")
    if req.status != "approved":
        raise HTTPException(status_code=400, detail="申请未通过，暂不能下载")
    return req, student


def _docx_response(content: bytes, filename: str) -> Response:
    """下载 Word 的响应

    文件名必须按 RFC 5987 百分号编码：HTTP 头只装得下 latin-1，
    直接塞中文名会让 Starlette 在编码响应头时抛 UnicodeEncodeError
    """
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": "attachment; filename*=utf-8''" + quote(filename),
            "Cache-Control": "no-store",
        },
    )


@router.get("/{req_id}/pass-docx", summary="下载电动车通行证申请表（Word）")
def download_pass_docx(
    req_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载申请表：本人或班委及以上，且仅已通过的可下载"""
    req, student = _docx_target(db, req_id, user)
    today = datetime.now().strftime("%Y%m%d")
    return _docx_response(
        generate_pass_docx(student, req),
        f"{student.name}_电动车通行证申请表_{today}.docx",
    )


@router.get("/{req_id}/promise-docx", summary="下载电动车使用承诺书（Word）")
def download_promise_docx(
    req_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载承诺书：本人或班委及以上，且仅已通过的可下载"""
    req, student = _docx_target(db, req_id, user)
    today = datetime.now().strftime("%Y%m%d")
    return _docx_response(
        generate_promise_docx(student, req),
        f"{student.name}_电动车承诺书_{today}.docx",
    )


# ---------- 管理员 / 班委审核 ----------

@router.get(
    "",
    response_model=list[EvPassRequestResponse],
    summary="电动车通行证申请列表（班委及以上）",
)
def list_applications(
    status: str | None = Query(None, description="按状态筛选：pending/approved/rejected"),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    query = db.query(EvPassRequest)
    if status:
        query = query.filter(EvPassRequest.status == status)
    rows = query.order_by(EvPassRequest.id.desc()).all()
    return [_to_response(db, r) for r in rows]


@router.post("/{req_id}/approve", summary="通过申请（管理员）")
def approve_application(
    req_id: int,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status == "approved":
        return {"message": "已通过"}
    req.status = "approved"
    req.reviewer_no = user.student_no
    req.reviewer_name = account_name(db, user)
    req.reviewed_at = datetime.now()
    req.reject_reason = None

    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "通过电动车通行证",
        target=student.name if student else f"id={req.student_id}",
        detail=f"品牌：{req.brand}，车牌：{req.plate_number}",
        ip=ip,
    )
    # 收件人在 commit 之前定下来（和请假一致）。申请人不在学生表里就没什么可发的，
    # 别退化成「only_no 为 None」——那在 recipients 里等于不筛人，会推给全班
    targets = recipients(db, only_no=student.student_no) if student else None
    db.commit()

    if targets:
        notify(
            background, targets, "电动车通行证申请已通过",
            f"你的电动车通行证申请（{req.plate_number}）已通过，现在可以下载申请表和承诺书",
            level="timeSensitive", page="/ev-pass",
        )
    return {"message": "已通过"}


@router.post("/{req_id}/reject", summary="驳回申请（管理员）")
def reject_application(
    req_id: int,
    body: EvPassRejectRequest,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    req.status = "rejected"
    req.reviewer_no = user.student_no
    req.reviewer_name = account_name(db, user)
    req.reviewed_at = datetime.now()
    req.reject_reason = body.reason.strip()

    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "驳回电动车通行证",
        target=student.name if student else f"id={req.student_id}",
        detail=f"原因：{body.reason}",
        ip=ip,
    )
    targets = recipients(db, only_no=student.student_no) if student else None
    db.commit()

    if targets:
        notify(
            background, targets, "电动车通行证申请被驳回",
            f"牌照号 {req.plate_number}，理由：{clip(req.reject_reason)}",
            level="timeSensitive", page="/ev-pass",
        )
    return {"message": "已驳回"}


@router.get("/{req_id}/license/admin", summary="查看行驶证（班委及以上）")
def admin_license(
    req_id: int,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if not req.license_file:
        raise HTTPException(status_code=404, detail="没有行驶证文件")
    file_path = LICENSE_DIR / Path(req.license_file).name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="行驶证文件不存在")
    return FileResponse(
        str(file_path),
        # 显式给类型：猜不出来时 Starlette 兜底成 text/plain（见 utils/media_type.py）
        media_type=guess_media_type(req.license_original_name, req.license_file),
        filename=req.license_original_name or req.license_file,
        content_disposition_type="inline",
    )
