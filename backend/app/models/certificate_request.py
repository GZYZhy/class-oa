"""证明（介绍信）开具申请"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from ..database import Base


class CertificateRequest(Base):
    """证明/介绍信开具申请

    学生提交 → 管理员审批 → 通过后管理员上传成品 PDF。
    班委只读（可看申请和附件，不能下载成品 PDF）。
    """
    __tablename__ = "certificate_requests"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True, comment="申请时间")

    # 学生填写的内容
    title = Column(String(200), comment="证明标题")
    recipient = Column(String(200), comment="收文单位")
    content = Column(Text, comment="证明正文")
    extra_request = Column(Text, comment="其他要求")

    # 申请依据附件：[{"file": "存盘名", "name": "原始名", "size": 字节数}]
    # 用 TEXT 存 JSON，和 feedback 附件同模式
    attachments = Column(Text, default="", comment="附件列表（JSON，最多 3 个）")

    # 审核
    status = Column(
        String(20), default="pending", index=True,
        comment="pending/accepted/correcting/approved/rejected/revoked",
    )
    reviewer_no = Column(String(20), comment="审核人学号")
    reviewer_name = Column(String(50), comment="审核人姓名")
    reviewed_at = Column(DateTime, comment="审核时间")
    reject_reason = Column(Text, comment="驳回理由")
    # 退回补正的理由（受理后发现材料不对，打回让申请人补齐；申请人重交时清空）。
    # default="" 而不是留空：补列时给的是 NOT NULL DEFAULT ''，模型这边不跟上的话
    # 新记录是 NULL、老记录是空串，同一列两种「没有」，响应体里一会儿 null 一会儿 ""
    correction_reason = Column(Text, default="", comment="退回补正的理由")

    # 成品 PDF（管理员上传）
    result_file = Column(String(100), comment="成品 PDF 存盘名")
    result_original_name = Column(String(200), comment="成品 PDF 原始文件名")

    student = relationship("Student", backref="certificate_requests")
