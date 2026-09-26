from typing import Optional

from pydantic import BaseModel, Field, field_validator

# 密码规则统一定义在 utils.security，管理员设域外账号密码时也用同一份
from ..utils.security import validate_password


class LoginRequest(BaseModel):
    """登录请求"""
    student_no: str = Field(..., description="学号")
    password: str = Field(..., description="密码")
    remember: bool = Field(False, description="是否保持登录 7 天")
    captcha: Optional[str] = Field(None, description="算术验证码的答案（失败 1 次后必填）")
    # 人机验证有两套，靠「哪个字段有值」区分，不做格式嗅探：
    # 配了 Turnstile 且控件正常 → 填 turnstile_token；没配、或浏览器加载不出控件
    # 而退回算术题 → 填上面的 captcha。两条路后端都认，见 api/auth.py 的登录接口
    turnstile_token: Optional[str] = Field(None, description="Turnstile 控件给的 token")


class ChangePasswordRequest(BaseModel):
    """主动修改密码：需要校验原密码"""
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=32)

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        return validate_password(v, "新密码")


class SetInitialPasswordRequest(BaseModel):
    """首次登录设置密码：此时用的还是默认密码，无需再输一遍原密码"""
    new_password: str = Field(..., min_length=6, max_length=32)

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        return validate_password(v, "新密码")


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
    """当前用户信息（不含任何敏感字段）

    姓名、头像的取法：域外账号用 users 表上的展示名/头像，
    学生账号仍实时取自学生表（改了名字各处能跟着变）。
    """
    # 学生账号是学号；域外账号是管理员指定的登录名
    student_no: str
    name: str
    avatar: Optional[str] = None
    class_name: Optional[str] = None
    # 角色决定前端能看到哪些菜单：admin 管理员 / committee 班委 / student 普通学生
    role: str = "student"
    must_change_password: bool
    # 域外账号：前端据此隐藏「我的信息」「办事中心」等绑定学生身份的入口
    is_external: bool = False
    # Bark 推送设备 key，没开推送时为空。只返给本人（就是他在自己手机 App 首页看到的那串）
    bark_key: Optional[str] = None
