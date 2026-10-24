"""电动车通行证补办 API"""
import os
import uuid
from datetime import date, datetime
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
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BASE_DIR, settings
from ..database import get_db
from ..models import EvPassRequest, Student, User
from ..schemas import (
    EvPassCorrectRequest,
    EvPassRejectRequest,
    EvPassRequestResponse,
    EvPassSignature,
)
from ..services import (
    TOKEN_SOURCE_EV_APPLY,
    TOKEN_SOURCE_EV_PROMISE,
    account_name,
    add_invisible_watermark,
    clip,
    log_operation,
    make_watermark_token,
    notify,
    recipients,
)
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
from ..services.signer_service import copy_signature, signer_options
from ..services.student_photo_service import sign_photo_path
from .deps import (
    admin_required,
    committee_required,
    get_client_ip,
    get_current_user,
    is_committee,
)
from ..utils.ev_pass_pdf import generate_pass_pdf, generate_promise_pdf
from ..utils.media_type import guess_media_type

router = APIRouter(prefix="/api/ev-passes", tags=["电动车通行证"])

# 通行证只有管理员能审批（班委只读，见下面的 admin_required / committee_required），
# 所以「待审核」的推送也只发给管理员
APPROVER_ROLES = ["admin"]

# 行驶证与经办班委**签字图副本**存放目录。吃环境变量是为了测试能指到临时目录去 ——
# 不吃的话接口测试一调「批准（带签字）」就会往本机演示库的真目录里写文件
# （照 PHOTO_DIR / LEAVE_DIR 的先例）
EV_PASS_DIR = Path(os.environ.get("EV_PASS_DIR") or BASE_DIR / "data" / "ev_passes")
EV_PASS_DIR.mkdir(parents=True, exist_ok=True)

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


async def _save_license(license_file: UploadFile) -> str:
    """校验并落盘一份行驶证，返回存盘文件名（提交与修改共用）"""
    if not license_file.filename:
        raise HTTPException(status_code=400, detail="请上传行驶证")
    safe_name = _safe_license_name(license_file.filename)
    content = await license_file.read()
    if len(content) > MAX_LICENSE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"行驶证文件超过 {MAX_LICENSE_SIZE // 1024 // 1024}MB",
        )
    with open(EV_PASS_DIR / safe_name, "wb") as f:
        f.write(content)
    return safe_name


def student_files(db: Session, student_id: int) -> list[Path]:
    """该生全部通行证申请占用的行驶证与签字副本

    删学生会连带删掉这些申请记录（见 student_service.delete_student），记录一没，
    文件就成了没人引用的孤儿。所以在删之前先把路径收出来，**等事务提交成功之后**
    再清磁盘（和删学生照片同一个套路）。只收集、不动磁盘。

    **签字副本也要收**：它是批准时从管理员那张图复制过来的（见 _save_committee_signature），
    只挂在申请记录上 —— 漏掉它，删学生就会在 data/ev_passes/ 里留下一堆孤儿 copy
    """
    out = []
    for req in db.query(EvPassRequest).filter(EvPassRequest.student_id == student_id).all():
        # Path(...).name 防路径穿越：库里那两列都是裸文件名，取 name 后就出不了这一层
        for name in (req.license_file, req.sign_file):
            if name:
                out.append(EV_PASS_DIR / Path(name).name)
    return out


def _to_response(db: Session, req: EvPassRequest) -> dict:
    """把 ORM 对象转成响应体（补上学生姓名/学号与签字状态）"""
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
        "correction_reason": req.correction_reason,
        # 经办班委签字：只要「签没签、谁签的」。签字图**副本的文件名**不进响应 ——
        # 前端拿不到它，也就拼不出别的下载地址
        "sign_name": req.sign_name or "",
        "has_sign": bool(req.sign_file),
    }


def _save_committee_signature(
    db: Session, req: EvPassRequest, payload: EvPassSignature | None,
) -> Path | None:
    """把选中的经办班委签字写进这条申请（批准与补签字共用）

    返回新落下的签字图副本路径（没签字就是 None），调用方在 commit 失败时拿它删副本 ——
    「先落签字再改状态」的代价就是这一步，不然会留下一个没人引用的孤儿文件。
    """
    payload = payload or EvPassSignature()
    sign_no = payload.sign_no.strip()
    if not sign_no:
        # 「暂不签署」：三列一个字都不动，申请表上那一行整行不出现
        return None

    # 副本落进 EV_PASS_DIR，按单据 id 起名（见 services/signer_service.py）
    dest, signer_name = copy_signature(db, sign_no, EV_PASS_DIR, f"sign_{req.id}")
    req.sign_no = sign_no
    req.sign_name = signer_name
    req.sign_file = dest.name
    return dest


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

    safe_name = await _save_license(license_file)

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
    #
    # **不排除提交人自己**：管理员给自己办的通行证也等着他审
    # （理由见 notify_service.recipients，四个办件提交接口口径一致）
    notify(
        db,
        background,
        recipients(db, roles=APPROVER_ROLES),
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
    file_path = EV_PASS_DIR /Path(req.license_file).name
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


@router.put("/{req_id}", response_model=EvPassRequestResponse, summary="修改申请（未办结时）")
async def update_application(
    req_id: int,
    brand: str = Form(..., min_length=1, max_length=100, description="电动车品牌"),
    plate_number: str = Form(..., min_length=1, max_length=50, description="车牌号"),
    # 不传就是「行驶证不动」；传了就把旧的换成新的（旧文件提交成功后删掉）
    license_file: UploadFile | None = File(None),
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
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
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

    old_license = req.license_file
    if license_file is not None:
        req.license_file = await _save_license(license_file)
        req.license_original_name = license_file.filename

    req.brand = brand.strip()
    req.plate_number = plate_number.strip()
    resubmit(req)

    log_operation(
        db, user, "修改电动车通行证申请",
        target=f"{student.student_no} {student.name}",
        detail=f"品牌：{req.brand}，车牌：{req.plate_number}",
        ip=ip,
    )
    db.commit()
    # 提交成功了再删旧行驶证：反过来的话 commit 一失败，学生手里就只剩一条指着
    # 不存在文件的记录（照 approve 里「先落签字再改状态」的次序）
    if license_file is not None and old_license and old_license != req.license_file:
        (EV_PASS_DIR / Path(old_license).name).unlink(missing_ok=True)
    db.refresh(req)
    return _to_response(db, req)


@router.delete("/{req_id}", summary="撤销申请（待受理时）")
def delete_application(
    req_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """申请人自己撤：**只有「待受理」能撤**，直接删掉记录和盘上的行驶证

    已受理的不给撤（那是班委看过、正在走流程的单子，要撤得先让班委撤回受理）；
    待补正的不给撤（是让补材料，不是让放弃，真不想办了跟班委说一声）。
    撤销**不留档、不通知**：撤回一条自己刚交的东西，不需要惊动谁。
    """
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    student = db.query(Student).filter(Student.student_no == user.student_no).first()
    if not student or req.student_id != student.id:
        raise HTTPException(status_code=403, detail="无权撤销")
    if req.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail="该申请已进入受理流程，不能撤销")

    log_operation(
        db, user, "撤销电动车通行证申请",
        target=f"{student.student_no} {student.name}",
        detail=f"品牌：{req.brand}，车牌：{req.plate_number}",
        ip=ip,
    )
    license_name = req.license_file
    db.delete(req)
    db.commit()
    if license_name:
        (EV_PASS_DIR / Path(license_name).name).unlink(missing_ok=True)
    return {"ok": True}


def _pdf_target(db: Session, req_id: int, user: User) -> tuple[EvPassRequest, Student]:
    """取回申请和申请人，并校验「能不能下载生成的 PDF」

    能下载的是两类人：申请人本人（拿去打印签字），以及班委及以上
    （要留档、要报学院盖章）。其余人一律不行 —— 表里是学生本人的个人信息。
    两份 PDF 的权限完全一样，所以收在一处，免得以后改一个漏一个。
    """
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    student = db.query(Student).filter(Student.id == req.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="申请人信息不存在")
    if not is_committee(user) and student.student_no != user.student_no:
        raise HTTPException(status_code=403, detail="无权下载")
    if req.status == STATUS_REVOKED:
        raise HTTPException(status_code=400, detail="该申请已撤销，不再提供申请表和承诺书")
    if req.status != "approved":
        raise HTTPException(status_code=400, detail="申请未通过，暂不能下载")
    return req, student


def _pdf_response(content: bytes, filename: str) -> Response:
    """下载 PDF 的响应

    文件名必须按 RFC 5987 百分号编码：HTTP 头只装得下 latin-1，
    直接塞中文名会让 Starlette 在编码响应头时抛 UnicodeEncodeError
    """
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename*=utf-8''" + quote(filename),
            "Cache-Control": "no-store",
        },
    )


def _file_name(req: EvPassRequest, student: Student, what: str) -> str:
    """下载文件名里的日期取**申请当天**

    以前用的是生成当天，而前端（EvPass.vue / Review.vue）拼的是 created_at ——
    两边本来就不一致，跨天就对不上。用 created_at，同一条记录每次下到的名字才稳定。
    """
    day = (req.created_at or datetime.now()).strftime("%Y%m%d")
    return f"{student.name}_电动车{what}_{day}.pdf"


def _stamp(content: bytes, req: EvPassRequest, user: User, source: str) -> bytes:
    """盖不可见溯源水印（谁下载的、下的是哪一份）

    **不写访问日志**：学生和班委下的是同一份文件，记下来只是一堆噪音，凭水印就够了。
    打水印失败不阻断下载 —— 学生等着要表，不能因为这一步炸了就空手出去。
    """
    try:
        token = make_watermark_token(req.id, user.student_no, source=source)
        return add_invisible_watermark(content, token)
    except Exception as exc:  # noqa: BLE001 —— 故意兜住所有异常，就是要不阻断
        print(f"[电动车通行证] 下水印失败（不影响下载）：{exc}", flush=True)
        return content


@router.get("/{req_id}/pass-pdf", summary="下载电动车通行证申请表 PDF")
def download_pass_pdf(
    req_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载申请表：本人或班委及以上，且仅已通过的可下载

    经办班委那一行的签字取**批准当时**存下的那张副本（见 _save_committee_signature）——
    原图后来换了或删了，都不该让这张表掉签字。没签字就不加那一行。
    """
    req, student = _pdf_target(db, req_id, user)
    committee_sign = EV_PASS_DIR / Path(req.sign_file).name if req.sign_file else None
    pdf = generate_pass_pdf(student, req, committee_sign=committee_sign)
    return _pdf_response(
        _stamp(pdf, req, user, TOKEN_SOURCE_EV_APPLY),
        _file_name(req, student, "通行证申请表"),
    )


@router.get("/{req_id}/promise-pdf", summary="下载电动车使用承诺书 PDF")
def download_promise_pdf(
    req_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载承诺书：本人或班委及以上，且仅已通过的可下载

    「本人签字：」那行印**学生本人**的签字图（申请里传过才有，没传就留一条空下划线手签）
    """
    req, student = _pdf_target(db, req_id, user)
    pdf = generate_promise_pdf(student, req, applicant_sign=sign_photo_path(student))
    return _pdf_response(
        _stamp(pdf, req, user, TOKEN_SOURCE_EV_PROMISE),
        _file_name(req, student, "承诺书"),
    )


# ---------- 管理员 / 班委审核 ----------

@router.get(
    "",
    response_model=list[EvPassRequestResponse],
    summary="电动车通行证申请列表（班委及以上）",
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
    query = db.query(EvPassRequest)
    if status == "open":
        # 「待处理」那一档：受理后状态会从 pending 变成 accepted，只看 pending 的话
        # 「受理」看起来像把申请弄丢了，而菜单红点还照数它（见 review_flow.ADMIN_TODO）
        query = query.filter(EvPassRequest.status.in_(ADMIN_TODO))
    elif status == "closed":
        # 「已办结」= 三个终态。筛选器上就四档：待处理 / 待补正 / 已办结 / 全部 ——
        # 待受理与已受理合在「待处理」里（都要同一个人动手），已通过、已驳回和已撤销
        # 合在「已办结」里（谁都不用再动手），具体是哪个状态看行上的 tag
        query = query.filter(EvPassRequest.status.in_(CLOSED))
    elif status:
        query = query.filter(EvPassRequest.status == status)

    # 这个表里没有姓名/学号列，提交人信息在学生表 —— 用子查询圈 id，不要逐条 join
    person_match = keyword_like(keyword, Student.name, Student.student_no)
    if person_match is not None:
        query = query.filter(
            EvPassRequest.student_id.in_(select(Student.id).where(person_match))
        )
    query = created_between(query, EvPassRequest.created_at, start, end)

    rows = query.order_by(EvPassRequest.id.desc()).all()
    return [_to_response(db, r) for r in rows]


@router.post("/{req_id}/accept", response_model=EvPassRequestResponse, summary="受理申请（管理员）")
def accept_application(
    req_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """受理：这份材料看过了，可以进入审批

    前端在管理员打开行驶证时顺手发一个，另有一个「受理」按钮兜底（没附件的单子
    只看是受理不了的）。已经受理过的原样返回（幂等）—— 反复打开材料不该报错。

    **不发通知**（用户口径）：受理只是审批人自己的一步，学生那边只看到状态变了；
    也不碰 reviewer_no / reviewed_at —— 那是审批结果的一部分。
    """
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if accept(req):
        student = db.query(Student).filter(Student.id == req.student_id).first()
        log_operation(
            db, user, "受理电动车通行证申请",
            target=student.name if student else f"id={req.student_id}",
            detail=f"车牌：{req.plate_number}",
            ip=ip,
        )
        db.commit()
        db.refresh(req)
    return _to_response(db, req)


@router.post("/{req_id}/unaccept", response_model=EvPassRequestResponse, summary="撤回受理（管理员）")
def unaccept_application(
    req_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """受理点错了的回头路：已受理 → 待受理

    只退受理，不动审批结果 —— 已办结（通过/驳回）的单子本来就退不回来：审批一旦
    发出（通知已推送、PDF 已生成、签字图已快照），静默改写等于篡改已发出的正式单据
    （与「补签字不重审」同一条口径）。
    """
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if not unaccept(req):
        raise HTTPException(status_code=400, detail="该申请不在「已受理」状态，撤回不了")
    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "撤回受理电动车通行证申请",
        target=student.name if student else f"id={req.student_id}",
        detail=f"车牌：{req.plate_number}",
        ip=ip,
    )
    db.commit()
    db.refresh(req)
    return _to_response(db, req)


@router.post(
    "/{req_id}/correcting",
    response_model=EvPassRequestResponse,
    summary="退回补正（管理员）",
)
def correcting_application(
    req_id: int,
    body: EvPassCorrectRequest,
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
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if not correct(req, body.reason):
        raise HTTPException(status_code=400, detail="只有已受理的申请才能退回补正")
    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "退回补正电动车通行证申请",
        target=student.name if student else f"id={req.student_id}",
        detail=f"理由：{body.reason.strip()}",
        ip=ip,
    )
    targets = recipients(db, only_no=student.student_no) if student else None
    db.commit()
    db.refresh(req)

    if targets:
        notify(
            db, background, targets, "电动车通行证申请需要补交材料",
            f"车牌 {req.plate_number}，理由：{clip(req.correction_reason)}",
            level="timeSensitive", page="/ev-pass?tab=record",
        )
    return _to_response(db, req)


@router.post("/{req_id}/approve", response_model=EvPassRequestResponse, summary="通过申请（管理员）")
def approve_application(
    req_id: int,
    background: BackgroundTasks,
    payload: EvPassSignature | None = None,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """批准时可顺带选一位管理员的签字（或「暂不签署」）

    body 整个是可选的：老前端那句 `approveEvPass(id)` 不带 body 也得照样能用。
    """
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    # 得先受理过；已办结的也不能再批一次（在已批准的单子上再点「通过」会重新快照签字、
    # **覆盖掉当初那张副本**，「用批准当时那张」这句承诺当场作废，外加把已发出的通知
    # 再来一遍）。两条都在这一句里
    require_accepted(req)

    # 先把签字副本落盘再改状态：复制失败时这条还是 pending，管理员能重试；
    # 反过来的话就会出现「状态已通过、签字丢了」的单子，而签字是批的时候才定的，
    # 事后补就只能靠补签字了
    snapshot = _save_committee_signature(db, req, payload)
    req.status = "approved"
    req.reviewer_no = user.student_no
    req.reviewer_name = account_name(db, user)
    req.reviewed_at = datetime.now()
    req.reject_reason = None

    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "通过电动车通行证",
        target=student.name if student else f"id={req.student_id}",
        detail=(f"品牌：{req.brand}，车牌：{req.plate_number}"
                f"；经办班委签字：{req.sign_name or '暂不签署'}"),
        ip=ip,
    )
    # 收件人在 commit 之前定下来（和请假一致）。申请人不在学生表里就没什么可发的，
    # 别退化成「only_no 为 None」——那在 recipients 里等于不筛人，会推给全班
    targets = recipients(db, only_no=student.student_no) if student else None
    try:
        db.commit()
    except Exception:
        # 提交失败 → 刚复制的副本没人引用了，删掉再抛，别留孤儿文件
        if snapshot:
            snapshot.unlink(missing_ok=True)
        raise
    db.refresh(req)

    if targets:
        notify(
            db, background, targets, "电动车通行证申请已通过",
            f"你的电动车通行证申请（{req.plate_number}）已通过，现在可以下载申请表和承诺书",
            level="timeSensitive", page="/ev-pass?tab=record",
        )
    return _to_response(db, req)


@router.post("/{req_id}/revoke", response_model=EvPassRequestResponse, summary="撤销已通过的申请（管理员）")
def revoke_application(
    req_id: int,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """把一条已通过的申请撤了：状态变成「已撤销」，申请人不能再编辑、不再提供两份 PDF

    **撤销是终态，没有反向操作**：撤销后它也不能再批、不能补签字。
    要发通知 —— 申请人手里可能已经打印出来了，不喊一声不会知道作废了。
    """
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "approved":
        raise HTTPException(status_code=400, detail="只有已通过的申请才能撤销")

    req.status = STATUS_REVOKED
    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "撤销已通过的电动车通行证申请",
        target=student.name if student else f"id={req.student_id}",
        detail=f"品牌：{req.brand}，车牌：{req.plate_number}",
        ip=ip,
    )
    targets = recipients(db, only_no=student.student_no) if student else None
    db.commit()
    db.refresh(req)

    if targets:
        notify(
            db, background, targets, "电动车通行证申请已撤销",
            f"你的电动车通行证申请（{req.plate_number}）已被管理员撤销",
            level="timeSensitive", page="/ev-pass?tab=record",
        )
    return _to_response(db, req)


@router.post(
    "/{req_id}/sign",
    response_model=EvPassRequestResponse,
    summary="补签字（批准时选了「暂不签署」之后）",
)
def sign_application(
    req_id: int,
    payload: EvPassSignature,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """给一条已批准、当初没签字的申请补上经办班委签字

    单独开一个接口、而不是「再批一次」，是为了不碰 status / reviewer / 审核时间 ——
    补的是签字，不是重新审一遍。

    **已经签过的一律 400**：快照语义下静默改写等于篡改已经发出去的那张表。
    """
    req = db.query(EvPassRequest).filter(EvPassRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "approved":
        raise HTTPException(status_code=400, detail="仅审核通过的申请可以补签字")
    if req.sign_file:
        raise HTTPException(status_code=400, detail="该申请已有经办班委签字")
    if not payload.sign_no.strip():
        raise HTTPException(status_code=400, detail="请选择签字人")

    snapshot = _save_committee_signature(db, req, payload)
    student = db.query(Student).filter(Student.id == req.student_id).first()
    log_operation(
        db, user, "补签经办班委签字",
        target=student.name if student else f"id={req.student_id}",
        detail=f"经办班委签字：{req.sign_name}",
        ip=ip,
    )
    try:
        db.commit()
    except Exception:
        if snapshot:
            snapshot.unlink(missing_ok=True)
        raise
    db.refresh(req)
    return _to_response(db, req)


@router.get("/signers", summary="能当经办班委签字人的账号（管理员）")
def committee_signers(
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """列管理员、且签字图在盘上的账号，供批准时选「用谁的签字」

    口径与请假的 GET /api/leaves/advisor-signers 共用（见 services/signer_service.py）。
    接口名不叫 advisor-signers：这边签字的是经办班委，落在落款处，不是班导师
    """
    return signer_options(db)


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
    require_accepted(req)
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
            db, background, targets, "电动车通行证申请被驳回",
            f"牌照号 {req.plate_number}，理由：{clip(req.reject_reason)}",
            level="timeSensitive", page="/ev-pass?tab=record",
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
    file_path = EV_PASS_DIR /Path(req.license_file).name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="行驶证文件不存在")
    return FileResponse(
        str(file_path),
        # 显式给类型：猜不出来时 Starlette 兜底成 text/plain（见 utils/media_type.py）
        media_type=guess_media_type(req.license_original_name, req.license_file),
        filename=req.license_original_name or req.license_file,
        content_disposition_type="inline",
    )
