from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from ..database import Base


class TwoFactorChallenge(Base):
    """一次二次验证挑战（登录时的验证码 / 开启二次验证时的待确认密钥）

    为什么要存服务端，而不是像 WebAuthn 挑战那样放签名会话里：
    邮件验证码只有 6 位，哈希要是发给客户端，拿到会话 Cookie 的人可以离线穷举
    10^6 次——几分钟就能试完。挑战的哈希、尝试次数、过期时间必须留在服务端，
    客户端只拿一个随机的挑战 id（存在自己的会话里）。

    purpose：
    - login：密码已通过、等第二因素；
    - setup：用户正在开启邮箱 / 身份验证器，确认后才写进 users 表。
    """
    __tablename__ = "two_factor_challenges"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="挑战所属账号")
    # login / setup
    purpose = Column(String(10), nullable=False, default="login", comment="login|setup")
    # email / totp
    method = Column(String(10), nullable=False, comment="email|totp")
    # 邮件验证码的 SHA-256；TOTP 不用这一列
    code_hash = Column(String(64), nullable=False, default="", comment="邮件验证码哈希")
    # 开启 TOTP 时、用户还没确认前的候选密钥。确认后才搬到 users.totp_secret
    secret = Column(String(64), nullable=False, default="", comment="待确认的 TOTP 密钥")
    attempts = Column(Integer, nullable=False, default=0, comment="已输错次数")
    sends = Column(Integer, nullable=False, default=1, comment="验证码已发送次数")
    remember = Column(Boolean, nullable=False, default=False, comment="登录成功后是否保持登录")
    ip = Column(String(45), nullable=True, comment="发起挑战时的 IP")
    # 用 Python 时间（北京时间），和库里其它表一致
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True)
    last_sent_at = Column(DateTime, nullable=True, comment="最近一次发送验证码的时间")
    expires_at = Column(DateTime, nullable=False, index=True, comment="挑战过期时间")


class TwoFactorRecoveryCode(Base):
    """一次性恢复码

    手机丢了、邮箱也进不去时的最后一条路。**只存哈希**，明文只在生成那一次
    显示给用户；用过的行留着并记 used_at，方便看出「这个码被用过」，
    也方便账号设置页显示还剩几个。

    每个账号固定 10 个，重新生成会把旧的整批删掉。
    """
    __tablename__ = "two_factor_recovery_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="所属账号")
    # 规范化（去空格/横杠、转大写）之后的 SHA-256
    code_hash = Column(String(64), nullable=False, index=True, comment="恢复码哈希")
    used_at = Column(DateTime, nullable=True, comment="使用时间；空 = 还没用过")
    created_at = Column(DateTime, default=datetime.now, nullable=False)
