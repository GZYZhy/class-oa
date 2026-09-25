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
    status: str
    reviewer_name: Optional[str] = None
    reject_reason: str = ""
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LeaveRejectRequest(BaseModel):
    """驳回申请"""
    reason: str = Field(..., min_length=1, max_length=500, description="驳回理由")
