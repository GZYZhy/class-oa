from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, text

from ..database import Base


class ResourceShareLink(Base):
    """资料下载外链

    一份资料可以被多人、多次分享，每次分享单独一条记录：有效期、下载次数、
    最近下载时间、吊销状态各算各的，互不影响。

    token 是随机串而不是「id + 签名」，因为签名方案没法按条吊销 ——
    换密钥等于把所有链接一起作废（见 share_service.py 的说明），
    而这里既要能单独吊销，也要统计每一条链接的下载次数，只能落库。

    字段口径对齐 access_tokens：expires_at 为 NULL 表示永久，
    revoked_at 非空即已失效，created_at 用 Python 端时间（SQLite 的
    CURRENT_TIMESTAMP 是 UTC，会比北京时间早 8 小时）。
    """

    __tablename__ = "resource_share_links"

    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(
        Integer, ForeignKey("resources.id"), nullable=False, index=True, comment="资料 ID"
    )
    token = Column(String(64), nullable=False, unique=True, index=True, comment="外链令牌")
    # 创建人快照：账号改名或被删之后，管理员仍然看得出是谁分享的
    created_by_no = Column(String(20), nullable=False, index=True, comment="创建人账号")
    created_by_name = Column(String(50), nullable=False, default="", comment="创建人姓名（快照）")
    expires_at = Column(DateTime, nullable=True, comment="失效时间，NULL 表示永久")
    revoked_at = Column(DateTime, nullable=True, comment="吊销时间，非空即失效")
    download_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="经由此链接的下载次数",
    )
    last_download_at = Column(DateTime, nullable=True, comment="最近一次下载时间")
    created_at = Column(DateTime, default=datetime.now, index=True, comment="创建时间")
