from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from ..database import Base


class IpBan(Base):
    """IP 封禁：一个封禁目标一行，**只存生效中的**，解封就是删行

    为什么单独一张表而不是塞进 operation_logs：
    - operation_logs 的定位是「内容变更 + 有人主动做出的动作」，自动封禁两者都不是
      （见 services/log_service.py 开头）。分开之后「清空日志」也不会把安全记录一起抹掉。
    - 封禁要能查、要能手解，需要一张可读可写的当前状态表，日志是只增不删的流水。

    自动封禁（登录失败触发）和手动封禁（管理员点的）共用这张表，
    用 is_manual 区分：自动的是 False，管理员插手过的是 True。
    """
    __tablename__ = "ip_bans"

    id = Column(Integer, primary_key=True, index=True)
    # 存**归一化之后**的单个 IP 或 CIDR 网段（1.2.3.4/24 会先被归成 1.2.3.0/24）。
    # 列名不叫 ip 是因为它可能是个网段，叫 ip 是撒谎；target 也和 OperationLog.target 措辞一致。
    # 45 位容得下 ::ffff:255.255.255.255 这种最长的形式。
    target = Column(String(45), unique=True, index=True, nullable=False,
                    comment="被封的 IP 或 CIDR 网段（已归一化）")
    reason = Column(String(200), comment="封禁原因")
    # 「有没有管理员插手」：管理员手动封的、或把自动封禁延长过的，都是 True
    is_manual = Column(Boolean, default=False, nullable=False, comment="是否管理员手动封禁")
    # 用 Python 端时间而不是 func.now()：SQLite 的 CURRENT_TIMESTAMP 是 UTC，
    # 会比北京时间早 8 小时（同 operation_logs.created_at）
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True, comment="封禁时间")
    # NULL = 永久封禁
    expires_at = Column(DateTime, nullable=True, index=True, comment="解封时间，NULL 表示永久")
    operator_no = Column(String(20), nullable=True, comment="封禁操作人学号（自动封禁为空）")
    operator_name = Column(String(50), nullable=True, comment="封禁操作人姓名（自动封禁为空）")
