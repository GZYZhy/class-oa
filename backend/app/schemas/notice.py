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
    """通知响应

    is_read 不是数据库字段：由接口按当前登录的人现算（游客恒为 False）。
    """
    id: int
    title: str
    publisher: str
    publish_date: date
    content: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_read: bool = False

    class Config:
        from_attributes = True


class NoticeReadRow(BaseModel):
    """已读名单里的一行"""
    student_no: str
    name: str
    read_at: Optional[datetime] = None
    frozen: bool = False


class NoticeReadStatus(BaseModel):
    """一条通知的已读情况"""
    total: int          # 应读人数 = 全部账号
    read_count: int
    rows: list[NoticeReadRow]
