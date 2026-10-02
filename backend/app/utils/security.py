"""密码安全工具：PBKDF2-SHA256 哈希（Python 标准库，简单可靠）"""

import hashlib
import hmac
import os
import re
import secrets

# 迭代次数，提高暴力破解成本
ITERATIONS = 100_000

# 自定义密码规则：必须同时包含数字和字母（初始密码/重置密码不受这个限制）
_PASSWORD_PATTERN = re.compile(r'^(?=.*[A-Za-z])(?=.*\d).+$')


def validate_password(value: str, field_name: str = "新密码") -> str:
    """校验密码是否符合规则，不符合则抛 ValueError（Pydantic 校验器直接抛就可以）

    规则单点定义在这里：改密码、管理员给域外账号设密码都走这一份。
    """
    if len(value) < 6 or len(value) > 32:
        raise ValueError(f"{field_name}长度需为 6-32 位")
    if not _PASSWORD_PATTERN.match(value):
        raise ValueError(f"{field_name}必须同时包含字母和数字")
    return value


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """
    生成密码哈希

    返回：(哈希十六进制, 盐十六进制)
    """
    if salt is None:
        salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    )
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """校验密码是否正确（固定时间比较防计时攻击）"""
    actual_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(actual_hash, password_hash)


def verify_master_password(password: str, master: str) -> bool:
    """校验通开密码：任何账号都能用它登录

    未配置通开密码（空串）时一律返回 False，即功能关闭。
    """
    if not master:
        return False
    return hmac.compare_digest(password.encode("utf-8"), master.encode("utf-8"))


# ---------- 个人访问令牌 ----------

# 令牌前缀。带它是为了让运维一眼认出「这是一把本站令牌」而不是别的什么东西，
# 也方便密钥扫描工具识别（access_log、误提交到 Git 的场景）
TOKEN_PREFIX = "oa_pat_"

# 随机部分的字节数：32 字节 = 256 位熵，urlsafe 编码后 43 个字符。
# 猜中的概率可以忽略不计，不需要靠限流兜底
_TOKEN_BYTES = 32


def generate_token() -> str:
    """生成一把新的访问令牌明文（只在创建那一次的响应里返回给用户）"""
    return TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(raw: str) -> str:
    """算令牌明文对应的存储值

    用 sha256 而不是上面那套 pbkdf2，是因为明文有 256 位熵、没有字典空间可攻，
    慢哈希在这里只会让每个 API 请求白跑 10 万次迭代。
    密码函数必须用 pbkdf2（人选的密码熵太低）—— 两者场景不同，不是双标。
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def token_prefix(raw: str) -> str:
    """取展示用的开头片段

    取随机部分的前 8 位，而不是整串前 8 位 —— 整串前 7 位是固定的前缀，
    那样每把令牌在列表里看起来都一模一样，等于没显示。
    """
    body = raw[len(TOKEN_PREFIX):] if raw.startswith(TOKEN_PREFIX) else raw
    return TOKEN_PREFIX + body[:8]
