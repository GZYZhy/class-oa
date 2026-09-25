"""意见反馈 schema"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    """学生提交反馈"""
    title: str = Field(..., min_length=1, max_length=100, description="标题")
    content: str = Field(..., min_length=1, max_length=5000, description="正文")


class FeedbackReply(BaseModel):
    """班委回复"""
    content: str = Field(..., min_length=1, max_length=2000, description="回复内容")


class FeedbackResponse(BaseModel):
    """反馈详情"""
    id: int
    student_id: int
    student_no: str
    student_name: str
    title: str
    content: str
    status: str  # unread / read / replied
    reply_content: Optional[str] = None
    reply_name: Optional[str] = None
    reply_no: Optional[str] = None
    reply_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
