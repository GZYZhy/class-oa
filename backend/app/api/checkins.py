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

import os
import secrets
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
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import AttendanceItem, Checkin, CheckinTarget, Student, User
from ..schemas import (
    CheckinCreate,
    CheckinDetailResponse,
    CheckinListItem,
    CheckinListResponse,
    CheckinLocationResponse,
    CheckinPublicResponse,
    CheckinTargetResponse,
)
from ..services import display_name, log_operation, notify, recipients
from ..services.checkin_service import (
    CHECKIN_ONGOING,
    approved_leave_nos,
    checkin_status,
    finalize_checkin,
    finalize_due,
    haversine_m,
)
from ..utils.links import full_url
from .deps import (
    committee_required,
    get_client_ip,
    get_current_student,
    get_optional_user,
)

router = APIRouter(prefix="/api/checkins", tags=["签到"])

# 签到照片单独一个目录，不和学生照片/请假证明混在一起。
# 测试用 CHECKIN_DIR 指到临时目录；生产默认落在挂载出来的 data/ 下，备份会一起打包
CHECKIN_DIR = Path(os.environ.get("CHECKIN_DIR") or (BASE_DIR / "data" / "checkins"))
CHECKIN_DIR.mkdir(parents=True, exist_ok=True)

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTO_BYTES = 10 * 1024 * 1024


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
        raise HTTPException(status_code=404, detail="签到不存在或链接已失效")
    return checkin


def _new_code(db: Session) -> str:
    """12 位 URL 安全随机串。够长，猜不到；撞了换一个，最多试 5 次"""
    for _ in range(5):
        code = secrets.token_urlsafe(9)
        if not db.query(Checkin.id).filter(Checkin.code == code).first():
            return code
    raise HTTPException(status_code=500, detail="生成签到链接失败，请重试")


def _link(request: Request, checkin: Checkin) -> str:
    return full_url(request, f"/#/checkin?code={checkin.code}")


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
    return CheckinPublicResponse(
        code=checkin.code,
        title=checkin.title or "",
        remark=checkin.remark or "",
        status=status,
        created_by_name=checkin.created_by_name or "",
        created_at=checkin.created_at,
        end_at=checkin.end_at,
        require_photo=bool(checkin.require_photo),
        location=_location_of(checkin),
        target_count=db.query(CheckinTarget)
        .filter(CheckinTarget.checkin_id == checkin.id)
        .count(),
        link=_link(request, checkin),
        is_login=is_login,
        is_target=target is not None,
        # 能不能签只由服务端给结论；前端拿这个字段决定按钮显不显示
        can_sign=bool(
            is_login
            and target is not None
            and target.signed_at is None
            and status == CHECKIN_ONGOING
        ),
        signed_at=target.signed_at if target else None,
        my_distance_m=target.distance_m if target else None,
        on_leave=on_leave,
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
    if data.end_at.tzinfo is not None:
        raise HTTPException(
            status_code=400, detail="时间请用不带时区的写法，例如 2026-10-18 19:30"
        )
    if data.end_at <= datetime.now():
        raise HTTPException(status_code=400, detail="截止时间必须晚于当前时间")

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
        detail=f"范围 {len(nos)} 人，截止 {data.end_at:%m-%d %H:%M}"
        + ("，需照片" if data.require_photo else "")
        + ("，需定位" if location else ""),
        ip=get_client_ip(request),
    )
    db.commit()

    # commit 之后才通知（见文件头第 2 条）。逐个人调 recipients：范围是任意子集，
    # recipients 没有「批量学号」参数；班级几十人，循环最简单。
    # 不排除发布人：发布人自己在范围内时同样要签到，也得收到这条信
    body = f"截止 {checkin.end_at:%m-%d %H:%M}，打开链接完成签到"
    for no in nos:
        notify(
            db,
            background,
            recipients(db, only_no=no),
            f"新签到：{title}",
            body,
            level="timeSensitive",
            page=f"/checkin?code={checkin.code}",
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
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    finalize_due(db)
    checkin = _get_by_code(db, code)
    return _public_response(
        db,
        request,
        checkin,
        is_login=user is not None,
        student_no=getattr(user, "student_no", None) if user else None,
    )


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
    "/public/{code}/sign",
    response_model=CheckinPublicResponse,
    summary="学生签到（需登录且在范围内）",
)
def sign_checkin(
    code: str,
    request: Request,
    lat: float | None = Form(None, description="GCJ-02 纬度"),
    lng: float | None = Form(None, description="GCJ-02 经度"),
    photo: UploadFile | None = File(None),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    finalize_due(db)
    checkin = _get_by_code(db, code)
    if checkin_status(checkin) != CHECKIN_ONGOING:
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

    if checkin.require_photo and (photo is None or not photo.filename):
        raise HTTPException(status_code=400, detail="本次签到需要上传一张照片")
    photo_file = _save_photo(photo) if (photo is not None and photo.filename) else None

    # 条件 UPDATE 抢签到权：两个请求同时提交时，只有第一个 signed_at 还是空的人能改到，
    # 第二个 rowcount=0，照片也不会留下孤儿文件
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
        if photo_file:
            (CHECKIN_DIR / photo_file).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="你已签到，不用重复提交")

    try:
        db.commit()
    except Exception:
        if photo_file:
            (CHECKIN_DIR / photo_file).unlink(missing_ok=True)
        raise

    # 应到的人都签到了就没必要再等截止：立即结束并结算。
    # 最后一个签的人拿到的就是「已结束」，页面上直接能看到最终结果
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
