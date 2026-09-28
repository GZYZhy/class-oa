from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class AnnouncementResponse(BaseModel):
    """公告响应"""
    id: int
    title: str
    doc_number: Optional[str] = None
    publish_date: date
    file_path: str
    file_name: Optional[str] = None
    # 发布人由服务端注入；本次改动之前录入的老数据为空，前端显示为「-」
    publisher: Optional[str] = None
    # 是否向班委以外公开：False 时只有班委及以上能看到、查看这条文件
    is_public: bool = True
    # 在线查看次数。给默认值：老库刚补列时这一列还是 0
    view_count: int = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
