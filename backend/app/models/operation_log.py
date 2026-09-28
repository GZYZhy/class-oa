from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime

from ..database import Base


class OperationLog(Base):
    """操作日志：只记内容变更（发布/修改/删除、审核、重置密码、改角色、冻结），不记登录

    登录和「本人自行改密」在 account_events —— 那是高频事件，混进来会把
    这里的操作记录冲没；而且本表会被「清空日志」整体删掉，
    放一起等于清日志时把登录痕迹一起抹了。
    """
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
    # 批量操作时涉及的多个学号（JSON 数组字符串），
    # 用于反查「被操作记录」：一次导出涉及 33 人，这 33 个人的被操作记录都能查到这一条
    target_student_nos = Column(Text, default="", comment="批量操作涉及的学号（JSON 数组）")
