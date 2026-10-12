"""请假申请：学生提交，管理员审核（批准时可填班导师意见、选谁的签字），
通过后申请人本人和管理员都能下载生成好的 PDF 请假审批表（带不可见溯源水印）
"""

import os
import shutil
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
from fastapi.responses import FileResponse, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import LeaveRequest, Student, User
from ..schemas import (
    LeaveAdvisorSignature,
    LeaveRequestCreate,
    LeaveRequestResponse,
    LeaveRejectRequest,
)
from ..services import (
    TOKEN_SOURCE_LEAVE,
    add_invisible_watermark,
    clip,
    display_name,
    log_operation,
    make_watermark_token,
    notify,
    recipients,
)
from ..services.student_photo_service import sign_photo_path, user_sign_photo_path
from ..utils.leave_pdf import generate_leave_pdf
from ..utils.media_type import guess_media_type
from .deps import (
    admin_required,
    committee_required,
    get_client_ip,
    get_current_student,
    get_current_user,
    is_admin,
)

router = APIRouter(prefix="/api/leaves", tags=["请假申请"])

# 请假相关文件（辅助证明、班导师签字图副本）存放目录。
# 吃环境变量是为了测试能指到临时目录去 —— 不吃的话接口测试一调「批准（带签字）」
# 就会往本机演示库的真目录里写文件（照 PHOTO_DIR 的先例）
LEAVE_DIR = Path(os.environ.get("LEAVE_DIR") or BASE_DIR / "data" / "leaves")
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
    resp = LeaveRequestResponse.model_validate(leave)
    # 派生字段：只要「签没签」。签字图副本的文件名不进响应 —— 前端拿不到它
    # 也就拼不出别的下载地址，需要看图时照旧走签字审批那条链
    resp.has_advisor_sign = bool(leave.advisor_sign_file)
    return resp


def _signer_photo(db: Session, student_no: str) -> tuple[Path, User] | None:
    """某登录名能不能当签字人：返回 (签字图路径, 账号)，不能就返回 None

    域外账号的签字图存 users.sign_photo、在册学生存 students.sign_photo，
    按 is_external 分流 —— 两边「同等权限」的账号在签字这件事上也同等
    （用户口径：可以用包含域外同等权限在内的某个管理员的签字）。

    **图必须在盘上**：库里留着文件名、文件却被删掉的情况是有的，
    候选人列表里就不该出现一个选了却插不进表的空签字。
    """
    user = db.query(User).filter(User.student_no == student_no).first()
    if not user:
        return None
    if user.is_external:
        path = user_sign_photo_path(user)
    else:
        student = db.query(Student).filter(Student.student_no == student_no).first()
        path = sign_photo_path(student) if student else None
    if not path or not path.exists():
        return None
    return path, user


def _save_signature_copy(db: Session, sign_no: str, leave_id: int) -> tuple[Path, str]:
    """把选中的签字图复制一份进 LEAVE_DIR，返回 (副本路径, 签字人姓名)

    存副本而不是只记原图名，是为了让「用批准当时那张」这句承诺站得住：
    原图被换掉或删掉时（换图/删图接口都有），历史单据不能静默掉签字。
    副本名带 leave_id，而补签不允许覆盖已签过的记录，所以不会撞名。
    """
    found = _signer_photo(db, sign_no)
    if not found:
        raise HTTPException(status_code=400, detail="该账号没有可用的签字图，请重新选择")
    src, user = found
    dest = LEAVE_DIR / f"sign_{leave_id}{src.suffix.lower()}"
    shutil.copyfile(src, dest)
    return dest, display_name(db, user)


def _save_advisor_signature(
    db: Session, leave: LeaveRequest, payload: LeaveAdvisorSignature | None,
) -> Path | None:
    """把班导师意见与签字写进这条请假记录（供批准与补签字共用）

    返回新落下的签字图副本路径（没签字就是 None），调用方在 commit 失败时拿它删副本 ——
    「先落签字再改状态」的代价就是这一步，不然会留下一个没人引用的孤儿文件。
    """
    payload = payload or LeaveAdvisorSignature()

    # 意见**空着就不动**：批准时留空本来就没意见（记录是新的），而补签字那条路上
    # 空意见是「这次不填」，不能把当初批的时候写的那段话顺手抹掉
    opinion = payload.advisor_opinion.strip()
    if opinion:
        leave.advisor_opinion = opinion

    sign_no = payload.advisor_sign_no.strip()
    if not sign_no:
        # 「暂不签字」：一个字都不动（补签字走这个函数时已经先卡过 400 了）
        return None

    dest, signer_name = _save_signature_copy(db, sign_no, leave.id)
    leave.advisor_sign_no = sign_no
    leave.advisor_sign_name = signer_name
    leave.advisor_sign_file = dest.name
    return dest


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
    #
    # **不排除提交人自己**：他自己就是审批人时（管理员给自己提请假），这件照样
    # 等着他审，排除掉就没人收到待办提醒了。详见 notify_service.recipients
    notify(
        db,
        background,
        recipients(db, roles=APPROVER_ROLES),
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
        # 显式给类型：猜不出来时 Starlette 兜底成 text/plain，
        # 存成 .txt 的证明材料是打不开的（见 utils/media_type.py）
        media_type=guess_media_type(leave.proof_original_name, leave.proof_file),
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


@router.get("/{leave_id}/pdf", summary="下载请假审批表 PDF（申请人本人或管理员）")
def download_pdf(
    leave_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """只有审核通过的申请才能生成表；申请人本人和管理员下到的是**同一份**文件

    学生端那个「下载请假表」按钮就在走这条接口 —— 以前它是 admin_required，
    学生点下去必定 403，是个死按钮（见 LeaveApply.vue）。

    表里的水印用来溯源「谁下载的」，需要下载人是谁，所以不再用 admin_required 那种
    只认角色的依赖，改成拿当前账号自己比对。
    """
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    # 先判权限再判状态：不是自己的单子、内容什么样都不该让他知道
    if leave.student_no != user.student_no and not is_admin(user):
        raise HTTPException(status_code=403, detail="无权下载该请假表")
    if leave.status != "approved":
        raise HTTPException(status_code=400, detail="仅审核通过的申请可生成请假表")

    student = db.query(Student).filter(Student.id == leave.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="学生信息不存在")

    # 两处签字图：申请人自己的（两处都印）与班导师的（在行 9）。缺图不报错，
    # 表照常出 —— 少一个签字不该让申请人拿不到表
    advisor_sign = LEAVE_DIR / leave.advisor_sign_file if leave.advisor_sign_file else None
    pdf_bytes = generate_leave_pdf(
        student, leave,
        applicant_sign=sign_photo_path(student),
        advisor_sign=advisor_sign,
    )

    # 不可见溯源水印（复用公告/导出那套）。**不加访问日志**：学生和管理员下的是
    # 同一份文件，记下来只是一堆噪音，凭水印就够了。
    # 打水印失败不阻断下载 —— 申请人等着要表，不能因为这一步炸了就空手出去
    try:
        token = make_watermark_token(leave.id, user.student_no, source=TOKEN_SOURCE_LEAVE)
        pdf_bytes = add_invisible_watermark(pdf_bytes, token)
    except Exception as exc:  # noqa: BLE001 —— 故意兜住所有异常，就是要不阻断
        print(f"[请假表] 下水印失败（不影响下载）：{exc}", flush=True)

    filename = f"{leave.student_name}_请假审批表_{leave.start_at:%Y%m%d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
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
        # 显式给类型：猜不出来时 Starlette 兜底成 text/plain，
        # 存成 .txt 的证明材料是打不开的（见 utils/media_type.py）
        media_type=guess_media_type(leave.proof_original_name, leave.proof_file),
        filename=leave.proof_original_name or leave.proof_file,
    )


@router.get("/advisor-signers", summary="能当班导师签字人的账号（管理员）")
def advisor_signers(
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """列管理员、且签字图在盘上的账号，供批准时选「用谁的签字」

    域外账号与在册学生同权（用户口径），两类都在列表里，用 is_external 标出来
    给前端做区分。**不复用** GET /api/admin/users 的 has_sign_photo：那一列的语义是
    「域外账号有没有签字图，学生账号恒 False」，拿它筛会把学生管理员整批漏掉。

    候选人一共没几个，逐个查图的 N+1 无所谓，好读优先。
    """
    rows = db.query(User).filter(User.role == "admin").order_by(User.student_no).all()
    return [
        {
            "student_no": row.student_no,
            "name": display_name(db, row),
            "is_external": bool(row.is_external),
        }
        for row in rows
        if _signer_photo(db, row.student_no)
    ]


@router.post("/{leave_id}/approve", response_model=LeaveRequestResponse, summary="通过请假申请")
def approve_leave(
    leave_id: int,
    background: BackgroundTasks,
    payload: LeaveAdvisorSignature | None = None,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """批准时可顺带填班导师意见、选一个管理员的签字（两者都选填）

    body 整个是可选的：老前端那句 `approveLeave(id)` 不带 body 也得照样能用。
    """
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    # 只允许批「待审核」的：能在已批准的单子上再点一次「通过」，会重新快照签字、
    # 覆盖掉当初那张，外加把已发出的通知再来一遍。这条同时兜住了重复提交
    if leave.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理过")

    # 先把签字副本落盘再改状态：复制失败时这条还是 pending，管理员能重试；
    # 反过来的话就会出现「状态已通过、签字丢了」的单子，而签字是批的时候才定的，
    # 事后补就只能靠补签字了
    snapshot = _save_advisor_signature(db, leave, payload)
    leave.status = "approved"
    leave.reviewed_at = datetime.now()
    leave.reviewer_no = user.student_no
    leave.reviewer_name = display_name(db, user)
    log_operation(
        db, user, "通过请假申请",
        target=f"{leave.student_no} {leave.student_name}",
        detail=(
            f"{leave.leave_type}：{leave.start_at:%Y-%m-%d %H时} ~ {leave.end_at:%Y-%m-%d %H时}"
            f"；班导师签字：{leave.advisor_sign_name or '暂不签字'}"
        ),
        ip=ip,
    )
    targets = recipients(db, only_no=leave.student_no)
    try:
        db.commit()
    except Exception:
        # 提交失败 → 刚复制的副本没人引用了，删掉再抛，别留孤儿文件
        if snapshot:
            snapshot.unlink(missing_ok=True)
        raise
    db.refresh(leave)

    # 批完通知学生。有意见就带上一句，学生不用点开表也能看到班导师说了什么
    notify(
        db, background, targets, "请假申请已通过",
        f"你的{leave.leave_type}（{leave.start_at:%m-%d %H时} 起）已通过审核",
        level="timeSensitive",
        page="/my-info?tab=workspace&sub=submitted",
    )
    return _to_response(leave)


@router.post(
    "/{leave_id}/advisor-sign",
    response_model=LeaveRequestResponse,
    summary="补签字（批准时选了「暂不签字」之后）",
)
def advisor_sign_leave(
    leave_id: int,
    payload: LeaveAdvisorSignature,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """给一条已批准、当初没签字的请假记录补上签字

    单独开一个接口、而不是「再批一次」，是为了不碰 status / reviewer / 审核时间 ——
    补的是签字，不是重新审一遍。意见也顺带收，那时候没填的可以一起补上。

    **已经签过的一律 400**：快照语义下静默改写等于篡改已经发出去的那张表。
    """
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if leave.status != "approved":
        raise HTTPException(status_code=400, detail="仅审核通过的申请可以补签字")
    if leave.advisor_sign_file:
        raise HTTPException(status_code=400, detail="该记录已有班导师签字")
    if not payload.advisor_sign_no.strip():
        raise HTTPException(status_code=400, detail="请选择签字人")

    snapshot = _save_advisor_signature(db, leave, payload)
    log_operation(
        db, user, "补签班导师签字",
        target=f"{leave.student_no} {leave.student_name}",
        detail=f"班导师签字：{leave.advisor_sign_name or '暂不签字'}",
        ip=ip,
    )
    try:
        db.commit()
    except Exception:
        if snapshot:
            snapshot.unlink(missing_ok=True)
        raise
    db.refresh(leave)
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
        db, background, targets, "请假申请被驳回",
        f"理由：{clip(leave.reject_reason)}", level="timeSensitive",
        page="/my-info?tab=workspace&sub=submitted",
    )
    return _to_response(leave)
