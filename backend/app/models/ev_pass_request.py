"""电动车通行证补办申请"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from ..database import Base


class EvPassRequest(Base):
    """电动车校内通行证补办申请

    复用请假申请的架构：学生提交 → 管理员审批 → 通过后生成通行证和承诺书两份 PDF。
    住址、毕业时间、专业年级这些全班一样的项不存库 —— 它们在 EV_PASS_* 配置里，
    生成 PDF 时由 utils/ev_pass_pdf.py 填上。
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
    status = Column(
        String(20), default="pending", index=True,
        comment="pending/accepted/correcting/approved/rejected",
    )
    reviewer_no = Column(String(20), comment="审核人学号")
    reviewer_name = Column(String(50), comment="审核人姓名")
    reviewed_at = Column(DateTime, comment="审核时间")
    reject_reason = Column(Text, comment="驳回理由")
    # 退回补正的理由（受理后发现材料不对，打回让申请人补齐；申请人重交时清空）。
    # default="" 而不是留空：补列时给的是 NOT NULL DEFAULT ''，模型这边不跟上的话
    # 新记录是 NULL、老记录是空串，同一列两种「没有」，响应体里一会儿 null 一会儿 ""
    correction_reason = Column(Text, default="", comment="退回补正的理由")

    # 经办班委签字。申请表的落款与日期之间那一行 —— 管理员**批准时**选一位管理员
    # （或「暂不签署」），取的是当时那张图的**副本**，落在 data/ev_passes/ 下。
    # 原图日后换了、删了都不影响已经批出去的单子，三列全空就是没签（见 services/signer_service.py）
    sign_no = Column(String(20), default="", comment="经办班委签字人登录名（快照）")
    sign_name = Column(String(50), default="", comment="经办班委签字人姓名（快照）")
    sign_file = Column(String(100), default="", comment="签字图副本名（存在 EV_PASS_DIR，非空即已签）")

    student = relationship("Student", backref="ev_pass_requests")
