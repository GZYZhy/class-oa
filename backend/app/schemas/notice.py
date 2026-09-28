import json
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class NoticeAttachment(BaseModel):
    """通知附件项"""
    index: int = 0   # 前端用的下标（下载时定位用），不是库字段
    file: str = ""   # 存盘名（UUID + 后缀）
    name: str = ""   # 原始文件名
    size: int = 0    # 字节数


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
    attachments: list[NoticeAttachment] = []
    editors: list[dict] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_read: bool = False

    @field_validator("editors", mode="after")
    @classmethod
    def fallback_editors(cls, v, info):
        """editors 为空时（老数据/老通知），用 publisher 补一条兜底

        升级前的老通知没有 editors 列，直接显示空会让用户觉得「发布人去哪了」。
        这里从 publisher 倒推一条，至少首发人能显示出来。
        """
        if not v:
            pub = info.data.get("publisher", "")
            if pub:
                return [{"no": "", "name": pub, "time": ""}]
        return v

    @field_validator("attachments", mode="before")
    @classmethod
    def parse_attachments(cls, v):
        """库里存的是 JSON 字符串，转成列表并补上 index（下载时按下标定位）"""
        if isinstance(v, list):
            return v
        if isinstance(v, str) and v.strip():
            try:
                items = json.loads(v)
                for i, item in enumerate(items):
                    item["index"] = i
                return items
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    @field_validator("editors", mode="before")
    @classmethod
    def parse_editors(cls, v):
        """库里存的是 JSON 字符串，转成列表；空或非法返回空列表"""
        if isinstance(v, list):
            return v
        if isinstance(v, str) and v.strip():
            try:
                items = json.loads(v)
                return items if isinstance(items, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return []

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
