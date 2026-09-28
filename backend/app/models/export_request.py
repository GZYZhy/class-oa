"""学生信息导出申请模型

复用请假/通行证的审批架构：
班委提交 → 管理员审核 → 通过后生成文件 → 申请人下载。

状态：pending / approved / rejected / generated / failed
- pending: 已提交，等待审核
- approved: 审核通过（= generated，已生成文件，保留 approved 是为了和其他审批流程视觉统一）
- rejected: 审核驳回
- generated: 文件已生成（通过时同步生成，所以 approved 后直接变 generated）
- failed: 生成失败
"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime

from ..database import Base


class ExportRequest(Base):
    __tablename__ = "export_requests"

    id = Column(Integer, primary_key=True, index=True)

    # 申请人
    student_id = Column(Integer, index=True, comment="申请人学生 ID")
    student_no = Column(String(20), index=True, comment="申请人学号")
    student_name = Column(String(50), comment="申请人姓名")

    # 导出类型：excel_list（名单 Excel）/ pdf_individual（个人信息表 PDF）
    export_type = Column(String(20), index=True, comment="导出类型")

    # 范围类型：all / filtered / selected / id_range
    scope_type = Column(String(20), comment="学生范围类型")
    # JSON 字符串：筛选条件 / 选中的 ID 列表 / 学号范围
    scope_param = Column(Text, default="", comment="范围参数（JSON）")

    # 选中的字段列表（JSON 字符串数组），Excel 导出用；PDF 导出忽略（全信息）
    fields = Column(Text, default="", comment="导出字段（JSON）")

    # 生成的文件
    file_name = Column(String(200), default="", comment="生成文件名（存 data/exports/）")
    file_original_name = Column(String(200), default="", comment="展示用文件名")

    # 审核
    status = Column(String(20), default="pending", index=True, comment="pending/approved/rejected/generated/failed")
    reviewer_name = Column(String(50), default="", comment="审核人姓名")
    reviewer_no = Column(String(20), default="", comment="审核人学号")
    reject_reason = Column(String(500), default="", comment="驳回理由")
    reviewed_at = Column(DateTime, comment="审核时间")
    error_msg = Column(String(500), default="", comment="生成失败时的错误信息")

    created_at = Column(DateTime, default=datetime.now, index=True, comment="申请时间")
