from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CertificateRequestResponse(BaseModel):
    """证明申请响应体"""
    id: int
    student_id: int
    student_name: Optional[str] = None
    student_no: Optional[str] = None
    title: Optional[str] = None
    recipient: Optional[str] = None
    content: Optional[str] = None
    extra_request: Optional[str] = None
    attachments: list[dict] = Field(default_factory=list, description="附件列表 [{file, name, size}]")
    status: str = "pending"
    created_at: Optional[datetime] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    result_original_name: Optional[str] = None

    class Config:
        from_attributes = True


class CertificateRejectRequest(BaseModel):
    """驳回请求体"""
    reason: str = Field(..., min_length=1, max_length=500, description="驳回理由")
