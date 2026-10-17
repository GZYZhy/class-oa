from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String

from ..database import Base


class PasskeyCredential(Base):
    """一把通行密钥（WebAuthn 凭据）

    为什么单独一张表：一个账号可以有多把（手机一把、笔记本一把），
    吊销其中一把不影响其它几把。密码仍然保留，通行密钥只是多一种登录方式 ——
    换手机、丢手机时还能用密码进门，管理员也能一键清掉全部通行密钥。

    **只存公钥**：登录验证靠浏览器里的私钥签名，服务器这把公钥只能验、不能签，
    所以库被拖走也仿冒不了登录。credential_id 是浏览器生成的随机串，
    用 base64url 存成字符串，方便直接和前端回传的 rawId 对上。

    刻意不定义 relationship()：和 AccessToken 保持一致；查的时候都是按 user_id
    或 credential_id 直接查，用不上关系加载。
    """
    __tablename__ = "passkey_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="持有人")
    # 浏览器那边的 rawId，base64url（无填充）。unique 保证同一把钥匙不会被重复登记
    credential_id = Column(String(500), unique=True, index=True, nullable=False, comment="凭据 ID（base64url）")
    # COSE 格式的公钥字节，验证签名时原样交给 webauthn 库
    public_key = Column(LargeBinary, nullable=False, comment="COSE 公钥")
    # 签名计数器：同步型通行密钥（iCloud / Google 钥匙串）通常一直是 0，
    # 只有两个都非零且不涨时才当成可疑，见 api/passkeys.py
    sign_count = Column(Integer, nullable=False, default=0, comment="签名计数器")
    # 浏览器报告的传输方式（usb / nfc / internal…），只做展示，不参与验证
    transports = Column(String(100), nullable=False, default="", comment="传输方式，逗号分隔")
    # 用户起的名字，例如「我的 iPhone」。空则由前端按时间显示
    label = Column(String(50), nullable=False, default="", comment="备注名")
    # 同步型（云钥匙串）还是单设备。只做展示：同步型的丢了手机还能从云里恢复
    backed_up = Column(Boolean, nullable=False, default=False, comment="是否同步到云端")
    # 用 Python 端时间而不是 CURRENT_TIMESTAMP：SQLite 那个是 UTC，会差 8 小时
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True, comment="创建时间")
    last_used_at = Column(DateTime, nullable=True, comment="最后一次用来登录的时间")
