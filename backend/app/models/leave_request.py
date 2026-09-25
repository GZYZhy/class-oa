"""请假申请模型"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime

from ..database import Base


class LeaveRequest(Base):
    """学生请假申请

    学生提交 → 管理员审核 → 通过后可生成 Word 请假表下载。
    状态：pending / approved / rejected
    """
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)

    # 申请人
    student_id = Column(Integer, index=True, comment="学生 ID")
    student_no = Column(String(20), index=True, comment="学号")
    student_name = Column(String(50), comment="姓名")

    # 请假信息
    leave_type = Column(String(20), comment="病假/事假/公假")
    # 起止时间精确到「时」（对应模板「年 月 日 时」）
    start_at = Column(DateTime, comment="开始时间（精确到小时）")
    end_at = Column(DateTime, comment="结束时间（精确到小时）")
    reason = Column(Text, comment="请假事由")
    travel_mode = Column(String(50), default="", comment="出行方式")
    travel_detail = Column(String(200), default="", comment="行程（车次等）")
    destination = Column(String(200), default="", comment="去向地址")
    destination_phone = Column(String(20), default="", comment="去向联系电话")

    # 辅助证明文件（存在 data/leaves/ 下，存文件名）
    proof_file = Column(String(100), comment="辅助证明文件名（UUID 前缀）")
    proof_original_name = Column(String(200), comment="辅助证明原始文件名")

    # 审核
    status = Column(String(20), default="pending", index=True, comment="pending/approved/rejected")
    reviewer_name = Column(String(50), comment="审核人姓名")
    reviewer_no = Column(String(20), comment="审核人学号")
    reject_reason = Column(String(500), default="", comment="驳回理由")
    reviewed_at = Column(DateTime, comment="审核时间")

    # 申请时间
    created_at = Column(DateTime, default=datetime.now, index=True, comment="申请时间")
