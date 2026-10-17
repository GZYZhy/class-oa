"""请假申请相关 schema"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LeaveRequestCreate(BaseModel):
    """学生提交请假申请"""
    leave_type: str = Field(..., description="病假/事假/公假")
    start_at: datetime
    end_at: datetime
    reason: str = Field(..., min_length=1, max_length=2000, description="请假事由")
    travel_mode: str = Field("", max_length=50, description="出行方式")
    travel_detail: str = Field("", max_length=200, description="行程（车次等）")
    destination: str = Field("", max_length=200, description="去向地址")
    destination_phone: str = Field("", max_length=20, description="去向联系电话")


class LeaveRequestResponse(BaseModel):
    """请假申请详情（列表和详情共用）"""
    id: int
    student_id: int
    student_no: str
    student_name: str
    leave_type: str
    start_at: datetime
    end_at: datetime
    reason: str
    travel_mode: str = ""
    travel_detail: str = ""
    destination: str = ""
    destination_phone: str = ""
    proof_original_name: Optional[str] = None
    status: str = Field(
        ...,
        description="pending 待受理 / accepted 已受理 / correcting 待补正 / approved 已通过 / "
                    "rejected 已驳回 / revoked 已撤销（终态）",
    )
    reviewer_name: Optional[str] = None
    reject_reason: str = ""
    # 退回补正的理由（受理后发现材料不对）。和 reject_reason 不是一回事：补正是
    # 「补齐了还能批」，驳回是「这件事不批了」，所以申请人看到的提示也不同
    correction_reason: str = ""
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    # 班导师意见与签字：批准时填（意见选填、签字可以「暂不签字」）
    advisor_opinion: str = ""
    advisor_sign_no: str = ""
    advisor_sign_name: str = ""
    # 派生：签没签字。签字图**副本的文件名**本身不进响应 —— 前端只需要
    # 知道「已由张三签字」/「暂不签字」，拿不到副本名也就拼不出别的下载地址
    has_advisor_sign: bool = False

    class Config:
        from_attributes = True


class LeaveRejectRequest(BaseModel):
    """驳回申请"""
    reason: str = Field(..., min_length=1, max_length=500, description="驳回理由")


class LeaveCorrectRequest(BaseModel):
    """退回补正：受理后发现材料不对，打回让申请人补齐

    和驳回不是一回事（补齐了还能批），所以理由另收一份、另存一列，申请人也分得清
    自己是被驳回了还是被打回去改。
    """
    reason: str = Field(..., min_length=1, max_length=500, description="要补什么材料")


class LeaveAdvisorSignature(BaseModel):
    """班导师意见 + 用谁的签字（批准时收一次，之后补签字时再收一次）

    两个字段都可空：意见选填，签字人留空就是「暂不签字」。
    200 字这个上限是排版算出来的，不是随手定的 —— 行 9 的内宽在 12pt 下约 28 字一行，
    200 字 8 行刚好在页面余量里，再长那张表就要翻页（请假表翻页等于半张表加
    三行备注孤零零留在第二页）。改这里之前先跑 tests/test_leave_template.py
    """
    advisor_opinion: str = Field("", max_length=200, description="班导师意见（选填）")
    advisor_sign_no: str = Field("", description="签字人的登录名，空串 = 暂不签字")
