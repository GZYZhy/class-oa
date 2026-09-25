from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AdminUserResponse(BaseModel):
    """管理员看到的账号信息"""
    student_no: str
    name: str
    role: str
    must_change_password: bool
    # 有无身份证号：没有的话默认密码会退化成学号后 6 位，重置时能提前提示
    has_id_card: bool
    # 最近登录时间；为空表示补列之后还没人用过这个号登录
    last_login_at: Optional[datetime] = None
    # 最近登录 IP
    last_login_ip: Optional[str] = None


class RoleUpdateRequest(BaseModel):
    role: str


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
