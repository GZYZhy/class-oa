"""证明（介绍信）开具 API"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Path as PathParam,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import CertificateRequest, Student, User
from ..schemas import CertificateRequestResponse, CertificateRejectRequest
from ..services import account_name, clip, log_operation, notify, recipients
from .deps import (
    admin_required,
    committee_required,
    get_client_ip,
    get_current_user,
    is_committee,
)
from ..utils.media_type import guess_media_type

router = APIRouter(prefix="/api/certificates", tags=["证明开具"])

# 审批权：只有管理员
APPROVER_ROLES = ["admin"]

# 附件存放目录
ATTACH_DIR = BASE_DIR / "data" / "certificates" / "attachments"
ATTACH_DIR.mkdir(parents=True, exist_ok=True)

# 成品 PDF 存放目录
RESULT_DIR = BASE_DIR / "data" / "certificates" / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# 允许的附件类型：PDF / 图片 / Word
ALLOWED_ATTACH_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".doc", ".docx",
}
MAX_ATTACH_SIZE = 20 * 1024 * 1024  # 20MB
MAX_ATTACHMENTS = 3

# 成品 PDF 允许的后缀
ALLOWED_RESULT_EXTENSIONS = {".pdf"}
MAX_RESULT_SIZE = 20 * 1024 * 1024


def _safe_attach_name(original: str) -> str:
    """校验附件后缀并生成安全存盘名"""
    ext = Path(original).suffix.lower() if original else ""
    if ext not in ALLOWED_ATTACH_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的附件类型：{ext or '（无后缀）'}，仅支持 PDF / 图片 / Word",
        )
    return f"{uuid.uuid4().hex}{ext}"


def _safe_result_name(original: str) -> str:
    """校验成品 PDF 后缀并生成安全存盘名"""
    ext = Path(original).suffix.lower() if original else ""
    if ext not in ALLOWED_RESULT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"成品文件只能是 PDF，当前类型：{ext or '（无后缀）'}",
        )
    return f"{uuid.uuid4().hex}{ext}"


def _load_attachments(req: CertificateRequest) -> list[dict]:
    """从 TEXT 列解析附件 JSON"""
    if not req.attachments:
        return []
    try:
        items = json.loads(req.attachments)
        return items if isinstance(items, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def student_files(db: Session, student_id: int) -> list[Path]:
    """该生全部证明申请占用的磁盘文件（附件 + 成品 PDF）

    删学生会连带删掉这些申请记录（见 student_service.delete_student），记录一没，
    文件就成了没人引用的孤儿。所以在删之前先把路径收出来，**等事务提交成功之后**
    再清磁盘 —— 中途失败时文件还得留着（和删学生照片同一个套路）。

    只收集、不动磁盘。
    """
    paths: list[Path] = []
    reqs = (
        db.query(CertificateRequest)
        .filter(CertificateRequest.student_id == student_id)
        .all()
    )
    for req in reqs:
        for item in _load_attachments(req):
            name = item.get("file") if isinstance(item, dict) else None
            if name:
                # 取 basename：存盘名本是 uuid，但手工放进来的文件名不该能跑到目录外
                paths.append(ATTACH_DIR / Path(name).name)
        if req.result_file:
            paths.append(RESULT_DIR / Path(req.result_file).name)
    return paths


def _to_response(db: Session, req: CertificateRequest) -> dict:
    """把 ORM 对象转成响应体（补上学生姓名/学号 + 解析附件）"""
    student = db.query(Student).filter(Student.id == req.student_id).first()
    return {
        "id": req.id,
        "student_id": req.student_id,
        "student_name": student.name if student else None,
        "student_no": student.student_no if student else None,
        "title": req.title,
        "recipient": req.recipient,
        "content": req.content,
        "extra_request": req.extra_request,
        "attachments": _load_attachments(req),
        "status": req.status,
        "created_at": req.created_at,
        "reviewer_name": req.reviewer_name,
        "reviewed_at": req.reviewed_at,
        "reject_reason": req.reject_reason,
        "result_original_name": req.result_original_name,
    }


# ---------- 学生端 ----------

@router.get("/my", response_model=list[CertificateRequestResponse], summary="我的证明申请")
def my_applications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前登录学生的所有申请，按时间倒序"""
    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student:
        return []
    rows = (
        db.query(CertificateRequest)
        .filter(CertificateRequest.student_id == student.id)
        .order_by(CertificateRequest.id.desc())
        .all()
    )
    return [_to_response(db, r) for r in rows]


@router.post("", response_model=CertificateRequestResponse, summary="提交证明开具申请")
async def submit_application(
    background: BackgroundTasks,
    title: str = Form(..., min_length=1, max_length=200, description="证明标题"),
    recipient: str = Form("", max_length=200, description="收文单位"),
    content: str = Form("", max_length=3000, description="证明正文"),
    extra_request: str = Form("", max_length=1000, description="其他要求"),
    attachments: list[UploadFile] = File(default=[], description="申请依据附件，最多 3 个"),
    confirmed: bool = Form(False, description="是否确认信息真实并已联系班委"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """学生提交证明开具申请（multipart form）"""
    if not confirmed:
        raise HTTPException(status_code=400, detail="请勾选确认事项")

    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student:
        raise HTTPException(status_code=400, detail="未找到学生信息")

    if len(attachments) > MAX_ATTACHMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_ATTACHMENTS} 个附件",
        )

    # 保存附件
    saved = []
    try:
        for f in attachments:
            if not f.filename:
                continue
            safe_name = _safe_attach_name(f.filename)
            data = await f.read()
            if len(data) > MAX_ATTACH_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"附件「{f.filename}」超过 {MAX_ATTACH_SIZE // 1024 // 1024}MB",
                )
            save_path = ATTACH_DIR / safe_name
            with open(save_path, "wb") as fp:
                fp.write(data)
            saved.append({
                "file": safe_name,
                "name": f.filename,
                "size": len(data),
            })
    except HTTPException:
        # 校验失败：删除已保存的文件
        for item in saved:
            p = ATTACH_DIR / item["file"]
            if p.exists():
                p.unlink()
        raise

    req = CertificateRequest(
        student_id=student.id,
        title=title.strip(),
        recipient=recipient.strip(),
        content=content.strip(),
        extra_request=extra_request.strip(),
        attachments=json.dumps(saved, ensure_ascii=False),
        status="pending",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # 通知管理员。**不排除提交人自己**：管理员给自己提的申请也等着他审
    # （理由见 notify_service.recipients，四个办件提交接口口径一致）
    notify(
        db,
        background,
        recipients(db, roles=APPROVER_ROLES),
        "有新的证明开具申请",
        f"{student.name} 提交了证明开具申请（{req.title}），等待你审核",
        level="timeSensitive",
        page="/review?tab=certificate",
    )
    return _to_response(db, req)


@router.get("/{req_id}/attachment/{index}", summary="查看我的申请附件")
def my_attachment(
    req_id: int,
    index: int = PathParam(..., ge=0, description="附件下标"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """学生查看自己提交的附件"""
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student or req.student_id != student.id:
        raise HTTPException(status_code=403, detail="无权查看")
    items = _load_attachments(req)
    if index >= len(items):
        raise HTTPException(status_code=404, detail="附件不存在")
    item = items[index]
    file_path = ATTACH_DIR / item["file"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="附件文件不存在")
    return FileResponse(
        str(file_path),
        media_type=guess_media_type(item["name"], item["file"]),
        filename=item["name"],
        content_disposition_type="inline",
    )


@router.get("/{req_id}/result", summary="下载成品证明 PDF（本人）")
def download_result(
    req_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """学生下载自己申请的成品 PDF（仅已通过状态）"""
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student or req.student_id != student.id:
        raise HTTPException(status_code=403, detail="无权下载")
    if req.status != "approved":
        raise HTTPException(status_code=400, detail="申请未通过，暂不能下载")
    if not req.result_file:
        raise HTTPException(status_code=404, detail="成品文件尚未上传")
    file_path = RESULT_DIR / req.result_file
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="成品文件不存在")
    return FileResponse(
        str(file_path),
        media_type=guess_media_type(req.result_original_name, req.result_file),
        filename=req.result_original_name or req.result_file,
        content_disposition_type="attachment",
    )


# ---------- 班委及以上 ----------

@router.get(
    "",
    response_model=list[CertificateRequestResponse],
    summary="证明申请列表（班委及以上）",
)
def list_applications(
    status: str | None = Query(None, description="按状态筛选：pending/approved/rejected"),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    query = db.query(CertificateRequest)
    if status:
        query = query.filter(CertificateRequest.status == status)
    rows = query.order_by(CertificateRequest.id.desc()).all()
    return [_to_response(db, r) for r in rows]


@router.get("/{req_id}/attachment/{index}/admin", summary="查看申请附件（班委及以上）")
def admin_attachment(
    req_id: int,
    index: int = PathParam(..., ge=0, description="附件下标"),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    items = _load_attachments(req)
    if index >= len(items):
        raise HTTPException(status_code=404, detail="附件不存在")
    item = items[index]
    file_path = ATTACH_DIR / item["file"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="附件文件不存在")
    return FileResponse(
        str(file_path),
        media_type=guess_media_type(item["name"], item["file"]),
        filename=item["name"],
        content_disposition_type="inline",
    )


# ---------- 管理员 ----------

@router.post("/{req_id}/approve", summary="通过申请（管理员）")
def approve_application(
    req_id: int,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
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
        db, user, "通过证明开具",
        target=student.name if student else f"id={req.student_id}",
        detail=f"标题：{req.title}，收文单位：{req.recipient}",
        ip=ip,
    )
    targets = recipients(db, only_no=student.student_no) if student else None
    db.commit()

    if targets:
        notify(
            db, background, targets, "证明开具申请已通过",
            f"你的证明申请（{req.title}）已通过，请在成品上传后下载",
            level="timeSensitive", page="/my-info?tab=workspace&sub=submitted",
        )
    return {"message": "已通过"}


@router.post("/{req_id}/reject", summary="驳回申请（管理员）")
def reject_application(
    req_id: int,
    body: CertificateRejectRequest,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    req.status = "rejected"
    req.reviewer_no = user.student_no
    req.reviewer_name = account_name(db, user)
    req.reviewed_at = datetime.now()
    req.reject_reason = body.reason.strip()

    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "驳回证明开具",
        target=student.name if student else f"id={req.student_id}",
        detail=f"原因：{body.reason}",
        ip=ip,
    )
    targets = recipients(db, only_no=student.student_no) if student else None
    db.commit()

    if targets:
        notify(
            db, background, targets, "证明开具申请被驳回",
            f"标题：{req.title}，理由：{clip(req.reject_reason)}",
            level="timeSensitive", page="/my-info?tab=workspace&sub=submitted",
        )
    return {"message": "已驳回"}


@router.post("/{req_id}/result", summary="上传成品证明 PDF（管理员）")
async def upload_result(
    req_id: int,
    background: BackgroundTasks,
    file: UploadFile = File(..., description="成品 PDF"),
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """管理员上传成品证明 PDF。申请须已通过，覆盖已有的成品文件。"""
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "approved":
        raise HTTPException(status_code=400, detail="申请未通过，不能上传成品")
    if not file.filename:
        raise HTTPException(status_code=400, detail="请上传成品 PDF 文件")

    safe_name = _safe_result_name(file.filename)
    data = await file.read()
    if len(data) > MAX_RESULT_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"成品文件超过 {MAX_RESULT_SIZE // 1024 // 1024}MB",
        )

    # 先写新文件
    save_path = RESULT_DIR / safe_name
    with open(save_path, "wb") as fp:
        fp.write(data)

    # 旧文件名（删旧文件用）
    old_file = req.result_file

    req.result_file = safe_name
    req.result_original_name = file.filename

    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "上传证明成品",
        target=student.name if student else f"id={req.student_id}",
        detail=f"标题：{req.title}，文件名：{file.filename}",
        ip=ip,
    )
    targets = recipients(db, only_no=student.student_no) if student else None
    db.commit()

    # 删旧成品
    if old_file and old_file != safe_name:
        old_path = RESULT_DIR / old_file
        if old_path.exists():
            old_path.unlink()

    if targets:
        notify(
            db, background, targets, "证明已开好",
            f"你的证明（{req.title}）已开好，现在可以下载",
            level="timeSensitive", page="/my-info?tab=workspace&sub=submitted",
        )
    return {"message": "上传成功", "result_original_name": file.filename}


@router.get("/{req_id}/result/admin", summary="下载成品证明 PDF（管理员）")
def admin_download_result(
    req_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """管理员下载成品 PDF。班委不可下（用 admin_required 锁住）。"""
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if not req.result_file:
        raise HTTPException(status_code=404, detail="成品文件尚未上传")
    file_path = RESULT_DIR / req.result_file
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="成品文件不存在")
    return FileResponse(
        str(file_path),
        media_type=guess_media_type(req.result_original_name, req.result_file),
        filename=req.result_original_name or req.result_file,
        content_disposition_type="attachment",
    )
