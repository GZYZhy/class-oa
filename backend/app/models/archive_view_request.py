"""完整档案查看申请：班委申请 → 管理员审批 → 批准后一小时内可看敏感字段

和签字图申请（SignPhotoRequest）是两条平行链路，不共用表：

- 签字申请看的是**一张图**，批准后走 /api/sign-photos/image 取图；
- 档案申请看的是**学生详情里的敏感字段**，批准后由 /api/students/{id} 放开裁剪。

两边的有效期都是 1 小时，但一个授权的是文件、一个授权的是接口字段，
塞进同一张表只会让「这条批准到底放开了什么」变得含糊。
审批界面和交互则沿用签字那一套（申请 / 待审核 / 已通过 / 已驳回 / 过期重申请）。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, text

from ..database import Base


class ArchiveViewRequest(Base):
    __tablename__ = "archive_view_requests"

    id = Column(Integer, primary_key=True, index=True)

    student_id = Column(Integer, nullable=False, index=True, comment="被查看档案的学生主键")
    # 姓名学号快照：学生被删掉之后，这条审批记录还读得出当时看的是谁
    student_no = Column(String(20), nullable=False, comment="学生学号（快照）")
    student_name = Column(String(50), nullable=False, comment="学生姓名（快照）")

    applicant_no = Column(
        String(20), nullable=False, index=True, comment="申请人学号（只有这个人能看完整档案）",
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
