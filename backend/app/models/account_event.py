from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from ..database import Base


class AccountEvent(Base):
    """账号事件：本人登录、改密，以及账号安全设置的变化
    （访问令牌、通行密钥、二次验证、恢复码）

    单独一张表，不并进 operation_logs：
    - operation_logs 的定位是「内容变更」，登录是每天几十条的高频事件，
      混进去会把真正的操作记录冲没
    - 「清空日志」只清 operation_logs，不会连登录记录一起抹掉
    - 前端「按账号查日志」里这两块的展示口径也不同（操作日志看全部，
      登录/改密只看最近 7 天）

    只记成功的事件，不记登录失败 —— 管理员不该看到别人拿错密码试的 IP。

    本表**只增不删**，查询窗口（7 天）是查的时候限的，不是往里写的时候限的。
    """
    __tablename__ = "account_events"

    id = Column(Integer, primary_key=True, index=True)
    # 用 Python 端时间而不是 func.now()：SQLite 的 CURRENT_TIMESTAMP 是 UTC，
    # 会比北京时间早 8 小时（同 operation_logs.created_at）
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True, comment="事件时间")
    student_no = Column(String(20), nullable=False, index=True, comment="账号（学号 / 域外账号登录名）")
    # 事件名全是英文、最长 20 字符（recovery_regenerate 已经 19 个）
    event = Column(String(20), nullable=False,
                   comment="login|change_password|token_create|token_revoke|"
                           "passkey_add|passkey_delete|two_factor_enable|"
                           "two_factor_disable|recovery_regenerate")
    ip = Column(String(45), nullable=True, comment="事件发生时的客户端 IP")
