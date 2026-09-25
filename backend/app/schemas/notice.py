from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class NoticeCreate(BaseModel):
    """新建/编辑通知

    不含 publisher：发布人由服务端按登录账号注入，前端传什么都不作数。
    """
    title: str = Field(..., max_length=200)
    publish_date: date
    content: str


class NoticeResponse(BaseModel):
    """通知响应"""
    id: int
    title: str
    publisher: str
    publish_date: date
    content: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
