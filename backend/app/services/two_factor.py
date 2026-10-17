"""二次验证（2FA）的公共逻辑

两种可选方式（默认都不开）：

- **电子邮件验证码**：复用现有的 SMTP 配置和「通知邮箱」地址。6 位数字，
  10 分钟有效；60 秒内不能重发。和「消息通知」用同一个地址，
  但**不受 notify_email_enabled 开关限制** —— 那个开关管的是「收不收通知」，
  二次验证是登录的一部分，用户明确开了 2FA 就该收得到。
- **TOTP**：身份验证器 App 里的 6 位动态码，30 秒一步、45 秒窗口（见 utils/totp.py）。

另外提供 10 个一次性恢复码，邮件进不去或手机丢了时用。

安全上的几个关键决定：
1. 验证码**只把哈希留在服务端**。6 位数字的哈希要是放进签名 Cookie 里，
   拿到会话的人可以直接离线穷举。
2. 每个挑战有自己的尝试次数（5 次）和过期时间，跨重发累计，不在重发时清零。
3. 恢复码只存哈希、用后标记，重新生成会整批作废旧的。
4. **通行密钥登录不经过这里**：钥匙本身已经要求用户在场验证，再要一次码
   只是多一道手续，不增加安全性。这个例外写在 api/passkeys.py 的登录接口里。
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..config import settings, smtp_enabled, two_factor_master_code
from ..models import Student, TwoFactorChallenge, TwoFactorRecoveryCode, User
from ..utils.email_addr import is_valid_email
from .email_service import TEST_BUDGET, TEST_TIMEOUT
from .email_service import push as email_push

# 验证码有效期。10 分钟足够从「点登录」到「打开邮箱」再到回来输入
EMAIL_CODE_TTL = 600
# 重发冷却：防止按着按钮连点把邮箱刷爆
RESEND_COOLDOWN = 60
# 每个挑战最多输错几次。轻度防爆破：密码那边有登录失败计数和封禁，
# 这里只需要挡住「拿到密码后顺手枚举 6 位验证码」这种最笨的尝试
MAX_ATTEMPTS = 5
# 恢复码数量与字符集。去掉 0/O/1/I 这类容易看错的字符
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_LENGTH = 8
RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def new_email_code() -> str:
    """6 位数字验证码（保留前导 0）"""
    return f"{secrets.randbelow(10 ** 6):06d}"


def hash_code(code: str) -> str:
    """验证码的存储形式

    邮件码空间只有 10^6，哈希本身挡不住整库泄露后的穷举；它挡的是
    「数据库被顺手读走一列，就能看到别人正在用的验证码」。恢复码有 32^8 种，
    哈希在这里是实打实的保护。
    """
    return hashlib.sha256((code or "").strip().encode("utf-8")).hexdigest()


def normalize_recovery_code(raw: str) -> str:
    """去掉横杠和空格、转大写：用户抄成「abcd-efgh」或「ABCD EFGH」都认"""
    return "".join(ch for ch in (raw or "").upper() if ch.isalnum())


def effective_email(db: Session, user: User) -> str:
    """二次验证的收件地址：和通知邮箱同一条回退规则，但**不看通知开关**

    覆盖值优先，空则回退学生档案邮箱。域外账号没有档案，只能用自己的覆盖值。
    格式不合法时返回空串 —— 调用方据此给出「没有可用邮箱」的提示，而不是
    对着一个发不出去的地址说「已发送」。
    """
    student = (
        db.query(Student).filter(Student.student_no == user.student_no).first()
    )
    archive = (student.email or "").strip() if student else ""
    address = (user.notify_email or "").strip() or archive
    return address if is_valid_email(address) else ""


def mask_email(address: str) -> str:
    """a***@example.com。登录页给密码正确但还没过第二因素的人看"""
    local, _, domain = (address or "").partition("@")
    if not local or not domain:
        return ""
    keep = local[:2] if len(local) > 2 else local[:1]
    return f"{keep}***@{domain}"


def issue_recovery_codes(db: Session, user: User) -> list[str]:
    """生成一批新的恢复码，旧的整批作废；返回**明文**（只在这一次给用户看）"""
    db.query(TwoFactorRecoveryCode).filter(
        TwoFactorRecoveryCode.user_id == user.id
    ).delete(synchronize_session=False)

    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
        db.add(
            TwoFactorRecoveryCode(
                user_id=user.id,
                code_hash=hash_code(raw),
                created_at=datetime.now(),
            )
        )
        # 显示成 XXXX-XXXX，便于抄写；存储与校验都用去掉横杠的形式
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def unused_recovery_count(db: Session, user: User) -> int:
    return (
        db.query(TwoFactorRecoveryCode)
        .filter(
            TwoFactorRecoveryCode.user_id == user.id,
            TwoFactorRecoveryCode.used_at.is_(None),
        )
        .count()
    )


def consume_recovery_code(db: Session, user: User, raw: str) -> bool:
    """核销一个恢复码；不 commit，由调用方和登录会话一起提交

    只认 8 位（去掉横杠后）。这样 6 位邮件/TOTP 验证码不会被误当成恢复码，
    也就不会出现「验证码碰巧等于某个恢复码」的歧义。
    """
    normalized = normalize_recovery_code(raw)
    if len(normalized) != RECOVERY_CODE_LENGTH:
        return False
    row = (
        db.query(TwoFactorRecoveryCode)
        .filter(
            TwoFactorRecoveryCode.user_id == user.id,
            TwoFactorRecoveryCode.code_hash == hash_code(normalized),
            TwoFactorRecoveryCode.used_at.is_(None),
        )
        .first()
    )
    if not row:
        return False
    row.used_at = datetime.now()
    return True


def verify_email_code(challenge: TwoFactorChallenge, code: str) -> bool:
    """比对邮件验证码（常量时间比较，别用 == ）"""
    expected = challenge.code_hash or ""
    return bool(expected) and hmac.compare_digest(
        expected, hash_code((code or "").strip())
    )


def matches_master_code(code: str) -> bool:
    """二次验证万能码（环境变量 TWO_FACTOR_MASTER_CODE）

    没配时恒为 False，行为与没有这个功能完全一致。邮箱验证码和 TOTP 都认，
    常量时间比较。

    **命中后的表现必须和真码一样**：不写日志、不记账号事件、响应里也不加字段。
    它只是一个应急入口，不该在操作痕迹上露出「这次用的是万能码」。
    """
    expected = two_factor_master_code()
    return bool(expected) and hmac.compare_digest(
        expected, (code or "").strip()
    )


def create_challenge(
    db: Session,
    user: User,
    method: str,
    purpose: str = "login",
    remember: bool = False,
    ip: str | None = None,
    code: str = "",
    secret: str = "",
    ttl_seconds: int = EMAIL_CODE_TTL,
    now: datetime | None = None,
) -> TwoFactorChallenge:
    """建一个挑战并 flush 出 id；顺手清掉已经过期的挑战

    过期清理不是必须的（校验时还会判一次），但它让这张表不会随着时间无限增长。
    只 add/flush，commit 由调用方决定：登录流程要在发信前先落库。
    """
    now = now or datetime.now()
    db.query(TwoFactorChallenge).filter(
        TwoFactorChallenge.expires_at < now
    ).delete(synchronize_session=False)

    challenge = TwoFactorChallenge(
        user_id=user.id,
        purpose=purpose,
        method=method,
        code_hash=hash_code(code) if code else "",
        secret=secret,
        remember=remember,
        ip=ip,
        created_at=now,
        last_sent_at=now if method == "email" else None,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    db.add(challenge)
    db.flush()
    return challenge


def send_login_code(user: User, address: str, code: str) -> bool:
    """同步发一封验证码邮件，返回是否发出去了

    用「发送测试」那套短超时：用户正等在登录页上，不能让他对着转圈的按钮
    等满一次完整的 SMTP 超时。push 自己不会抛异常，失败只记日志。
    """
    ok = email_push(
        [address],
        f"{settings.app_name}登录验证码",
        f"你的登录验证码是 {code}，{EMAIL_CODE_TTL // 60} 分钟内有效。\n\n"
        "如果不是你本人操作，请忽略本邮件，并尽快修改密码。",
        page="/login",
        timeout=TEST_TIMEOUT,
        budget=TEST_BUDGET,
    )
    return bool(ok)


def start_login_two_factor(
    request, db: Session, user: User, ip: str, remember: bool
) -> dict:
    """密码已经对了：建挑战、发验证码，并让前端切到第二个输入框

    不在这里调用 complete_login —— 会话要等第二因素通过后才写。
    挑战 id 放进签名会话：它是随机整数，泄漏了也只知道「试哪一条」，
    验证码哈希和尝试次数都还在服务端。
    """
    method = user.two_factor_method
    address = effective_email(db, user) if method == "email" else ""
    code = new_email_code() if method == "email" else ""

    challenge = create_challenge(
        db, user, method, purpose="login", remember=remember, ip=ip, code=code
    )
    request.session["pending_2fa_id"] = challenge.id
    db.commit()

    sent = bool(method == "email" and address and send_login_code(user, address, code))
    result = {
        "two_factor_required": True,
        "method": method,
        "masked_email": mask_email(address) if address else "",
        "email_sent": sent,
    }
    if method == "email" and not sent:
        # 发不出去也要让用户有路可走：恢复码、或过一会儿重发
        result["message"] = "验证码没能发出去，可以稍后重发，或使用一次性恢复码"
    return result


def smtp_ready() -> bool:
    """开启邮件 2FA 的前提。单独包一层，方便接口和状态接口共用同一句话"""
    return smtp_enabled()
