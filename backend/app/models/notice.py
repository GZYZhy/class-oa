from sqlalchemy import Column, Integer, String, Date, DateTime, Text, func

from ..database import Base


class Notice(Base):
    """通知公告表（站内信式，支持 Markdown 正文）"""
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, comment="标题")
    publisher = Column(String(50), nullable=False, comment="首发人")
    # 编辑人列表，JSON 串：[{"no":"学号","name":"姓名","time":"YYYY-MM-DD HH:MM"}, ...]
    # 首发人也算第一个；顺序即参与顺序，同一个人多次编辑只保留最新一次。
    editors = Column(Text, default="", comment="参与发布/编辑的人（JSON）")
    publish_date = Column(Date, nullable=False, index=True, comment="发布时间")
    content = Column(Text, nullable=False, comment="正文（Markdown）")
    # 附件列表，JSON 字符串（参考 feedbacks.attachments 的模式）。
    # 格式：[{"file": "uuid名", "name": "原始名", "size": 12345}, ...]
    attachments = Column(Text, default="", comment="附件列表（JSON）")
    created_at = Column(DateTime, server_default=func.now(), comment="录入时间")
    updated_at = Column(DateTime, nullable=True, comment="最后编辑时间")
