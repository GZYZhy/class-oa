"""电动车通行证补办申请"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from ..database import Base


class EvPassRequest(Base):
    """电动车校内通行证补办申请

    复用请假申请的架构：学生提交 → 管理员审批 → 通过后生成通行证和承诺书两份文档。
    住址固定为「示例公寓」、毕业时间固定为「2030年6月」，不存库，生成文档时直接填。
    """
    __tablename__ = "ev_pass_requests"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True, comment="申请时间")

    # 学生填写的内容
    brand = Column(String(100), comment="电动车品牌")
    plate_number = Column(String(50), comment="车牌号")

    # 行驶证证明材料（图片或 PDF，和请假证明一样的模式）
    license_file = Column(String(100), comment="行驶证文件存盘名（UUID 前缀）")
    license_original_name = Column(String(200), comment="行驶证原始文件名")

    # 审核
    status = Column(String(20), default="pending", index=True, comment="pending/approved/rejected")
    reviewer_no = Column(String(20), comment="审核人学号")
    reviewer_name = Column(String(50), comment="审核人姓名")
    reviewed_at = Column(DateTime, comment="审核时间")
    reject_reason = Column(Text, comment="驳回理由")

    student = relationship("Student", backref="ev_pass_requests")
