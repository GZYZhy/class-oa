from sqlalchemy import Boolean, Column, Integer, String, Date, DateTime, func, text

from ..database import Base


class Announcement(Base):
    """文件公告表"""
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, comment="文件标题")
    doc_number = Column(String(100), comment="文号")
    publish_date = Column(Date, nullable=False, index=True, comment="发布时间")
    file_path = Column(String(300), nullable=False, comment="PDF 文件路径")
    file_name = Column(String(200), comment="原始文件名")
    # 发布人由服务端按登录账号注入，前端不可伪造；老数据为空
    publisher = Column(String(50), default="", server_default=text("''"), comment="发布人姓名")
    # 是否向班委以外公开：1=全班（登录用户）可见，0=仅班委及以上可见。
    # 默认公开 —— 本字段上线前录入的文件维持原有行为（所有登录用户都能看）
    is_public = Column(
        Boolean, nullable=False, default=True, server_default=text("1"),
        comment="是否向班委以外公开",
    )
    created_at = Column(DateTime, server_default=func.now(), comment="录入时间")
