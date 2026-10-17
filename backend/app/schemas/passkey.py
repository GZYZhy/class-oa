from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PasskeyRegisterOptionsRequest(BaseModel):
    """开始登记一把通行密钥

    要密码：登录态本身可能是别人借你电脑后留下的，重输一次密码能确认「是本人要加」，
    否则同学借一次登录就能给自己塞一把长期钥匙。
    """
    password: str
    label: str = Field("", max_length=50, description="备注名，例如「我的 iPhone」")


class PasskeyRegisterVerifyRequest(PasskeyRegisterOptionsRequest):
    # 浏览器 navigator.credentials.create() 的结果，已转成 JSON 可传的形状
    credential: dict


class PasskeyLoginOptionsRequest(BaseModel):
    """用通行密钥登录：**不再需要学号**

    登记时要求的是「可发现凭据」（resident key），钥匙里带着账号；登录时
    浏览器会列出本机上属于本站的钥匙，服务器在验证那一步按凭据 ID 反查持有人。
    """
    remember: bool = Field(True, description="是否保持登录 7 天")


class PasskeyLoginVerifyRequest(PasskeyLoginOptionsRequest):
    credential: dict


class PasskeyResponse(BaseModel):
    """列表里的一把通行密钥。**不含公钥**：前端用不上，也不该往外发"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    backed_up: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None


class PasskeyListResponse(BaseModel):
    items: list[PasskeyResponse]
    max_count: int
