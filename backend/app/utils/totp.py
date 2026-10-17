"""TOTP（基于时间的一次性密码）

只依赖标准库，按 RFC 6238 实现：HMAC-SHA1（密钥, 时间步计数器）→ 动态截断 → 6 位。
和身份验证器 App（Google Authenticator、微软 Authenticator、1Password 等）互通，
因为它们认的就是这套算法。

**时间是难点，不是算法**：验证器与服务器的时钟不可能完全一致，所以通常要允许
前后各一个时间步。本项目的口径是「验证码从它所属时间步的起点算起，45 秒内有效」：

- 当前步：任何时刻都认（最多离起点 30 秒）；
- 上一步：只在进入下一步的头 15 秒内还认。

这样最坏情况下用户有 45 秒可用，比标准 TOTP 的 30 秒宽松，又没有放宽到
「上一分钟生成的码还能用」那种程度。时间步是 30 秒，与 RFC 及各大 App 一致。
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30          # 时间步长（秒），身份验证器 App 的默认值
WINDOW = 45        # 验证码有效期（秒），从所属时间步的起点算起
DIGITS = 6         # 位数，App 默认值
SECRET_BYTES = 20  # RFC 4226 推荐的 HMAC-SHA1 密钥长度


def generate_secret() -> str:
    """生成一个新密钥（Base32，去掉补位的 =）

    20 字节随机数 = 160 位熵，足够。Base32 是身份验证器唯一接受的录入格式，
    手工输错的风险也小（只有 A-Z 和 2-7）。
    """
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def code_for_step(secret: str, step: int) -> str:
    """算出某个时间步的 6 位验证码

    算法看不懂没关系，关键是它必须和 RFC 逐字节一致 —— 差一位 App 就算不出来。
    """
    # base32 的 = 补位可以省略，解回来时补上
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10 ** DIGITS:0{DIGITS}d}"


def code_at(secret: str, at: float | None = None) -> str:
    """当前时刻的验证码（测试与排查用；线上校验走 matches）"""
    now = time.time() if at is None else at
    return code_for_step(secret, int(now // STEP))


def matches(secret: str, code: str, last_step: int = 0, at: float | None = None) -> int | None:
    """校验验证码；通过时返回命中的时间步，不通过返回 None

    last_step 是**上次已经用过的步数**，用来防重放：同一个验证码（或它的同一步）
    只能用一次。没有它的话，截到验证码的人在 45 秒内可以再登一次。

    密钥损坏、空密钥、乱七八糟的输入一律当作「不匹配」，不让异常冒到登录接口上。
    """
    now = time.time() if at is None else at
    code = (code or "").strip()
    if not code or not secret:
        return None

    current = int(now // STEP)
    try:
        for step in (current, current - 1):
            # 用过的步不再接受（比较用 <=，所以重放直接落空）
            if step <= last_step:
                continue
            # 45 秒窗口：当前步天然满足；上一步只有走到下一步的头 15 秒内才算
            if now - step * STEP > WINDOW:
                continue
            if hmac.compare_digest(code_for_step(secret, step), code):
                return step
    except (ValueError, TypeError):
        # Base32 解码失败等异常：当成没配对，而不是 500
        return None
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    """身份验证器 App 的扫码 / 点击链接（otpauth://）

    页面上没有二维码库，直接把这个链接和密钥一起显示出来：用户可以手输密钥，
    手机上点链接也能唤起 App。
    """
    label = quote(issuer, safe="") + ":" + quote(account, safe="")
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP}"
    )
