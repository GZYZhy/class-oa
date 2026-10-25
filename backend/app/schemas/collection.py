"""投票收集的出入参

和 schemas/poll.py 分开：收集允许每人多份、六种题型，字段形状和投票差别很大
（投票是 choices-only 的一人一卷）。这里只放形状，业务校验在 api/collections.py。
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ---------- 出卷 ----------

class CollectionQuestionIn(BaseModel):
    title: str = Field(..., max_length=500, description="题干")
    qtype: str = Field(..., description="single/multiple/short_text/long_text/image/rating")
    required: bool = Field(True, description="是否必答")
    options: list[str] = Field(default_factory=list, description="选择题选项")
    max_choices: int | None = Field(None, ge=1, description="多选题最多选几项")


class CollectionCreate(BaseModel):
    title: str = Field(..., max_length=200, description="标题")
    description: str = Field("", max_length=2000, description="详细说明（支持 Markdown）")
    anonymous: bool = Field(False, description="不记名：接口层不返回答卷身份")
    allow_withdraw: bool = Field(
        False, description="是否允许答题人在进行中撤回自己的答卷（撤回释放竞争名额）"
    )
    start_at: datetime = Field(..., description="开始时间")
    end_at: datetime = Field(..., description="截止时间")
    notify_on_start: bool = Field(
        True, description="到开始时间是否提醒范围内的人（创建时不发）"
    )
    submit_quota: int = Field(1, ge=1, le=50, description="每人最多可填几份")
    max_responses: int = Field(
        0, ge=0, description="全局只收前几份；0=不限"
    )
    targets: list[str] = Field(..., min_length=1, description="可填写人员的学号")
    questions: list[CollectionQuestionIn] = Field(
        ..., min_length=1, max_length=30, description="题目"
    )


class CollectionUpdate(BaseModel):
    title: str = Field(..., max_length=200, description="标题")
    description: str = Field("", max_length=2000, description="详细说明（支持 Markdown）")
    start_at: datetime | None = Field(None, description="新的开始时间，不传=不改")
    end_at: datetime | None = Field(None, description="新的截止时间，不传=不改")
    anonymous: bool | None = Field(None, description="记名/不记名，不传=不改")
    allow_withdraw: bool | None = Field(
        None, description="是否允许答题人撤回，不传=不改；结束后不再生效"
    )
    notify_on_start: bool | None = Field(
        None, description="开始提醒开关，不传=不改；只在未开始且没发过时能改"
    )
    submit_quota: int | None = Field(
        None, ge=1, le=50, description="每人份数，不传=不改；有答卷后锁定"
    )
    max_responses: int | None = Field(
        None, ge=0, description="全局上限，0=不限；不传=不改；有答卷后锁定"
    )
    questions: list[CollectionQuestionIn] | None = Field(
        None, min_length=1, max_length=30,
        description="传了=整卷替换；有答卷后锁定",
    )


# ---------- 读 ----------

class CollectionQuestionResponse(BaseModel):
    id: int
    sort: int = 0
    title: str
    qtype: str
    required: bool = True
    options: list[str] = Field(default_factory=list)
    max_choices: int | None = None
    text_limit: int | None = None
    rating_min: int | None = None
    rating_max: int | None = None
    max_files: int | None = None


# 答卷形状放在分享返回之前：CollectionShareResponse 里的 my_responses 直接引用它
class CollectionFileMeta(BaseModel):
    name: str
    original: str = ""
    size: int = 0


class CollectionAnswerResponse(BaseModel):
    question_id: int
    qtype: str
    choices: list[int] = Field(default_factory=list)
    text: str = ""
    rating: int | None = None
    files: list[CollectionFileMeta] = Field(default_factory=list)


class CollectionResponseItem(BaseModel):
    id: int
    seq_no: int
    submitted_at: datetime
    duration_seconds: int | None = None
    student_no: str | None = None
    student_name: str | None = None
    answers: list[CollectionAnswerResponse] = Field(default_factory=list)


class CollectionListItem(BaseModel):
    """列表项：公开信息 + 我的进度 + 份数设置"""

    id: int
    share_token: str = ""
    title: str
    description: str = ""
    anonymous: bool = False
    allow_withdraw: bool = False
    status: str
    start_at: datetime
    end_at: datetime
    closed_at: datetime | None = None
    creator_name: str = ""
    created_at: datetime | None = None

    question_count: int = 0
    target_count: int = 0
    submitted_count: int = Field(0, description="已收答卷份数")
    submitted_people: int = Field(0, description="已填过至少一份的人数")
    completed_count: int = Field(0, description="已达到每人配额的人数")
    scope_label: str = ""

    submit_quota: int = 1
    max_responses: int | None = Field(None, description="全局竞争上限；空=不限")
    response_count: int = Field(0, description="已收份数（竞争计数器）")
    remaining_slots: int | None = Field(None, description="竞争模式剩余名额")
    cap_reached: bool = False

    my_submitted_count: int = 0
    my_remaining: int = 0
    quota_reached: bool = False
    is_target: bool = False
    can_manage: bool = False
    can_submit: bool = False

    notify_on_start: bool = True
    start_notified_at: datetime | None = None


class CollectionDetailResponse(CollectionListItem):
    questions: list[CollectionQuestionResponse] = Field(default_factory=list)


class CollectionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CollectionListItem]


class CollectionShareResponse(BaseModel):
    """外链分享页的数据（公开字段 + 登录者的进度）"""

    id: int
    share_token: str = ""
    title: str
    description: str = ""
    anonymous: bool = False
    allow_withdraw: bool = False
    status: str
    start_at: datetime
    end_at: datetime
    closed_at: datetime | None = None
    scope_label: str = ""
    question_count: int = 0
    target_count: int = 0
    submitted_count: int = 0
    submit_quota: int = 1
    max_responses: int | None = None
    remaining_slots: int | None = None
    cap_reached: bool = False

    is_login: bool = False
    in_scope: bool = False
    my_submitted_count: int = 0
    my_remaining: int = 0
    quota_reached: bool = False
    can_submit: bool = False
    can_manage: bool = False
    questions: list[CollectionQuestionResponse] = Field(default_factory=list)
    # 自己交过的答卷（只回显给本人）：配额 1 时答过就展示这一份；
    # 多份时也能看已提交的每一份，并在允许时逐份撤回
    my_responses: list[CollectionResponseItem] = Field(default_factory=list)


# ---------- 提交 ----------

class CollectionAnswerIn(BaseModel):
    question_id: int
    choices: list[int] = Field(default_factory=list, description="选择题下标")
    text: str = Field("", max_length=2000, description="文本题原文（长度按题型再校验）")
    rating: int | None = Field(None, description="评分 1–5")
    files: list[str] = Field(default_factory=list, description="图片上传凭证列表")


class CollectionSubmitIn(BaseModel):
    answers: list[CollectionAnswerIn] = Field(..., min_length=1)
    # 前端从打开填写页到提交的秒数；上限 24 小时，避免异常值把统计带偏
    duration_seconds: int | None = Field(None, ge=0, le=86400)


class CollectionSubmitResponse(BaseModel):
    id: int
    seq_no: int
    submitted_at: datetime
    duration_seconds: int | None = None
    my_submitted_count: int
    my_remaining: int
    can_submit: bool


class CollectionResponseList(BaseModel):
    total: int
    page: int
    page_size: int
    order: str = "asc"
    items: list[CollectionResponseItem]


class CollectionBatchDeleteIn(BaseModel):
    response_ids: list[int] = Field(..., min_length=1, max_length=200)


class CollectionCloseResponse(BaseModel):
    status: str
    response_count: int


class CollectionWithdrawResponse(BaseModel):
    """答题人撤回自己的答卷：竞争名额同事务释放"""

    deleted: int = 1
    response_count: int
    my_submitted_count: int
    can_submit: bool


class CollectionFileResponse(BaseModel):
    token: str
    name: str
    size: int


class CollectionPendingItem(BaseModel):
    student_no: str
    name: str
    submitted_count: int | None = Field(
        None, description="匿名收集不返回，避免暴露每个人交了几份"
    )
    remaining: int | None = None
    frozen: bool = False
    is_self: bool = Field(
        False, description="是不是当前操作人；提醒时会跳过本人"
    )


class CollectionPendingResponse(BaseModel):
    total: int
    items: list[CollectionPendingItem]
    unfilled_count: int = Field(
        0, description="一份都没交、且可催的人数（不含本人和冻结账号）"
    )
    partial_count: int = Field(
        0, description="交过但没填满、且可催的人数（不含本人和冻结账号）"
    )


class CollectionTargetItem(BaseModel):
    student_no: str
    student_name: str = ""


class CollectionTargetList(BaseModel):
    """可填写名单（仅发起人/管理员，复用范围用）"""

    total: int
    items: list[CollectionTargetItem]


class CollectionDurationStats(BaseModel):
    count: int = 0
    average_seconds: int = 0
    median_seconds: int = 0
    min_seconds: int = 0
    max_seconds: int = 0


class CollectionStatisticsResponse(BaseModel):
    items: list[dict] = Field(default_factory=list)
    duration: CollectionDurationStats = Field(default_factory=CollectionDurationStats)


class CollectionExportRequest(BaseModel):
    """导出参数（GET 用 query，这里只给前端/文档一个形状）"""
    order: str = Field("asc", description="asc / desc")
