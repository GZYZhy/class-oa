"""证明（介绍信）开具 API"""
import json
import os
import uuid
from datetime import date, datetime
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
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import CertificateRequest, Student, User
from ..schemas import (
    CertificateCorrectRequest,
    CertificateRejectRequest,
    CertificateRequestResponse,
)
from ..services import account_name, clip, log_operation, notify, recipients
from ..services.list_filters import created_between, keyword_like
from ..services.review_flow import (
    ADMIN_TODO,
    CLOSED,
    STATUS_CORRECTING,
    STATUS_PENDING,
    STATUS_REVOKED,
    accept,
    correct,
    require_accepted,
    resubmit,
    unaccept,
)
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

# 附件存放目录。吃环境变量是为了测试能指到临时目录去 —— 不吃的话用例一上传附件
# 就写进本机演示库的真目录，而且事后没人清得掉（照 PHOTO_DIR / LEAVE_DIR 的先例）
ATTACH_DIR = Path(os.environ.get("CERT_ATTACH_DIR") or BASE_DIR / "data" / "certificates" / "attachments")
ATTACH_DIR.mkdir(parents=True, exist_ok=True)

# 成品 PDF 存放目录（同上，测试要能隔离）
RESULT_DIR = Path(os.environ.get("CERT_RESULT_DIR") or BASE_DIR / "data" / "certificates" / "results")
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


async def _save_attachments(files: list[UploadFile]) -> list[dict]:
    """校验并落盘一批附件，返回 [{file, name, size}]（提交与修改共用）

    中途校验失败会把这一趟已经落盘的文件删掉再抛 —— 不然磁盘上留一堆没人引用的
    孤儿文件（照原来的写法）。
    """
    if len(files) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"最多上传 {MAX_ATTACHMENTS} 个附件")

    saved: list[dict] = []
    try:
        for f in files:
            if not f.filename:
                continue
            safe_name = _safe_attach_name(f.filename)
            data = await f.read()
            if len(data) > MAX_ATTACH_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"附件「{f.filename}」超过 {MAX_ATTACH_SIZE // 1024 // 1024}MB",
                )
            with open(ATTACH_DIR / safe_name, "wb") as fp:
                fp.write(data)
            saved.append({"file": safe_name, "name": f.filename, "size": len(data)})
    except HTTPException:
        for item in saved:
            (ATTACH_DIR / item["file"]).unlink(missing_ok=True)
        raise
    return saved


def _drop_attachments(items: list[dict]) -> None:
    """删掉一批附件的磁盘文件（撤销、换附件时用；只删文件，不动记录）"""
    for item in items:
        name = item.get("file") if isinstance(item, dict) else None
        if name:
            (ATTACH_DIR / Path(name).name).unlink(missing_ok=True)


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
        "correction_reason": req.correction_reason,
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

    saved = await _save_attachments(attachments)

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


@router.put("/{req_id}", response_model=CertificateRequestResponse, summary="修改证明申请（未办结时）")
async def update_application(
    req_id: int,
    title: str = Form(..., min_length=1, max_length=200, description="证明标题"),
    recipient: str = Form("", max_length=200, description="收文单位"),
    content: str = Form("", max_length=3000, description="证明正文"),
    extra_request: str = Form("", max_length=1000, description="其他要求"),
    # 不传附件 = 原来那批不动（前端编辑时没法把服务端的文件再传一遍）；
    # 传了就**整批换掉**，旧文件在提交成功后删。所以「把附件全删光」做不到，
    # 只能换不能减 —— 真要去掉附件，撤销重交
    attachments: list[UploadFile] | None = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """申请人自己改：待受理、待补正这两种状态能改，其余一律 400

    字段是**整套覆盖**，跟重新提交一次一样 —— 少传一个就等于清空它，所以前端
    编辑时必须把原值都带上。

    改完的落点分两种（见 review_flow.resubmit）：原本待补正的回到「已受理」——
    待补正也算已受理，受理没被撤销，只是材料要补齐，补完不必让班委再看一遍；
    原本待受理的仍是待受理，它本来就还没人看过。
    """
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student or req.student_id != student.id:
        raise HTTPException(status_code=403, detail="无权修改")
    if req.status not in (STATUS_PENDING, STATUS_CORRECTING):
        raise HTTPException(
            status_code=400,
            detail="该申请已受理，需要修改请联系班委先撤回受理",
        )

    old_items = _load_attachments(req)
    replaced = bool(attachments)
    if replaced:
        saved = await _save_attachments(attachments)
        req.attachments = json.dumps(saved, ensure_ascii=False)

    req.title = title.strip()
    req.recipient = recipient.strip()
    req.content = content.strip()
    req.extra_request = extra_request.strip()
    resubmit(req)

    log_operation(
        db, user, "修改证明开具申请",
        target=f"{student.student_no} {student.name}",
        detail=f"标题：{req.title}",
        ip=ip,
    )
    db.commit()
    # 提交成功了再删旧附件：反过来的话 commit 一失败，学生手里就只剩一条指着
    # 不存在文件的记录
    if replaced:
        _drop_attachments(old_items)
    db.refresh(req)
    return _to_response(db, req)


@router.delete("/{req_id}", summary="撤销证明申请（待受理时）")
def delete_application(
    req_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """申请人自己撤：**只有「待受理」能撤**，直接删掉记录和盘上的附件

    已受理的不给撤（那是班委看过、正在走流程的单子，要撤得先让班委撤回受理）；
    待补正的不给撤（是让补材料，不是让放弃，真不想办了跟班委说一声）。
    撤销**不留档、不通知**：撤回一条自己刚交的东西，不需要惊动谁。
    """
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student or req.student_id != student.id:
        raise HTTPException(status_code=403, detail="无权撤销")
    if req.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail="该申请已进入受理流程，不能撤销")

    log_operation(
        db, user, "撤销证明开具申请",
        target=f"{student.student_no} {student.name}",
        detail=f"标题：{req.title}",
        ip=ip,
    )
    items = _load_attachments(req)
    db.delete(req)
    db.commit()
    _drop_attachments(items)
    return {"ok": True}


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
    if req.status == STATUS_REVOKED:
        raise HTTPException(status_code=400, detail="该申请已撤销，不再提供成品证明")
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
    status: str | None = Query(
        None,
        description="按状态筛选：pending/accepted/correcting/approved/rejected/revoked；"
                    "open = 待处理（待受理+已受理），closed = 已办结（已通过+已驳回+已撤销）",
    ),
    keyword: str | None = Query(None, description="按提交人姓名或学号模糊搜索"),
    start: date | None = Query(None, description="提交日期起始，含当天"),
    end: date | None = Query(None, description="提交日期结束，含当天"),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    query = db.query(CertificateRequest)
    if status == "open":
        # 「待处理」那一档：受理后状态会从 pending 变成 accepted，只看 pending 的话
        # 「受理」看起来像把申请弄丢了，而菜单红点还照数它（见 review_flow.ADMIN_TODO）
        query = query.filter(CertificateRequest.status.in_(ADMIN_TODO))
    elif status == "closed":
        # 「已办结」= 三个终态。筛选器上就四档：待处理 / 待补正 / 已办结 / 全部 ——
        # 待受理与已受理合在「待处理」里（都要同一个人动手），已通过、已驳回和已撤销
        # 合在「已办结」里（谁都不用再动手），具体是哪个状态看行上的 tag
        query = query.filter(CertificateRequest.status.in_(CLOSED))
    elif status:
        query = query.filter(CertificateRequest.status == status)

    # 同电动车：姓名/学号在学生表，用子查询圈 id
    person_match = keyword_like(keyword, Student.name, Student.student_no)
    if person_match is not None:
        query = query.filter(
            CertificateRequest.student_id.in_(select(Student.id).where(person_match))
        )
    query = created_between(query, CertificateRequest.created_at, start, end)

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

@router.post("/{req_id}/accept", summary="受理申请（管理员）")
def accept_application(
    req_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """受理：这份材料看过了，可以进入审批

    前端在管理员打开附件时顺手发一个，另有一个「受理」按钮兜底 —— 证明的附件是
    **可选**的，一条没带附件的申请没有「打开材料」这个动作，只靠自动受理会永久卡死。
    已经受理过的原样返回（幂等）。

    **不发通知**（用户口径）：受理只是审批人自己的一步，学生那边只看到状态变了；
    也不碰 reviewer_no / reviewed_at —— 那是审批结果的一部分。
    """
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if accept(req):
        student = db.query(Student).filter(Student.id == req.student_id).first()
        log_operation(
            db, user, "受理证明开具申请",
            target=student.name if student else f"id={req.student_id}",
            detail=f"标题：{req.title}",
            ip=ip,
        )
        db.commit()
        db.refresh(req)
    return _to_response(db, req)


@router.post("/{req_id}/unaccept", summary="撤回受理（管理员）")
def unaccept_application(
    req_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """受理点错了的回头路：已受理 → 待受理

    只退受理，不动审批结果 —— 已办结（通过/驳回）的单子本来就退不回来：审批一旦
    发出（通知已推送、成品 PDF 已上传），静默改写等于篡改已发出的正式单据
    （与「补签字不重审」同一条口径）。
    """
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if not unaccept(req):
        raise HTTPException(status_code=400, detail="该申请不在「已受理」状态，撤回不了")
    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "撤回受理证明开具申请",
        target=student.name if student else f"id={req.student_id}",
        detail=f"标题：{req.title}",
        ip=ip,
    )
    db.commit()
    db.refresh(req)
    return _to_response(db, req)


@router.post("/{req_id}/correcting", summary="退回补正（管理员）")
def correcting_application(
    req_id: int,
    body: CertificateCorrectRequest,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """材料不对，打回让申请人补齐（带理由，申请人看得见）

    和驳回分开：驳回是「这件事不批了」，补正是「补齐了还能批」。学生改完重交会回到
    「已受理」—— 受理没被撤销，不必让班委再看一遍。

    退回补正**要发通知**：这是一句需要学生动手的交代，不喊一声他不会知道材料被退回来了。
    """
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if not correct(req, body.reason):
        raise HTTPException(status_code=400, detail="只有已受理的申请才能退回补正")
    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "退回补正证明开具申请",
        target=student.name if student else f"id={req.student_id}",
        detail=f"理由：{body.reason.strip()}",
        ip=ip,
    )
    targets = recipients(db, only_no=student.student_no) if student else None
    db.commit()
    db.refresh(req)

    if targets:
        notify(
            db, background, targets, "证明开具申请需要补交材料",
            f"标题：{req.title}，理由：{clip(req.correction_reason)}",
            level="timeSensitive", page="/certificate?tab=record",
        )
    return _to_response(db, req)


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
    # 已经通过的重复点一次算无事发生（幂等）；其余的交给守卫 —— 得先受理过，
    # 已驳回的也不能再翻成通过（这条原先漏着）
    if req.status == "approved":
        return {"message": "已通过"}
    require_accepted(req)
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
            level="timeSensitive", page="/certificate?tab=record",
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
    # 原先这里一句检查都没有：已通过的单子还能再驳回一次，状态当场翻回去
    require_accepted(req)
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
            level="timeSensitive", page="/certificate?tab=record",
        )
    return {"message": "已驳回"}


@router.post("/{req_id}/revoke", summary="撤销已通过的申请（管理员）")
def revoke_application(
    req_id: int,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """把一条已通过的申请撤了：状态变成「已撤销」，申请人不能再编辑、不再下载成品

    **撤销是终态，没有反向操作**：撤销后它也不能再批，成品也不能再上传（上传接口
    要求已通过）。要发通知 —— 申请人可能已经拿到打印件，不喊一声不会知道作废了。
    """
    req = db.query(CertificateRequest).filter(CertificateRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "approved":
        raise HTTPException(status_code=400, detail="只有已通过的申请才能撤销")

    req.status = STATUS_REVOKED
    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "撤销已通过的证明开具",
        target=student.name if student else f"id={req.student_id}",
        detail=f"标题：{req.title}",
        ip=ip,
    )
    targets = recipients(db, only_no=student.student_no) if student else None
    db.commit()

    if targets:
        notify(
            db, background, targets, "证明开具申请已撤销",
            f"你的证明申请（{req.title}）已被管理员撤销",
            level="timeSensitive", page="/certificate?tab=record",
        )
    return {"message": "已撤销"}


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
            level="timeSensitive", page="/certificate?tab=record",
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
    if req.status == STATUS_REVOKED:
        raise HTTPException(status_code=400, detail="该申请已撤销，不再提供成品证明")
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
