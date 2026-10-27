"""资料分享外链的请求/响应结构

资料清单本身一直走 dict（见 resource_service.list_resources），这里只给
「创建外链」和「外链落地页」这两处加类型：前者要校验有效期，后者是公开接口，
字段必须明确到「能吐什么、不能吐什么」。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ResourceShareCreate(BaseModel):
    """创建外链：分享人只选有效期"""

    days: int = Field(7, description="有效期天数：1 / 7 / 30，0 表示永久")


class ResourceShareCreated(BaseModel):
    """创建成功后给分享人的链接信息"""

    token: str
    path: str
    url: str
    expires_at: datetime | None = None
    created_at: datetime


class ResourceShareInfo(BaseModel):
    """外链落地页要的数据

    刻意不带磁盘文件名、创建人、内部 ID：外链是给游客看的，
    只该知道「这是什么材料、多大、还能下多久」。
    """

    valid: bool
    """链接当前是否可用"""
    reason: str = ""
    """不可用原因：expired / revoked / missing，valid=True 时为空"""
    resource_name: str = ""
    category: str = ""
    file_ext: str = ""
    size: int = 0
    download_name: str = ""
    """存盘用的文件名（展示名 + 扩展名），和站内下载同一口径"""
    expires_at: datetime | None = None
    created_at: datetime | None = None
    download_url: str = ""
