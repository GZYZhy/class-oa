"""日程模型

数据模型设计要点：

1. **每条日程只属于一个学生** —— 不存在「全局公共日程表」。
   班委批量分配的日程，本质是把日程复制写入每个目标学生的日程库，
   通过 source_batch_id 溯源和统一管理。

2. **重复日程只存一条模板** —— repeat_type + repeat_end_date 描述周期，
   查询时由 service 层展开成具体实例（前端看到的是展开后的）。
   这样编辑「本次及以后」只需改一条记录，不会产生 N 条独立数据。

3. **通知是每条日程的独立属性** —— notify_enabled 默认 False，
   未开启的日程一律不推送，绝不默认通知。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from ..database import Base

# 重复类型常量。词表只定义这一份，schema / service / 前端都从这里取。
REPEAT_NONE = "none"
REPEAT_WEEKLY = "weekly"          # 每周重复
REPEAT_MONTHLY = "monthly"        # 每月重复
REPEAT_ODD_WEEK = "odd_week"      # 单周重复
REPEAT_EVEN_WEEK = "even_week"    # 双周重复

REPEAT_TYPES = (REPEAT_NONE, REPEAT_WEEKLY, REPEAT_MONTHLY, REPEAT_ODD_WEEK, REPEAT_EVEN_WEEK)

# 来源类型
SOURCE_PERSONAL = "personal"      # 个人自建
SOURCE_BATCH = "batch"            # 班委批量分配

SOURCE_TYPES = (SOURCE_PERSONAL, SOURCE_BATCH)

# 编辑/删除范围
SCOPE_SINGLE = "single"           # 仅本次
SCOPE_FORWARD = "forward"         # 本次及以后
SCOPE_ALL = "all"                 # 全部

EDIT_SCOPES = (SCOPE_SINGLE, SCOPE_FORWARD, SCOPE_ALL)

# 一天的时间范围（与前端日历一致）
DAY_START_HOUR = 7     # 07:00
DAY_END_HOUR = 22      # 22:00（不含，最后一格是 21:50 开始）
TIME_SLOT_MINUTES = 10  # 每格 10 分钟


class Schedule(Base):
    """日程主表 —— 一个学生的一条日程（可能是重复日程的模板）

    start_time / end_time 是带具体日期的「第一次」或「单次那一次」的时间。
    重复日程由 service 层在查询时按 repeat_type 展开。
    """
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, index=True, nullable=False, comment="所属学生 ID")

    title = Column(String(200), nullable=False, comment="日程标题")
    event_type = Column(String(20), default="", comment="事件类型，如 课程/体育/网络课；导入时识别")
    location = Column(String(200), default="", comment="地点")
    description = Column(Text, default="", comment="备注")

    # 单次日程：就是具体那一次的起止
    # 重复日程：是第一次的起止（时间部分作为每天的起止模板）
    start_time = Column(DateTime, nullable=False, index=True, comment="开始时间")
    end_time = Column(DateTime, nullable=False, comment="结束时间")

    all_day = Column(Boolean, default=False, comment="是否全天事件")

    repeat_type = Column(
        String(20), nullable=False, default=REPEAT_NONE,
        comment=f"重复类型：{' / '.join(REPEAT_TYPES)}",
    )
    repeat_end_date = Column(Date, nullable=True, comment="重复结束日期（含）；不重复则为 null")
    # 单/双周判断的基准：第 1 周的周一（导入课表时从表头推断写入）。
    # 为空时展开退化为「以开始日期所在周为第 1 周」，保证手动创建的单双周在自己的坐标系里自洽。
    week_start = Column(Date, nullable=True, comment="单双周基准（第1周的周一），空则按开始日期所在周推算")

    # 通知开关 —— 默认关闭，严格不默认通知
    notify_enabled = Column(Boolean, default=False, comment="是否开启通知")
    notify_minutes_before = Column(
        Integer, default=10, comment="提前多少分钟提醒（默认 10 分钟）",
    )

    source_type = Column(
        String(20), nullable=False, default=SOURCE_PERSONAL,
        comment=f"来源：{' / '.join(SOURCE_TYPES)}",
    )
    source_batch_id = Column(
        Integer, index=True, nullable=True,
        comment="批量分配批次 ID（source_type=batch 时有值）",
    )
    source_series_id = Column(
        String(64), nullable=True,
        comment="重复序列 ID（同一条原始重复日程展开后共用，方便批量编辑溯源）",
    )

    created_by = Column(Integer, nullable=True, comment="创建人学生 ID（班委批量分配时记录）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")


class ScheduleBatch(Base):
    """批量分配批次表

    班委一次导入或一次批量创建，产生一个批次。
    用于溯源、统一撤销（删除整个批次的所有日程）。
    """
    __tablename__ = "schedule_batches"

    id = Column(Integer, primary_key=True, index=True)
    operator_id = Column(Integer, nullable=False, comment="操作人（班委）学生 ID")
    operator_name = Column(String(50), comment="操作人姓名（快照）")

    name = Column(String(200), nullable=False, comment="批次名称，如「2026 秋季学期课表」")
    target_count = Column(Integer, default=0, comment="目标学生数")
    schedule_count = Column(Integer, default=0, comment="日程条数（每个学生的日程数）")

    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class ICalToken(Base):
    """iCal 订阅令牌表

    每个学生一个有效 token，用于外部日历客户端订阅。
    token 用 uuid4 hex（32 位），防猜解。
    重置 = 旧 token 置无效 + 生成新 token。
    """
    __tablename__ = "ical_tokens"
    __table_args__ = (
        # 一人只允许一个有效 token
        UniqueConstraint("student_id", "is_active", name="uq_ical_student_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, index=True, nullable=False, comment="学生 ID")

    token = Column(String(64), unique=True, nullable=False, comment="令牌（uuid4 hex）")
    is_active = Column(Boolean, default=True, comment="是否有效")

    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    last_accessed_at = Column(DateTime, nullable=True, comment="最后访问时间")
