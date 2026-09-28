"""电动车通行证补办 schema"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# 提交接口是 multipart（brand / plate_number / license_file 一起传），
# 参数在 api/ev_passes.py 里用 Form/File 声明，所以这里没有 Create schema


class EvPassRequestResponse(BaseModel):
    """申请记录响应"""
    id: int
    student_id: int
    student_name: Optional[str] = None
    student_no: Optional[str] = None
    brand: Optional[str] = None
    plate_number: Optional[str] = None
    license_original_name: Optional[str] = None
    status: Optional[str] = None  # pending / approved / rejected
    created_at: Optional[datetime] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reject_reason: Optional[str] = None

    class Config:
        from_attributes = True


class EvPassRejectRequest(BaseModel):
    """驳回申请"""
    reason: str = Field(..., min_length=1, max_length=500, description="驳回理由")
