from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, text

from ..database import Base


class ChangeRequest(Base):
    """学生信息修改申请：学生提交 → 班委审核 → 通过后才写入学生表

    `changes` 存 JSON 串（如 {"qq": "12345", "email": "a@b.c"}），只允许白名单字段。
    """
    __tablename__ = "change_requests"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, nullable=False, index=True, comment="学生表主键")
    student_no = Column(String(20), nullable=False, comment="申请人学号")
    student_name = Column(String(50), nullable=False, comment="申请人姓名")
    changes = Column(Text, nullable=False, comment="申请修改的内容（JSON）")
    status = Column(
        String(20), nullable=False, default="pending", server_default=text("'pending'"),
        index=True, comment="pending 待审核 | approved 已通过 | rejected 已驳回",
    )
    reason = Column(String(200), comment="驳回理由")
    # Python 端时间，理由同 operation_log.created_at（SQLite 的 CURRENT_TIMESTAMP 是 UTC）
    created_at = Column(DateTime, default=datetime.now, comment="提交时间")
    reviewed_at = Column(DateTime, comment="审核时间")
    reviewer_no = Column(String(20), comment="审核人学号")
    reviewer_name = Column(String(50), comment="审核人姓名")
