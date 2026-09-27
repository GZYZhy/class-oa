"""通知已读记录

一人一条通知一行。为什么不像意见反馈那样在 notices 表上放一个 status 字段：
反馈的「已读」是**整条记录的全局状态**（一个班委读了，所有人都显示已读），
而通知要回答的是「这条通知谁还没看」，必须按人存。

用学号而不是 user_id 做关联，和 PushSubscription 同一个理由：
数据重置脚本会重建账号，重建之后学号仍然对得上。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from ..database import Base


class NoticeRead(Base):
    """通知已读记录"""
    __tablename__ = "notice_reads"

    id = Column(Integer, primary_key=True, index=True)
    notice_id = Column(Integer, index=True, nullable=False, comment="通知 id")
    student_no = Column(String(20), index=True, nullable=False, comment="读过的账号（学号）")
    # 用 datetime.now（北京时间）而不是 func.now()：SQLite 的 CURRENT_TIMESTAMP 是 UTC，会差 8 小时
    read_at = Column(DateTime, default=datetime.now, comment="首次打开的时间")

    # 展开/收起通知会重复触发标记，靠这条唯一约束兜底，不指望前端只调一次
    __table_args__ = (
        UniqueConstraint("notice_id", "student_no", name="uq_notice_read"),
    )
