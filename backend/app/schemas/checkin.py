"""签到相关 schema

状态（ongoing/ended）和「能不能签」由 services/checkin_service.py 算好塞进来，
前端只认字段，不自己拿时间重算。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class CheckinLocationIn(BaseModel):
    """发布时选的地点。坐标必须是 GCJ-02（高德坐标系）"""
    lat: float = Field(..., ge=-90, le=90, description="纬度")
    lng: float = Field(..., ge=-180, le=180, description="经度")
    radius_m: int = Field(500, ge=100, le=10000, description="允许的偏移范围（米）")
    name: str = Field("", max_length=200, description="地点名称，可手填")


class CheckinCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100, description="标题")
    remark: str = Field("", max_length=500, description="备注，空串 = 没写")
    targets: list[str] = Field(
        ..., min_length=1, max_length=500, description="范围内学生的学号"
    )
    # 为空 = 发布即可签（兼容老前端）。新前端总会带上，默认是「现在」
    start_at: datetime | None = Field(None, description="开始时间，为空 = 发布即可签")
    end_at: datetime = Field(..., description="截止时间")
    require_photo: bool = Field(False, description="是否要求上传一张照片")
    location: CheckinLocationIn | None = None


class CheckinLocationResponse(BaseModel):
    lat: float
    lng: float
    radius_m: int
    name: str = ""


class CheckinTitleUpdate(BaseModel):
    """改签到的标题

    列表的「备注」列显示的就是标题，关键词搜索也搜它 ——
    所以这个接口改的是标题，不是发布时那句补充说明。
    标题不能清空：空标题在列表里认不出是哪次签到，也没法搜。
    """
    title: str = Field(..., max_length=100, description="签到标题，不能为空")


class CheckinTargetResponse(BaseModel):
    """班委看签到详情时，每个目标的状态

    `on_leave` 是「截止时刻持有已批准请假」—— 他们仍然可以签到，签了就更算「到」；
    没签才按请假结算。前端据此在「待签到」旁边标一句「请假中」。

    `status` 是结算后那条考勤明细里的出勤状态（present/leave/absent），未结算为空。
    结算后班委在详情里改状态，读写的都是考勤明细，两边不会各说各话。
    """
    student_no: str
    student_name: str
    signed_at: datetime | None = None
    distance_m: int | None = None
    on_leave: bool = False
    status: str = ""
    photo_url: str = ""


class CheckinListItem(BaseModel):
    id: int
    code: str
    title: str
    status: str
    created_by_name: str = ""
    created_at: datetime | None = None
    # 为空 = 老数据（发布即可签）
    start_at: datetime | None = None
    end_at: datetime
    target_count: int = 0
    signed_count: int = 0
    link: str = ""


class CheckinListResponse(BaseModel):
    total: int
    items: list[CheckinListItem]


class CheckinDetailResponse(CheckinListItem):
    remark: str = ""
    require_photo: bool = False
    location: CheckinLocationResponse | None = None
    created_by_no: str = ""
    closed_at: datetime | None = None
    finalized_at: datetime | None = None
    # 结算生成的考勤记录；详情里改状态走考勤明细的接口
    attendance_record_id: int | None = None
    targets: list[CheckinTargetResponse] = Field(default_factory=list)


class CheckinPublicResponse(BaseModel):
    """公开信息页看到的全部内容

    游客也拿得到标题、备注、地点和时间；`is_login / is_target / can_sign`
    决定页面上显示哪一句提示。`my_distance_m` 只对登录的目标本人有意义。
    """
    code: str
    title: str
    remark: str = ""
    status: str
    created_by_name: str = ""
    created_at: datetime | None = None
    # 为空 = 老数据（发布即可签）
    start_at: datetime | None = None
    end_at: datetime
    require_photo: bool = False
    location: CheckinLocationResponse | None = None
    target_count: int = 0
    link: str = ""

    is_login: bool = False
    is_target: bool = False
    can_sign: bool = False
    # 已结束、但页面是截止前打开的：补签宽限到这一刻（进行中时为空）
    grace_until: datetime | None = None
    signed_at: datetime | None = None
    my_distance_m: int | None = None
    on_leave: bool = False
