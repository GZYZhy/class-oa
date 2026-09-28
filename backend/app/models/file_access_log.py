from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Index

from ..database import Base


class FileAccessLog(Base):
    """文件访问日志：记录谁在什么时候查看/下载了哪个公开文件

    独立于 operation_logs，原因：
    1. operation_logs 的设计原则是「只记内容变更，不记查询」
    2. 查看是高频动作，混进去会把操作日志冲没
    3. 需要独立的筛选维度（按文件、按动作类型）
    4. 审计记录不应被「清空日志」操作抹掉
    """
    __tablename__ = "file_access_logs"

    id = Column(Integer, primary_key=True, index=True)
    # 用 Python 端时间而不是 func.now()：SQLite 的 CURRENT_TIMESTAMP 是 UTC，
    # 会比北京时间早 8 小时（容器和宿主机都已设 TZ=Asia/Shanghai）
    created_at = Column(DateTime, default=datetime.now, index=True, comment="访问时间")
    user_no = Column(String(20), index=True, comment="访问人学号")
    user_name = Column(String(50), comment="访问人姓名")
    file_id = Column(Integer, index=True, comment="文件 ID（announcement.id）")
    # 冗余存一份标题：文件被删了记录里也能看到是什么
    file_title = Column(String(200), comment="文件标题")
    action = Column(String(20), index=True, comment="动作：view / download")
    ip = Column(String(45), nullable=True, comment="客户端 IP")

    __table_args__ = (
        # 常用联合查询：按人 + 动作、按文件 + 动作
        Index("ix_file_access_user_action", "user_no", "action"),
        Index("ix_file_access_file_action", "file_id", "action"),
    )
