from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from ..utils.security import validate_password


class AdminUserResponse(BaseModel):
    """管理员看到的账号信息"""
    # 学生账号是学号；域外账号是管理员指定的登录名
    student_no: str
    name: str
    role: str
    must_change_password: bool
    # 是否域外账号（不与学生表关联）：前端据此显示「编辑/删除」并隐去身份证号那一列
    is_external: bool = False
    # 有无身份证号：没有的话默认密码会退化成学号后 6 位，重置时能提前提示。
    # 域外账号没有这一说，恒为 False
    has_id_card: bool
    # 域外账号有没有上传头像（学生账号恒为 False，头像看学生照片）
    has_avatar: bool = False
    # 最近登录时间；为空表示补列之后还没人用过这个号登录
    last_login_at: Optional[datetime] = None
    # 最近登录 IP
    last_login_ip: Optional[str] = None


class RoleUpdateRequest(BaseModel):
    role: str


class ResetPasswordRequest(BaseModel):
    """管理员给域外账号指定新密码

    学生账号的重置不走这里（学生是重置成身份证号后 6 位），所以这个字段可选。
    """
    password: Optional[str] = Field(None, description="域外账号的新密码")

    @field_validator("password")
    @classmethod
    def check_password(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return validate_password(v, "新密码")


class ResetPasswordResponse(BaseModel):
    message: str
    # 只有「没有身份证号、退回学号后 6 位」时才回带密码，方便管理员转告学生；
    # 身份证后 6 位不回带 —— 那属于学生隐私，管理员要用自己去看学生信息
    password: Optional[str] = None
    fallback: bool = False


class OperationLogResponse(BaseModel):
    id: int
    created_at: Optional[datetime] = None
    operator_no: Optional[str] = None
    operator_name: Optional[str] = None
    action: Optional[str] = None
    target: Optional[str] = None
    detail: Optional[str] = None
    ip: Optional[str] = None

    class Config:
        from_attributes = True


class OperationLogListResponse(BaseModel):
    total: int
    items: list[OperationLogResponse]
