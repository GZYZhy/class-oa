"""签到式点名：发布、公开信息、学生签到、提前结束

和「考勤记录」的分工：这里只负责收集谁签了到，**结算成到/请假/无应答**
由 services/checkin_service.py 统一做，产物是一条普通考勤记录。考勤页的
明细修改、备注、导出因此一行都不用改。

两条容易踩的规矩：
1. `/public/...` 这类固定路径必须定义在 `/{checkin_id}` 之前，否则
   `/api/checkins/public/xxx` 会先撞上 `{checkin_id}` 被当成数字解析（422）。
2. 站内信必须在建签到的事务 commit 之后发 —— notify 里的站内信写入自己会
   commit，提前发会把「建签到」这笔半截事务一起提交掉（全项目统一口径）。
"""

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import resolve_session_secret
from ..database import get_db
from ..models import AttendanceItem, Checkin, CheckinTarget, Student, User
from ..schemas import (
    CheckinCreate,
    CheckinDetailResponse,
    CheckinListItem,
    CheckinListResponse,
    CheckinLocationResponse,
    CheckinPublicResponse,
    CheckinTitleUpdate,
    CheckinTargetResponse,
)
from ..services import display_name, log_operation, notify, recipients
from ..services.checkin_service import (
    CHECKIN_DIR,
    CHECKIN_ENDED,
    CHECKIN_ONGOING,
    CHECKIN_PAUSED,
    CHECKIN_PENDING,
    approved_leave_nos,
    checkin_status,
    finalize_checkin,
    finalize_due,
    haversine_m,
    remove_checkin,
    remove_photos,
)
from ..services.share_service import share_path
from ..utils.links import full_url
from .deps import (
    committee_required,
    get_client_ip,
    get_current_student,
    get_optional_user,
)

router = APIRouter(prefix="/api/checkins", tags=["签到"])

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTO_BYTES = 10 * 1024 * 1024

# 迟到的两条有界理由共用一个窗口，都要求「截止前」已经动手：
# 1. 照片是截止前开始传的 —— 慢网络下十几 MB 的照片传几分钟很正常；
# 2. 页面是截止前打开的 —— 打开时还没登录，找学号、输密码花掉的时间不该让人白跑。
# 5 分钟：够登录、够传一张图，又不会变成「过了截止还能慢慢签」。
GRACE = timedelta(minutes=5)


# ---------- 小工具 ----------

def _get_checkin(db: Session, checkin_id: int) -> Checkin:
    checkin = db.query(Checkin).filter(Checkin.id == checkin_id).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="签到不存在")
    return checkin


def _get_by_code(db: Session, code: str) -> Checkin:
    checkin = db.query(Checkin).filter(Checkin.code == code).first()
    if not checkin:
        # 不知道 code 的人不该知道「有这么一场签到」（同投票的越权口径）
        raise HTTPException(
            status_code=404, detail="这次签到不存在或已被删除，链接已失效"
        )
    return checkin


def _new_code(db: Session) -> str:
    """12 位 URL 安全随机串。够长，猜不到；撞了换一个，最多试 5 次"""
    for _ in range(5):
        code = secrets.token_urlsafe(9)
        if not db.query(Checkin.id).filter(Checkin.code == code).first():
            return code
    raise HTTPException(status_code=500, detail="生成签到链接失败，请重试")


def _link(request: Request, checkin: Checkin) -> str:
    """对外分享的链接：真实路径，服务器能看到是哪一场

    不能用 `/#/checkin?code=…`：hash 后面的内容不会发给服务器，微信爬虫
    读不到这一场的 meta。真实路径由 nginx 返回 index.html 并注入 head 片段，
    浏览器落地后由 share-boot.js 映射到同一个应用内路由。
    """
    return full_url(request, share_path("checkin", checkin.code))


def _location_of(checkin: Checkin) -> CheckinLocationResponse | None:
    """只有坐标齐全才算「要求定位」；只写了个地点名不算"""
    if checkin.lat is None or checkin.lng is None:
        return None
    return CheckinLocationResponse(
        lat=checkin.lat,
        lng=checkin.lng,
        radius_m=checkin.radius_m or 0,
        name=checkin.location_name or "",
    )


def _signed_counts(db: Session, checkin_ids: list[int]) -> dict[int, int]:
    """一次分组查询把本页所有签到的已签人数拿回来，不要每条各查一遍"""
    if not checkin_ids:
        return {}
    rows = (
        db.query(CheckinTarget.checkin_id, func.count())
        .filter(
            CheckinTarget.checkin_id.in_(checkin_ids),
            CheckinTarget.signed_at.isnot(None),
        )
        .group_by(CheckinTarget.checkin_id)
        .all()
    )
    return {checkin_id: count for checkin_id, count in rows}


def _target_counts(db: Session, checkin_ids: list[int]) -> dict[int, int]:
    if not checkin_ids:
        return {}
    rows = (
        db.query(CheckinTarget.checkin_id, func.count())
        .filter(CheckinTarget.checkin_id.in_(checkin_ids))
        .group_by(CheckinTarget.checkin_id)
        .all()
    )
    return {checkin_id: count for checkin_id, count in rows}


def _list_item(
    request: Request,
    checkin: Checkin,
    target_count: int,
    signed_count: int,
) -> CheckinListItem:
    return CheckinListItem(
        id=checkin.id,
        code=checkin.code,
        title=checkin.title or "",
        status=checkin_status(checkin),
        created_by_name=checkin.created_by_name or "",
        created_at=checkin.created_at,
        start_at=checkin.start_at,
        end_at=checkin.end_at,
        target_count=target_count,
        signed_count=signed_count,
        link=_link(request, checkin),
    )


def _detail(db: Session, request: Request, checkin: Checkin) -> CheckinDetailResponse:
    targets = (
        db.query(CheckinTarget)
        .filter(CheckinTarget.checkin_id == checkin.id)
        .order_by(CheckinTarget.student_no)
        .all()
    )
    # 请假按「截止时刻」判：页面在截止前打开时，这标的是「不签会被算成请假」，
    # 而不是「现在就在请假」。结算用的是同一个参考时刻，两处不会打架
    reference = checkin.closed_at or checkin.end_at
    leave_nos = approved_leave_nos(db, [t.student_no for t in targets], reference)
    # 结算后的出勤状态以考勤明细为准：班委在明细里改过之后，这里要跟着变
    status_by_no: dict[str, str] = {}
    if checkin.attendance_record_id:
        status_by_no = dict(
            db.query(AttendanceItem.student_no, AttendanceItem.status)
            .filter(AttendanceItem.record_id == checkin.attendance_record_id)
            .all()
        )
    base = _list_item(request, checkin, len(targets), sum(1 for t in targets if t.signed_at))
    return CheckinDetailResponse(
        **base.model_dump(),
        remark=checkin.remark or "",
        require_photo=bool(checkin.require_photo),
        location=_location_of(checkin),
        created_by_no=checkin.created_by_no or "",
        closed_at=checkin.closed_at,
        finalized_at=checkin.finalized_at,
        attendance_record_id=checkin.attendance_record_id,
        targets=[
            CheckinTargetResponse(
                student_no=t.student_no,
                student_name=t.student_name or "",
                signed_at=t.signed_at,
                distance_m=t.distance_m,
                on_leave=t.student_no in leave_nos,
                status=status_by_no.get(t.student_no, ""),
                photo_url=(
                    f"/api/checkins/{checkin.id}/targets/{t.student_no}/photo"
                    if t.photo_file
                    else ""
                ),
            )
            for t in targets
        ],
    )


def _public_response(
    db: Session,
    request: Request,
    checkin: Checkin,
    *,
    is_login: bool,
    student_no: str | None,
) -> CheckinPublicResponse:
    target = None
    if student_no:
        target = (
            db.query(CheckinTarget)
            .filter(
                CheckinTarget.checkin_id == checkin.id,
                CheckinTarget.student_no == student_no,
            )
            .first()
        )
    reference = checkin.closed_at or checkin.end_at
    on_leave = bool(
        target
        and approved_leave_nos(db, [target.student_no], reference)
    )
    status = checkin_status(checkin)
    # 截止前打开过页面的，截止后还有一段补签宽限（GRACE）。
    # 只有已结束才查：未开始时参考时刻还在未来，凭证会被误判成「宽限内」
    open_until = (
        _open_grace_until(request, checkin, student_no or "")
        if status == CHECKIN_ENDED
        else None
    )
    return CheckinPublicResponse(
        code=checkin.code,
        title=checkin.title or "",
        remark=checkin.remark or "",
        status=status,
        created_by_name=checkin.created_by_name or "",
        created_at=checkin.created_at,
        start_at=checkin.start_at,
        end_at=checkin.end_at,
        require_photo=bool(checkin.require_photo),
        location=_location_of(checkin),
        target_count=db.query(CheckinTarget)
        .filter(CheckinTarget.checkin_id == checkin.id)
        .count(),
        link=_link(request, checkin),
        is_login=is_login,
        is_target=target is not None,
        # 能不能签只由服务端给结论；前端拿这个字段决定按钮显不显示。
        # 已结束但还在开页宽限内的，同样算能签
        can_sign=bool(
            is_login
            and target is not None
            and target.signed_at is None
            and checkin.paused_at is None
            and (status == CHECKIN_ONGOING or open_until is not None)
        ),
        signed_at=target.signed_at if target else None,
        my_distance_m=target.distance_m if target else None,
        on_leave=on_leave,
        grace_until=open_until,
    )


def _save_photo(file: UploadFile) -> str:
    """把签到照片写进 CHECKIN_DIR，返回 UUID 文件名

    只认后缀和大小、不解析图片 —— 与学生照片、请假证明的口径一致
    （student_photo_service.save_photo）。
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in PHOTO_SUFFIXES:
        raise HTTPException(status_code=400, detail="只支持 JPG / PNG / WEBP 图片")
    data = file.file.read(MAX_PHOTO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="照片是空文件")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="照片不能超过 10MB")
    name = f"{uuid.uuid4().hex}{suffix}"
    (CHECKIN_DIR / name).write_bytes(data)
    return name


def _photo_token(checkin: Checkin, student_no: str, started_at: datetime, name: str) -> str:
    """把「谁、哪场签到、几点开始传、传成了哪个文件」签成一个令牌

    签到接口凭它判断照片是不是本人、是不是这场、是不是截止前开始传的。
    不签名的话，改一下时间就能把截止后才开始传的照片算成截止前。
    """
    payload = f"{checkin.id}:{student_no}:{int(started_at.timestamp())}:{name}"
    sig = hmac.new(
        resolve_session_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def _read_photo_token(token: str, checkin: Checkin, student_no: str) -> tuple[datetime, str]:
    """验照片令牌，返回（上传开始时间, 文件名）；不合法一律 400"""
    invalid = HTTPException(status_code=400, detail="照片凭证无效，请重新选择照片上传")
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit(":", 1)
        cid, no, ts, name = payload.split(":", 3)
    except (ValueError, UnicodeDecodeError):
        raise invalid

    expected = hmac.new(
        resolve_session_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    if (
        not hmac.compare_digest(sig, expected)
        or cid != str(checkin.id)
        or no != student_no
        or Path(name).name != name
    ):
        raise invalid
    return datetime.fromtimestamp(int(ts)), name


def _open_cookie_name(checkin_id: int) -> str:
    """带上 id：同一浏览器同时开着两场签到，两份凭证互不覆盖"""
    return f"checkin_open_{checkin_id}"


def _open_token(checkin: Checkin, student_no: str | None, opened_at: datetime) -> str:
    """把「谁、哪场签到、几点打开的页面」签成 Cookie 凭证

    只证明页面是截止前打开的；到底能不能签，签到接口还会再按截止时间 + 宽限
    判一次。游客打开时还不知道是谁，学号留空，登录后哪个本班账号都能接上。
    """
    payload = f"{checkin.id}:{student_no or ''}:{int(opened_at.timestamp())}"
    sig = hmac.new(
        resolve_session_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def _read_open_token(
    token: str, checkin: Checkin, student_no: str
) -> datetime | None:
    """验开页凭证，返回打开时间；不合法一律当作没有

    这不是错误：没有凭证的普通签到照常按截止时间走，不该因为浏览器禁了 Cookie
    就回一句看不明白的 400。
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit(":", 1)
        cid, no, ts = payload.split(":", 2)
        opened_at = datetime.fromtimestamp(int(ts))
    except (ValueError, UnicodeDecodeError, OverflowError, OSError):
        return None

    expected = hmac.new(
        resolve_session_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected) or cid != str(checkin.id):
        return None
    # 游客凭证（no 为空）谁登录都能用；已登录时打开的凭证只认本人
    if no and no != student_no:
        return None
    return opened_at


def _open_grace_until(
    request: Request, checkin: Checkin, student_no: str
) -> datetime | None:
    """这次请求还在不在「截止前打开过页面」的补签宽限内；在就返回到什么时候

    三个条件缺一不可：页面确实在截止前打开、本人（或游客）的凭证、现在没超过
    截止后 GRACE。
    """
    token = request.cookies.get(_open_cookie_name(checkin.id))
    if not token:
        return None
    opened_at = _read_open_token(token, checkin, student_no)
    if opened_at is None:
        return None
    reference = checkin.closed_at or checkin.end_at
    if opened_at >= reference:
        return None
    until = reference + GRACE
    return until if datetime.now() <= until else None


# ---------- 班委端 ----------

@router.post("", response_model=CheckinDetailResponse, summary="发布签到（班委及以上）")
def create_checkin(
    data: CheckinCreate,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    # 与投票同口径：前端传的是不带时区的串。带 Z / +08:00 的输入拿去和
    # naive 的 now() 比会抛 TypeError，静默去时区又会悄悄错 8 小时，所以直接拒
    if data.end_at.tzinfo is not None or (
        data.start_at is not None and data.start_at.tzinfo is not None
    ):
        raise HTTPException(
            status_code=400, detail="时间请用不带时区的写法，例如 2026-10-18 19:30"
        )
    if data.end_at <= datetime.now():
        raise HTTPException(status_code=400, detail="截止时间必须晚于当前时间")
    if data.start_at is not None and data.start_at >= data.end_at:
        raise HTTPException(status_code=400, detail="开始时间必须早于截止时间")

    # 去重、去空：同一学号传两次只会插一行（唯一约束兜底，但提前收拾干净）
    nos: list[str] = []
    seen: set[str] = set()
    for raw in data.targets:
        no = raw.strip()
        if no and no not in seen:
            seen.add(no)
            nos.append(no)
    if not nos:
        raise HTTPException(status_code=400, detail="至少要选一名同学")

    students = db.query(Student).filter(Student.student_no.in_(nos)).all()
    by_no = {s.student_no: s for s in students}
    missing = [no for no in nos if no not in by_no]
    if missing:
        raise HTTPException(
            status_code=400, detail=f"有 {len(missing)} 名同学不在名单中"
        )

    location = data.location
    checkin = Checkin(
        code=_new_code(db),
        title=title,
        remark=data.remark.strip(),
        created_by_no=user.student_no,
        created_by_name=display_name(db, user),
        created_at=datetime.now(),
        start_at=data.start_at,
        end_at=data.end_at,
        require_photo=data.require_photo,
        lat=location.lat if location else None,
        lng=location.lng if location else None,
        radius_m=location.radius_m if location else None,
        location_name=location.name.strip() if location else "",
    )
    db.add(checkin)
    db.flush()   # 拿到自增 id，targets 要用

    # 姓名从 Student 表取，不信任前端传的名字
    db.add_all(
        [
            CheckinTarget(
                checkin_id=checkin.id,
                student_no=no,
                student_name=by_no[no].name,
            )
            for no in nos
        ]
    )
    log_operation(
        db,
        user,
        action="发布签到",
        target=title,
        detail=f"范围 {len(nos)} 人"
        + (f"，{data.start_at:%m-%d %H:%M} 开始" if data.start_at else "")
        + f"，截止 {data.end_at:%m-%d %H:%M}"
        + ("，需照片" if data.require_photo else "")
        + ("，需定位" if location else ""),
        ip=get_client_ip(request),
    )
    db.commit()

    # commit 之后才通知（见文件头第 2 条）。逐个人调 recipients：范围是任意子集，
    # recipients 没有「批量学号」参数；班级几十人，循环最简单。
    # 不排除发布人：发布人自己在范围内时同样要签到，也得收到这条信
    body = (
        (f"{checkin.start_at:%m-%d %H:%M} 开始，" if checkin.start_at else "")
        + f"截止 {checkin.end_at:%m-%d %H:%M}，打开链接完成签到"
    )
    for no in nos:
        notify(
            db,
            background,
            recipients(db, only_no=no),
            f"新签到：{title}",
            body,
            level="timeSensitive",
            # 站内信直接落到分享落地页：和列表、外链是同一张整页
            page=share_path("checkin", checkin.code),
        )

    db.refresh(checkin)
    return _detail(db, request, checkin)


@router.get("", response_model=CheckinListResponse, summary="签到列表（班委及以上）")
def list_checkins(
    request: Request,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    finalize_due(db)
    checkins = db.query(Checkin).order_by(Checkin.id.desc()).all()
    ids = [c.id for c in checkins]
    signed = _signed_counts(db, ids)
    totals = _target_counts(db, ids)
    return CheckinListResponse(
        total=len(checkins),
        items=[
            _list_item(request, c, totals.get(c.id, 0), signed.get(c.id, 0))
            for c in checkins
        ],
    )


# 固定路径必须排在 /{checkin_id} 前面，否则 /api/checkins/public/xxx 会先撞上
# {checkin_id} 被当成数字解析，直接 422
@router.get(
    "/public/{code}",
    response_model=CheckinPublicResponse,
    summary="签到公开信息（凭链接，无需登录）",
)
def public_checkin(
    code: str,
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    finalize_due(db)
    checkin = _get_by_code(db, code)
    student_no = getattr(user, "student_no", None) if user else None
    payload = _public_response(
        db,
        request,
        checkin,
        is_login=user is not None,
        student_no=student_no,
    )

    # 截止前打开的都签发「打开过页面」的凭证；未开始也算 —— 有人可能提前点开
    # 链接，登录回来时已经过点。过了截止再打开的不发 —— 否则就成了随时可以来
    # 拿一张、补签窗口永远开着的卡。每次打开都重签一次，时间跟着更新
    now = datetime.now()
    if checkin_status(checkin, now=now) != CHECKIN_ENDED:
        reference = checkin.closed_at or checkin.end_at
        response.set_cookie(
            _open_cookie_name(checkin.id),
            _open_token(checkin, student_no, now),
            # 未开始的签到参考时刻可能还很远，给 cookie 设个 7 天上限，
            # 免得浏览器直接丢弃超长 max_age
            max_age=min(
                7 * 24 * 3600,
                max(60, int((reference + GRACE - now).total_seconds())),
            ),
            path="/api/checkins",
            httponly=True,
            samesite="lax",
        )
    return payload


@router.get(
    "/share/{code}",
    summary="旧签到分享链接（302 到新地址）",
    include_in_schema=False,
)
def share_checkin(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """兼容老聊天里的链接：校验通过就 302 到新的真实路径

    新链接由 _link 直接给出 `/share/checkin/{code}`，这个接口只为已经发出去的
    旧链接保留。302 不用 301：以后路径再调时不会被浏览器永久锁死。
    """
    _get_by_code(db, code)
    return RedirectResponse(
        full_url(request, share_path("checkin", code)),
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/{checkin_id}/pause",
    response_model=CheckinDetailResponse,
    summary="暂停签到（班委及以上）",
)
def pause_checkin(
    checkin_id: int,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """暂停收签到。**暂停不是结束**：恢复后照样能签；到截止时间还没恢复则照常自动结束"""
    finalize_due(db)
    checkin = _get_checkin(db, checkin_id)
    state = checkin_status(checkin)
    # 已经暂停时幂等返回，别把「什么时候暂停的」一直往后推
    if state == CHECKIN_PAUSED:
        return _detail(db, request, checkin)
    if state != CHECKIN_ONGOING:
        raise HTTPException(status_code=400, detail="只有进行中的签到才能暂停")

    checkin.paused_at = datetime.now()
    log_operation(
        db, user, action="暂停签到",
        target=f"{checkin.end_at:%Y-%m-%d} {checkin.title}",
        ip=get_client_ip(request),
    )
    db.commit()
    db.refresh(checkin)
    return _detail(db, request, checkin)


@router.post(
    "/{checkin_id}/resume",
    response_model=CheckinDetailResponse,
    summary="恢复签到（班委及以上）",
)
def resume_checkin(
    checkin_id: int,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """恢复收签到。

    和投票一样**不判当前状态、无条件清空**：暂停中过了截止时间的签到，
    这时候状态已经是「已结束」了，按状态判会回一句「没有暂停」；清掉没副作用。
    """
    finalize_due(db)
    checkin = _get_checkin(db, checkin_id)
    was_paused = checkin.paused_at is not None
    checkin.paused_at = None
    if was_paused:
        log_operation(
            db, user, action="恢复签到",
            target=f"{checkin.end_at:%Y-%m-%d} {checkin.title}",
            ip=get_client_ip(request),
        )
        db.commit()
        db.refresh(checkin)
    return _detail(db, request, checkin)


@router.post(
    "/{checkin_id}/close",
    response_model=CheckinDetailResponse,
    summary="提前结束签到（班委及以上）",
)
def close_checkin(
    checkin_id: int,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    finalize_due(db)
    checkin = _get_checkin(db, checkin_id)
    if checkin.finalized_at is not None:
        raise HTTPException(status_code=400, detail="这次签到已经结束")

    checkin.closed_at = datetime.now()
    log_operation(
        db,
        user,
        action="结束签到",
        target=checkin.title or "",
        detail="提前结束并结算",
        ip=get_client_ip(request),
    )
    db.commit()
    finalize_checkin(db, checkin)   # 立即结算，不用等任何人刷新页面
    db.refresh(checkin)
    return _detail(db, request, checkin)


@router.post(
    "/{checkin_id}/extend",
    response_model=CheckinDetailResponse,
    summary="延长签到截止时间 5 分钟（班委及以上）",
)
def extend_checkin(
    checkin_id: int,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """截止前可反复延长，每次 5 分钟，不设上限。

    只能在本来的截止时间到之前操作：已经到点（哪怕还没懒结算）就不算了，
    否则会把一次已经结束的签到重新拉回进行中，和结算结果对不上。
    """
    checkin = _get_checkin(db, checkin_id)
    if checkin.finalized_at is not None:
        raise HTTPException(status_code=400, detail="这次签到已经结束")
    now = datetime.now()
    if now >= checkin.end_at:
        raise HTTPException(
            status_code=400, detail="已经过了截止时间，不能再延长"
        )

    before = checkin.end_at
    checkin.end_at = before + timedelta(minutes=5)
    log_operation(
        db,
        user,
        action="延长签到",
        target=checkin.title or "",
        detail=f"截止 {before:%m-%d %H:%M} → {checkin.end_at:%m-%d %H:%M}",
        ip=get_client_ip(request),
    )
    db.commit()
    db.refresh(checkin)
    return _detail(db, request, checkin)


@router.post(
    "/{checkin_id}/remind",
    summary="提醒还没签到的同学（班委及以上）",
)
def remind_checkin(
    checkin_id: int,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """只给还没签到的人发站内信，已签的、范围外的人都不打扰。

    和发布时一样，notify 自己会 commit，必须放在这次请求的事务 commit 之后。
    """
    checkin = _get_checkin(db, checkin_id)
    if checkin.finalized_at is not None or datetime.now() >= checkin.end_at:
        raise HTTPException(status_code=400, detail="这次签到已经结束")

    unsigned = (
        db.query(CheckinTarget)
        .filter(
            CheckinTarget.checkin_id == checkin.id,
            CheckinTarget.signed_at.is_(None),
        )
        .all()
    )
    log_operation(
        db,
        user,
        action="提醒签到",
        target=checkin.title or "",
        detail=f"提醒 {len(unsigned)} 名未签到的同学",
        ip=get_client_ip(request),
    )
    db.commit()

    body = f"截止 {checkin.end_at:%m-%d %H:%M}，你还没签到，打开链接完成签到"
    for target in unsigned:
        notify(
            db,
            background,
            recipients(db, only_no=target.student_no),
            f"提醒签到：{checkin.title}",
            body,
            level="timeSensitive",
            page=share_path("checkin", checkin.code),
        )
    return {"ok": True, "reminded": len(unsigned)}


@router.get(
    "/{checkin_id}",
    response_model=CheckinDetailResponse,
    summary="签到详情（班委及以上）",
)
def get_checkin(
    checkin_id: int,
    request: Request,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    finalize_due(db)
    return _detail(db, request, _get_checkin(db, checkin_id))


@router.patch(
    "/{checkin_id}",
    response_model=CheckinDetailResponse,
    summary="改签到标题（班委及以上）",
)
def update_checkin_title(
    checkin_id: int,
    data: CheckinTitleUpdate,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """列表的「备注」列显示的、关键词搜索搜的，都是这里改的标题。

    标题不能清空：空标题在列表里认不出是哪次签到，也没法搜。
    """
    checkin = _get_checkin(db, checkin_id)
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    before = checkin.title or ""
    if title != before:
        checkin.title = title
        log_operation(
            db,
            user,
            action="修改签到标题",
            target=f"{checkin.end_at:%Y-%m-%d} {before}",
            detail=f"「{before}」→「{title}」",
            ip=get_client_ip(request),
        )
        db.commit()
        db.refresh(checkin)
    return _detail(db, request, checkin)


@router.delete("/{checkin_id}", summary="删除一次签到（班委及以上）")
def delete_checkin(
    checkin_id: int,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """删掉签到本身、签到照片，以及结算时生成的那条考勤记录。

    反过来，在考勤列表里删那条生成的考勤也会连这次签到一起删
    （见 attendance.delete_attendance），两边都不留指空的数据。
    """
    checkin = _get_checkin(db, checkin_id)
    targets = (
        db.query(CheckinTarget)
        .filter(CheckinTarget.checkin_id == checkin_id)
        .all()
    )

    log_operation(
        db,
        user,
        action="删除签到",
        target=f"{checkin.end_at:%Y-%m-%d} {checkin.title}",
        detail=f"应到 {len(targets)} 人，已签 {sum(1 for t in targets if t.signed_at)} 人"
        + ("，结算生成的考勤记录一并删除" if checkin.attendance_record_id else ""),
        ip=get_client_ip(request),
        target_student_nos=[t.student_no for t in targets],
    )
    photo_files = remove_checkin(db, checkin)
    db.commit()
    # 事务成功后再删照片文件；回滚时照片还留着
    remove_photos(photo_files)
    return {"ok": True}


@router.get(
    "/{checkin_id}/targets/{student_no}/photo",
    summary="查看签到照片（班委及以上）",
)
def get_checkin_photo(
    checkin_id: int,
    student_no: str,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    target = (
        db.query(CheckinTarget)
        .filter(
            CheckinTarget.checkin_id == checkin_id,
            CheckinTarget.student_no == student_no,
        )
        .first()
    )
    if not target or not target.photo_file:
        raise HTTPException(status_code=404, detail="没有签到照片")
    # 只取 basename：库里的值是我们自己生成的 UUID 文件名，仍然不拼路径
    path = CHECKIN_DIR / Path(target.photo_file).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="照片文件已丢失")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


# ---------- 公开端 ----------

@router.post(
    "/public/{code}/photo",
    summary="先上传签到照片（需登录且在范围内）",
)
async def upload_checkin_photo(
    code: str,
    request: Request,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """选中照片就传上来，不等点「签到」。

    **不能**把文件声明成 `File(...)` 参数：FastAPI 会先收完整个请求体才进函数，
    那样记下的是「传完」时间。这里一进函数就先取时间，作为上传开始时间签进
    令牌；截止前开始传的，哪怕传完已经过点，签到接口也会认。
    """
    started_at = datetime.now()
    finalize_due(db)
    checkin = _get_by_code(db, code)
    if checkin_status(checkin, now=started_at) == CHECKIN_PENDING:
        raise HTTPException(status_code=400, detail="签到还没开始")
    if checkin.paused_at is not None:
        raise HTTPException(status_code=400, detail="签到已暂停，等发布人恢复后才能签到")
    # 截止前打开过页面的，补签宽限内也允许传照片（否则要求照片的签到根本补不上）
    if (
        checkin_status(checkin, now=started_at) != CHECKIN_ONGOING
        and _open_grace_until(request, checkin, student.student_no) is None
    ):
        raise HTTPException(status_code=400, detail="签到已经结束")

    target = (
        db.query(CheckinTarget)
        .filter(
            CheckinTarget.checkin_id == checkin.id,
            CheckinTarget.student_no == student.student_no,
        )
        .first()
    )
    if not target:
        raise HTTPException(status_code=400, detail="你不在本次签到范围内")
    if target.signed_at is not None:
        raise HTTPException(status_code=400, detail="你已签到，不用重复提交")

    form = await request.form()
    photo = form.get("photo")
    # 用属性判断而不是 isinstance：request.form() 给的是 Starlette 的 UploadFile，
    # 和 fastapi.UploadFile 不是同一个类，isinstance 会恒为 False
    if not getattr(photo, "filename", ""):
        raise HTTPException(status_code=400, detail="请选择一张照片")

    name = _save_photo(photo)
    return {"token": _photo_token(checkin, student.student_no, started_at, name)}


@router.post(
    "/public/{code}/sign",
    response_model=CheckinPublicResponse,
    summary="学生签到（需登录且在范围内）",
)
def sign_checkin(
    code: str,
    request: Request,
    lat: float | None = Form(None, description="GCJ-02 纬度"),
    lng: float | None = Form(None, description="GCJ-02 经度"),
    photo_token: str | None = Form(None, description="先上传照片拿到的令牌"),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    finalize_due(db)
    checkin = _get_by_code(db, code)
    # 未开始不能签。必须先拦：这时参考时刻（截止）还在未来，开页凭证会被
    # 后面的宽限判据误当成「已结束但在窗口内」
    if checkin_status(checkin) == CHECKIN_PENDING:
        raise HTTPException(status_code=400, detail="签到还没开始")
    if checkin.paused_at is not None:
        raise HTTPException(status_code=400, detail="签到已暂停，等发布人恢复后才能签到")

    # 照片已经先传完了，这里只验令牌。上传统计的是「开始传」的时刻：
    # 截止前开始传、传完才点签到，仍然算数
    photo_file: str | None = None
    upload_started: datetime | None = None
    if photo_token:
        upload_started, photo_file = _read_photo_token(
            photo_token, checkin, student.student_no
        )
        if not (CHECKIN_DIR / photo_file).is_file():
            raise HTTPException(status_code=400, detail="照片已失效，请重新选择上传")

    reference = checkin.closed_at or checkin.end_at
    now = datetime.now()
    # 两条有界的迟到理由：照片是截止前开始传的，或者页面是截止前打开的（登录耗时）
    late_ok = bool(
        photo_file
        and upload_started is not None
        and upload_started < reference
        and now <= reference + GRACE
    )
    late_open = _open_grace_until(request, checkin, student.student_no) is not None
    if (
        checkin_status(checkin, now=now) != CHECKIN_ONGOING
        and not late_ok
        and not late_open
    ):
        raise HTTPException(status_code=400, detail="签到已经结束")

    target = (
        db.query(CheckinTarget)
        .filter(
            CheckinTarget.checkin_id == checkin.id,
            CheckinTarget.student_no == student.student_no,
        )
        .first()
    )
    if not target:
        raise HTTPException(status_code=400, detail="你不在本次签到范围内")
    if target.signed_at is not None:
        raise HTTPException(status_code=400, detail="你已签到，不用重复提交")

    distance: int | None = None
    if checkin.lat is not None and checkin.lng is not None:
        if lat is None or lng is None:
            raise HTTPException(status_code=400, detail="本次签到需要获取你的位置")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(status_code=400, detail="位置坐标不合法")
        distance = round(haversine_m(checkin.lat, checkin.lng, lat, lng))
        if distance > (checkin.radius_m or 0):
            raise HTTPException(
                status_code=400,
                detail=f"你距离签到地点约 {distance} 米，超出允许范围"
                f"（{checkin.radius_m or 0} 米）",
            )

    if checkin.require_photo and not photo_file:
        raise HTTPException(status_code=400, detail="本次签到需要上传一张照片")

    # 条件 UPDATE 抢签到权：两个请求同时提交时，只有第一个 signed_at 还是空的人能改到。
    # 失败时**不要**删照片：同一个照片令牌可能被重复提交，第一个请求已经把它
    # 挂到签到记录上，第二个删掉就成了坏图；宁可留一个没被引用的文件。
    claimed = (
        db.query(CheckinTarget)
        .filter(
            CheckinTarget.id == target.id,
            CheckinTarget.signed_at.is_(None),
        )
        .update(
            {
                CheckinTarget.signed_at: datetime.now(),
                CheckinTarget.lat: lat,
                CheckinTarget.lng: lng,
                CheckinTarget.distance_m: distance,
                CheckinTarget.photo_file: photo_file,
                CheckinTarget.ip: get_client_ip(request),
            },
            synchronize_session=False,
        )
    )
    if not claimed:
        raise HTTPException(status_code=400, detail="你已签到，不用重复提交")

    db.commit()
    db.refresh(checkin)

    # 过了点才签上：结算可能已经跑过，把考勤明细里这个人从「无应答/请假」
    # 改回「到」，否则签到记录和考勤明细会对不上
    if checkin.finalized_at is not None and checkin.attendance_record_id:
        item = (
            db.query(AttendanceItem)
            .filter(
                AttendanceItem.record_id == checkin.attendance_record_id,
                AttendanceItem.student_no == student.student_no,
            )
            .first()
        )
        if item is not None and item.status != "present":
            item.status = "present"
            db.commit()

    # 应到的人都签到了就没必要再等截止：立即结束并结算。
    # 已经结算过的（上面那种过了点才签上的）不用再走一遍。
    # 最后一个签的人拿到的就是「已结束」，页面上直接能看到最终结果
    if checkin.finalized_at is None:
        unsigned = (
            db.query(CheckinTarget)
            .filter(
                CheckinTarget.checkin_id == checkin.id,
                CheckinTarget.signed_at.is_(None),
            )
            .count()
        )
        if unsigned == 0:
            checkin.closed_at = datetime.now()
            db.commit()
            finalize_checkin(db, checkin)

    return _public_response(
        db,
        request,
        checkin,
        is_login=True,
        student_no=student.student_no,
    )
