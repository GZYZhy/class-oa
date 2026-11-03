from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ArchiveViewRequestCreate(BaseModel):
    """班委提交：申请查看某个学生的完整档案"""
    student_id: int = Field(..., description="被查看档案的学生 ID")


class ArchiveViewRequestResponse(BaseModel):
    id: int
    student_id: int
    student_no: str
    student_name: str
    applicant_no: str
    applicant_name: str
    status: str
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewer_name: Optional[str] = None

    class Config:
        from_attributes = True


class ArchiveViewRequestListResponse(BaseModel):
    total: int
    items: list[ArchiveViewRequestResponse]


class ArchiveViewStatusResponse(BaseModel):
    """当前用户对某个学生的完整档案查看状态，给详情页那个按钮用

    status: none 没申请过（或被驳回）| pending 待审批 | approved 可看 | expired 已过期
    expires_at: 仅 approved 时有值
    """
    status: str
    expires_at: Optional[datetime] = None
