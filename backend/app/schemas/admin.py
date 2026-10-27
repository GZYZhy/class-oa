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
    # 域外账号有没有上传签字图（学生账号恒为 False；学生签字看 Student.sign_photo）。
    # 前端拿它显示弹窗里的「已有签字图」状态，列表里不铺成列
    has_sign_photo: bool = False
    # 最近登录时间；为空表示补列之后还没人用过这个号登录
    last_login_at: Optional[datetime] = None
    # 最近登录 IP
    last_login_ip: Optional[str] = None
    # 是否已冻结：冻结后不能登录，已登录的会话下一个请求就 401。
    # 老库补列时一律为 False
    is_frozen: bool = False
    # 二次验证方式：空 = 没开；email / totp。管理员据此显示「已开启」并提供清除入口
    two_factor_method: str = ""


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

    水印的 file_id 可能对应公告文件（announcement）、导出申请（export_request）、
    请假审批表（leave）或电动车那两份（evpass），用 source_type 区分。几边的 id
    各自编号会撞号，靠令牌里的来源段区分（见 pdf_watermark_service）。

    导出文件（source_type = "export"）不在文件访问日志里，accessed_at 是它的
    **生成时间**而不是访问时间，也没有 action / ip 可核 —— 前端要照着这个区别
    调整措辞，别写成「某人于某时下载了这份文件」。

    请假审批表（source_type = "leave"）同样不在文件访问日志里，但它的
    accessed_at 是**真的下载时间**（令牌是下载那一刻现打的），只是没有 action / ip
    可核。前端措辞可以写「某人于某时下载了这张表」。

    电动车的申请表与承诺书（source_type = "evpass"，两份共用这一个值，
    靠 file_title 区分是哪一份）和请假表一模一样：不写访问日志、accessed_at
    是真的下载时间、没有 action / ip。措辞照请假那支写即可。

    公告文件这一支另有一种情况：令牌说是公告，公告表里却已经查不到那一行
    （file_deleted = True）—— 这份文件已经从「文件公开」里删掉了，而删除时会
    连它的访问记录一起清掉，所以动作和 IP 必然核不到、file_title 也是空的。
    能确定的只有水印里那三样：谁、何时、取的是哪一号文件。
    """
    found: bool
    token: Optional[str] = None
    file_id: Optional[int] = None
    user_no: Optional[str] = None
    user_name: Optional[str] = None
    file_title: Optional[str] = None
    accessed_at: Optional[datetime] = None
    # 水印来源：announcement（公告文件） / export（导出申请） / leave（请假审批表）
    # / evpass（电动车申请表与承诺书，两份共用一个值，靠 file_title 区分）
    source_type: Optional[str] = None
    # 导出申请相关（source_type = "export" 时有值）
    export_type: Optional[str] = None
    export_scope: Optional[str] = None
    export_status: Optional[str] = None
    export_reviewer: Optional[str] = None
    # 和 file_access_logs 核对上的那条记录：动作、IP（仅公告文件有）
    action: Optional[str] = None
    ip: Optional[str] = None
    # 有没有在日志里核到。核不到就不能说人家「下载」了，只能如实说不确定
    log_matched: bool = False
    # 这份文件已经从「文件公开」里删掉了（令牌写着来源是公告，公告表里却没有
    # 那一行）。文件被删时它的访问记录也一并清了，所以动作、IP 必然核不到，
    # file_title 也是空的 —— 前端据此换个说法，别让管理员对着一份查无此物、
    # 只写着「文件#5」的结果发懵
    file_deleted: bool = False
    message: Optional[str] = None


class DataHealthItem(BaseModel):
    """一条体检问题：哪个学生（或哪个文件）+ 一句人话说明"""
    # 学生行才有；文件类（签字图/文件丢失/孤儿文件）没有
    id: Optional[int] = None
    # 这两个理论上可能为空（库里的历史脏数据），空着也别让整个报告 500
    student_no: Optional[str] = None
    name: Optional[str] = None
    # 文件类：给人看的对象说明（资料「xx」、公告「xx」、账号 张三）
    subject: Optional[str] = None
    reason: str
    # 孤儿文件要能定位到具体目录 + 文件名，清理时才敢删
    domain: Optional[str] = None
    file: Optional[str] = None
    size: Optional[int] = None


class DataHealthGroup(BaseModel):
    """一类体检结果，前端渲染成一张卡片"""
    key: str
    label: str
    # error = 确实有问题；warn = 可疑或缺失，可能只是还没填。前端据此上色
    level: str
    items: list[DataHealthItem]
    # 只有「孤儿文件」这类能一键清理；丢失文件只报告，绝不删库记录
    can_cleanup: bool = False


class DataHealthResponse(BaseModel):
    """学生数据体检报告（只读，不改任何数据）"""
    checked_at: datetime
    total_students: int
    # 一项问题都没有的卡片不会出现在这里，前端直接顺序渲染
    groups: list[DataHealthGroup]


class OrphanCleanupRequest(BaseModel):
    """清理孤儿文件：domains 为空 = 所有目录"""

    domains: list[str] | None = None


class OrphanCleanupDomain(BaseModel):
    domain: str
    label: str
    deleted: int
    freed_bytes: int


class OrphanCleanupResponse(BaseModel):
    message: str
    deleted: int
    freed_bytes: int
    failed: int
    by_domain: list[OrphanCleanupDomain] = Field(default_factory=list)


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
    """一条账号事件（登录、改密、账号安全设置变化）"""
    id: int
    created_at: Optional[datetime] = None
    # 如 login | change_password | passkey_add。存英文值、前端映射中文，
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


class MyLogsResponse(BaseModel):
    """「我的日志」：本人自助查看的两块（api/auth.py）

    和管理员的 AdminUserLogsResponse 是同一套查询，少一块 `targeted`
    （被操作记录）—— 那是管理员视角，本人看不到别人对自己做了什么。
    """
    # 我作为「操作人」留下的全部记录，分页
    operations: OperationLogListResponse
    # 最近 7 天的登录 / 自行改密，最多 200 条，超出在 events_total 里报数
    events: list[AccountEventResponse]
    events_total: int
    events_since: datetime


class BirthdaySettingsUpdate(BaseModel):
    """生日关怀设置的整体保存请求（PUT 全量覆盖）

    模板里的占位符合法性**不在这里校验**，放在接口层：schema 里 import services
    是反的依赖方向（同 set_webhook 的写法）。
    """

    banner_enabled: bool
    banner_show_names: bool
    greet_enabled: bool
    # 空串 = 用内置默认文案（同 webhook_template 的约定）
    greet_template: str = Field("", max_length=500)
    notify_enabled: bool
    notify_student_nos: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("notify_student_nos")
    @classmethod
    def clean_nos(cls, v: list[str]) -> list[str]:
        # 去重保序 + 丢掉空串，别把空学号写进 JSON 数组
        return list(dict.fromkeys(n.strip() for n in v if n and n.strip()))
