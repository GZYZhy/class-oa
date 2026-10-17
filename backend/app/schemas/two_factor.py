from pydantic import BaseModel, Field


class TwoFactorVerifyRequest(BaseModel):
    """登录时提交第二因素：6 位验证码，或 XXXX-XXXX 形式的恢复码"""
    code: str = Field(..., min_length=4, max_length=20, description="验证码或一次性恢复码")


class TwoFactorCodeRequest(BaseModel):
    """开启二次验证时确认验证码 / 关闭与重生成恢复码时的密码确认

    两个接口都用「用户手里已有的东西」再确认一次：开启时是刚收到的验证码，
    关闭和重生成恢复码时是登录密码。字段名统一叫 code / password，分开定义
    是为了别让「密码」和「验证码」两种东西混进同一个 schema。
    """
    code: str = Field(..., min_length=4, max_length=20)


class TwoFactorPasswordRequest(BaseModel):
    """敏感操作的密码再确认（开启前取选项、关闭、重生成恢复码）"""
    password: str = Field(..., max_length=64, description="登录密码")
