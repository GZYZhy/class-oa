from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime

from ..database import Base


class OperationLog(Base):
    """操作日志：只记内容变更（发布/修改/删除、审核、重置密码、改角色），不记登录"""
    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, index=True)
    # 用 Python 端时间而不是 func.now()：SQLite 的 CURRENT_TIMESTAMP 是 UTC，
    # 会比北京时间早 8 小时，日志时间就不对了（容器和宿主机都已设 TZ=Asia/Shanghai）
    created_at = Column(DateTime, default=datetime.now, index=True, comment="操作时间")
    operator_no = Column(String(20), index=True, comment="操作人学号")
    operator_name = Column(String(50), comment="操作人姓名")
    action = Column(String(50), comment="动作，如「发布通知」")
    target = Column(String(200), comment="操作对象，如通知标题")
    detail = Column(Text, comment="细节说明（如改了哪些字段）")
    ip = Column(String(45), nullable=True, comment="操作时的客户端 IP")
