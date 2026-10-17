"""请假申请模型"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime

from ..database import Base


class LeaveRequest(Base):
    """学生请假申请

    学生提交 → 管理员审核（批准时可填班导师意见并选谁的签字）→ 申请人本人和
    管理员都能下载生成好的 PDF 请假审批表（带不可见溯源水印）。
    状态：pending（待受理）/ accepted（已受理）/ correcting（待补正）/ approved / rejected /
    revoked（已撤销：管理员把已通过的单子撤了，终态、不可恢复）
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
    status = Column(
        String(20), default="pending", index=True,
        comment="pending/accepted/correcting/approved/rejected/revoked",
    )
    reviewer_name = Column(String(50), comment="审核人姓名")
    reviewer_no = Column(String(20), comment="审核人学号")
    reject_reason = Column(String(500), default="", comment="驳回理由")
    reviewed_at = Column(DateTime, comment="审核时间")
    # 退回补正的理由：受理后发现材料不对，打回让申请人补齐。它和「驳回」不是一回事
    # （驳回是这件事不批了，补正是补了还能批），所以另起一列，申请人重交时清空
    correction_reason = Column(String(500), default="", comment="退回补正的理由")

    # 班导师意见与签字（批准时填；意见选填、签字可以「暂不签字」）
    advisor_opinion = Column(String(200), default="", comment="班导师意见（批准时填，可空）")
    # 签字人存快照：登录名 + 姓名 + 签字图**副本**的文件名（副本存在 data/leaves/ 下）。
    # 存副本而不是存原图名，是为了「用批准当时那张」这句承诺站得住 —— 原图被换掉或删掉时，
    # 历史单据不能静默掉签字（换图/删图接口是有的）
    advisor_sign_no = Column(String(20), default="", comment="班导师签字人登录名（快照）")
    advisor_sign_name = Column(String(50), default="", comment="班导师签字人姓名（快照）")
    advisor_sign_file = Column(String(100), default="", comment="班导师签字图副本名（非空即已签）")

    # 申请时间
    created_at = Column(DateTime, default=datetime.now, index=True, comment="申请时间")
