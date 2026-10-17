"""请假申请：学生提交，管理员审核（批准时可填班导师意见、选谁的签字），
通过后申请人本人和管理员都能下载生成好的 PDF 请假审批表（带不可见溯源水印）
"""

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
from fastapi.responses import FileResponse, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import LeaveRequest, Student, User
from ..schemas import (
    LeaveAdvisorSignature,
    LeaveCorrectRequest,
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
from ..services.signer_service import copy_signature, signer_options
from ..services.student_photo_service import sign_photo_path
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


def _check_fields(leave_type: str, start_at: datetime, end_at: datetime, reason: str) -> None:
    """提交与修改共用的字段校验（两边必须一模一样，所以抽出来一处写）"""
    if leave_type not in LEAVE_TYPES:
        raise HTTPException(status_code=400, detail=f"请假类型只能是：{'/'.join(LEAVE_TYPES)}")
    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")
    if not reason.strip():
        raise HTTPException(status_code=400, detail="请假事由不能为空")


async def _save_proof(proof: UploadFile) -> str:
    """校验并落盘一份证明材料，返回存盘文件名（提交与修改共用）"""
    if not proof.filename:
        raise HTTPException(status_code=400, detail="请上传请假辅助证明")
    proof_name = _safe_name(proof.filename)
    content = await proof.read()
    if len(content) > MAX_PROOF_SIZE:
        raise HTTPException(status_code=400, detail="证明文件大小不能超过 20MB")
    with open(LEAVE_DIR / proof_name, "wb") as f:
        f.write(content)
    return proof_name


def _to_response(leave: LeaveRequest) -> LeaveRequestResponse:
    resp = LeaveRequestResponse.model_validate(leave)
    # 派生字段：只要「签没签」。签字图副本的文件名不进响应 —— 前端拿不到它
    # 也就拼不出别的下载地址，需要看图时照旧走签字审批那条链
    resp.has_advisor_sign = bool(leave.advisor_sign_file)
    return resp


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

    # 副本落进 LEAVE_DIR，按单据 id 起名（见 services/signer_service.py）
    dest, signer_name = copy_signature(db, sign_no, LEAVE_DIR, f"sign_{leave.id}")
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
    _check_fields(leave_type, start_at, end_at, reason)
    proof_name = await _save_proof(proof)

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


@router.put("/{leave_id}", response_model=LeaveRequestResponse, summary="修改请假申请（未办结时）")
async def update_leave(
    leave_id: int,
    leave_type: str = Form(..., description="病假/事假/公假"),
    start_at: datetime = Form(..., description="开始时间，精确到小时"),
    end_at: datetime = Form(..., description="结束时间，精确到小时"),
    reason: str = Form(..., description="请假事由"),
    travel_mode: str = Form(""),
    travel_detail: str = Form(""),
    destination: str = Form(""),
    destination_phone: str = Form(""),
    # 不传就是「证明文件不动」；传了就把旧的换成新的（旧文件提交成功后删掉）
    proof: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """申请人自己改：待受理、待补正这两种状态能改，其余一律 400

    字段是**整套覆盖**，跟重新提交一次一样 —— 少传一个就等于清空它，所以前端
    编辑时必须把原值都带上。

    改完的落点分两种（见 review_flow.resubmit）：原本待补正的回到「已受理」——
    待补正也算已受理，受理没被撤销，只是材料要补齐，补完不必让班委再看一遍；
    原本待受理的仍是待受理，它本来就还没人看过。补正后重交也走这里，不必另开接口。

    **不发通知**：这条申请从头到尾都在管理员的「待处理」列表里（open 档含这两档状态），
    不需要再喊一声。
    """
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave or leave.student_id != student.id:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if leave.status not in (STATUS_PENDING, STATUS_CORRECTING):
        raise HTTPException(
            status_code=400,
            detail="该申请已受理，需要修改请联系班委先撤回受理",
        )

    _check_fields(leave_type, start_at, end_at, reason)

    old_proof = leave.proof_file
    if proof is not None:
        leave.proof_file = await _save_proof(proof)
        leave.proof_original_name = proof.filename

    leave.leave_type = leave_type
    leave.start_at = start_at
    leave.end_at = end_at
    leave.reason = reason.strip()
    leave.travel_mode = travel_mode.strip()
    leave.travel_detail = travel_detail.strip()
    leave.destination = destination.strip()
    leave.destination_phone = destination_phone.strip()
    resubmit(leave)

    log_operation(
        db, user, "修改请假申请",
        target=f"{leave.student_no} {leave.student_name}",
        detail=f"{leave_type}：{start_at:%Y-%m-%d %H时} ~ {end_at:%Y-%m-%d %H时}",
        ip=ip,
    )
    db.commit()
    # 提交成功了再删旧证明：反过来的话 commit 一失败，学生手里就只剩一条指着
    # 不存在文件的记录（照 approve 里「先落签字再改状态」的次序）
    if proof is not None and old_proof and old_proof != leave.proof_file:
        (LEAVE_DIR / old_proof).unlink(missing_ok=True)
    db.refresh(leave)
    return _to_response(leave)


@router.delete("/{leave_id}", summary="撤销请假申请（待受理时）")
def delete_leave(
    leave_id: int,
    user: User = Depends(get_current_user),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """申请人自己撤：**只有「待受理」能撤**，直接删掉记录和盘上的证明材料

    已受理的不给撤（那是班委看过、正在走流程的单子，要撤得先让班委撤回受理）；
    待补正的不给撤（是让补材料，不是让放弃，真不想办了跟班委说一声）。
    撤销**不留档、不通知**：撤回一条自己刚交的东西，不需要惊动谁。
    """
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave or leave.student_id != student.id:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if leave.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail="该申请已进入受理流程，不能撤销")

    log_operation(
        db, user, "撤销请假申请",
        target=f"{leave.student_no} {leave.student_name}",
        detail=f"{leave.leave_type}：{leave.start_at:%Y-%m-%d %H时} ~ {leave.end_at:%Y-%m-%d %H时}",
        ip=ip,
    )
    proof = leave.proof_file
    db.delete(leave)
    db.commit()
    if proof:
        (LEAVE_DIR / proof).unlink(missing_ok=True)
    return {"ok": True}


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
    status: str | None = Query(
        None,
        description="pending/accepted/correcting/approved/rejected/revoked；"
                    "open = 待处理（待受理+已受理），closed = 已办结（已通过+已驳回+已撤销），"
                    "不传为全部",
    ),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """班委可以看列表和详情，但只有管理员能审批（通过/驳回）和生成 Word

    `open` 是「待处理」那一档：受理后状态会从 pending 变成 accepted，只看 pending
    的话「受理」这个动作看起来像把申请弄丢了，而菜单红点还照数它 —— 所以待办口径
    必须是「还没办结且轮到我动手的」，见 services/review_flow.py 的 ADMIN_TODO。
    默认档是「全部」：进来先看见所有的，要收窄再自己点
    """
    query = db.query(LeaveRequest)
    if status == "open":
        query = query.filter(LeaveRequest.status.in_(ADMIN_TODO))
    elif status == "closed":
        # 「已办结」= 三个终态。筛选器上就四档：待处理 / 待补正 / 已办结 / 全部 ——
        # 待受理与已受理合在「待处理」里（都要同一个人动手），已通过、已驳回和已撤销
        # 合在「已办结」里（谁都不用再动手），具体是哪个状态看行上的 tag
        query = query.filter(LeaveRequest.status.in_(CLOSED))
    elif status:
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
    if leave.status == STATUS_REVOKED:
        raise HTTPException(status_code=400, detail="该申请已撤销，不再提供请假审批表")
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


@router.post("/{leave_id}/accept", response_model=LeaveRequestResponse, summary="受理请假申请")
def accept_leave(
    leave_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """受理：这份材料看过了，可以进入审批

    前端在管理员打开证明材料时顺手发一个，另有一个「受理」按钮兜底（材料文件丢了、
    或者根本没附件的单子，只看是受理不了的）。已经受理过的原样返回（幂等）——
    反复打开材料不该报错。

    **不发通知**（用户口径）：受理只是审批人自己的一步，学生那边只看到状态变了；
    受理也不碰 reviewer_no / reviewed_at —— 那是审批结果的一部分，记上去会让这条
    申请提前出现在「我审批的」里。
    """
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if accept(leave):
        log_operation(
            db, user, "受理请假申请",
            target=f"{leave.student_no} {leave.student_name}",
            detail=leave.leave_type,
            ip=ip,
        )
        db.commit()
        db.refresh(leave)
    return _to_response(leave)


@router.post("/{leave_id}/unaccept", response_model=LeaveRequestResponse, summary="撤回受理")
def unaccept_leave(
    leave_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """受理点错了的回头路：已受理 → 待受理

    只退受理，不动审批结果 —— 但已办结（通过/驳回）的单子本来就退不回来：审批一旦
    发出（通知已推送、PDF 已生成、签字图已快照），静默改写等于篡改已发出的正式单据
    （与「补签字不重审」同一条口径）。
    """
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if not unaccept(leave):
        raise HTTPException(status_code=400, detail="该申请不在「已受理」状态，撤回不了")
    log_operation(
        db, user, "撤回受理请假申请",
        target=f"{leave.student_no} {leave.student_name}",
        detail=leave.leave_type,
        ip=ip,
    )
    db.commit()
    db.refresh(leave)
    return _to_response(leave)


@router.post("/{leave_id}/correcting", response_model=LeaveRequestResponse, summary="退回补正")
def correcting_leave(
    leave_id: int,
    payload: LeaveCorrectRequest,
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
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if not correct(leave, payload.reason):
        raise HTTPException(status_code=400, detail="只有已受理的申请才能退回补正")
    log_operation(
        db, user, "退回补正请假申请",
        target=f"{leave.student_no} {leave.student_name}",
        detail=f"理由：{payload.reason.strip()}",
        ip=ip,
    )
    targets = recipients(db, only_no=leave.student_no)
    db.commit()
    db.refresh(leave)

    notify(
        db, background, targets, "请假申请需要补交材料",
        f"理由：{clip(leave.correction_reason)}", level="timeSensitive",
        page="/my-info?tab=workspace&sub=submitted",
    )
    return _to_response(leave)


@router.get("/advisor-signers", summary="能当班导师签字人的账号（管理员）")
def advisor_signers(
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """列管理员、且签字图在盘上的账号，供批准时选「用谁的签字」

    口径与电动车那份（GET /api/ev-passes/signers）共用，见 services/signer_service.py
    """
    return signer_options(db)


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
    # 得先受理过；已办结的也不能再批一次（在已批准的单子上再点「通过」会重新快照
    # 签字、覆盖掉当初那张，外加把已发出的通知再来一遍）。两条都在这一句里
    require_accepted(leave)

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


@router.post("/{leave_id}/revoke", response_model=LeaveRequestResponse, summary="撤销已通过的请假申请")
def revoke_leave(
    leave_id: int,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """管理员把一条已通过的申请撤了：状态变成「已撤销」，学生端不再显示审核意见

    撤销后这条单子不能再编辑、不再生成审批表（下载接口按状态拦）；它也不再能批、
    不能补签字 —— **撤销是终态，没有反向操作**。

    要发通知：申请人手里的表可能已经打印出去了，不喊一声他不会知道这张表作废了。
    """
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if leave.status != "approved":
        raise HTTPException(status_code=400, detail="只有已通过的申请才能撤销")

    leave.status = STATUS_REVOKED
    log_operation(
        db, user, "撤销已通过的请假申请",
        target=f"{leave.student_no} {leave.student_name}",
        detail=f"{leave.leave_type}：{leave.start_at:%Y-%m-%d %H时} ~ {leave.end_at:%Y-%m-%d %H时}",
        ip=ip,
    )
    targets = recipients(db, only_no=leave.student_no)
    db.commit()
    db.refresh(leave)

    notify(
        db, background, targets, "请假申请已撤销",
        f"你的{leave.leave_type}（{leave.start_at:%m-%d %H时} 起）已被管理员撤销",
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
    require_accepted(leave)

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
