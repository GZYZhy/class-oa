"""密码安全工具：PBKDF2-SHA256 哈希（Python 标准库，简单可靠）"""

import hashlib
import hmac
import os

# 迭代次数，提高暴力破解成本
ITERATIONS = 100_000


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
