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
    # 是否已冻结：冻结后不能登录，已登录的会话下一个请求就 401。
    # 老库补列时一律为 False
    is_frozen: bool = False


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


class AccountEventResponse(BaseModel):
    """一条账号事件（登录 / 本人自行改密）"""
    id: int
    created_at: Optional[datetime] = None
    # login | change_password。存英文值、前端映射中文，
    # 免得以后加事件类型时库里已经存了一批中文
    event: str
    ip: Optional[str] = None

    class Config:
        from_attributes = True


class AdminUserLogsResponse(BaseModel):
    """某个账号的日志：操作日志（全部）+ 账号事件（最近 7 天）"""
    student_no: str
    name: str
    # 该账号作为「操作人」留下的操作日志。只按操作人过滤，不看时间；
    # 不是用 /logs?operator= 那个模糊匹配 —— 按 2026012 查会把 20260123、
    # 20260124 一起带出来
    operations: OperationLogListResponse
    # 最近 7 天的登录 / 改密事件。events 最多 200 条，events_total 是窗口内的真实条数，
    # 前端在 total 大于条数时提示「仅显示最近 200 条」—— 不做静默截断
    events: list[AccountEventResponse]
    events_total: int
    # 7 天窗口的左端。回给前端是为了让它把边界显示出来，
    # 而不是让人猜「为什么只有这几条」
    events_since: datetime
