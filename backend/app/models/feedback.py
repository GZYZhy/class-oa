"""意见反馈模型"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime

from ..database import Base


class Feedback(Base):
    """学生意见反馈

    学生提交 → 班委查看 → 可标记已读、可回复。
    状态：unread / read / replied
    """
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)

    # 提交人
    student_id = Column(Integer, index=True, comment="学生 ID")
    student_no = Column(String(20), index=True, comment="学号")
    student_name = Column(String(50), comment="姓名")

    title = Column(String(100), comment="标题")
    content = Column(Text, comment="正文")

    # 状态：unread 未读 / read 已读 / replied 已回复
    status = Column(String(20), default="unread", index=True, comment="unread/read/replied")

    # 回复
    reply_content = Column(Text, default="", comment="回复内容")
    reply_name = Column(String(50), comment="回复人姓名")
    reply_no = Column(String(20), comment="回复人学号")
    reply_at = Column(DateTime, comment="回复时间")

    created_at = Column(DateTime, default=datetime.now, index=True, comment="提交时间")
