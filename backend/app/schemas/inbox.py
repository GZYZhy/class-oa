"""站内信接口的出入参"""

from datetime import datetime

from pydantic import BaseModel


class InboxMessageResponse(BaseModel):
    """收件箱里的一条消息"""
    id: int
    title: str
    body: str = ""
    level: str = "active"
    page: str | None = None
    created_at: datetime
    read_at: datetime | None = None

    class Config:
        from_attributes = True


class InboxListResponse(BaseModel):
    """一页消息

    unread 是**全量**未读数，不是这一页里的未读数：前端拿它更新菜单红点，
    翻到第 3 页时也该显示总共还有多少条没看。
    """
    total: int
    page: int
    page_size: int
    unread: int
    items: list[InboxMessageResponse]
