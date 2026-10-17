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
    # pending 待受理 / accepted 已受理 / correcting 待补正 / approved 已通过 / rejected 已驳回 / revoked 已撤销
    status: str = "pending"
    created_at: Optional[datetime] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    # 退回补正的理由（受理后发现材料不对）。和 reject_reason 不是一回事：补正是
    # 「补齐了还能批」，驳回是「这件事不批了」
    correction_reason: Optional[str] = None
    result_original_name: Optional[str] = None

    class Config:
        from_attributes = True


class CertificateRejectRequest(BaseModel):
    """驳回请求体"""
    reason: str = Field(..., min_length=1, max_length=500, description="驳回理由")


class CertificateCorrectRequest(BaseModel):
    """退回补正：受理后发现材料不对，打回让申请人补齐（和驳回不是一回事）"""
    reason: str = Field(..., min_length=1, max_length=500, description="要补什么材料")
