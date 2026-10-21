"""投票（表决）接口的出入参

**这里只放字段形状和长度上限，业务校验一律在 api/polls.py 里做**：schema 的
field_validator 抛异常会变成 422，而 detail 是个数组，前端 request.js 的调用方
全都按字符串用它（`e?.response?.data?.detail`），会显示成怪东西 —— 同
schemas/auth.py 里那条注释。所以选项下标越没越界、时间先后对不对，都在接口里判，
好回一句能直接显示给用户的中文。
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ---------- 出卷 ----------

class PollQuestionIn(BaseModel):
    """出卷时写的一道题"""
    title: str = Field(..., max_length=500, description="题干")
    multiple: bool = Field(False, description="单选还是多选")
    max_choices: int = Field(1, ge=1, description="多选时最多选几项；单选由接口强制成 1")
    options: list[str] = Field(..., min_length=2, max_length=20, description="选项文案")


class PollCreate(BaseModel):
    """发起一次投票

    start_at / end_at 由前端 el-date-picker 的 `value-format="YYYY-MM-DD HH:mm"`
    产生，是**不带时区**的字符串，解析出来是 naive datetime，与库里存的
    datetime.now() 同源可比。带时区的输入（第三方发的 ISO 里带 Z / +08:00）
    由接口拒绝 —— 不能在这儿静默去掉时区，那会悄悄错 8 小时。
    """
    title: str = Field(..., max_length=200, description="标题")
    description: str = Field("", max_length=2000, description="描述（支持 Markdown）")
    anonymous: bool = Field(False, description="不记名投票：接口层不再返回谁投了什么")
    start_at: datetime = Field(..., description="开始时间")
    end_at: datetime = Field(..., description="截止时间")
    notify_on_start: bool = Field(
        True,
        description="到开始时间是否提醒范围内的人；创建时立即发的是旧行为，已取消",
    )
    targets: list[str] = Field(..., min_length=1, description="有权表决的学号（接口会核对是否真存在）")
    questions: list[PollQuestionIn] = Field(..., min_length=1, max_length=30, description="一张卷子上的题")


class PollUpdate(BaseModel):
    """编辑一次投票（发起人或管理员）

    **标题和描述随便改**；起止时间按状态分档（**不在这里判，见 api/polls.py 的
    update_poll**）：还没开始的两个都能改，已经开始的只能改截止时间，已结束的一个
    都不给改。**记名与否只有还没开始时能改。**

    **表决范围一个都不在这里** —— 它改了会动摇已经投出去的票：把已投的人改成范围外，
    他那张票算不算数就说不清了，反过来加人等于已经开投了才放人进来。要换人只能删了
    重发（删除接口本来就允许删已有人投的）。

    questions 不传 = 只改标题和描述；传了 = 整卷替换，而且**只有还没开始的投票**
    接受，理由见 api/polls.py 的 update_poll。
    """
    title: str = Field(..., max_length=200, description="标题")
    description: str = Field("", max_length=2000, description="描述")
    # None = 不改。**不给空值留别的含义**：时间本来就不可能被清成空
    start_at: datetime | None = Field(
        None, description="新的开始时间，不传=不改。只有还没开始的投票能改"
    )
    end_at: datetime | None = Field(
        None, description="新的截止时间，不传=不改。已经开始的（含已暂停）也能调整"
    )
    anonymous: bool | None = Field(
        None, description="记名还是匿名，不传=不改。只有还没开始的投票能改"
    )
    notify_on_start: bool | None = Field(
        None,
        description="开始时间是否提醒，不传=不改。只有还没开始、还没发过提醒时能改",
    )
    questions: list[PollQuestionIn] | None = Field(
        None, min_length=1, max_length=30,
        description="传了就把题目整卷换掉，只对还没开始的投票有效",
    )


# ---------- 投票 ----------

class PollAnswerIn(BaseModel):
    """对一道题的作答

    choices 上**故意不加** min_length / max_length：空选、选太多、下标越界都由
    接口判，好回一句「「要不要聚餐」是单选题，只能选一项」这样的中文；
    写成 schema 约束会变成 422，前端只能看到一个数组（见模块开头的说明）。
    """
    question_id: int
    choices: list[int] = Field(..., description="选中选项的**下标**")


class PollVoteIn(BaseModel):
    """整卷一次提交，每题一条

    choices 存的是选项**下标**而不是文案：文案将来改了，历史作答也不会跟着错位。
    **不许改票**，所以这个请求体一个人一辈子只会成功送进来一次。
    """
    answers: list[PollAnswerIn] = Field(..., min_length=1)


# ---------- 读 ----------

class PollQuestionResponse(BaseModel):
    """一道题，作答界面和结果界面共用"""
    id: int
    sort: int
    title: str
    multiple: bool
    max_choices: int
    options: list[str] = Field(default_factory=list, description="选项文案")
    my_choices: list[int] = Field(default_factory=list, description="我选中的下标；没投过是空数组")
    tallies: list[int] | None = Field(
        None, description="每个选项的票数，下标与 options 对齐；结果不可见时为 None"
    )


class PollListItem(BaseModel):
    """列表里的一场投票

    **状态和权限全由后端算好塞进来**，前端只认这些字段、不自己拿时间去比 ——
    可见性只有 services/poll_service.py 一处口径。

    `target_count` / `voted_count` 在 `results_visible` 为假时一律给 0：
    看不到结果的人也不该看到投票率（照用户口径，参与者要等投票结束才看得到）。
    """
    id: int
    share_token: str = Field(
        "", description="分享页地址里的签名串（微信卡片用），前端拼 /share/vote/{token}"
    )
    title: str
    description: str = ""
    anonymous: bool = Field(False, description="不记名：界面上要标出来，记名反而不标")
    status: str = Field(
        ...,
        description="pending 未开始 / open 进行中 / locked 已暂停（临时停收票，解锁后还能投）"
        " / closed 已结束",
    )
    start_at: datetime
    end_at: datetime
    closed_at: datetime | None = None
    creator_no: str = ""
    creator_name: str = ""
    created_at: datetime | None = None
    # 开始提醒：出卷人指定；start_notified_at 非空表示已经发过，不能再改
    notify_on_start: bool = True
    start_notified_at: datetime | None = None

    question_count: int = 0
    scope_label: str = Field("", description="全班 / 班委 / 团员 / 定向 N 人")
    target_count: int = Field(0, description="应投人数，投票率的分母")
    voted_count: int = Field(0, description="已投人数")
    is_target: bool = Field(False, description="我在不在表决范围内")
    has_voted: bool = Field(False, description="我投没投")
    results_visible: bool = Field(False, description="我能不能看结果")
    can_manage: bool = Field(False, description="我是不是发起人或管理员，能不能结束/催票/删除")
    # **列表项也得有它**：列表页「操作」列的按钮靠它决定叫「投票」还是「查看结果」、
    # 点了进投票弹窗还是结果弹窗。只在详情里给，列表页就会出现「状态写着待投票、
    # 操作却只能点查看结果」——能投的人从列表投不了票
    can_vote: bool = Field(
        False, description="我现在能不能投（进行中 + 我在范围内 + 我还没投过）"
    )


class PollDetailResponse(PollListItem):
    """详情 = 列表项 + 题目

    继承列表项而不是重写一遍：前端只维护一套读法。
    """
    questions: list[PollQuestionResponse] = Field(default_factory=list)


class PollShareResponse(BaseModel):
    """外链分享页的数据（公开接口）

    **不继承 PollListItem**：游客拿到的分享链接里不该带发起人学号
    （creator_no）。公开字段只有标题、完整描述、范围、状态、时间和人数；
    题目、选项、我的作答、票数只在 in_scope 为真时下发。

    in_scope = 我在表决范围内，或者我是发起人 / 管理员。范围外的人即使投票
    已结束也不返回结果 —— 和详情接口「越权一律 404」的口径一致。
    """
    id: int
    share_token: str = ""
    title: str
    description: str = ""
    anonymous: bool = False
    status: str
    start_at: datetime
    end_at: datetime
    closed_at: datetime | None = None
    scope_label: str = Field("", description="全班 / 班委 / 团员 / 定向 N 人")
    question_count: int = 0
    target_count: int = Field(0, description="应投人数；不可见结果时也返回真实人数")
    voted_count: int = Field(0, description="已投人数；结果不可见时为 0")
    is_login: bool = False
    in_scope: bool = False
    is_target: bool = False
    has_voted: bool = False
    results_visible: bool = False
    can_manage: bool = False
    can_vote: bool = False
    questions: list[PollQuestionResponse] = Field(default_factory=list)


class PollListResponse(BaseModel):
    """分页列表"""
    total: int
    page: int
    page_size: int
    items: list[PollListItem]


class PollBallotRow(BaseModel):
    """有权表决的人，一人一行"""
    student_no: str
    name: str = ""
    voted: bool = False
    voted_at: datetime | None = None
    frozen: bool = Field(False, description="账号被冻结：投不了票，催票时也会跳过")
    choices: dict[str, list[int]] | None = Field(
        None,
        description=(
            "记名投票才有：{题目 ID: 选中的下标}（JSON 的键是字符串，前端用 String(q.id) 取）。"
            "不记名恒为 None；记名但此人没投是空对象"
        ),
    )


class PollBallotsResponse(BaseModel):
    """谁投了、谁没投

    不记名投票**一样给这份名单**（催票要按它算未投人数），只是每行的 choices
    恒为 None —— 「谁投了什么」在接口层就不返回，库里的 student_no 照存。
    """
    total: int
    voted_count: int
    rows: list[PollBallotRow]


class PollRosterItem(BaseModel):
    """出卷时可勾选的一名学生"""
    student_no: str
    name: str = ""
    committee: bool = Field(False, description="班委及以上，供「仅班委」快捷键用")
    # 给「仅团员」快捷键用。**回的是政治面貌原文而不是一个 league 布尔**：判据
    # （比「共青团员」这四个字）在前端 utils/roster.js 里只写一份，点名和分类统计
    # 用的也是它；这里另造一个布尔就等于把同一件事在后端再判一遍，两边迟早漂开
    political_status: str = Field("", description="政治面貌，供「仅团员」快捷键用")


class PollRosterResponse(BaseModel):
    items: list[PollRosterItem]


class PollRemindResponse(BaseModel):
    """催票结果。提醒一定落进对方收件箱（站内信必达），所以这个数就是真收到的人数"""
    reminded: int


class PollCloseResponse(BaseModel):
    """立即结束的结果。重复调用是幂等的，第二次拿到的数一样、只是不再记日志"""
    status: str
    voted_count: int
