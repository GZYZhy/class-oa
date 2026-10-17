"""二次验证的接口

分两类：

1. **登录时**（不需要登录态）：`/verify` 校验第二因素、`/resend` 重发邮件码。
   挑战 id 存在签名会话里，验证码哈希、尝试次数、过期时间都只在服务端。
2. **设置时**（需登录 + 再确认密码）：开启邮箱 / 身份验证器、关闭、重生成恢复码。

开启流程都要求**先证明这个第二因素真的能用**（邮件码收到并输对、身份验证器
生成的码对得上），不允许「先打开再说」—— 否则邮箱填错或手机时间不对的人，
下一次登录就被自己锁在门外了。
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings, smtp_enabled
from ..database import get_db
from ..models import TwoFactorChallenge, TwoFactorRecoveryCode, User
from ..schemas import (
    TwoFactorCodeRequest,
    TwoFactorPasswordRequest,
    TwoFactorVerifyRequest,
)
from ..services.two_factor import (
    EMAIL_CODE_TTL,
    MAX_ATTEMPTS,
    RESEND_COOLDOWN,
    consume_recovery_code,
    create_challenge,
    effective_email,
    hash_code,
    issue_recovery_codes,
    mask_email,
    new_email_code,
    send_login_code,
    unused_recovery_count,
    verify_email_code,
)
from ..utils.security import verify_password
from ..utils.totp import generate_secret
from ..utils.totp import matches as totp_matches
from ..utils.totp import provisioning_uri
from . import auth as auth_api
from .deps import get_client_ip, require_cookie_auth

router = APIRouter(prefix="/api/auth/2fa", tags=["二次验证"])


# ---------- 小工具 ----------


def _check_password(user: User, password: str) -> None:
    """敏感设置操作必须再输一次登录密码

    和访问令牌、通行密钥登记一个口径：登录态只说明「这台电脑现在是你」，
    改二次验证会影响以后所有设备的登录，得再确认一次。
    """
    if not verify_password(password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=400, detail="密码不正确")


def _setup_challenge(
    db: Session, user: User, method: str
) -> TwoFactorChallenge | None:
    """取当前账号最新的一条开启挑战；过期的顺手删掉"""
    challenge = (
        db.query(TwoFactorChallenge)
        .filter(
            TwoFactorChallenge.user_id == user.id,
            TwoFactorChallenge.purpose == "setup",
            TwoFactorChallenge.method == method,
        )
        .order_by(TwoFactorChallenge.id.desc())
        .first()
    )
    if challenge and challenge.expires_at < datetime.now():
        db.delete(challenge)
        db.commit()
        return None
    return challenge


def _login_challenge(request: Request, db: Session) -> TwoFactorChallenge:
    """从会话里取出这次登录对应的挑战

    只认会话里的 id，不接受请求体传 challenge_id —— 否则别人可以拿自己
    浏览器的挑战 id 来试你账号的验证码（虽然也要先知道密码）。
    """
    challenge_id = request.session.get("pending_2fa_id")
    if not challenge_id:
        raise HTTPException(status_code=400, detail="登录状态已过期，请重新输入密码")
    challenge = db.get(TwoFactorChallenge, challenge_id)
    if not challenge or challenge.purpose != "login":
        request.session.pop("pending_2fa_id", None)
        raise HTTPException(status_code=400, detail="登录状态已过期，请重新输入密码")
    if challenge.expires_at < datetime.now():
        db.delete(challenge)
        db.commit()
        request.session.pop("pending_2fa_id", None)
        raise HTTPException(status_code=400, detail="验证码已过期，请重新登录")
    return challenge


def _discard(db: Session, request: Request, challenge: TwoFactorChallenge) -> None:
    """作废挑战并清掉会话里的引用（尝试次数用尽 / 账号状态变了）"""
    db.delete(challenge)
    db.commit()
    request.session.pop("pending_2fa_id", None)


def _too_many_attempts(db: Session, request: Request, challenge: TwoFactorChallenge) -> None:
    _discard(db, request, challenge)
    raise HTTPException(status_code=400, detail="验证码错误次数过多，请重新登录")


# ---------- 登录时 ----------


@router.post("/verify", summary="校验登录二次验证码")
def verify_login_code(
    data: TwoFactorVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """第二因素通过后才真正写登录会话

    通行密钥登录不会走到这里（见 api/passkeys.py）：钥匙本身已经是第二因素。
    邮件验证码、TOTP 验证码、一次性恢复码都填在同一个框里提交，后端先试
    当前方式，不中再试恢复码；恢复码命中即作废，并在响应里告诉还剩几个。
    """
    challenge = _login_challenge(request, db)
    user = db.get(User, challenge.user_id)
    if not user or user.is_frozen:
        _discard(db, request, challenge)
        raise HTTPException(status_code=400, detail="账号状态已变化，请重新登录")
    # 管理员可能在等待期间清掉了二次验证或换了方式
    if user.two_factor_method != challenge.method:
        _discard(db, request, challenge)
        raise HTTPException(status_code=400, detail="二次验证设置已变化，请重新登录")
    if challenge.attempts >= MAX_ATTEMPTS:
        _too_many_attempts(db, request, challenge)

    step = None
    if challenge.method == "email":
        ok = verify_email_code(challenge, data.code)
    else:
        step = totp_matches(
            user.totp_secret or "", data.code, user.totp_last_step or 0
        )
        ok = step is not None

    used_recovery = False
    if not ok:
        # 恢复码是「最后一条路」，两种方式都要认
        used_recovery = consume_recovery_code(db, user, data.code)
        ok = used_recovery

    if not ok:
        challenge.attempts += 1
        left = MAX_ATTEMPTS - challenge.attempts
        if left <= 0:
            _too_many_attempts(db, request, challenge)
        db.commit()
        raise HTTPException(
            status_code=400, detail=f"验证码不正确，还可以再试 {left} 次"
        )

    # TOTP 记下用过的步，防同一步的码被重复使用
    if step is not None:
        user.totp_last_step = step

    remember = bool(challenge.remember)
    db.delete(challenge)
    db.commit()
    request.session.pop("pending_2fa_id", None)

    # 到这里才算真正登录：最近登录时间、登录事件、会话都只由 complete_login 写
    auth_api.complete_login(request, db, user, ip, remember)
    result = auth_api.build_user_info(
        db, user, auth_api._student_of(db, user)
    ).model_dump()
    if used_recovery:
        result["recovery_codes_left"] = unused_recovery_count(db, user)
        result["message"] = "已使用一个恢复码，这个码不能再用"
    return result


@router.post("/resend", summary="重新发送登录验证码")
def resend_login_code(
    request: Request,
    db: Session = Depends(get_db),
):
    """只对邮箱方式有效；60 秒冷却

    重发换一个新码，旧码立即失效。**尝试次数不清零** —— 否则拿到密码的人
    可以每 60 秒重发一次，把 5 次机会滚成无限次。
    """
    challenge = _login_challenge(request, db)
    if challenge.method != "email":
        raise HTTPException(status_code=400, detail="当前方式不需要验证码邮件")
    if challenge.attempts >= MAX_ATTEMPTS:
        _too_many_attempts(db, request, challenge)

    user = db.get(User, challenge.user_id)
    if not user:
        _discard(db, request, challenge)
        raise HTTPException(status_code=400, detail="登录状态已过期，请重新输入密码")

    if challenge.last_sent_at:
        elapsed = (datetime.now() - challenge.last_sent_at).total_seconds()
        if elapsed < RESEND_COOLDOWN:
            wait = int(RESEND_COOLDOWN - elapsed) + 1
            raise HTTPException(status_code=400, detail=f"请 {wait} 秒后再重新发送")

    address = effective_email(db, user)
    if not address:
        raise HTTPException(
            status_code=400, detail="没有可用的邮箱地址，请使用一次性恢复码"
        )

    code = new_email_code()
    challenge.code_hash = hash_code(code)
    # 先发、成功了再落库：发信失败时旧码仍然有效，用户不会两头落空
    if not send_login_code(user, address, code):
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="验证码没能发出去，请稍后重试，或使用一次性恢复码",
        )
    challenge.last_sent_at = datetime.now()
    challenge.sends += 1
    db.commit()
    return {"message": f"已重新发送到 {mask_email(address)}"}


# ---------- 设置 ----------


@router.get("/status", summary="我的二次验证设置")
def my_two_factor(
    user: User = Depends(require_cookie_auth), db: Session = Depends(get_db)
):
    """页面靠它决定显示「已开启」还是开启入口

    email 是实际会收验证码的地址（覆盖值优先，其次档案邮箱）；没有可用地址时
    是空串，前端要把「电子邮件验证码」那一块置灰并说明原因。
    """
    address = effective_email(db, user)
    return {
        "enabled": bool(user.two_factor_method),
        "method": user.two_factor_method or "",
        "email": address,
        "masked_email": mask_email(address) if address else "",
        "smtp_enabled": smtp_enabled(),
        "recovery_codes_left": unused_recovery_count(db, user),
    }


@router.post("/email/send", summary="发送开启邮箱二次验证的验证码")
def send_setup_email_code(
    data: TwoFactorPasswordRequest,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """先发一封测试码，确认这个邮箱真能收到，再允许开启

    复用消息通知的 SMTP 与地址口径，但**不看 notify_email_enabled**：
    二次验证是登录的一部分，不是「订阅通知」。
    """
    _check_password(user, data.password)
    if not smtp_enabled():
        raise HTTPException(
            status_code=400, detail="管理员还没配置发信服务（SMTP），暂不能用邮箱验证码"
        )
    address = effective_email(db, user)
    if not address:
        raise HTTPException(
            status_code=400,
            detail="没有可用的邮箱，请先在「通知设置」里填一个，或让学生档案补上邮箱",
        )

    now = datetime.now()
    challenge = _setup_challenge(db, user, "email")
    if challenge and challenge.last_sent_at:
        elapsed = (now - challenge.last_sent_at).total_seconds()
        if elapsed < RESEND_COOLDOWN:
            wait = int(RESEND_COOLDOWN - elapsed) + 1
            raise HTTPException(status_code=400, detail=f"请 {wait} 秒后再重新发送")

    code = new_email_code()
    if challenge:
        # 复用同一条挑战：尝试次数累计，不会靠「重新发一封」把次数刷回去
        challenge.code_hash = hash_code(code)
        challenge.last_sent_at = now
        challenge.expires_at = now + timedelta(seconds=EMAIL_CODE_TTL)
        challenge.sends += 1
    else:
        create_challenge(db, user, "email", purpose="setup", ip=ip, code=code)
    db.commit()

    if not send_login_code(user, address, code):
        raise HTTPException(
            status_code=400,
            detail="验证码没能发出去，请确认邮箱地址；若仍失败请联系管理员",
        )
    masked = mask_email(address)
    return {
        "message": f"验证码已发送到 {masked}，10 分钟内有效",
        "masked_email": masked,
    }


@router.post("/email/confirm", summary="确认邮箱验证码并开启")
def confirm_setup_email(
    data: TwoFactorCodeRequest,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """输对验证码才真正把 method 改成 email，并生成恢复码

    恢复码明文只出现在这一次响应里；后端只留哈希。
    """
    challenge = _setup_challenge(db, user, "email")
    if not challenge:
        raise HTTPException(status_code=400, detail="验证码已过期，请重新发送")
    if challenge.attempts >= MAX_ATTEMPTS:
        db.delete(challenge)
        db.commit()
        raise HTTPException(status_code=400, detail="错误次数过多，请重新发送验证码")

    if not verify_email_code(challenge, data.code):
        challenge.attempts += 1
        db.commit()
        left = MAX_ATTEMPTS - challenge.attempts
        if left <= 0:
            raise HTTPException(status_code=400, detail="错误次数过多，请重新发送验证码")
        raise HTTPException(
            status_code=400, detail=f"验证码不正确，还可以再试 {left} 次"
        )

    # 换成邮箱方式：旧的 TOTP 密钥和恢复码一并作废
    user.two_factor_method = "email"
    user.totp_secret = ""
    user.totp_last_step = 0
    db.query(TwoFactorChallenge).filter(
        TwoFactorChallenge.user_id == user.id,
        TwoFactorChallenge.purpose == "setup",
    ).delete(synchronize_session=False)
    codes = issue_recovery_codes(db, user)
    db.commit()
    return {"message": "已开启电子邮件二次验证", "recovery_codes": codes}


@router.post("/totp/begin", summary="生成一个待确认的 TOTP 密钥")
def begin_totp(
    data: TwoFactorPasswordRequest,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """只生成密钥，**先不写进账号**：等用户输对一次 App 里的码再确认

    密钥放在挑战表里，10 分钟没确认就作废。重复点「开始设置」以最后一次为准。
    """
    _check_password(user, data.password)

    db.query(TwoFactorChallenge).filter(
        TwoFactorChallenge.user_id == user.id,
        TwoFactorChallenge.purpose == "setup",
        TwoFactorChallenge.method == "totp",
    ).delete(synchronize_session=False)

    secret = generate_secret()
    create_challenge(db, user, "totp", purpose="setup", ip=ip, secret=secret)
    db.commit()
    issuer = settings.site_name.strip() or settings.app_name
    return {
        "secret": secret,
        "otpauth_uri": provisioning_uri(secret, user.student_no, issuer),
        "expires_in": EMAIL_CODE_TTL,
    }


@router.post("/totp/confirm", summary="确认 TOTP 验证码并开启")
def confirm_totp(
    data: TwoFactorCodeRequest,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """App 里显示的 6 位码对得上，才把密钥搬到账号上并生成恢复码"""
    challenge = _setup_challenge(db, user, "totp")
    if not challenge:
        raise HTTPException(status_code=400, detail="设置已过期，请重新开始")
    if challenge.attempts >= MAX_ATTEMPTS:
        db.delete(challenge)
        db.commit()
        raise HTTPException(status_code=400, detail="错误次数过多，请重新开始设置")

    step = totp_matches(challenge.secret or "", data.code, 0)
    if step is None:
        challenge.attempts += 1
        db.commit()
        left = MAX_ATTEMPTS - challenge.attempts
        if left <= 0:
            raise HTTPException(status_code=400, detail="错误次数过多，请重新开始设置")
        raise HTTPException(
            status_code=400, detail=f"验证码不正确，还可以再试 {left} 次"
        )

    user.two_factor_method = "totp"
    user.totp_secret = challenge.secret
    # 不把确认用的这一步记进 totp_last_step：否则用户开启后马上退出再登录，
    # 同一个 30 秒窗口内的码会被当成重放而拒绝，像是「刚开的就坏了」。
    # 这个码只在设置页出现过一次，重放风险远小于这里造成的困惑
    user.totp_last_step = 0
    db.query(TwoFactorChallenge).filter(
        TwoFactorChallenge.user_id == user.id,
        TwoFactorChallenge.purpose == "setup",
    ).delete(synchronize_session=False)
    codes = issue_recovery_codes(db, user)
    db.commit()
    return {"message": "已开启身份验证器二次验证", "recovery_codes": codes}


@router.post("/disable", summary="关闭二次验证")
def disable_two_factor(
    data: TwoFactorPasswordRequest,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """关闭后回到「只要密码」的登录方式，恢复码和待确认的挑战一并清掉"""
    _check_password(user, data.password)
    user.two_factor_method = ""
    user.totp_secret = ""
    user.totp_last_step = 0
    db.query(TwoFactorRecoveryCode).filter(
        TwoFactorRecoveryCode.user_id == user.id
    ).delete(synchronize_session=False)
    db.query(TwoFactorChallenge).filter(
        TwoFactorChallenge.user_id == user.id
    ).delete(synchronize_session=False)
    db.commit()
    return {"message": "已关闭二次验证，之后只需密码即可登录"}


@router.post("/recovery/regenerate", summary="重新生成 10 个一次性恢复码")
def regenerate_recovery_codes(
    data: TwoFactorPasswordRequest,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """旧码整批作废；新码只在这条响应里出现一次"""
    _check_password(user, data.password)
    if not user.two_factor_method:
        raise HTTPException(status_code=400, detail="二次验证还没开启")
    codes = issue_recovery_codes(db, user)
    db.commit()
    return {
        "message": "已重新生成，旧的恢复码全部作废",
        "recovery_codes": codes,
    }
