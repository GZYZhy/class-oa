import os
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import (
    BASE_DIR,
    login_ban_values,
    master_password_allowed_from,
    settings,
    smtp_enabled,
    turnstile_enabled,
)
from ..database import get_db
from ..models import AccessToken, AccountEvent, IpBan, Student, User
from ..schemas import (
    AccountEventResponse,
    MyLogsResponse,
    OperationLogListResponse,
)
from ..schemas.auth import (
    AccessTokenCreate,
    AccessTokenCreated,
    AccessTokenList,
    AccessTokenResponse,
    BarkKeyRequest,
    EmailNotifyRequest,
    LoginRequest,
    ChangePasswordRequest,
    SetInitialPasswordRequest,
    UserInfoResponse,
    WebhookSettingRequest,
    WebPushSubscribeRequest,
    WebPushUnsubscribeRequest,
)
from ..services import (
    DEFAULT_TEMPLATE_TEXT,
    account_events,
    account_name,
    account_operations,
    ban_ip,
    check_template,
    clear_failures,
    email_push,
    get_active_ban,
    icon_url,
    is_ban_candidate,
    is_valid_email,
    needs_captcha,
    parse_template,
    push,
    record_failure,
    vapid_public_key,
    web_subscriptions,
    webhook_push,
    webpush_subscribe,
    webpush_unsubscribe,
)
from ..services.email_service import TEST_BUDGET as EMAIL_TEST_BUDGET
from ..services.email_service import TEST_TIMEOUT as EMAIL_TEST_TIMEOUT
from ..services.two_factor import start_login_two_factor
from ..services.webpush_service import TEST_BUDGET
from ..services.webpush_service import push as web_push
from ..utils.security import (
    generate_token,
    hash_password,
    hash_token,
    token_prefix,
    verify_master_password,
    verify_password,
)
from ..utils.url_guard import is_allowed_webhook_url
from ..utils.captcha import generate_captcha
from ..utils.turnstile import verify as turnstile_verify
from .deps import get_current_user, get_client_ip, require_cookie_auth

router = APIRouter(prefix="/api/auth", tags=["认证"])

# 头像目录：域外账号的头像存这里，学生账号的照片在 data/photos（见 students.py）
AVATAR_DIR = BASE_DIR / "data" / "avatars"
PHOTO_DIR = BASE_DIR / "data" / "photos"

# 头像文件后缀 → 响应类型。认不出来的按 jpeg 兜底（上传时已经卡过后缀白名单）
_AVATAR_MEDIA_TYPES = {
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

def _record_event(db: Session, student_no: str, event: str, ip: str | None) -> None:
    """记一条账号事件（登录 / 自行改密）

    只 add 不 commit，和 log_operation 一样由调用方提交
    （这两类接口本来就要 commit，多一次提交反而是两个事务）。

    只记成功的事件，不记登录失败 —— 记了等于让管理员看到别人拿错密码试的 IP，
    而且那是另一个用途（防爆破），由 services/login_guard 和 ip_bans 在管。
    """
    db.add(AccountEvent(student_no=student_no, event=event, ip=ip))


def _ban_detail(ban: IpBan) -> str:
    """被封时给用户看的文案（登录接口 403 和登录页的封禁提示共用同一套措辞）"""
    if ban.expires_at is None:
        return "本机 IP 已被封禁（永久），请联系管理员"
    return f"本机 IP 已被封禁，将于 {ban.expires_at.strftime('%Y-%m-%d %H:%M')} 自动解除"


def _reject(db: Session, ip: str, detail: str) -> None:
    """记一次登录失败；够阈值就地封禁，然后抛错。

    只覆盖**真的校验失败**的三处：Turnstile 校验不过、算术验证码答错、学号或密码错。
    两个地方**不能**并进来：
    - 「请输入验证码」（漏填）—— 那是操作失误，不是爆破信号，现在就没计数
    - 「账号已被冻结」—— 密码是对的；而且失败是按 IP 记的，
      一加就会把同一出口 IP 下的正常同事一起拖下水

    封禁写库**必须自己 commit**：get_db() 只 close() 不 commit，
    SQLAlchemy 关闭时未提交的事务一律回滚。不 commit 的话封禁行根本落不了库，
    而接口照样返回 400 —— 这种「看着都对但没有效果」的问题极难查。
    """
    count = record_failure(ip)
    threshold, ban_minutes = login_ban_values()
    banned = None

    if threshold > 0 and count >= threshold:
        if not is_ban_candidate(ip):
            print(f"[封禁] 跳过 {ip}：不是可封禁的地址（代理网段 / 非法值 / 未配可信网段）",
                  flush=True)
        else:
            try:
                banned = ban_ip(
                    db, ip, ban_minutes,
                    reason=f"{settings.login_fail_window_minutes} 分钟内登录失败 {count} 次",
                )
                db.commit()
                # 不清的话，解封后第一次输错立刻又被封（计数还停在阈值上）
                clear_failures(ip)
                print(f"[封禁] {ip} 封禁 {ban_minutes} 分钟（{count} 次失败）", flush=True)
            except Exception as e:
                # 写库失败（磁盘满、锁冲突）不该把本该返回的 400 变成 500
                db.rollback()
                print(f"[封禁] 写库失败，本次未封禁：{e}", flush=True)

    if banned:
        # 语义是**当次就报封禁**，不是等下一次请求
        raise HTTPException(status_code=403, detail=_ban_detail(banned))
    raise HTTPException(status_code=400, detail=detail)


def _student_of(db: Session, user: User) -> Student | None:
    """取账号对应的学生记录；域外账号（以及学生被删掉的老账号）没有，返回 None

    注意别换成 get_current_student：那个对域外账号会直接抛 403，
    而登录和 /me 恰恰需要容忍「没有学生记录」。
    """
    return db.query(Student).filter(Student.student_no == user.student_no).first()


def build_user_info(db: Session, user: User, student: Student | None) -> UserInfoResponse:
    """组装返回给前端的用户信息

    姓名：域外账号用自定义展示名，学生账号用学生姓名（见 account_name）。
    头像：域外账号用自己上传的那张，学生账号用高考照片。

    头像 URL 带登录名后缀，避免切换账号后浏览器命中缓存 ——
    所有账号的头像都叫同一个地址，浏览器会以为是同一张。
    文件名再当一次版本号（v 参数）：换了头像/照片之后地址跟着变，
    否则管理员刚换的图会被浏览器缓存里的旧图盖住。
    """
    # 学生账号没有学生记录时（理论上不会发生）student 为 None，这里一并兜住
    file_name = user.avatar if user.is_external else (student.gaokao_photo if student else None)
    return UserInfoResponse(
        student_no=user.student_no,
        name=account_name(db, user),
        avatar=(
            f"/api/auth/avatar?u={user.student_no}&v={file_name}" if file_name else None
        ),
        class_name=student.class_name if student else None,
        role=user.role or "student",
        must_change_password=user.must_change_password,
        is_external=bool(user.is_external),
        is_bootstrap=bool(user.is_bootstrap),
        bark_key=user.bark_key or None,
        # 前端靠它决定「电子邮件通知」那块能不能操作。管理员没把 SMTP 配齐时
        # 任何人开了也收不到信，所以整块置灰比让人对着一个假开关强
        smtp_enabled=smtp_enabled(),
    )


def complete_login(
    request: Request, db: Session, user: User, ip: str, remember: bool
) -> None:
    """密码登录与通行密钥登录共用的收尾：清失败计数、记登录、写会话

    两条路的可观测行为必须一致 —— 最近登录时间、登录事件、会话代次、保持登录
    的 cookie 有效期，都只在这里写一次。分开写迟早会出现「用钥匙登录不更新最近
    登录时间」这种只有管理员能看出来的差异。
    """
    clear_failures(ip)

    # 记录最近登录时间和 IP。
    # 时间用 datetime.now() 取北京时间，不用 SQLite 的 CURRENT_TIMESTAMP（那是 UTC，会差 8 小时）。
    # IP 也一起记，账号管理页能看到这个号最近是从哪登的。
    user.last_login_at = datetime.now()
    user.last_login_ip = ip
    # 登录事件。只记「登录了」，**不记用的是哪种方式** —— 密码与通行密钥
    # 在这张表里必须表现完全一致，否则从事件表就能把两者区分开
    _record_event(db, user.student_no, "login", ip)
    db.commit()

    # 写入签名会话
    request.session.clear()
    request.session["user_id"] = user.id
    # 会话代次：管理员「吊销所有会话」后，客户端手里的旧 cookie 会因为代次对不上而失效。
    # 这里记下签发时的代次，deps.get_current_user 每次请求拿它和库里的值比对
    request.session["epoch"] = user.session_epoch or 0
    # 标记是否保持登录。RememberMeMiddleware 会根据这个标志调整 cookie 的 Max-Age：
    #   true  → 7 天持久化
    #   false → session cookie（浏览器关了就没）
    if remember:
        request.session["_remember"] = True


@router.get("/captcha", summary="获取验证码（SVG 图片）")
def get_captcha(request: Request):
    """生成一道算术题，答案存会话里，下一次登录时校验。

    验证码 SVG 直接返回，不需要额外 id —— 未登录用户也有会话 Cookie，
    答案就存在 session["captcha_answer"] 里。
    每次调用都会刷新答案。
    """
    svg, answer = generate_captcha()
    request.session["captcha_answer"] = answer
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/captcha-required", summary="当前 IP 是否需要人机验证，以及用哪一种")
def captcha_required(
    ip: str = Depends(get_client_ip), db: Session = Depends(get_db)
):
    """登录页先问一下要不要显示验证码框，免得每次都加载 SVG。

    required 为 False 时也要带上 mode / site_key：前端要靠它知道
    「等会儿万一输错了，该去加载 Turnstile 控件还是拉算术题」。
    site key 本来就是公开的（它要发给浏览器），secret key 永远不出后端。

    顺带带上 banned / banned_until：让登录页能**直接**显示「本机 IP 已被封禁，
    X 解除」，而不是等用户填完表单吃了 403，还先看到一张永远用不上的验证码。
    """
    enabled = turnstile_enabled()
    ban = get_active_ban(db, ip)
    return {
        "required": needs_captcha(ip),
        "mode": "turnstile" if enabled else "math",
        "site_key": settings.turnstile_site_key if enabled else "",
        "banned": bool(ban),
        "banned_until": (
            ban.expires_at.isoformat() if ban and ban.expires_at else None
        ),
        "ban_message": _ban_detail(ban) if ban else "",
    }


# 不用 response_model=UserInfoResponse：开了二次验证时这里先返回
# {"two_factor_required": true, ...}，UserInfoResponse 会把这个标记过滤掉
@router.post("/login", summary="登录")
def login(
    data: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):

    # 封禁闸门放在最前面（在人机验证之前），三个理由：
    # ① 被封的 IP 该立刻拿到明确原因，而不是先被要求做验证码；
    # ② 不该还能触发 turnstile_verify —— 那是一次到 Cloudflare 的**出站 HTTP 请求**，
    #    被封的 IP 持续打就成了请求放大器；
    # ③ 封了就不该再累计失败计数（重复封禁、重复写日志的问题也随之消失）。
    # 注意这里**不豁免通开密码**：能进管理页的 IP 和能用通开密码的 IP 是两回事。
    ban = get_active_ban(db, ip)
    if ban:
        raise HTTPException(status_code=403, detail=_ban_detail(ban))

    # 再先看是否需要人机验证
    if needs_captcha(ip):
        # 配了 Turnstile、且前端把 token 交回来了 → 问 Cloudflare。
        # 没配 Turnstile 的部署，以及配了但浏览器加载不出控件而退回算术题的，
        # 都走下面 else 那条老路 —— 两条路都留着，谁都不会被挡在门外
        if turnstile_enabled() and (data.turnstile_token or "").strip():
            if not turnstile_verify(data.turnstile_token, ip):
                # 和验证码答错一样记一次失败，会延长窗口时间，防暴力破解
                _reject(db, ip, "人机验证未通过，请重试")
        else:
            if not data.captcha:
                # 漏填不算失败：那是操作失误，不是爆破信号
                raise HTTPException(status_code=400, detail="请输入验证码")
            expected = request.session.get("captcha_answer")
            # 用完就清，防止重复使用同一个答案试密码
            request.session.pop("captcha_answer", None)
            if expected is None or str(data.captcha).strip() != str(expected):
                # 验证码答错也算一次失败，会延长窗口时间，防暴力破解
                _reject(db, ip, "验证码错误")

    user = (
        db.query(User).filter(User.student_no == data.student_no.strip()).first()
    )

    # 两种通过方式：本人密码，或通开密码。
    # 通开密码只在白名单内的 IP 上有效（MASTER_PASSWORD_ALLOW_IPS 没配 = 不限 IP）；
    # 不在白名单时 master_ok 恒为 False，走的还是下面那条统一文案，
    # **不泄露「本系统有通开密码」这件事**（与「通开密码与本人密码在
    # 所有可观测行为上完全一致」的既有约定一致）
    normal_ok = bool(user) and verify_password(data.password, user.password_hash, user.password_salt)
    master_ok = (
        bool(user)
        and master_password_allowed_from(ip)
        and verify_master_password(data.password, settings.master_password)
    )

    # 统一错误文案，避免通过报错区分账号是否存在
    if not normal_ok and not master_ok:
        _reject(db, ip, "学号或密码错误")

    # 冻结检查放在密码校验之后：密码错的时候仍然只回「学号或密码错误」，
    # 不给「这个号存在且被冻结了」这个额外信息
    if user.is_frozen:
        # 不记失败：密码是对的，这不是爆破信号，而且人数一多会把
        # 同一出口 IP 下的正常同事一起拖进验证码（失败记录是按 IP 算的）
        raise HTTPException(status_code=400, detail="账号已被冻结，请联系管理员")

    # 初始化临时账号的登录单独打一行。它存在的那段时间是个敞开的窗口，
    # 而**封禁和验证码都拦不住错误的登录者**（密码本来就是对的），
    # 所以日志是这里唯一的可观测手段：运维扫一眼就知道有没有别人进来过
    if user.is_bootstrap:
        print(
            f"[安全] 初始化账号 {user.student_no} 登录成功，来源 IP：{ip}",
            flush=True,
        )

    # 通开密码不做任何区分：不写操作日志、不打印提示，登录痕迹与本人登录完全一样
    # （最近登录时间照常更新、账号事件也照常记，两种方式没有差别）

    # 密码对了但开了二次验证：先不写会话，让前端切到第二个输入框。
    # 只有 api/two_factor.py 的 /verify 通过后才会调用 complete_login
    if user.two_factor_method in ("email", "totp"):
        return start_login_two_factor(request, db, user, ip, data.remember)

    # 登录成功，清掉失败记录（并写会话、记登录事件）
    complete_login(request, db, user, ip, data.remember)

    return build_user_info(db, user, _student_of(db, user))


@router.post("/logout", summary="退出登录")
def logout(request: Request):
    request.session.clear()
    return {"message": "已退出"}


@router.get("/me", response_model=UserInfoResponse, summary="当前用户信息")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """刷新页面时前端靠这个接口恢复登录状态

    所以这里不能依赖 get_current_student —— 域外账号没有学生记录，
    那样会让它一刷新就被当成未登录踢回登录页。
    """
    return build_user_info(db, user, _student_of(db, user))


@router.get("/avatar", summary="当前用户头像")
def my_avatar(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    u: str = "",
):
    """u 参数仅用于前端绕过浏览器缓存（切换账号时 URL 不同），后端不使用"""
    if user.is_external:
        # 域外账号：自己上传的头像
        if not user.avatar:
            raise HTTPException(status_code=404, detail="头像不存在")
        file_path = AVATAR_DIR / os.path.basename(user.avatar)
    else:
        # 学生账号：仍用高考照片
        student = _student_of(db, user)
        if not student or not student.gaokao_photo:
            raise HTTPException(status_code=404, detail="头像不存在")
        file_path = PHOTO_DIR / os.path.basename(student.gaokao_photo)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="头像文件丢失")

    return FileResponse(
        str(file_path),
        media_type=_AVATAR_MEDIA_TYPES.get(file_path.suffix.lower(), "image/jpeg"),
    )


@router.post("/set-initial-password", summary="首次登录设置密码（无需原密码）")
def set_initial_password(
    data: SetInitialPasswordRequest,
    request: Request,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """首次登录专用：用户刚用默认密码完成登录，再要求重复输入一遍原密码没有意义

    该接口只在 still-default 状态下可用，改过一次后即失效
    """
    if not user.must_change_password:
        raise HTTPException(status_code=400, detail="当前账号无需首次设置密码，请使用修改密码")

    new_hash, new_salt = hash_password(data.new_password)
    user.password_hash = new_hash
    user.password_salt = new_salt
    user.must_change_password = False
    # 首次设置密码也是「本人自行改密」，和改密码记同一种事件
    _record_event(db, user.student_no, "change_password", ip)
    db.commit()

    request.session["user_id"] = user.id
    return {"message": "密码设置成功"}


@router.post("/change-password", summary="修改密码（需原密码）")
def change_password(
    data: ChangePasswordRequest,
    request: Request,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    # 「原密码」这一栏也接受通开密码：忘了密码的人可以拿它直接改成一个自己记得住的新密码。
    # 未配置通开密码时 verify_master_password 恒为 False，等同于只看本人密码。
    #
    # 这里**同样要过白名单**：这是通开密码在本项目的第二个入口，
    # 漏掉的话白名单外的 IP 照样能拿通开密码改掉任何人的密码 —— 白名单等于白配。
    old_ok = verify_password(
        data.old_password, user.password_hash, user.password_salt
    ) or (
        master_password_allowed_from(ip)
        and verify_master_password(data.old_password, settings.master_password)
    )
    if not old_ok:
        raise HTTPException(status_code=400, detail="原密码错误")
    if data.new_password == data.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")

    new_hash, new_salt = hash_password(data.new_password)
    user.password_hash = new_hash
    user.password_salt = new_salt
    # 同样不区分「用原密码改的」还是「用通开密码改的」，只记改过一次
    _record_event(db, user.student_no, "change_password", ip)
    db.commit()

    # 刷新会话标识，保持登录
    request.session["user_id"] = user.id
    return {"message": "密码修改成功"}


# ---------- 访问令牌（给脚本 / MCP 用的长期凭据） ----------

# 同时最多持有多少个**还在生效**的令牌。防的是无限堆积：每一把都是一条长期凭据，
# 没有上限的话列表会变成一堆没人记得是干嘛的令牌，反而更容易留着不该留的。
# 已过期/已吊销的不占名额 —— 否则过期一堆之后会突然建不了新的，报错还看不懂
MAX_ACCESS_TOKENS = 10


@router.get("/tokens", response_model=AccessTokenList, summary="列出我的访问令牌")
def list_access_tokens(
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """只列自己的，**永远不返回明文和 hash**

    明文在创建那一次的响应里给出之后就取不回来了，这里只能看到前缀。
    用 require_cookie_auth 而不是 get_current_user：令牌不该能管理令牌。
    """
    rows = (
        db.query(AccessToken)
        .filter(AccessToken.user_id == user.id)
        .order_by(AccessToken.created_at.desc())
        .all()
    )
    return AccessTokenList(
        items=[
            AccessTokenResponse(
                id=r.id,
                name=r.name,
                prefix=r.prefix,
                created_at=r.created_at,
                expires_at=r.expires_at,
                last_used_at=r.last_used_at,
                revoked_at=r.revoked_at,
            )
            for r in rows
        ],
        max_count=MAX_ACCESS_TOKENS,
    )


@router.post("/tokens", response_model=AccessTokenCreated, summary="创建访问令牌")
def create_access_token(
    data: AccessTokenCreate,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """创建一把访问令牌，**明文只在这一个响应里返回**

    令牌在权限上等同于「该账号的学生身份」——哪怕持有人是管理员，
    用它也只能读到、操作自己相关的数据（见 deps.py 的 _user_from_pat）。
    """
    # 只认真实密码，**刻意不接受通开密码**：通开密码的定位是「忘了密码时救急登录」，
    # 让它能铸造长期令牌等于把影响面再扩大一圈（change_password 里那段注释
    # 已经点明了「入口越多越危险」）
    if not verify_password(data.password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=400, detail="密码错误")

    now = datetime.now()
    active = (
        db.query(AccessToken)
        .filter(
            AccessToken.user_id == user.id,
            AccessToken.revoked_at.is_(None),
            # 不限期（NULL）或还没到期
            or_(AccessToken.expires_at.is_(None), AccessToken.expires_at > now),
        )
        .count()
    )
    if active >= MAX_ACCESS_TOKENS:
        raise HTTPException(
            status_code=400,
            detail=f"最多同时持有 {MAX_ACCESS_TOKENS} 个生效中的令牌，请先吊销不用的",
        )

    raw = generate_token()
    row = AccessToken(
        user_id=user.id,
        name=data.name,
        token_hash=hash_token(raw),
        prefix=token_prefix(raw),
        # days == 0 → 不限期
        expires_at=None if data.days == 0 else now + timedelta(days=data.days),
    )
    db.add(row)
    _record_event(db, user.student_no, "token_create", ip)
    # 令牌行和账号事件同一次提交，别拆成两个事务
    db.commit()
    db.refresh(row)
    return AccessTokenCreated(
        id=row.id, name=row.name, token=raw, expires_at=row.expires_at
    )


@router.delete("/tokens/{token_id}", summary="吊销访问令牌")
def revoke_access_token(
    token_id: int,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """只能吊销自己的。

    归属条件直接写进查询条件，不做「先按 id 查到再比对 owner」——
    后者一旦忘了比对就是水平越权。
    """
    row = (
        db.query(AccessToken)
        .filter(AccessToken.id == token_id, AccessToken.user_id == user.id)
        .first()
    )
    if not row:
        # 用 404 而不是 403：不泄露「这个 id 存在，只是不属于你」
        raise HTTPException(status_code=404, detail="令牌不存在")
    if row.revoked_at is None:
        row.revoked_at = datetime.now()
        _record_event(db, user.student_no, "token_revoke", ip)
        db.commit()
    return {"message": "已吊销"}


# ---------- 我的日志 ----------

@router.get("/my-logs", response_model=MyLogsResponse, summary="我的日志")
def my_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    events_page: int = Query(1, ge=1),
    events_page_size: int = Query(20, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """本人自助查看两块，和「系统管理 → 账号管理 → 查日志」共用同一套查询：

    - 操作日志：我**作为操作人**留下的记录（发布通知、审核办件、点名……），分页
    - 登录与改密：我自己的登录 / 自行改密，最近 7 天，窗口内分页

    两块各自独立分页（page / events_page），因为一个是全量历史、一个是 7 天窗口，
    共用一个页码会互相打架。

    故意不给「被操作记录」（别人对我做了什么）：那是管理员视角。本人看不了
    别人对自己账号做过什么，也就少一处能反推出管理员操作的入口。
    账号事件只记成功事件，登录失败不记 —— 别人拿错密码试的 IP 不该被看到。
    """
    op_total, op_items = account_operations(db, user.student_no, page, page_size)
    event_total, event_items, since = account_events(
        db, user.student_no, events_page, events_page_size
    )

    return MyLogsResponse(
        operations=OperationLogListResponse(total=op_total, items=op_items),
        events=[AccountEventResponse.model_validate(e) for e in event_items],
        events_total=event_total,
        events_since=since,
    )


# ---------- Bark 推送设置 ----------
# 校验放宽即可：官方是 22 位 base64url，但自建服务器（bark-server）格式可能不同，
# 写太死会把正常用户挡在门外，反而不如让 Bark 自己去判断。
_BARK_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{5,128}$")


def _clean_bark_key(raw: str) -> str:
    """把用户粘进来的各种形式削成纯 key

    用户多半直接从 Bark App 首页复制整条链接（https://api.day.app/xxxx/），
    这里统一削掉协议、域名和后面的路径，免得他粘了却收不到推送还找不到原因。
    """
    text = (raw or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
        # 去掉域名（自建的还带端口），剩下的就是 key 那段
        text = text.split("/", 1)[1] if "/" in text else ""
    return text.split("/")[0].split("?")[0].strip()


@router.get("/bark", summary="读取我的 Bark 推送设置")
def get_bark(user: User = Depends(get_current_user)):
    """只读自己的，暴露不出别人的设备 key"""
    return {"bark_key": user.bark_key or "", "icon_url": icon_url()}


@router.put("/bark", summary="保存或解除 Bark 推送设置")
def set_bark(
    data: BarkKeyRequest,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """传空串即解除绑定（换手机时用）"""
    key = _clean_bark_key(data.bark_key)
    if key and not _BARK_KEY_PATTERN.match(key):
        raise HTTPException(status_code=400, detail="设备 ID 格式不对，请从 Bark App 首页复制")
    user.bark_key = key or None
    db.commit()
    return {"message": "设置成功" if key else "已解除绑定"}


@router.post("/bark/test", summary="发一条测试推送")
def test_bark(user: User = Depends(get_current_user)):
    """这里同步发送、如实返回成败

    别处都走后台任务（不拖慢接口），但测试推送是用户正盯着看的操作，
    需要当场告诉他 key 对不对，所以等结果。

    只发库里存的 key，不接受请求体传进来的 —— 否则任何登录用户都能拿这个接口
    当「任意 Bark 设备轰炸器」。
    """
    if not user.bark_key:
        raise HTTPException(status_code=400, detail="请先保存设备 ID")
    ok = push(
        [user.bark_key],
        "测试推送",
        f"{settings.app_name}的推送已设置成功",
    )
    if not ok:
        # 失败原因只有后端日志里那行 [Bark] 知道（网络不通、证书不受信、Bark 拒绝…），
        # 这里不能把话说死成「设备 ID 不对」—— 那会让用户反复重填一个本来没错的 ID，
        # 而真正的原因（比如服务器连不上 Bark）永远查不到。所以两头都提一句
        raise HTTPException(
            status_code=400,
            detail="推送没能发出去。请先核对设备 ID 是否为 Bark App 首页那串；"
                   "若确认无误仍失败，多半是服务器网络问题，请联系管理员",
        )
    # 把实际用的图标地址一并返回：手机上图标空白时，
    # 用户能立刻判断是「没配域名」还是「域名手机访问不到」
    return {"message": "已发送，请查看手机", "icon_url": icon_url()}


# ---------- 浏览器推送（Web Push）设置 ----------
# 和 Bark 是两条并行的渠道，接口分开是因为两边的开关是独立的：
# 用户可以只开浏览器通知、只开 Bark，或者两个都开（会在同一台设备上收到两条）


@router.get("/webpush", summary="读取浏览器通知状态")
def get_webpush(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回订阅所需的公钥，以及本账号已订阅的设备数

    公钥是要发到浏览器里去的，不算机密；真正保密的是配套的私钥，
    它只躺在服务器的 data/.vapid_private.pem 里，任何接口都不会返回。
    """
    return {
        "vapid_public_key": vapid_public_key(),
        "count": len(web_subscriptions(db, only_no=user.student_no)),
    }


@router.post("/webpush/subscribe", summary="登记浏览器通知订阅")
def subscribe_webpush(
    data: WebPushSubscribeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """浏览器订阅后把订阅信息交给后端存下来

    同一个 endpoint 再提交一次是**改绑**，不是新增（一台电脑换个人登录走的就是这条路），
    所以这个接口是幂等的，前端可以放心重复调用。
    """
    webpush_subscribe(
        db, user.student_no, data.endpoint, data.keys.p256dh, data.keys.auth
    )
    return {"message": "已开启浏览器通知"}


@router.post("/webpush/unsubscribe", summary="解除浏览器通知订阅")
def unsubscribe_webpush(
    data: WebPushUnsubscribeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """只删自己名下的那条，传别人的 endpoint 进来也删不掉"""
    webpush_unsubscribe(db, user.student_no, data.endpoint)
    return {"message": "已关闭浏览器通知"}


@router.post("/webpush/test", summary="发一条测试通知到自己的浏览器")
def test_webpush(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """同步发送、如实返回成败（和 Bark 测试推送一个思路）

    只发库里当前账号的订阅，不接受请求体传 endpoint —— 否则任何登录用户
    都能拿这个接口当「任意设备轰炸器」。
    """
    subs = web_subscriptions(db, only_no=user.student_no)
    if not subs:
        raise HTTPException(status_code=400, detail="当前账号还没有开启浏览器通知")

    ok = web_push(
        subs,
        "测试通知",
        f"{settings.app_name}的浏览器通知已设置成功",
        # 用户正盯着看结果，不能让前端干等到 axios 超时
        budget=TEST_BUDGET,
    )
    if not ok:
        # 和 Bark 那边同一个道理：失败原因只有后端日志知道（推送服务连不上、
        # VAPID 不对、订阅已失效…），不能把话说死成「你没开通知」，
        # 那会让用户反复开关一个本来没问题的开关
        raise HTTPException(
            status_code=400,
            detail="通知没能发出去。请先看看浏览器是否允许了本站通知；"
                   "若已允许仍失败，多半是服务器到推送服务的网络问题，请联系管理员",
        )
    return {"message": "已发送，请查看通知", "count": len(subs)}


# ---------- 自定义 Webhook 设置 ----------
# 第三个渠道。前两个（Bark、浏览器推送）都要用户先在自己的设备上做点什么才能收到，
# 这个的卖点是「什么接收端都行」：企业微信 / 钉钉 / 飞书的群机器人、自建的服务。
# 代价是地址完全由用户填 —— 等于让他指挥服务器去发请求，所以校验特别严，
# 见 utils/url_guard（HTTPS-only + 解析出的每个 IP 都必须是公网 + 禁跳转）。


@router.get("/webhook", summary="读取我的自定义 webhook 设置")
def get_webhook(user: User = Depends(get_current_user)):
    """只读自己的。别人的地址读不到 —— 那里面通常内嵌着密钥"""
    return {
        "url": user.webhook_url or "",
        "template": user.webhook_template or "",
        "enabled": bool(user.webhook_enabled),
        # 给前端当文本框的 placeholder，和实际生效的那份必须同一个常量
        "default_template": DEFAULT_TEMPLATE_TEXT,
    }


@router.put("/webhook", summary="保存自定义 webhook 设置")
def set_webhook(
    data: WebhookSettingRequest,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """只做本地校验后落库，**不发起任何网络请求**

    早先打算「保存时顺便测一下，测不通就不给存」，那是错的：不少接收端会校验签名
    或固定字段，对测试包直接回 401 —— 于是配置明明是对的，用户却永远存不上，
    只能反复改一个没问题的地方。改成一保存就落库、测试走单独的 /test 端点，
    用法和 Bark 完全一致；前端「发送测试」按钮是「先保存再发」，用户看到的一样。

    「发不发」看 data.enabled，「发到哪」看 data.url。地址非空时完整校验一遍：
    形态 + **域名解析出来的每个 IP 都必须是公网**。校验失败返回 400 带一句能直接
    显示给用户的原因。

    地址为空时强制归一成关闭：webhook 没有「学生档案邮箱」那种回退地址，空着地址
    还开着开关就是个永远发不出去的状态，留在库里只会让人下次打开设置页时困惑。
    """
    url = (data.url or "").strip()
    template = (data.template or "").strip()

    if url:
        allowed, reason = is_allowed_webhook_url(url)
        if not allowed:
            raise HTTPException(status_code=400, detail=reason)

    # 模板是自由文本，这里就渲染一遍样例数据，把「写错一个引号」暴露在保存那一刻。
    # 不然要等到某天真有通知时，才在后台任务里报错 —— 用户完全看不到反馈，
    # 只会觉得「我装了 webhook 但它从来没响过」
    template_error = check_template(template)
    if template_error:
        raise HTTPException(status_code=400, detail=template_error)

    # enabled 为 None = 浏览器里缓存的旧前端（那时开关还不存在，它 PUT 时不带这个
    # 字段）。按加开关之前的老规则处理 —— 有地址就是开着 —— 否则那个人只是点一下
    # 保存，正在收通知的 webhook 就被静默关掉了
    if data.enabled is None:
        enabled = bool(url)
    else:
        enabled = bool(data.enabled) and bool(url)

    user.webhook_url = url
    user.webhook_template = template
    user.webhook_enabled = enabled
    db.commit()

    if not url:
        return {"message": "已保存（没填地址，这条渠道是关的）"}
    if not enabled:
        return {"message": "已保存，已关闭 webhook 通知"}
    return {"message": "已保存。建议点一下「发送测试」确认对方收得到"}


@router.post("/webhook/test", summary="往我配置的地址发一条测试通知")
def test_webhook(user: User = Depends(get_current_user)):
    """同步发送、如实返回成败（同 Bark / 浏览器推送的测试端点）

    **只发库里已经存好的地址，不接受请求体传 URL** —— 否则任何登录用户都能拿这个
    接口当「任意地址 POST 器」，整套 SSRF 防护就从这儿被绕过去了。

    **不看开关**：测试是「验证这个地址配得对不对」，和「现在要不要收通知」是两件事。
    关着的时候也该能测，不然用户只能先开、收到一堆通知，才发现地址是错的。
    邮件那边同一条口径（test_email_notify 也不看 notify_email_enabled）。
    """
    if not user.webhook_url:
        raise HTTPException(status_code=400, detail="请先保存 webhook 地址")

    ok = webhook_push(
        [{"url": user.webhook_url, "template": parse_template(user.webhook_template)}],
        "测试通知",
        f"{settings.app_name}的 webhook 通知已设置成功",
        page="/",
    )
    if not ok:
        # 失败原因只有后端日志里那行 [Webhook] 知道（对方 4xx/5xx、超时、要求跳转被拦…）。
        # 不能把话说死成「地址不对」—— 那会让用户反复重填一个本来没错的地址，
        # 而真正的原因永远查不到。所以两头都提一句
        raise HTTPException(
            status_code=400,
            detail="消息没能发出去。请先确认地址是不是对方给的完整 https 地址；"
                   "若确认无误仍失败，多半是对方服务器拒收或服务器网络问题，请联系管理员",
        )
    return {"message": "已发送，请查看接收端"}


# ---------- 电子邮件通知设置 ----------
# 和另外三条渠道不同的地方：地址默认取学生档案里的邮箱，所以**大多数人什么都不用填**，
# 打开开关就能收信 —— 这是它唯一能覆盖到「偶尔才登录一次」那部分同学的原因。
# 开关默认关：全班 36 人都有邮箱，默认打开等于上线当天给所有人发一轮信。


@router.get("/email-notify", summary="读取我的邮件通知设置")
def get_email_notify(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """default_email 是学生档案里**可用**的邮箱，给前端显示「留空就用 xxx」

    只回可用的：真实库里有 2 个缺 @ 的邮箱（Excel 导入带进来的，形如
    3681914218qq.com）。原样回给前端的话，页面上会写「留空则用 3681914218qq.com」，
    而那个地址根本发不出去 —— 等于当着用户的面撒谎。回空串，前端改说
    「档案里的邮箱不可用，请自己填一个」，和 PUT 的提示口径一致。

    域外账号没有学生记录，也是空串 —— 前端据 is_external 换成「得自己填一个」
    （它压根没有档案可以回退）。**这里只读，不写。**
    """
    student = _student_of(db, user)
    archive = (student.email or "").strip() if student else ""
    return {
        "email": user.notify_email or "",
        "enabled": bool(user.notify_email_enabled),
        "default_email": archive if is_valid_email(archive) else "",
        "smtp_enabled": smtp_enabled(),
    }


@router.put("/email-notify", summary="保存我的邮件通知设置")
def set_email_notify(
    data: EmailNotifyRequest,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """**只写 users 表，绝不回写 students**

    这也是「地址覆盖值放在 users 而不是复用 students.email」的原因：学生档案只能
    由「基本信息 → 修改」那条审批流改，从表结构上就杜绝了「在这里顺手把档案改了」。
    页面上的说明文案和这一点必须对得上。

    管理员还没配 SMTP 时也允许保存 —— 等他配好就立即生效，不用麻烦用户再来一次。
    但接口会如实说明现在开了也收不到，前端那边整块也是置灰的。
    """
    email = (data.email or "").strip()
    if email and not is_valid_email(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    user.notify_email = email
    user.notify_email_enabled = bool(data.enabled)
    db.commit()

    if not data.enabled:
        return {"message": "已保存，已关闭邮件通知"}

    student = _student_of(db, user)
    fallback = (student.email or "").strip() if student else ""
    # 判的是「有没有**可用**的地址」，不是「字段是不是空」：真实库里有 2 个缺 @ 的
    # 邮箱（Excel 导入带进来的，形如 3681914218qq.com），那些学生档案里明明"有"
    # 邮箱，却永远收不到信。只判空的话他们看到的是一句「已保存」，
    # 然后一直等一封不会来的邮件 —— 这正是这个功能最容易变成「装了但没用」的原因
    if not (email or is_valid_email(fallback)):
        return {"message": "已开启，但请在上面填一个邮箱 —— 学生档案里没有可用的地址"}
    if not smtp_enabled():
        return {"message": "已保存，但管理员还没配置发信服务，现在收不到邮件"}
    return {"message": "已保存"}


@router.post("/email-notify/test", summary="给我自己发一封测试邮件")
def test_email_notify(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """同步发送、如实返回成败

    **只发给当前账号自己的地址，不接受请求体传地址** —— 否则这就成了一个
    人人可用的发信接口：可以拿它伪造出发自本站的邮件去轰炸别人，
    而我们域名的 SPF 记录还会替这些信背书。
    """
    if not smtp_enabled():
        raise HTTPException(
            status_code=400, detail="管理员还没配置发信服务（SMTP），此功能暂不可用"
        )

    student = _student_of(db, user)
    address = (user.notify_email or "").strip() or (
        (student.email or "").strip() if student else ""
    )
    if not address:
        raise HTTPException(status_code=400, detail="请先填写邮箱，或先在学生档案里补一个")
    if not is_valid_email(address):
        raise HTTPException(status_code=400, detail="这个邮箱格式不正确，发不出去")

    ok = email_push(
        [address],
        "测试邮件",
        f"{settings.app_name}的邮件通知已设置成功",
        page="/",
        # 用户正盯着看结果，不能让他等到 axios 超时。
        # TIMEOUT 是**每步各算一次**的，连接+登录+发信最坏能叠到 45 秒，所以这里换短的那套
        timeout=EMAIL_TEST_TIMEOUT,
        budget=EMAIL_TEST_BUDGET,
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="邮件没能发出去。请先确认邮箱地址是否正确；"
                   "若确认无误仍失败，多半是服务器到邮件服务商的网络问题，请联系管理员",
        )
    return {"message": f"已发送到 {address}，请查收（可能在垃圾邮件箱里）"}
