from sqlalchemy import Column, Integer, String, Date, DateTime, Text, func

from ..database import Base


class Notice(Base):
    """通知公告表（站内信式，支持 Markdown 正文）"""
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, comment="标题")
    publisher = Column(String(50), nullable=False, comment="发布人")
    publish_date = Column(Date, nullable=False, index=True, comment="发布时间")
    content = Column(Text, nullable=False, comment="正文（Markdown）")
    created_at = Column(DateTime, server_default=func.now(), comment="录入时间")
    updated_at = Column(DateTime, nullable=True, comment="最后编辑时间")
