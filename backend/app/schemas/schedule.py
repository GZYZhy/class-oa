"""日程接口的出入参

**这里只放字段形状和长度上限，业务校验一律在 api/schedules.py 里做**：
schema 的 field_validator 抛异常会变成 422，而 detail 是个数组，前端
request.js 的 errText 遇到非字符串只会退回兜底文案，所以「标题空不空」
「结束时间在不在开始之前」都得在接口里判，好回一句能直接显示给用户的中文。
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------- 日程基础 ----------

class ScheduleBase(BaseModel):
    title: str = Field(..., max_length=200, description="日程标题")
    event_type: str = Field("", max_length=20, description="事件类型，如 课程/体育/网络课")
    location: str = Field("", max_length=200, description="地点")
    description: str = Field("", description="备注")
    start_time: datetime = Field(..., description="开始时间")
    end_time: datetime = Field(..., description="结束时间")
    all_day: bool = False
    repeat_type: str = Field("none", description="重复类型：none/weekly/monthly/odd_week/even_week")
    repeat_end_date: Optional[date] = Field(None, description="重复结束日期（含）")
    notify_enabled: bool = Field(False, description="是否开启通知（默认关闭）")
    notify_minutes_before: int = Field(10, ge=1, le=1440, description="提前多少分钟提醒")


class ScheduleCreate(ScheduleBase):
    """新建日程

    班委还可以传 target_student_ids / target_all 做批量分配。
    普通学生传了会被后端忽略（只建自己的）。
    """
    target_all: bool = Field(False, description="是否目标为全部学生（班委用）")
    target_student_ids: list[int] = Field(
        default_factory=list, description="目标学生 ID 列表（班委用，target_all=false 时生效）",
    )


class ScheduleUpdate(BaseModel):
    """编辑日程

    编辑重复日程时通过 scope 控制范围：
    - single：仅本次
    - forward：本次及以后
    - all：全部
    """
    title: Optional[str] = Field(None, max_length=200)
    event_type: Optional[str] = Field(None, max_length=20)
    location: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    all_day: Optional[bool] = None
    repeat_type: Optional[str] = None
    repeat_end_date: Optional[date] = None
    notify_enabled: Optional[bool] = None
    notify_minutes_before: Optional[int] = Field(None, ge=1, le=1440)
    scope: str = Field("all", description="编辑范围：single/forward/all")


class ScheduleResponse(BaseModel):
    """单条日程响应（展开后的实例）

    前端拿到的都是展开后的具体日程实例。
    有 repeat 字段说明它来自重复日程模板，编辑时可选择范围。
    """
    id: int
    # 模板 ID（重复日程的原始记录 ID），用于编辑/删除时定位模板
    template_id: int
    title: str
    event_type: str = ""
    location: str = ""
    description: str = ""
    start_time: datetime
    end_time: datetime
    all_day: bool = False
    repeat_type: str = "none"
    repeat_end_date: Optional[date] = None
    notify_enabled: bool = False
    notify_minutes_before: int = 10
    source_type: str = "personal"
    source_batch_id: Optional[int] = None
    # 本次实例是重复序列中的第几个实例日期（用于 scope=single/forward 判断）
    instance_date: date

    class Config:
        from_attributes = True


# ---------- 导入 ----------

class ScheduleImportPreviewItem(BaseModel):
    """预览时的一条日程（还没入库）"""
    title: str
    event_type: str = ""
    location: str = ""
    description: str = ""
    weekday: int = Field(..., description="星期几，1=周一 ... 7=周日")
    start_date: Optional[date] = Field(None, description="该块落到的具体日期")
    start_time: str = Field(..., description="开始时间 HH:MM")
    end_time: str = Field(..., description="结束时间 HH:MM")
    all_day: bool = False
    repeat_type: str = "none"
    repeat_end_date: Optional[date] = None
    notify_enabled: bool = False
    notify_minutes_before: int = 10
    # 在导入表里的位置，方便用户核对
    sheet: str = ""
    cell_ref: str = ""


class ScheduleImportPreviewResponse(BaseModel):
    """导入预览响应"""
    token: str = Field(..., description="预览令牌，确认导入时用")
    week_count: int = Field(0, description="识别到的周数（sheet 数）")
    schedule_count: int = Field(0, description="识别出的日程块数")
    all_day_count: int = Field(0, description="全天事件数")
    items: list[ScheduleImportPreviewItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="解析警告")


class ScheduleImportConfirm(BaseModel):
    """确认导入请求"""
    token: str = Field(..., description="预览令牌")
    batch_name: str = Field("", max_length=200, description="批次名称")
    target_all: bool = Field(False, description="是否导入给全部学生")
    target_student_ids: list[int] = Field(
        default_factory=list, description="目标学生 ID 列表（target_all=false 时生效）",
    )
    # 选中的日程索引（对应预览返回的 items 下标）。空列表表示全部选中。
    selected_indices: list[int] = Field(default_factory=list)


class ScheduleImportResultResponse(BaseModel):
    """导入结果"""
    batch_id: int
    batch_name: str
    target_count: int = Field(0, description="目标学生数")
    schedule_per_student: int = Field(0, description="每个学生的日程数")
    total_created: int = Field(0, description="总共创建的日程条目数")
    warnings: list[str] = Field(default_factory=list)


# ---------- 批次 ----------

class ScheduleBatchResponse(BaseModel):
    id: int
    name: str
    target_count: int = 0
    schedule_count: int = 0
    operator_name: Optional[str] = ""
    created_at: datetime


# ---------- 学期信息 ----------

class SemesterInfoResponse(BaseModel):
    """学期信息（页面上的「第几周」按它算）"""
    week_start: Optional[date] = Field(
        None, description="学期第 1 周的周一；一条日程都没有时为空",
    )


# ---------- iCal 订阅 ----------

class ICalTokenResponse(BaseModel):
    token: str
    url: str = Field(..., description="完整订阅 URL")
    last_accessed_at: Optional[datetime] = None
