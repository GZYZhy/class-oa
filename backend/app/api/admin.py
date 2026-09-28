"""系统管理：仅管理员可用（账号角色、重置密码、冻结、域外账号、资料下载、操作日志）"""

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import BASE_DIR, settings
from ..database import get_db
from ..models import (
    AccountEvent,
    FileAccessLog,
    IpBan,
    OperationLog,
    PushSubscription,
    Resource,
    Student,
    User,
)
from ..schemas import (
    AccountEventResponse,
    AdminUserLogsResponse,
    AdminUserResponse,
    FileAccessLogListResponse,
    FileAccessLogResponse,
    IpBanListResponse,
    IpBanRequest,
    OperationLogListResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    RoleUpdateRequest,
    WatermarkExtractResponse,
)
from ..services import (
    account_name,
    add_invisible_watermark,
    add_resource,
    ban_ip,
    clear_failures,
    default_password,
    delete_resource,
    extract_watermark,
    list_all_resources,
    log_operation,
    parse_watermark_token,
    reorder_category,
    unban_ip,
    update_resource,
)
from ..utils.ip import normalize_target, parse_cidrs, parse_network, target_matches
from ..utils.security import hash_password, validate_password
from .deps import admin_required, get_client_ip

router = APIRouter(prefix="/api/admin", tags=["系统管理"])

ROLES = ("student", "committee", "admin")
ROLE_LABELS = {"student": "普通学生", "committee": "班委", "admin": "管理员"}

# 域外账号的头像存放目录（容器内 /app/data/avatars，启动时由 main.py 创建）
AVATAR_DIR = BASE_DIR / "data" / "avatars"
ALLOWED_AVATAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB，头像不需要更大
# 域外账号登录名：不能有空白字符，否则登录时 strip 过就对不上了
EXTERNAL_LOGIN_NAME_MAX = 20  # 与 users.student_no 的字段长度一致

# 「按账号查日志」里登录 / 改密事件的查询窗口（天）。
# 只是查询窗口，不删数据 —— account_events 只增不删
ACCOUNT_EVENT_DAYS = 7
# 窗口内的事件最多回这么多条，多出来的在 events_total 里报数，前端提示「仅显示最近 N 条」
ACCOUNT_EVENT_LIMIT = 200


def _save_avatar(file: UploadFile) -> str:
    """把上传的头像写到磁盘，返回裸文件名（库里只存文件名，不存路径）

    后缀走白名单、文件名用 UUID —— 与请假证明、公告 PDF 的做法保持一致。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        allowed = " / ".join(sorted(e.lstrip(".") for e in ALLOWED_AVATAR_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"头像只支持 {allowed} 格式")

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="头像文件不能为空")
    if len(content) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="头像不能超过 2MB")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    (AVATAR_DIR / safe_name).write_bytes(content)
    return safe_name


def _remove_avatar(file_name: str | None) -> None:
    """删头像文件。文件已经不在了也不报错（手工清理过、换过盘都可能）"""
    if not file_name:
        return
    try:
        (AVATAR_DIR / os.path.basename(file_name)).unlink(missing_ok=True)
    except OSError:
        pass


def _clean_login_name(raw: str) -> str:
    """规范并校验域外账号的登录名"""
    login_name = (raw or "").strip()
    if not login_name:
        raise HTTPException(status_code=400, detail="登录名不能为空")
    if len(login_name) > EXTERNAL_LOGIN_NAME_MAX:
        raise HTTPException(status_code=400, detail=f"登录名不能超过 {EXTERNAL_LOGIN_NAME_MAX} 个字符")
    if any(c.isspace() for c in login_name):
        raise HTTPException(status_code=400, detail="登录名不能包含空格")
    return login_name


def _clean_display_name(raw: str) -> str:
    """规范并校验展示用户名"""
    name = (raw or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="展示用户名不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="展示用户名不能超过 50 个字符")
    return name


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(
            status_code=400,
            detail="角色只能是 " + " / ".join(f"{r}（{ROLE_LABELS[r]}）" for r in ROLES),
        )
    return role


def _check_password(raw: str) -> str:
    """域外账号的密码由管理员直接指定，规则与用户自己改密时一致"""
    try:
        return validate_password(raw, "密码")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _get_external_user(db: Session, login_name: str) -> User:
    """按登录名取域外账号；不存在或不是域外账号都报错"""
    target = db.query(User).filter(User.student_no == login_name).first()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not target.is_external:
        raise HTTPException(status_code=400, detail="这是学生账号，不能在域外账号里操作")
    return target


def _get_user(db: Session, login_name: str) -> User:
    """按登录名取账号，不区分类别（冻结、查日志两种账号都要管）"""
    target = db.query(User).filter(User.student_no == login_name).first()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    return target


@router.get("/users", response_model=list[AdminUserResponse], summary="账号列表")
def list_users(_: User = Depends(admin_required), db: Session = Depends(get_db)):
    rows = (
        db.query(User, Student)
        .outerjoin(Student, Student.student_no == User.student_no)
        .order_by(User.student_no)
        .all()
    )
    return [
        AdminUserResponse(
            student_no=user.student_no,
            # 域外账号用自定义展示名，学生账号用学生姓名
            name=account_name(db, user),
            role=user.role or "student",
            must_change_password=user.must_change_password,
            is_external=bool(user.is_external),
            has_id_card=bool(student and (student.id_card or "").strip()),
            has_avatar=bool(user.is_external and user.avatar),
            last_login_at=user.last_login_at,
            last_login_ip=user.last_login_ip,
            is_frozen=bool(user.is_frozen),
        )
        for user, student in rows
    ]


@router.put("/users/{student_no}/role", summary="设置角色")
def set_role(
    student_no: str,
    payload: RoleUpdateRequest,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    if payload.role not in ROLES:
        raise HTTPException(
            status_code=400,
            detail="角色只能是 " + " / ".join(f"{r}（{ROLE_LABELS[r]}）" for r in ROLES),
        )
    target = db.query(User).filter(User.student_no == student_no).first()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    # 管理员把自己降权后就再也改不回来了，只能另找一位管理员
    if target.student_no == user.student_no and payload.role != "admin":
        raise HTTPException(status_code=400, detail="不能降低自己的权限，请让另一位管理员操作")
    if target.role == payload.role:
        return {"message": "角色未变化"}

    old_label = ROLE_LABELS.get(target.role or "student", target.role)
    target.role = payload.role
    # target 写全「学号 姓名」，与其它 20 来处保持一致 —— 账号日志的「被操作记录」
    # 就是按这个格式反查的（见 user_logs）。只写学号的话新记录得靠那条兜底条件才查得到
    log_operation(
        db, user, "修改角色", target=f"{student_no} {account_name(db, target)}",
        detail=f"{old_label} → {ROLE_LABELS[payload.role]}",
        ip=ip,
    )
    db.commit()
    return {"message": "角色已更新"}


@router.post(
    "/users/{student_no}/reset-password",
    response_model=ResetPasswordResponse,
    summary="重置密码",
)
def reset_password(
    student_no: str,
    payload: ResetPasswordRequest | None = None,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """两种账号，两种重置方式：

    - 学生账号：重置成「身份证号后 6 位」并重新要求首次登录改密。
      没有身份证号的退回学号后 6 位，那种情况下接口会把密码回带给管理员，
      好让管理员转告学生（学号后 6 位本来就不是秘密）。
      这里会忽略请求体里的密码 —— 学生账号不允许管理员指定密码。
    - 域外账号：没有身份证号可依据，由管理员在请求体里直接指定新密码，
      设完即可用、不再要求首次登录改密。
    """
    target = db.query(User).filter(User.student_no == student_no).first()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")

    if target.is_external:
        if not payload or not payload.password:
            raise HTTPException(status_code=400, detail="请为域外账号指定新密码")
        password = payload.password
        new_hash, new_salt = hash_password(password)
        target.password_hash = new_hash
        target.password_salt = new_salt
        # 密码是管理员当场定的、能当面告知，再强迫改一次没有意义
        target.must_change_password = False
        log_operation(
            db, user, "重置密码", target=f"{student_no} {account_name(db, target)}",
            detail="域外账号，由管理员指定新密码", ip=ip,
        )
        db.commit()
        return ResetPasswordResponse(message="密码已重置，新密码即刻可用")

    student = db.query(Student).filter(Student.student_no == student_no).first()
    if not student:
        raise HTTPException(status_code=404, detail="账号不存在")

    password, is_fallback = default_password(student)
    new_hash, new_salt = hash_password(password)
    target.password_hash = new_hash
    target.password_salt = new_salt
    target.must_change_password = True  # 重置后第一次登录仍要改密码

    log_operation(
        db, user, "重置密码", target=f"{student_no} {student.name}",
        detail="无身份证号，重置为学号后 6 位" if is_fallback else "重置为身份证号后 6 位",
        ip=ip,
    )
    db.commit()
    return ResetPasswordResponse(
        message="已重置为原始密码，该生下次登录需修改密码",
        password=password if is_fallback else None,
        fallback=is_fallback,
    )


# ---------- 冻结 / 解冻 ----------
# 冻结 = 禁止登录 + 已登录的会话下一个请求就 401。
# 前者拦在 auth.login，后者拦在 deps.get_current_user —— 只有那两处，
# 别在别的接口里再补判断（补了就会漏，那两个点才是必经之路）。


@router.post("/users/{student_no}/freeze", summary="冻结账号")
def freeze_user(
    student_no: str,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """冻结学生账号和域外账号都行（_get_user 不区分类别）

    不需要额外判断「是不是最后一个未冻结的管理员」——下面那道「不能冻自己」
    已经把它盖住了，理由是：
      调用者此刻**必定是未冻结的管理员**（admin_required 查的是库里的实时角色，
       冻结的账号在 get_current_user 里就被 401 挡掉，根本进不到这个函数），
      而它冻不了自己，所以冻完任何一个目标之后，系统里至少还剩它这一个
       未冻结管理员。目标不是自己、又是个管理员时，未冻结管理员必然 ≥ 2 个，
      「冻完就没管理员了」这种情况不可能出现。
    """
    target = _get_user(db, student_no)

    # 冻自己 = 下一步自己的会话就被踢掉，再想解冻都没人操作得了
    if target.student_no == user.student_no:
        raise HTTPException(status_code=400, detail="不能冻结当前登录的账号")

    # 重复点不报错：两个管理员同时点一下不该弹红字，也不该记两条日志
    if target.is_frozen:
        return {"message": "该账号已是冻结状态"}

    target.is_frozen = True
    log_operation(
        db, user, "冻结账号", target=f"{student_no} {account_name(db, target)}", ip=ip,
    )
    db.commit()
    return {"message": "已冻结"}


@router.post("/users/{student_no}/unfreeze", summary="解冻账号")
def unfreeze_user(
    student_no: str,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    target = _get_user(db, student_no)
    if not target.is_frozen:
        return {"message": "该账号本来就是未冻结状态"}

    target.is_frozen = False
    log_operation(
        db, user, "解冻账号", target=f"{student_no} {account_name(db, target)}", ip=ip,
    )
    db.commit()
    return {"message": "已解冻"}


@router.post("/users/{student_no}/revoke-sessions", summary="吊销该账号的所有会话")
def revoke_sessions(
    student_no: str,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """把这个账号在所有设备上的登录一次性踢掉，但**不禁止它重新登录**

    用途是「密码可能泄露了，先把所有设备登出」这类不想停用账号的场合。
    和冻结的区别：冻结是禁止登录（is_frozen），这个是允许登录、只让已签发的 cookie 作废。

    会话是签名 Cookie、服务端没有会话表，所以这里不是去删什么记录，而是把
    session_epoch +1；deps.get_current_user 每次请求拿 cookie 里的代次和这一列比对，
    对不上的下一个请求就 401。全部设备一起生效，不用挨个通知。
    """
    target = _get_user(db, student_no)

    # 不拦「吊销自己」：管理员怀疑自己的会话被蹭了同样需要这个操作，
    # 代价只是自己也被踢下线、重新登录一遍而已，不像冻结自己那样会锁死系统
    target.session_epoch = (target.session_epoch or 0) + 1
    log_operation(
        db, user, "吊销会话", target=f"{student_no} {account_name(db, target)}", ip=ip,
    )
    db.commit()
    return {"message": "已吊销该账号的全部会话"}


@router.get(
    "/users/{student_no}/logs",
    response_model=AdminUserLogsResponse,
    summary="某个账号的日志",
)
def user_logs(
    student_no: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    target_page: int = Query(1, ge=1),
    target_page_size: int = Query(20, ge=1, le=200),
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """三块内容：

    - 操作日志：这个账号**作为操作人**留下的全部记录，分页
    - 被操作记录：这个账号**作为操作对象**的记录（别人重置他的密码、改他的
      角色、改他的学生信息、审批他的申请……），分页
    - 账号事件：这个账号最近 7 天的登录 / 自行改密

    事件那块只能查到本功能上线之后 —— 之前这两种行为压根没入库，
    不存在的历史补不回来（不是漏查，是从来没有）。
    """
    target = _get_user(db, student_no)

    # operator_no 是精确匹配。现有的 /logs?operator= 走的是 LIKE %x%，
    # 拿 2026012 去查会把 20260123、20260124 一起带出来，那种模糊匹配不能用来「看某个账号」
    operations = db.query(OperationLog).filter(OperationLog.operator_no == student_no)
    op_total = operations.count()
    op_items = (
        operations.order_by(OperationLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 被操作记录：以这个账号为**对象**的操作。
    # 匹配两种情况：
    # 1) target 字段：格式是「学号 姓名」（见各处 log_operation 调用的约定）
    #    第 2 个条件（裸学号）为历史数据保留：老版本的「修改角色」只写学号没写姓名。
    # 2) target_student_nos 字段：批量操作时写入的 JSON 学号数组，
    #    比如导出申请一次涉及 N 人，每个学生查被操作记录时都能通过这个字段匹配到。
    # LIKE 里的 % 和 _ 要转义：域外账号的登录名允许带下划线（teacher_li 之类），
    # 不转义的话 _ 会当通配符，把 teacherXli 的记录也拉进来
    escaped_no = student_no.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    targeted = db.query(OperationLog).filter(
        or_(
            OperationLog.target == student_no,
            OperationLog.target.like(f"{escaped_no} %", escape="\\"),
            # target_student_nos 是 JSON 数组字符串，形如 ["20260000001","20260000002"]
            # 用 "学号" 包含匹配——学号是纯数字且长度固定，不会误匹配
            OperationLog.target_student_nos.like(f'%"{escaped_no}"%', escape="\\"),
        )
    )
    targeted_total = targeted.count()
    targeted_items = (
        targeted.order_by(OperationLog.id.desc())
        .offset((target_page - 1) * target_page_size)
        .limit(target_page_size)
        .all()
    )

    since = datetime.now() - timedelta(days=ACCOUNT_EVENT_DAYS)
    events = db.query(AccountEvent).filter(
        AccountEvent.student_no == student_no,
        # created_at 是 Python 端写入的北京时间，这里也用 datetime.now()，
        # 两边同源才比得了（SQLite 的 CURRENT_TIMESTAMP 是 UTC，混用就会错 8 小时）
        AccountEvent.created_at >= since,
    )
    event_total = events.count()
    event_items = (
        # 按 created_at 倒序而不是 id 倒序：窗口本来就是拿 created_at 划的，
        # 排序用同一个字段才自洽。id 倒序只在「写入顺序 = 时间顺序」时等价，
        # 补数据、导数据时会露馅（本模块的注释也说了本表只增不删，
        # 但没人保证一定是按时间顺序增的）
        events.order_by(AccountEvent.created_at.desc(), AccountEvent.id.desc())
        .limit(ACCOUNT_EVENT_LIMIT)
        .all()
    )

    return AdminUserLogsResponse(
        student_no=student_no,
        name=account_name(db, target),
        operations=OperationLogListResponse(total=op_total, items=op_items),
        targeted=OperationLogListResponse(total=targeted_total, items=targeted_items),
        events=[AccountEventResponse.model_validate(e) for e in event_items],
        events_total=event_total,
        events_since=since,
    )


# ---------- 域外账号 ----------
# 不属于本班学生、也不在学生名单里的账号（老师、协助人员等）。
# 它只是在 users 表里多一行，学生表完全不动，所以点名、筛选、统计都不受影响。


@router.post("/external-users", summary="新建域外账号")
def create_external_user(
    login_name: str = Form(..., description="登录名（就是登录时填在学号那一栏的东西）"),
    display_name: str = Form(..., description="展示用户名（姓名、水印都用它）"),
    password: str = Form(..., description="初始密码"),
    role: str = Form("student", description="等效权限"),
    avatar: UploadFile | None = File(None, description="头像，可选"),
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    login_name = _clean_login_name(login_name)
    display_name = _clean_display_name(display_name)
    _check_role(role)
    password = _check_password(password)

    # 登录名必须唯一：学生学号也占着这个位置，撞上了那个学生就登不进自己的账号
    if db.query(User).filter(User.student_no == login_name).first():
        raise HTTPException(status_code=400, detail=f"登录名「{login_name}」已被占用，请换一个")

    avatar_name = _save_avatar(avatar) if avatar and avatar.filename else None
    new_hash, new_salt = hash_password(password)
    db.add(
        User(
            student_no=login_name,
            password_hash=new_hash,
            password_salt=new_salt,
            # 密码是管理员当场定的、能当面告知，再强迫改一次没有意义
            must_change_password=False,
            role=role,
            display_name=display_name,
            avatar=avatar_name,
            is_external=True,
        )
    )
    log_operation(
        db, user, "新建域外账号", target=f"{login_name} {display_name}",
        detail=f"角色：{ROLE_LABELS[role]}", ip=ip,
    )
    try:
        db.commit()
    except Exception:
        # 写库没成功就别把头像文件留在磁盘上
        db.rollback()
        _remove_avatar(avatar_name)
        raise
    return {"message": "域外账号已创建"}


@router.put("/external-users/{login_name}", summary="修改域外账号")
def update_external_user(
    login_name: str,
    display_name: str = Form(...),
    role: str = Form(...),
    remove_avatar: bool = Form(False, description="是否删掉现有头像"),
    avatar: UploadFile | None = File(None, description="新头像，可选；传了就换掉旧的"),
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    target = _get_external_user(db, login_name)
    display_name = _clean_display_name(display_name)
    _check_role(role)

    if target.student_no == user.student_no and role != "admin":
        raise HTTPException(status_code=400, detail="不能降低自己的权限，请让另一位管理员操作")

    changes: list[str] = []
    if target.display_name != display_name:
        changes.append(f"展示名：{target.display_name or '（空）'} → {display_name}")
        target.display_name = display_name
    if target.role != role:
        old_label = ROLE_LABELS.get(target.role or "student", target.role)
        changes.append(f"角色：{old_label} → {ROLE_LABELS[role]}")
        target.role = role

    old_avatar = target.avatar
    new_avatar = None
    stale_avatar = None  # 落库成功之后要删掉的旧文件
    if avatar and avatar.filename:
        new_avatar = _save_avatar(avatar)
        target.avatar = new_avatar
        stale_avatar = old_avatar
        changes.append("更换头像")
    elif remove_avatar and old_avatar:
        target.avatar = None
        stale_avatar = old_avatar
        changes.append("删除头像")

    if not changes:
        return {"message": "没有改动"}

    log_operation(
        db, user, "修改域外账号", target=f"{login_name} {target.display_name}",
        detail="；".join(changes), ip=ip,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        _remove_avatar(new_avatar)
        raise
    # 只有换了新头像、或者明确要求清空时才删旧文件。
    # 改个名字那种「没动头像」的编辑绝不能删 —— 库里那一列还指着这个文件
    _remove_avatar(stale_avatar)
    return {"message": "已保存"}


@router.delete("/external-users/{login_name}", summary="删除域外账号")
def delete_external_user(
    login_name: str,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    target = _get_external_user(db, login_name)
    if target.student_no == user.student_no:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号")

    log_operation(
        db, user, "删除域外账号",
        target=f"{login_name} {account_name(db, target)}", ip=ip,
    )
    # 推送订阅跟着账号走，账号没了就别再往下推
    db.query(PushSubscription).filter(PushSubscription.student_no == login_name).delete()
    avatar_name = target.avatar
    db.delete(target)
    db.commit()
    # 提交成功后再删头像文件
    _remove_avatar(avatar_name)
    return {"message": "已删除"}


@router.get("/logs", response_model=OperationLogListResponse, summary="操作日志")
def list_logs(
    _: User = Depends(admin_required),
    operator: str | None = Query(None, description="按操作人姓名或学号模糊搜索"),
    action: str | None = Query(None, description="按动作模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(OperationLog)
    if operator:
        query = query.filter(
            or_(
                OperationLog.operator_name.like(f"%{operator}%"),
                OperationLog.operator_no.like(f"%{operator}%"),
            )
        )
    if action:
        query = query.filter(OperationLog.action.like(f"%{action}%"))

    total = query.count()
    items = (
        query.order_by(OperationLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": items}


@router.delete("/logs", summary="清空操作日志")
def clear_logs(
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """删除全部操作日志，**然后补一条「清空了日志」**

    清空本身也是要留痕的动作 —— 否则日志突然变空之后谁也说不清是清过、
    还是库出问题了。清掉了多少条写进 detail，两次清空之间对得上账。

    顺序是先删后写，`query.delete()` 是立即执行的批量删除（不是挂到 flush 上），
    所以补的那条不会被自己删掉。
    """
    deleted = db.query(OperationLog).delete()
    log_operation(db, user, "清空了日志", detail=f"清空前共 {deleted} 条", ip=ip)
    db.commit()
    return {"message": f"已清空 {deleted} 条日志", "deleted": deleted}


# ==================== IP 封禁 ====================
# 自动封禁（登录失败触发，见 api/auth.py 的 _reject）不写 operation_logs ——
# log_service 的章程是「内容变更 + 有人主动做出的动作」，自动封禁两者都不是。
# 它的留痕由 ip_bans 行本身（reason 里写着失败次数）+ stdout 的 [封禁] 行承担。
# 附带好处：「清空日志」不会把自动封禁的记录一起抹掉。
# 管理员的手动封禁 / 解封是人的动作，照常记日志。


@router.get("/ip-bans", response_model=IpBanListResponse, summary="封禁中的 IP 列表")
def list_ip_bans(
    user: User = Depends(admin_required),
    target: str | None = Query(None, description="按 IP 或网段模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """只列**生效中**的封禁（过期行在 SQL 里过滤掉）。

    过期行留在表里不清：清的理由只有「列表好看」，
    而清的动作要么放在 GET 里（写库还忘了 commit 就静默无效，没人会注意），
    要么加一堆定时任务。启动时 purge 一次已经够，平时让它们躺着不影响任何判定。
    """
    now = datetime.now()
    query = db.query(IpBan).filter(
        (IpBan.expires_at.is_(None)) | (IpBan.expires_at > now)
    )
    if target:
        query = query.filter(IpBan.target.like(f"%{target}%"))

    total = query.count()
    items = (
        query.order_by(IpBan.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": items, "self_ip": ip}


@router.post("/ip-bans", summary="手动封禁 IP 或网段")
def create_ip_ban(
    payload: IpBanRequest,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """手动封禁。三步校验的顺序是有讲究的，别调换（见下面每条的理由）。"""
    # ① 格式：单个 IP 或 CIDR 网段都收，不接受带端口的写法
    normalized = normalize_target(payload.target)
    if normalized is None:
        raise HTTPException(
            status_code=400,
            detail="IP 或网段格式不正确（示例：203.0.113.9 或 203.0.113.0/24）",
        )

    # ② 不能封到操作者自己头上。用**包含**判定而不是相等判定：
    #    填 0.0.0.0/0 或 127.0.0.0/8 也会被这条挡住，顺手避免「一个网段把所有人
    #    （包括自己）一起封掉」——那种情况下连挽救的入口都没有了。
    #    这条要放在「可信网段」之前：本地开发时 peer 就是 127.0.0.1、正好落在
    #    默认可信网段里，先判可信网段会给出牛头不对马嘴的提示
    if target_matches(normalized, ip):
        raise HTTPException(status_code=400, detail="不能封禁当前操作所在的 IP")

    # ③ 不能封到反向代理网段。没有这条的话，管理员一个手滑填 172.16.0.0/12
    #    就等于把全班挡在门外，而且**连挽救的入口（登录）都一起没了**
    if _overlaps_trusted_proxies(normalized):
        raise HTTPException(
            status_code=400,
            detail="该网段与反向代理网段重叠，封禁会导致所有人无法登录",
        )

    record = ban_ip(
        db, normalized, payload.minutes, reason=payload.reason, operator=user,
    )
    if record is None:
        # 结束时间没有任何变化（重复点了同一个时长），不报错也不留痕，
        # 和冻结那套的容错口径一致
        return {"message": "该目标已在封禁中，设置未发生变化"}

    log_operation(
        db, user, "封禁IP", target=normalized,
        detail=_ban_log_detail(record, payload.reason), ip=ip,
    )
    db.commit()
    return {"message": "已封禁"}


@router.delete("/ip-bans/{ban_id}", summary="解除 IP 封禁")
def delete_ip_ban(
    ban_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """按主键解封。

    接口参数用自增 id 而不是 target：IPv6 和网段里的 / : % 在 URL 路径里
    都要转义，转完还可能被中间层还原错，踩一次很难查。前端列表里本来就有 id。

    解封后必须清掉内存里的失败计数，否则该 IP 下次输错一次立刻又被自动封，
    管理员会以为「解封没生效」。
    """
    record = unban_ip(db, ban_id)
    if record is None:
        raise HTTPException(status_code=404, detail="该封禁记录不存在，可能已被解除")

    clear_failures(record.target)
    log_operation(db, user, "解封IP", target=record.target, ip=ip)
    db.commit()
    return {"message": "已解除封禁"}


def _overlaps_trusted_proxies(target: str) -> bool:
    """这个封禁目标是否和任一可信代理网段有交集

    没配 TRUSTED_PROXIES 时无法判定，一律返回 False（放行）。
    这是**预期的降级**：那种部署下 XFF 本来就不采信，
    也就分不清谁是真的客户端，封网段的风险由「不能封自己」那条兜住。
    """
    nets = parse_cidrs(settings.trusted_proxies)
    if not nets:
        return False
    net = parse_network(target)
    if net is None:
        return False
    for trusted in nets:
        try:
            if net.overlaps(trusted):
                return True
        except (TypeError, ValueError):
            # v4 网段和 v6 网段没法比，那本来就不重叠
            continue
    return False


def _ban_log_detail(record: IpBan, reason: str) -> str:
    """拼操作日志的 detail：说清楚封到什么时候"""
    if record.expires_at is None:
        until = "永久"
    else:
        until = record.expires_at.strftime("%Y-%m-%d %H:%M")
    return f"至 {until}" + (f"；原因：{reason}" if reason else "")


# ==================== 资料下载管理 ====================
# 只有管理员能改资料清单；普通用户读的接口在 resources.py 里。


@router.get("/resources", summary="资料列表（管理员用）")
def admin_list_resources(
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """返回所有资料条目，不分组，按分类+排序。
    管理界面用，方便做拖拽排序和增删改。
    """
    rows = list_all_resources(db)
    return [
        {
            "id": r.id,
            "name": r.name,
            "file_name": r.file_name,
            "original_name": r.original_name,
            "category": r.category,
            "sort_order": r.sort_order,
            "size": 0,  # 前端暂时不用
            "download_count": r.download_count or 0,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/resources", summary="上传新资料")
async def upload_resource(
    user: User = Depends(admin_required),
    name: str = Form(..., min_length=1, max_length=200, description="显示名称"),
    category: str = Form(..., min_length=1, max_length=50, description="分类名称"),
    file: UploadFile = File(..., description="资料文件"),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """上传一个新资料到指定分类

    文件存到 data/downloads/，文件名用 UUID 前缀（防路径穿越和重名覆盖）。
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件不能为空")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 50MB")

    original = file.filename or name
    row = add_resource(db, name, category, content, original)
    log_operation(
        db, user, "上传资料", target=f"{category}/{name}",
        detail=f"文件：{original}，{len(content)} 字节",
        ip=ip,
    )
    db.commit()
    db.refresh(row)
    return {"message": "上传成功", "id": row.id}


@router.put("/resources/{resource_id}", summary="修改资料信息")
def update_resource_api(
    resource_id: int,
    user: User = Depends(admin_required),
    name: str = Form(None, max_length=200, description="新的显示名称"),
    category: str = Form(None, max_length=50, description="新的分类"),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """只改名称和/或分类，不改文件本身"""
    if name is None and category is None:
        raise HTTPException(status_code=400, detail="至少改一项")

    row = update_resource(db, resource_id, name=name, category=category)
    if not row:
        raise HTTPException(status_code=404, detail="资料不存在")

    detail_parts = []
    if name is not None:
        detail_parts.append(f"名称→{name}")
    if category is not None:
        detail_parts.append(f"分类→{category}")
    log_operation(
        db, user, "修改资料", target=f"{row.category}/{row.name}",
        detail="，".join(detail_parts),
        ip=ip,
    )
    db.commit()
    return {"message": "已更新"}


@router.put("/resources/reorder/{category}", summary="重排某分类下的资料顺序")
def reorder_resources(
    category: str,
    order: list[int],
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """按给定的 ID 列表重排某个分类内的资料顺序"""
    reorder_category(db, category, order)
    log_operation(
        db, user, "重排资料", target=category,
        detail=f"调整 {len(order)} 项的顺序",
        ip=ip,
    )
    db.commit()
    return {"message": "已更新顺序"}


@router.delete("/resources/{resource_id}", summary="删除资料")
def remove_resource(
    resource_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """同时删除数据库记录和磁盘文件。不可恢复。"""
    row = db.query(Resource).filter(Resource.id == resource_id).first()
    target_label = f"{row.category}/{row.name}" if row else f"id={resource_id}"

    ok = delete_resource(db, resource_id)
    if not ok:
        raise HTTPException(status_code=404, detail="资料不存在")

    log_operation(
        db, user, "删除资料", target=target_label,
        ip=ip,
    )
    db.commit()
    return {"message": "已删除"}


# ==================== 文件访问日志 ====================

@router.get(
    "/file-access-logs",
    response_model=FileAccessLogListResponse,
    summary="文件访问日志（查看/下载）",
)
def list_file_access_logs(
    _: User = Depends(admin_required),
    user: str | None = Query(None, description="按访问人姓名或学号模糊搜索"),
    file: str | None = Query(None, description="按文件标题模糊搜索"),
    action: str | None = Query(None, description="按动作筛选：view / download，留空=全部"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(FileAccessLog)
    if user:
        query = query.filter(
            or_(
                FileAccessLog.user_name.like(f"%{user}%"),
                FileAccessLog.user_no.like(f"%{user}%"),
            )
        )
    if file:
        query = query.filter(FileAccessLog.file_title.like(f"%{file}%"))
    if action:
        query = query.filter(FileAccessLog.action == action)

    total = query.count()
    items = (
        query.order_by(FileAccessLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": items}


@router.post(
    "/file-access-logs/extract",
    response_model=WatermarkExtractResponse,
    summary="从 PDF 中提取不可见水印（溯源）",
)
async def extract_watermark_from_pdf(
    _: User = Depends(admin_required),
    file: UploadFile = File(..., description="待提取水印的 PDF 文件"),
    db: Session = Depends(get_db),
):
    """上传一份 PDF，提取里面的不可见水印令牌，解析出下载人、时间、文件信息"""
    # 校验必须是 PDF
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        return {"found": False, "message": "只支持 PDF 文件"}

    content = await file.read()
    if not content:
        return {"found": False, "message": "文件为空"}

    # 限制大小，防止超大文件把内存打满
    if len(content) > 50 * 1024 * 1024:
        return {"found": False, "message": "文件过大（上限 50MB）"}

    token = extract_watermark(content)
    if not token:
        return {"found": False, "message": "未检测到水印"}

    parsed = parse_watermark_token(token)
    if not parsed:
        return {"found": False, "message": f"水印格式无法解析：{token}"}

    # 试着从数据库里把人和文件的详细信息捞出来，方便管理员直接看
    user_row = db.query(User).filter(User.student_no == parsed["user_no"]).first()
    user_name = account_name(db, user_row) if user_row else None

    accessed_at = datetime.fromtimestamp(parsed["timestamp"])

    # file_id 可能是公告文件（announcement），也可能是导出申请（export_request），
    # 先查公告，查不到再查导出申请
    from ..models import Announcement, ExportRequest

    file_row = db.query(Announcement).filter(Announcement.id == parsed["file_id"]).first()
    if file_row:
        source_type = "announcement"
        file_title = file_row.title

        # 拿令牌去文件访问日志里核对（动作、IP）
        matched = (
            db.query(FileAccessLog)
            .filter(
                FileAccessLog.user_no == parsed["user_no"],
                FileAccessLog.file_id == parsed["file_id"],
                FileAccessLog.created_at >= accessed_at - timedelta(seconds=5),
                FileAccessLog.created_at <= accessed_at + timedelta(seconds=5),
            )
            .order_by(FileAccessLog.id.desc())
            .first()
        )
        action = matched.action if matched else None
        ip = matched.ip if matched else None
        log_matched = matched is not None

        export_type = None
        export_scope = None
        export_status = None
        export_reviewer = None

    else:
        # 不是公告文件，看看是不是导出申请
        export_row = db.query(ExportRequest).filter(ExportRequest.id == parsed["file_id"]).first()
        if export_row:
            source_type = "export"
            file_title = f"{export_row.student_name} 的导出申请"
            export_type = export_row.export_type
            export_scope = export_row.scope_type
            export_status = export_row.status
            export_reviewer = export_row.reviewer_name or None
            action = None
            ip = None
            log_matched = False
        else:
            # 都不是，就只显示 token 里的基本信息
            source_type = None
            file_title = None
            export_type = None
            export_scope = None
            export_status = None
            export_reviewer = None
            action = None
            ip = None
            log_matched = False

    return {
        "found": True,
        "token": token,
        "file_id": parsed["file_id"],
        "user_no": parsed["user_no"],
        "user_name": user_name,
        "file_title": file_title,
        "accessed_at": accessed_at,
        "source_type": source_type,
        "export_type": export_type,
        "export_scope": export_scope,
        "export_status": export_status,
        "export_reviewer": export_reviewer,
        "action": action,
        "ip": ip,
        "log_matched": log_matched,
        "message": "水印提取成功",
    }
