"""签字图查看申请：班委申请 → 管理员审批 → 批准后一小时内本人可看

为什么单开一张表，不复用 change_requests：那条链路改的是**学生自己的**信息，
申请人就是学生本人；这条是**一个班委要看另一个学生的签字**，申请人和被看的对象
是两个人，判定权限时两个都要对上。塞进同一张表，「谁在申请」就有了两个含义。

**有效期不存字段**：授权时长是写死的 1 小时，判定时用 reviewed_at 现算（见
api/sign_photos.py 的 SIGN_VIEW_TTL）。存一份 expires_at 等于把同一个事实记两遍，
还会和 reviewed_at 走散。（对照 ban_service 的 expires_at 是存字段 —— 那里时长
由管理员输入、不固定，非存不可。）
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, text

from ..database import Base


class SignPhotoRequest(Base):
    __tablename__ = "sign_photo_requests"

    id = Column(Integer, primary_key=True, index=True)

    student_id = Column(Integer, nullable=False, index=True, comment="被查看签字的学生主键")
    # 姓名学号快照：学生被删掉之后，这条审批记录还读得出当时看的是谁
    student_no = Column(String(20), nullable=False, comment="学生学号（快照）")
    student_name = Column(String(50), nullable=False, comment="学生姓名（快照）")

    applicant_no = Column(
        String(20), nullable=False, index=True, comment="申请人学号（只有这个人能看图）",
    )
    applicant_name = Column(String(50), nullable=False, comment="申请人姓名")

    status = Column(
        String(20), nullable=False, default="pending", server_default=text("'pending'"),
        index=True, comment="pending 待审批 | approved 已通过 | rejected 已驳回",
    )
    reason = Column(String(200), comment="驳回理由")

    # Python 端时间，理由同 operation_log.created_at（SQLite 的 CURRENT_TIMESTAMP 是 UTC）
    created_at = Column(DateTime, default=datetime.now, comment="申请时间")
    reviewed_at = Column(DateTime, comment="审批时间")
    reviewer_no = Column(String(20), comment="审批人学号")
    reviewer_name = Column(String(50), comment="审批人姓名")
