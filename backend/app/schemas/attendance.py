"""考勤记录相关 schema"""

from datetime import date, datetime

from pydantic import BaseModel, Field

# 上报点名时只收这三种。**late（迟到）不在里面**：它只能由班委/管理员事后在
# 明细里手动标记（AttendanceItemUpdate），不能由点名流程顺手写进去 ——
# 点名的界面本来也只有「到 / 无应答」两个键。
STATUS_PATTERN = "^(present|absent|leave)$"

# 事后改状态时多一个迟到。与 STATUS_PATTERN 分开，才能保证「只能手动标记」
ALL_STATUS_PATTERN = "^(present|absent|leave|late)$"


class AttendanceItemIn(BaseModel):
    """上报时某人的状态"""
    student_no: str = Field(..., max_length=20, description="学号")
    name: str = Field("", max_length=50, description="姓名")
    status: str = Field(..., pattern=STATUS_PATTERN, description="present/absent/leave")


class AttendanceCreate(BaseModel):
    """一次点名结束后上报"""
    scope: str = Field(..., max_length=10, description="点名范围：全班 / 男生 / 女生 / 共青团员")
    records: list[AttendanceItemIn] = Field(..., min_length=1, description="被点到的每个人")


class AttendanceItemResponse(BaseModel):
    student_no: str
    student_name: str
    status: str


class AttendanceRecordResponse(BaseModel):
    """列表和详情共用

    计数全部从明细现算，表里没有对应的列 —— 两者永远不会对不上。
    列表接口不带 items（只给计数），详情接口（GET /{record_id}）才带。
    """
    id: int
    call_date: date
    scope: str
    # 展示用的标准简语（全班/团员/班委/N人）；原始 scope 仍保留给日志和兼容调用
    scope_label: str = ""
    called_at: datetime | None = None
    operator_no: str = ""
    operator_name: str = ""
    remark: str = Field("", description="这次点名的一句话备注，空串 = 没写")

    total: int = Field(0, description="应到")
    present: int = 0
    # 迟到是「到」的子集：页面上的实到 = present + late
    late: int = Field(0, description="迟到（只能由班委/管理员手动标记）")
    leave: int = 0
    absent: int = 0

    items: list[AttendanceItemResponse] = Field(default_factory=list)


class AttendanceListResponse(BaseModel):
    """分页列表"""
    total: int
    items: list[AttendanceRecordResponse]


class AttendanceOverviewItem(BaseModel):
    """点名与签到合在一张列表里的一行

    `type` 区分两种记录：attendance = 点名记录，checkin = 签到。
    两边的字段放在同一个模型里，前端只按 type 取自己那几列。
    """
    type: str = Field(..., description="attendance / checkin")
    id: int
    date: date
    # 点名时刻；签到是截止或提前结束的时刻
    time: datetime | None = None
    # 点名的范围 / 签到的标题
    title: str = ""
    # 列表「范围」列用的标准简语：全班 / 团员 / 班委 / N人。
    # 点名的原始 scope 可能是「男生」「共青团员」，不直接拿去展示
    scope_label: str = ""
    operator_name: str = ""
    remark: str = ""

    # 点名记录的计数
    total: int = 0
    present: int = 0
    late: int = Field(0, description="迟到，实到 = present + late")
    leave: int = 0
    absent: int = 0

    # 签到的情况
    status: str = ""
    # 开始时间，可空（老签到没有这一列）
    start_at: datetime | None = None
    target_count: int = 0
    signed_count: int = 0
    link: str = ""
    # 分享弹窗重新打开时要显示备注和签到要求
    require_photo: bool = False
    location: dict | None = None


class AttendanceOverviewResponse(BaseModel):
    """点名与签到合并后的分页列表"""
    total: int
    items: list[AttendanceOverviewItem]


class MyAttendanceItem(BaseModel):
    """学生本人的一条考勤记录（点名或签到）

    只列「这次考勤里有我」的记录：点名看 attendance_items，
    签到看 checkin_targets；签到结算生成的考勤记录不另外再占一行。
    """
    type: str = Field(..., description="attendance / checkin")
    id: int
    occurred_at: datetime | None = None
    title: str = ""
    category: str = Field("", description="点名 / 签到")
    scope: str = Field("", description="全班 / 团员 / 班委 / N人")
    status: str = Field("", description="present/late/leave/absent/pending/unsigned")
    status_label: str = Field("", description="到 / 迟到 / 请假 / 无应答 / 未签到 / 未开始")


class MyAttendanceListResponse(BaseModel):
    total: int
    items: list[MyAttendanceItem]


class AttendanceItemUpdate(BaseModel):
    """改某人状态。**这里是产生「迟到」的唯一入口**（班委/管理员手动标记）"""
    status: str = Field(..., pattern=ALL_STATUS_PATTERN)


class AttendanceRemarkUpdate(BaseModel):
    """写某次点名的备注

    整条替换：传什么存什么，传空串（或只传空格）就是把这段备注清掉 ——
    不另设「删除备注」的接口，空即没有。
    """
    remark: str = Field("", max_length=200, description="备注，空串表示清掉")


class AttendanceBatchDelete(BaseModel):
    """批量删除勾选的记录：点名和签到分两组传

    两类记录的 id 各自独立（都从 1 开始），不能混在一个数组里。
    """
    record_ids: list[int] = Field(default_factory=list, description="考勤记录 id")
    checkin_ids: list[int] = Field(default_factory=list, description="签到 id")
