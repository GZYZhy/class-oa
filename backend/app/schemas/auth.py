from typing import Optional

import re
from pydantic import BaseModel, Field, field_validator


# 自定义密码规则：必须同时包含数字和字母（初始密码/重置密码不受这个限制）
_PASSWORD_PATTERN = re.compile(r'^(?=.*[A-Za-z])(?=.*\d).+$')


def _validate_password(value: str, field_name: str = "新密码") -> str:
    if len(value) < 6 or len(value) > 32:
        raise ValueError(f"{field_name}长度需为 6-32 位")
    if not _PASSWORD_PATTERN.match(value):
        raise ValueError(f"{field_name}必须同时包含字母和数字")
    return value


class LoginRequest(BaseModel):
    """登录请求"""
    student_no: str = Field(..., description="学号")
    password: str = Field(..., description="密码")
    remember: bool = Field(False, description="是否保持登录 7 天")
    captcha: Optional[str] = Field(None, description="验证码答案（失败 1 次后必填）")


class ChangePasswordRequest(BaseModel):
    """主动修改密码：需要校验原密码"""
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=32)

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        return _validate_password(v, "新密码")


class SetInitialPasswordRequest(BaseModel):
    """首次登录设置密码：此时用的还是默认密码，无需再输一遍原密码"""
    new_password: str = Field(..., min_length=6, max_length=32)

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        return _validate_password(v, "新密码")


class BarkKeyRequest(BaseModel):
    """Bark 设备 key；传空串表示解除绑定"""
    bark_key: str = Field("", max_length=128)


class WebPushKeysRequest(BaseModel):
    """浏览器给的加密公钥：服务器用它们加密通知内容，只有那台浏览器解得开"""
    p256dh: str = Field(..., max_length=200)
    auth: str = Field(..., max_length=64)


class WebPushSubscribeRequest(BaseModel):
    """浏览器的订阅信息，字段形状与前端 sub.toJSON() 完全一致，前端不用做转换"""
    endpoint: str = Field(..., max_length=500)
    keys: WebPushKeysRequest

    @field_validator("endpoint")
    @classmethod
    def check_endpoint(cls, v: str) -> str:
        """只收 https 的推送服务地址

        这个地址之后会被服务器拿去发 POST，用户能自定义就等于给内网开了一个
        可以任意发 POST 的口子（SSRF）。正规推送服务（FCM/APNs/Mozilla/WNS）
        一律是 https，所以卡死协议这一条既拦得住绝大多数内网地址，
        又不会误伤正常用户。
        """
        if not v.startswith("https://"):
            raise ValueError("订阅地址必须是 https")
        return v


class WebPushUnsubscribeRequest(BaseModel):
    """解除一条订阅"""
    endpoint: str = Field(..., max_length=500)


class UserInfoResponse(BaseModel):
    """当前用户信息（姓名、头像均自动取自学生表，不含任何敏感字段）"""
    student_no: str
    name: str
    avatar: Optional[str] = None
    class_name: Optional[str] = None
    # 角色决定前端能看到哪些菜单：admin 管理员 / committee 班委 / student 普通学生
    role: str = "student"
    must_change_password: bool
    # Bark 推送设备 key，没开推送时为空。只返给本人（就是他在自己手机 App 首页看到的那串）
    bark_key: Optional[str] = None
