"""学生信息修改申请：学生提交 → 班委审核 → 通过后才写入学生表

白名单之外的字段不开放申请：学号、姓名、身份证号、班委职务属于身份标识（改了等于换个人），
「是否贫困生」属于内部认定事项 —— 都由班委/管理员在名单页直接维护，学生不能自己发起变更。

唯一一个不走「学生填值」的字段是自备证件照：学生交的是文件，得先落盘才有值可存。
所以它由服务端在 multipart 分支里注入，见 PHOTO_EDITABLE_FIELDS。
"""

import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ChangeRequest, Student, User
from ..schemas import ChangeRequestCreate, ChangeRequestResponse, RejectRequest
from ..services import clip, display_name, log_operation, notify, recipients
# 照片的落盘 / 删除 / 取文件三件事与 api/students.py 共用同一份实现
from ..services.student_photo_service import photo_path, photo_response, remove_photo, save_photo
from ..utils.student_fields import describe_changes
from .deps import committee_required, get_current_student, get_current_user, get_client_ip

router = APIRouter(prefix="/api/change-requests", tags=["修改申请"])

# 审核人：申请要班委或管理员审，所以推送也只发给他们
REVIEWER_ROLES = ["admin", "committee"]

# 允许学生申请修改的字段。改这里就行，校验、落库、审核三处共用同一份
# 顺序与前端 utils/changeFields.js 的 CHANGE_FIELDS 保持一致（决定表单里的排列）
EDITABLE_FIELDS = (
    "qq",
    "email",
    # 两个电话不卡格式：真实档案里有座机（010-…）、有带区号/分机的写法，
    # 卡正则只会把合法号码挡在外面，而这两个字段既不进邮件头也不参与鉴权
    "phone",
    "family_phone",
    "family_address",
    "postal_code",
    "league_position",
    "dormitory",
    "bed",
)

# 学生能申请改、但**不能自己填值**的字段：值由服务端在落盘之后注入。
# 单独列一份而不是并进上面那个元组，是因为 submit 的白名单**只认上面那份** ——
# 合在一起的话，学生从 JSON 里传 {"id_photo": "2024000002_id.jpg"} 就能引用别人的
# 照片（批量导入的文件名是 {学号}_{类型} 这种可预测的），班委一点通过，档案就指向
# 别人的图，之后换照片、删学生还会顺手删掉别人的文件。basename 只防路径穿越，防不住这个
PHOTO_EDITABLE_FIELDS = ("id_photo",)
ALL_EDITABLE_FIELDS = EDITABLE_FIELDS + PHOTO_EDITABLE_FIELDS


def _to_response(req: ChangeRequest, student: Student | None) -> ChangeRequestResponse:
    """组装出参，并带上学生当前值供前端做「原值 → 新值」对照"""
    data = ChangeRequestResponse.model_validate(req)
    if student:
        data.current = {f: getattr(student, f, None) for f in ALL_EDITABLE_FIELDS}
    return data


def _describe(student: Student, changes: dict) -> str:
    """写进日志和通知的「改了啥」

    照片单独成句：那一项的值是 uuid 文件名（`a1b2…jpg → c3d4…jpg`），
    对学生和班委都不构成信息，还把一句话撑得没法读。
    """
    texts = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS}
    parts = [describe_changes({k: getattr(student, k, None) for k in texts}, texts)]
    if changes.get("id_photo"):
        parts.append("换了一张自备证件照")
    return "；".join(p for p in parts if p)


async def _parse(request: Request) -> tuple[ChangeRequestCreate, UploadFile | None]:
    """把请求体解析成（表单字段, 照片）。

    带照片的申请只能走 multipart（浏览器发文件就这么发），不带照片的仍是 JSON。
    两种格式挤进同一个接口、而不是拆成两个，是为了让「照片落盘」和「建申请」
    发生在同一个请求里：分成两步的话，学生传了照片却没提交（或提交失败），
    那张图就永远躺在盘上没人引用。

    手动解析 body 有个副作用：FastAPI 不再替我们把校验错误翻成 422，
    所以下面那层 try 不能省 —— 少了它，邮箱格式不对会以 500 抛出。
    """
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        # 表单里的文本项一律是字符串，文件项不是，于是照片天然被排除在外。
        # 值原样保留：空串的语义与 JSON 路径一致，都表示「清空这一项」
        raw = {k: v for k, v in form.multi_items() if isinstance(v, str) and k != "photo"}
        upload = form.get("photo")
        # 没选文件时浏览器可能发来一个空串，统一成 None
        if not getattr(upload, "filename", None):
            upload = None
    else:
        upload = None
        try:
            raw = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail="请求体不是合法的 JSON")

    try:
        return ChangeRequestCreate.model_validate(raw), upload
    except ValidationError as e:
        raise RequestValidationError(e.errors())


@router.post("", response_model=ChangeRequestResponse, summary="提交信息修改申请")
async def submit(
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    payload, upload = await _parse(request)

    # 按白名单过滤（与 approve 同口径）：不过滤的话，schema 里多一个字段、白名单里
    # 少一个，就会存进一条「提交成功但永远不会生效」的申请 —— changes 里有，审批时不认。
    # 只认纯文本那份白名单：照片的值由服务端下面注入，见 PHOTO_EDITABLE_FIELDS 的注释
    changes = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if key in EDITABLE_FIELDS
    }
    # 只传了照片也算一次有效申请，所以判据要带上传
    if not changes and not upload:
        raise HTTPException(status_code=400, detail="没有要修改的内容")

    # 不让申请叠着排队：一条还没审完，后面的改了也是白改。
    # 这一步必须排在落盘之前 —— 反过来的话，被这次 400 拒掉的请求会在盘上留一个孤儿文件
    pending = (
        db.query(ChangeRequest)
        .filter(ChangeRequest.student_id == student.id, ChangeRequest.status == "pending")
        .first()
    )
    if pending:
        raise HTTPException(status_code=400, detail="已有一条待审核的申请，等班委处理后再提交")

    if upload:
        try:
            # 落盘拿到文件名后才由服务端写进 changes：学生从头到尾碰不到这个值，
            # 也就构造不出「引用别人照片」的申请
            changes["id_photo"] = save_photo(upload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    req = ChangeRequest(
        student_id=student.id,
        student_no=student.student_no,
        student_name=student.name,
        changes=json.dumps(changes, ensure_ascii=False),
    )
    try:
        db.add(req)
        log_operation(
            db, user, "提交修改申请", target=f"{student.student_no} {student.name}",
            # 写成「本人电话：138… → 139…」，和通过申请时那条日志一个口径
            detail=_describe(student, changes),
            ip=ip,
        )
        db.commit()
    except Exception:
        db.rollback()
        # 申请没建起来，刚落的那张照片就成了没人引用的孤儿（remove_photo 收到 None 是空操作）
        remove_photo(changes.get("id_photo"))
        raise
    db.refresh(req)

    # 提醒班委来处理。待办性质，用 timeSensitive 让它能穿透专注模式
    # **不排除提交人自己**：班委自己提的修改申请也等着他们审
    # （理由见 notify_service.recipients，四个办件提交接口口径一致）
    notify(
        db,
        background,
        recipients(db, roles=REVIEWER_ROLES),
        "有新的信息修改申请待审核",
        f"{student.name} 提交了 {len(changes)} 项修改，等待你审核",
        level="timeSensitive",
        page="/review",
    )
    return _to_response(req, student)


@router.get("/me", response_model=list[ChangeRequestResponse], summary="我的申请记录")
def my_requests(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ChangeRequest)
        .filter(ChangeRequest.student_id == student.id)
        .order_by(ChangeRequest.id.desc())
        .all()
    )
    return [_to_response(r, student) for r in rows]


@router.get("", response_model=list[ChangeRequestResponse], summary="申请列表（班委及以上）")
def list_requests(
    _: User = Depends(committee_required),
    status: str | None = Query(None, description="pending|approved|rejected，不传为全部"),
    db: Session = Depends(get_db),
):
    query = db.query(ChangeRequest)
    if status:
        query = query.filter(ChangeRequest.status == status)
    rows = query.order_by(ChangeRequest.id.desc()).all()

    # 一次把涉及的学生查出来，避免逐条查（N+1）
    student_ids = {r.student_id for r in rows}
    students = (
        {s.id: s for s in db.query(Student).filter(Student.id.in_(student_ids)).all()}
        if student_ids else {}
    )
    return [_to_response(r, students.get(r.student_id)) for r in rows]


@router.get("/{request_id}/photo", summary="审核时对照用的照片（班委及以上）")
def review_photo(
    request_id: int,
    side: str = Query("new", description="old=学生当前的照片，new=申请里上传的新照片"),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """给审核页并排展示「原图 / 新图」用。

    新照片在通过之前只躺在这条申请的 changes 里（还没写进学生表），
    所以取不到 —— 拿 GET /api/students/{id}/photo 来取的话，两个方向都是旧图。
    """
    if side not in ("old", "new"):
        raise HTTPException(status_code=400, detail="side 只能是 old 或 new")

    req = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")

    if side == "new":
        name = json.loads(req.changes or "{}").get("id_photo")
    else:
        student = db.query(Student).filter(Student.id == req.student_id).first()
        name = student.id_photo if student else None

    # 学生本来就没照片、这条申请也没传照片，都是正常的 404，前端靠它决定画不画缩略图
    if not name:
        raise HTTPException(status_code=404, detail="没有可对照的照片")
    if not photo_path(name).exists():
        raise HTTPException(status_code=404, detail="照片文件丢失")

    # 不能缓存：地址里没有版本号，而图会变（这条申请通过后学生那张就换成新的了）。
    # students.py 那边敢缓存一年，是因为它的 URL 里带着文件名当版本号
    return photo_response(name, cache="no-store")


def _get_pending(db: Session, request_id: int) -> ChangeRequest:
    """取出待审核的申请，不存在或已处理过就报错"""
    req = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理过")
    return req


def _finish(
    db: Session, req: ChangeRequest, user: User, status: str, action: str,
    reason: str | None = None, detail: str = "", ip: str | None = None,
) -> ChangeRequestResponse:
    """记录审核人与审核时间，写日志，一起提交"""
    req.status = status
    req.reason = reason
    req.reviewed_at = datetime.now()
    req.reviewer_no = user.student_no
    req.reviewer_name = display_name(db, user)
    log_operation(db, user, action, target=f"{req.student_no} {req.student_name}", detail=detail, ip=ip)
    db.commit()
    db.refresh(req)
    return _to_response(req, db.query(Student).filter(Student.id == req.student_id).first())


# 允许班委审自己的申请（不拦截），但每次都会写进操作日志
@router.post("/{request_id}/approve", response_model=ChangeRequestResponse, summary="通过申请")
def approve(
    request_id: int,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = _get_pending(db, request_id)
    student = db.query(Student).filter(Student.id == req.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")

    # 双保险：落库前再按白名单过滤一次，防止历史脏数据越权改字段。
    # 这一份要连照片字段一起认 —— 照片值就是存在 changes 里的那个文件名
    changes = {
        key: value
        for key, value in json.loads(req.changes or "{}").items()
        if key in ALL_EDITABLE_FIELDS
    }

    # 待审照片的文件得先在：文件丢了还照写，学生的档案就指向一张打不开的图
    new_photo = changes.get("id_photo")
    if new_photo and not photo_path(new_photo).exists():
        raise HTTPException(status_code=400, detail="申请里的照片文件已丢失，请驳回后让学生重新上传")

    # 详情要在 setattr 之前算：算完 student 就只剩新值了
    detail = _describe(student, changes)
    old_photo = student.id_photo
    for key, value in changes.items():
        setattr(student, key, value)

    # 先取收件人再收尾：_finish 只负责数据库，通知不该混进它里面
    targets = recipients(db, only_no=req.student_no)
    result = _finish(db, req, user, "approved", "通过修改申请", detail=detail, ip=ip)
    # 提交成功之后才删旧照片（与 api/students.py 换照片同一顺序：失败时旧数据完好）
    if new_photo and old_photo and old_photo != new_photo:
        remove_photo(old_photo)
    notify(
        db, background, targets, "信息修改申请已通过",
        f"你提交的 {len(changes)} 项修改已生效", level="timeSensitive", page="/my-info?tab=workspace&sub=submitted",
    )
    return result


@router.post("/{request_id}/reject", response_model=ChangeRequestResponse, summary="驳回申请")
def reject(
    request_id: int,
    payload: RejectRequest,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = _get_pending(db, request_id)
    targets = recipients(db, only_no=req.student_no)
    result = _finish(db, req, user, "rejected", "驳回修改申请", reason=payload.reason, ip=ip)
    # 驳回之后这张照片再没人会引用，不删就是永久孤儿（req.changes 收尾时不会被改动）
    remove_photo(json.loads(req.changes or "{}").get("id_photo"))
    notify(
        db, background, targets, "信息修改申请被驳回",
        f"理由：{clip(payload.reason)}", level="timeSensitive", page="/my-info?tab=workspace&sub=submitted",
    )
    return result
