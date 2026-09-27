"""意见反馈 schema"""

import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class FeedbackAttachment(BaseModel):
    """反馈附件

    index 是下载用的下标，显式写进每一项：前端就不必靠列表顺序去猜，
    将来 UI 上加排序或过滤也不会静默下错文件。
    """
    index: int = Field(..., description="下载用下标（对应 /attachments/{index}）")
    name: str = Field(..., description="原始文件名（下载时显示）")
    size: int = Field(..., description="字节数")


class FeedbackReply(BaseModel):
    """班委回复"""
    content: str = Field(..., min_length=1, max_length=2000, description="回复内容")


class FeedbackResponse(BaseModel):
    """反馈详情

    提交反馈的入参不用 schema（走 multipart 的 Form），所以这里没有 Create。
    """
    id: int
    student_id: int
    student_no: str
    student_name: str
    title: str
    content: str
    status: str  # unread / read / replied
    attachments: list[FeedbackAttachment] = []
    reply_content: Optional[str] = None
    reply_name: Optional[str] = None
    reply_no: Optional[str] = None
    reply_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @field_validator("attachments", mode="before")
    @classmethod
    def parse_attachments(cls, v: Any) -> Any:
        """库里存的是 JSON 串，出参转成带 index 的列表

        解析失败返回空列表而不是抛异常：反馈列表接口一次返回全部记录，
        一行脏数据不该让整个列表跟着 500。
        """
        if v is None:
            return []
        if not isinstance(v, str):
            return v
        if not v.strip():
            return []
        try:
            items = json.loads(v)
        except (ValueError, TypeError):
            return []
        if not isinstance(items, list):
            return []
        return [
            {"index": i, "name": item.get("name", ""), "size": item.get("size") or 0}
            for i, item in enumerate(items)
            if isinstance(item, dict)
        ]
