"""考勤记录相关 schema"""

from datetime import date, datetime

from pydantic import BaseModel, Field

# 三种状态的合法取值。前后端各写一份，改的时候两边一起改：
# 前端在 RollCallDialog.vue / Attendance.vue，这里是入库前的最后一道闸
STATUS_PATTERN = "^(present|absent|leave)$"


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
    called_at: datetime | None = None
    operator_no: str = ""
    operator_name: str = ""
    remark: str = Field("", description="这次点名的一句话备注，空串 = 没写")

    total: int = Field(0, description="应到")
    present: int = 0
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
    operator_name: str = ""
    remark: str = ""

    # 点名记录的计数
    total: int = 0
    present: int = 0
    leave: int = 0
    absent: int = 0

    # 签到的情况
    status: str = ""
    # 开始时间，可空（老签到没有这一列）
    start_at: datetime | None = None
    target_count: int = 0
    signed_count: int = 0
    link: str = ""


class AttendanceOverviewResponse(BaseModel):
    """点名与签到合并后的分页列表"""
    total: int
    items: list[AttendanceOverviewItem]


class AttendanceItemUpdate(BaseModel):
    """改某人状态"""
    status: str = Field(..., pattern=STATUS_PATTERN)


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
