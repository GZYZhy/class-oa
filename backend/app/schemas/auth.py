from datetime import datetime
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


class AccessTokenCreate(BaseModel):
    """创建访问令牌。

    要再输一遍登录密码：令牌是「长期」凭据，而登录态是「临时」的 ——
    同学借你已登录的电脑点一下，本来只能用那一次；免密创建令牌就能给自己留把长期钥匙。
    """
    name: str = Field(..., max_length=50, description="备注名，用来区分这把令牌是干嘛的")
    days: int = Field(90, description="有效期天数：30 / 90 / 365，0 表示不限期")
    password: str = Field(..., description="登录密码，二次确认用")

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("请填写备注名")
        return v

    @field_validator("days")
    @classmethod
    def check_days(cls, v: int) -> int:
        # 只认这几档。不校验的话前端能传个 7 天出来，
        # 而页面上根本没有这个选项，出了问题无从解释
        if v not in (0, 30, 90, 365):
            raise ValueError("有效期只能是 30 天、90 天、1 年或不限期")
        return v


class AccessTokenResponse(BaseModel):
    """列表里的一条令牌。**永远不含明文和 hash**

    明文在创建那一次的响应里给出之后就取不回来了；hash 更不该出网。
    列表只能看到前缀，足够认出是哪一把。
    """
    id: int
    name: str
    prefix: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class AccessTokenList(BaseModel):
    """令牌列表。max_count 给前端判断有没有到上限（超了就别让点创建了）"""
    items: list[AccessTokenResponse]
    max_count: int


class AccessTokenCreated(BaseModel):
    """创建响应：**明文 token 只在这里出现这一次**"""
    id: int
    name: str
    token: str
    expires_at: Optional[datetime] = None


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


class WebhookSettingRequest(BaseModel):
    """自定义 webhook 的配置

    `enabled` 决定发不发，`url` 决定发到哪 —— 和邮件渠道同一条约定。
    两个字段都传空串（或 enabled=false）表示关闭这条渠道。

    这里只放字段形状。**地址的安全判定和模板的 JSON 校验都不在 schema 里做**，
    而是在接口里做：这两项失败要回一句能直接显示给用户的中文原因，而 schema 的
    field_validator 抛出异常会变成 422，前端拿到的 detail 是个数组 —— 它按字符串
    用（见 request.js 的调用方全是 e?.response?.data?.detail），会显示成怪东西。
    """
    url: str = Field("", max_length=500, description="要 POST 过去的 https 地址；空 = 没配地址")
    # 不加 max_length：长度上限由 webhook_service.MAX_TEMPLATE_LEN 一处管，
    # 那边给的是「模板太长了，请控制在 N 个字符以内」这种能看懂的话
    template: str = Field("", description="请求体 JSON 模板；空 = 用内置默认模板")
    # 三态，别改成 bool：开关是后加的，而 webhook 渠道**已经在线上了** ——
    # 浏览器里缓存的旧前端 PUT 过来时是不带这个字段的，若默认 False，用户
    # 什么都不改、只点一下「保存」，正在收通知的 webhook 就被静默关掉了。
    # None 表示「旧前端没传」，接口那边按老规则（有地址就是开着）处理
    enabled: Optional[bool] = Field(None, description="是否往这个地址发通知；不传 = 沿用旧规则")


class EmailNotifyRequest(BaseModel):
    """邮件通知的配置

    `email` 是**覆盖值**，只存在 users 表里，永远不会写回学生档案：
    留空表示「用学生档案里的邮箱」。改档案得走「基本信息 → 修改」的审批流，
    这样学生档案只有一个入口，不会被这里悄悄改掉。
    """
    email: str = Field("", max_length=100, description="收通知的邮箱；空 = 用学生档案邮箱")
    enabled: bool = Field(False, description="是否接收通知邮件")


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
    # 管理员有没有把 SMTP 配齐（config.smtp_enabled()）。
    # 前端靠它把「电子邮件通知」整块置灰：没配的时候**任何人开了也收不到**，
    # 与其让用户对着一个存得下、按钮也点得动、就是不来信的开关，不如直接说清楚。
    # 新加的字段有默认值，旧前端不认识它也不会坏
    smtp_enabled: bool = False
