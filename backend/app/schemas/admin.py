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


class FileAccessLogResponse(BaseModel):
    """文件访问日志（查看 / 下载）"""
    id: int
    created_at: Optional[datetime] = None
    user_no: Optional[str] = None
    user_name: Optional[str] = None
    file_id: Optional[int] = None
    file_title: Optional[str] = None
    action: Optional[str] = None  # view / download
    ip: Optional[str] = None

    class Config:
        from_attributes = True


class FileAccessLogListResponse(BaseModel):
    total: int
    items: list[FileAccessLogResponse]


class WatermarkExtractResponse(BaseModel):
    """水印提取结果

    accessed_at 而不是 downloaded_at：自从改成「一律打水印」之后，在线查看
    拿到的副本也带水印，一份流传出来的 PDF 未必是下载出去的。动作到底是查看
    还是下载，靠下面的 action 字段去日志里核对，不靠这里猜。
    """
    found: bool
    token: Optional[str] = None
    file_id: Optional[int] = None
    user_no: Optional[str] = None
    user_name: Optional[str] = None
    file_title: Optional[str] = None
    accessed_at: Optional[datetime] = None
    # 和 file_access_logs 核对上的那条记录：动作、IP
    action: Optional[str] = None
    ip: Optional[str] = None
    # 有没有在日志里核到。核不到就不能说人家「下载」了，只能如实说不确定
    log_matched: bool = False
    message: Optional[str] = None


class IpBanRequest(BaseModel):
    """手动封禁请求

    target 既可以是单个 IP，也可以是一个 CIDR 网段（格式由后端校验）。
    未归一化也没关系 —— 后端会先归一再入库。
    """
    target: str = Field(..., description="IP 或 CIDR 网段，如 203.0.113.9 或 203.0.113.0/24")
    # None = 永久封禁。上下界都必须有：
    # 下界 0/负数会和无期（null）的语义撞车；
    # 上界不加的话 timedelta(minutes=10**18) 会抛 OverflowError，变成 500
    minutes: Optional[int] = Field(
        None, ge=1, le=5256000, description="封禁分钟数，留空表示永久（上限 10 年）"
    )
    reason: str = Field("", max_length=200, description="封禁原因")


class IpBanResponse(BaseModel):
    """一条封禁记录"""
    id: int
    # 单个 IP 或 CIDR 网段（已归一化）
    target: str
    reason: Optional[str] = None
    # 手动封禁 = True；登录失败自动触发的 = False。
    # 管理员延长过的自动封禁也置 True
    is_manual: bool
    created_at: Optional[datetime] = None
    # 为 None 表示永久封禁
    expires_at: Optional[datetime] = None
    operator_no: Optional[str] = None
    operator_name: Optional[str] = None

    class Config:
        from_attributes = True


class IpBanListResponse(BaseModel):
    total: int
    items: list[IpBanResponse]
    # 当前操作者自己的 IP。前端显示成「你当前的 IP：x（不能封自己）」，
    # 比只在提交时报错友好
    self_ip: Optional[str] = None


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
    """某个账号的日志：操作日志（全部）+ 被操作记录 + 账号事件（最近 7 天）"""
    student_no: str
    name: str
    # 该账号作为「操作人」留下的操作日志。只按操作人过滤，不看时间；
    # 不是用 /logs?operator= 那个模糊匹配 —— 按 2026012 查会把 20260123、
    # 20260124 一起带出来
    operations: OperationLogListResponse
    # 该账号作为「被操作对象」的日志（别人重置他的密码、改他的角色、冻结他、
    # 改他的学生信息、审批他的申请等），分页。定位方式见 api/admin.py 的注释
    targeted: OperationLogListResponse
    # 最近 7 天的登录 / 改密事件。events 最多 200 条，events_total 是窗口内的真实条数，
    # 前端在 total 大于条数时提示「仅显示最近 200 条」—— 不做静默截断
    events: list[AccountEventResponse]
    events_total: int
    # 7 天窗口的左端。回给前端是为了让它把边界显示出来，
    # 而不是让人猜「为什么只有这几条」
    events_since: datetime
