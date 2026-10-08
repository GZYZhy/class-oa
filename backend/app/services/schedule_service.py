"""日程服务 —— CRUD、重复日程展开、批量分配

设计要点：

1. **重复日程的存储与展开**
   存储只存一条模板（start_time 是第一次的开始时间），查询时由
   `expand_schedules` 函数在给定日期范围内展开成具体实例。
   这样编辑「本次及以后」只需改一条模板记录，不用维护 N 条独立数据。

2. **编辑/删除范围**
   - single（仅本次）：把原模板在本次处拆分成两段，本次变成独立日程
   - forward（本次及以后）：修改原模板的 start_time 到本次日期，并应用新字段
   - all（全部）：直接改模板

3. **批量分配**
   班委创建日程时如果选了多人，系统为每个目标学生各创建一条日程记录，
   它们共享同一个 source_batch_id，便于后续统一管理。

   批次里可能有很多条互不相干的日程（导入一整张课表就是这样），所以「哪些
   记录是同一条日程的副本」另用 source_series_id 标记：一条原始日程一个 ID，
   发给多少人就复制多少份、共用这个 ID。改/删时靠它找到其他学生的副本
   （见 update_shared / delete_shared）。
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Schedule, ScheduleBatch, Student, User
from ..models.schedule import (
    DAY_END_HOUR,
    DAY_START_HOUR,
    EDIT_SCOPES,
    REPEAT_EVEN_WEEK,
    REPEAT_MONTHLY,
    REPEAT_NONE,
    REPEAT_ODD_WEEK,
    REPEAT_TYPES,
    REPEAT_WEEKLY,
    SCOPE_ALL,
    SCOPE_FORWARD,
    SCOPE_SINGLE,
    SOURCE_BATCH,
    SOURCE_PERSONAL,
    TIME_SLOT_MINUTES,
)


# ---------- 工具函数 ----------

def _week_of_school(d: date, semester_start: Optional[date] = None) -> int:
    """计算某一天是第几周（1-based）。

    以 semester_start（期望是某周的周一）为第 1 周的起点。
    没有就按 1 月 1 日所在周的周一估算，兜底用。
    注：周一为一周的开始。
    """
    if semester_start is None:
        # 1 月 1 日所在周的周一
        jan1 = date(d.year, 1, 1)
        jan1_weekday = jan1.weekday()  # 0=周一
        week1_monday = jan1 - timedelta(days=jan1_weekday)
    else:
        week1_monday = semester_start - timedelta(days=semester_start.weekday())
    days = (d - week1_monday).days
    return days // 7 + 1


def _is_odd_week(d: date, semester_start: Optional[date] = None) -> bool:
    """判断某天是不是单周"""
    return _week_of_school(d, semester_start) % 2 == 1


def _week_base(template) -> date:
    """单双周判断的基准日（第 1 周的周一）

    优先用模板上持久化的 week_start（课表导入时写入，能对上真实学期）；
    为空就退回「以该日程开始日期所在周为第 1 周」，保证手动创建的单双周自洽。
    """
    if template.week_start:
        return template.week_start
    s = template.start_time.date()
    return s - timedelta(days=s.weekday())


def _next_occurrence(
    template: Schedule,
    from_date: date,
    semester_start: Optional[date] = None,
) -> Optional[date]:
    """给定模板和起始日期，找出 >= from_date 的下一个发生日期。

    返回 None 表示在 repeat_end_date 之后没有了。
    """
    start_date = template.start_time.date()
    end_date = template.repeat_end_date or start_date

    if template.repeat_type == REPEAT_NONE:
        if start_date >= from_date and start_date <= end_date:
            return start_date
        return None

    # 从模板的起始日期开始，按周期找
    cursor = max(start_date, from_date)
    if cursor > end_date:
        return None

    if template.repeat_type == REPEAT_WEEKLY:
        # 找到 cursor 之后第一个与 start_date 星期相同的日期
        diff_days = (cursor - start_date).days
        remainder = diff_days % 7
        if remainder != 0:
            cursor += timedelta(days=7 - remainder)
        if cursor <= end_date:
            return cursor
        return None

    if template.repeat_type in (REPEAT_ODD_WEEK, REPEAT_EVEN_WEEK):
        # 先找到下一个同星期的日期
        diff_days = (cursor - start_date).days
        remainder = diff_days % 7
        if remainder != 0:
            cursor += timedelta(days=7 - remainder)
        # 然后逐周跳，直到满足单/双周条件。
        # 奇偶以「第1周基准」为准（见 _week_base），保证和课表导入的周次对上
        base = _week_base(template)
        target_odd = template.repeat_type == REPEAT_ODD_WEEK
        while cursor <= end_date:
            if _is_odd_week(cursor, base) == target_odd:
                return cursor
            cursor += timedelta(days=7)
        return None

    if template.repeat_type == REPEAT_MONTHLY:
        # 每月同一天；如果当月没有那一天（如 31 号），取月末
        target_day = start_date.day
        # 找到 cursor 所在月或之后月份的 target_day
        year, month = cursor.year, cursor.month
        while True:
            # 计算这个月的 target_day
            if month == 12:
                next_month_year, next_month = year + 1, 1
            else:
                next_month_year, next_month = year, month + 1
            # 本月最后一天
            last_day = (date(next_month_year, next_month, 1) - timedelta(days=1)).day
            actual_day = min(target_day, last_day)
            candidate = date(year, month, actual_day)
            if candidate >= cursor and candidate <= end_date:
                return candidate
            if candidate > end_date:
                return None
            # 跳到下个月
            year, month = next_month_year, next_month

    return None


def _prev_occurrence(
    template: Schedule,
    to_date: date,
    semester_start: Optional[date] = None,
) -> Optional[date]:
    """给定模板和结束日期，找出 <= to_date 的最后一个发生日期

    简单实现：从模板起始日期开始一个个找，直到下一个超过 to_date，
    返回上一个。重复次数不会太大（一学期 20 周顶天），这样写不容易错。
    """
    start_date = template.start_time.date()
    if start_date > to_date:
        return None

    if template.repeat_type == REPEAT_NONE:
        return start_date if start_date <= to_date else None

    end_date = template.repeat_end_date or start_date
    effective_end = min(end_date, to_date)

    # 逐个迭代找最后一个
    last = None
    cursor = start_date
    while cursor <= effective_end:
        occ = _next_occurrence(template, cursor, semester_start)
        if occ is None or occ > effective_end:
            break
        last = occ
        cursor = occ + timedelta(days=1)
    return last


def _generate_series_id() -> str:
    """生成重复序列 ID（uuid4 hex）"""
    return uuid.uuid4().hex


# ---------- 查询 ----------

def list_by_range(
    db: Session,
    student_id: int,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """查询某学生在 [start_date, end_date] 范围内的日程（已展开）

    返回的是 dict 列表，每个 dict 是一个具体日程实例，字段：
    id, template_id, title, location, description, start_time, end_time,
    all_day, repeat_type, repeat_end_date, notify_enabled, notify_minutes_before,
    source_type, source_batch_id, instance_date
    """
    # 先取所有可能落在范围内的模板
    # - 单次日程：start_time.date 在范围内
    # - 重复日程：start_time <= end_date 且 (repeat_end_date is null 或 repeat_end_date >= start_date)
    from sqlalchemy import or_, and_

    templates = (
        db.query(Schedule)
        .filter(
            Schedule.student_id == student_id,
            or_(
                # 不重复：开始日期在范围内
                and_(
                    Schedule.repeat_type == REPEAT_NONE,
                    Schedule.start_time >= datetime.combine(start_date, datetime.min.time()),
                    Schedule.start_time <= datetime.combine(end_date, datetime.max.time()),
                ),
                # 重复：模板结束日期 >= 范围开始 且 模板开始日期 <= 范围结束
                and_(
                    Schedule.repeat_type != REPEAT_NONE,
                    Schedule.start_time <= datetime.combine(end_date, datetime.max.time()),
                    or_(
                        Schedule.repeat_end_date.is_(None),
                        Schedule.repeat_end_date >= start_date,
                    ),
                ),
            ),
        )
        .order_by(Schedule.start_time)
        .all()
    )

    # 只查自己分配出去的那些：别人发给你的那份你没资格下发，前端也不该出现这一档
    counts = share_counts(db, templates, student_id)

    instances = []
    for tpl in templates:
        share_count = counts.get(tpl.source_series_id, 1)
        if tpl.repeat_type == REPEAT_NONE:
            d = tpl.start_time.date()
            if start_date <= d <= end_date:
                instances.append(_to_instance(tpl, d, share_count))
        else:
            # 展开重复日程
            cursor = start_date
            effective_end = tpl.repeat_end_date or tpl.start_time.date()
            # 范围取交集
            range_end = min(end_date, effective_end)
            if range_end < cursor:
                continue
            # 从 cursor 开始找下一个发生日期
            occ = _next_occurrence(tpl, cursor)
            while occ is not None and occ <= range_end:
                instances.append(_to_instance(tpl, occ, share_count))
                # 找下一个
                occ = _next_occurrence(tpl, occ + timedelta(days=1))

    # 按开始时间排序
    instances.sort(key=lambda x: x["start_time"])
    return instances


def _to_instance(tpl: Schedule, instance_date: date, share_count: int = 1) -> dict:
    """把模板 + 具体日期展开成一个日程实例 dict

    share_count：这条日程现在在几个学生的表里（见 share_counts）。只有
    list_by_range 会传真实值，别处保持默认 1 即可。
    """
    t = tpl.start_time.time()
    e = tpl.end_time.time()
    # 如果结束时间 < 开始时间（跨天），实际场景不太会有，这里简单处理
    start_dt = datetime.combine(instance_date, t)
    end_dt = datetime.combine(instance_date, e)

    return {
        "id": tpl.id,
        "template_id": tpl.id,
        "title": tpl.title,
        "event_type": tpl.event_type or "",
        "location": tpl.location or "",
        "description": tpl.description or "",
        "start_time": start_dt,
        "end_time": end_dt,
        "all_day": tpl.all_day,
        "repeat_type": tpl.repeat_type,
        "repeat_end_date": tpl.repeat_end_date,
        "notify_enabled": tpl.notify_enabled,
        "notify_minutes_before": tpl.notify_minutes_before or 10,
        "source_type": tpl.source_type,
        "source_batch_id": tpl.source_batch_id,
        "instance_date": instance_date,
        "share_count": share_count,
    }


def get_template(db: Session, schedule_id: int, student_id: int) -> Optional[Schedule]:
    """按 ID 取日程模板（带学生权限过滤）"""
    return (
        db.query(Schedule)
        .filter(Schedule.id == schedule_id, Schedule.student_id == student_id)
        .first()
    )


# ---------- 创建 ----------

def create_schedule(
    db: Session,
    student_id: int,
    data: dict,
    source_type: str = SOURCE_PERSONAL,
    source_batch_id: Optional[int] = None,
    created_by: Optional[int] = None,
    source_series_id: Optional[str] = None,
) -> Schedule:
    """为单个学生创建一条日程（模板）

    source_series_id：分组 ID（同一条原始日程的副本共用）。批量分配时由
    create_batch 统一生成传进来，这样多个学生的副本才能互相认出来。个人
    日程没有副本，自己一个 ID 即可。
    """
    series_id = source_series_id or _generate_series_id()

    schedule = Schedule(
        student_id=student_id,
        title=data["title"],
        event_type=data.get("event_type", ""),
        location=data.get("location", ""),
        description=data.get("description", ""),
        start_time=data["start_time"],
        end_time=data["end_time"],
        all_day=data.get("all_day", False),
        repeat_type=data.get("repeat_type", REPEAT_NONE),
        repeat_end_date=data.get("repeat_end_date"),
        week_start=data.get("week_start"),
        notify_enabled=data.get("notify_enabled", False),
        notify_minutes_before=data.get("notify_minutes_before", 10),
        source_type=source_type,
        source_batch_id=source_batch_id,
        source_series_id=series_id,
        created_by=created_by,
    )
    db.add(schedule)
    db.flush()
    return schedule


def create_batch(
    db: Session,
    operator_id: int,
    operator_name: str,
    batch_name: str,
    schedules_data: list[dict],
    target_student_ids: list[int],
) -> ScheduleBatch:
    """批量创建日程（为多个学生各创建一组日程）

    返回批次记录。
    """
    batch = ScheduleBatch(
        operator_id=operator_id,
        operator_name=operator_name,
        name=batch_name or "批量日程",
        target_count=len(target_student_ids),
        schedule_count=len(schedules_data),
    )
    db.add(batch)
    db.flush()

    # 分组 ID 在「每条日程」这一层生成，不能放在学生循环里 —— 同一个学生拿到的
    # 每条日程要各不相同（导入一张课表就有几十条），而不同学生的同一节课要相同。
    group_ids = [_generate_series_id() for _ in schedules_data]

    for sid in target_student_ids:
        for sched_data, group_id in zip(schedules_data, group_ids):
            create_schedule(
                db,
                student_id=sid,
                data=sched_data,
                source_type=SOURCE_BATCH,
                source_batch_id=batch.id,
                created_by=operator_id,
                source_series_id=group_id,
            )

    return batch


# ---------- 更新 ----------

def update_schedule(
    db: Session,
    schedule_id: int,
    student_id: int,
    update_data: dict,
    scope: str = SCOPE_ALL,
    instance_date: Optional[date] = None,
) -> int:
    """更新日程。返回受影响的日程数。

    scope:
    - all：直接改模板
    - single：只改本次（把本次从重复序列里拆出来变成独立日程）
    - forward：本次及以后（原模板截断到前一天，新建一条从本次开始的新模板）
    """
    if scope not in EDIT_SCOPES:
        scope = SCOPE_ALL

    tpl = get_template(db, schedule_id, student_id)
    if not tpl:
        return 0

    # 单次日程 或 全部修改：直接改模板
    if tpl.repeat_type == REPEAT_NONE or scope == SCOPE_ALL:
        for key, value in update_data.items():
            if value is not None and hasattr(tpl, key):
                setattr(tpl, key, value)
        db.flush()
        return 1

    # 以下是重复日程的 single / forward 场景
    assert instance_date is not None, "编辑重复日程的 single/forward 必须传 instance_date"

    # 先保存原模板的关键信息（后面要改 tpl）
    original_end = tpl.repeat_end_date or tpl.start_time.date()
    original_start_time = tpl.start_time.time()
    original_end_time = tpl.end_time.time()

    if scope == SCOPE_SINGLE:
        # 思路：
        # 1. 原模板结束日期截断到 instance_date 前一天（前半段）
        # 2. 本次拆出来变成独立日程（应用新字段）
        # 3. 后面还有的话，原模板起始跳到下次（后半段）
        prev_date = instance_date - timedelta(days=1)
        next_date = instance_date + timedelta(days=1)

        # 本次变成独立日程（应用新字段）
        merged = _apply_update_to_dict(_to_instance(tpl, instance_date), update_data)
        merged["repeat_type"] = REPEAT_NONE
        merged["repeat_end_date"] = None
        create_schedule(
            db, student_id=student_id, data=merged,
            source_type=tpl.source_type, source_batch_id=tpl.source_batch_id,
            created_by=tpl.created_by,
            # 拆分出来的这一段还是同一条原始日程，分组 ID 必须跟着走，
            # 否则拆一次就和别人表里的副本认不出来了
            source_series_id=tpl.source_series_id,
        )

        # 判断后面还有没有。此时原模板还没被改过（上面只新建了独立日程），
        # 直接基于原模板算下一次即可，不必复制。
        next_occ = _next_occurrence(tpl, next_date)

        if next_occ is not None and next_occ <= original_end:
            # 前后都还有：原模板改成从 next_occ 开始，到 original_end 结束
            tpl.start_time = datetime.combine(next_occ, original_start_time)
            tpl.end_time = datetime.combine(next_occ, original_end_time)
            tpl.repeat_end_date = original_end
        else:
            # 后面没有了：原模板缩短到前一天
            tpl.repeat_end_date = prev_date

        db.flush()
        return 1

    if scope == SCOPE_FORWARD:
        # 思路：
        # 1. 原模板结束日期截断到前一天（前半段保留）
        # 2. 新建一条从本次开始的新模板（应用新字段，后半段）
        prev_date = instance_date - timedelta(days=1)

        # 新模板字段：以 instance 为基础，应用 update_data
        new_data = _apply_update_to_dict(_to_instance(tpl, instance_date), update_data)
        # 重复规则：update_data 里没指定就沿用原模板的
        if "repeat_type" not in update_data or update_data["repeat_type"] is None:
            new_data["repeat_type"] = tpl.repeat_type
        if "repeat_end_date" not in update_data or update_data["repeat_end_date"] is None:
            new_data["repeat_end_date"] = original_end

        create_schedule(
            db, student_id=student_id, data=new_data,
            source_type=tpl.source_type, source_batch_id=tpl.source_batch_id,
            created_by=tpl.created_by,
            source_series_id=tpl.source_series_id,  # 后半段同属一条原始日程
        )

        # 原模板缩短到前一天
        tpl.repeat_end_date = prev_date

        db.flush()
        return 1

    return 0


def _apply_update_to_dict(instance: dict, update_data: dict) -> dict:
    """把 update_data 里的非 None 字段应用到 instance dict，返回新 dict"""
    result = dict(instance)
    for key, value in update_data.items():
        if value is not None and key in result:
            result[key] = value
    # 重新计算 start_time / end_time 如果日期相关字段变了
    return result


# ---------- 删除 ----------

def delete_schedule(
    db: Session,
    schedule_id: int,
    student_id: int,
    scope: str = SCOPE_ALL,
    instance_date: Optional[date] = None,
) -> int:
    """删除日程。返回删除的条数。

    scope 同 update_schedule。
    """
    if scope not in EDIT_SCOPES:
        scope = SCOPE_ALL

    tpl = get_template(db, schedule_id, student_id)
    if not tpl:
        return 0

    if tpl.repeat_type == REPEAT_NONE or scope == SCOPE_ALL:
        db.delete(tpl)
        db.flush()
        return 1

    assert instance_date is not None, "删除重复日程的 single/forward 必须传 instance_date"

    if scope == SCOPE_SINGLE:
        # 只删本次：分三种情况
        # 1. 是第一次：起始跳到下一次
        # 2. 是最后一次：结束日期提前到上一次
        # 3. 中间的：拆成两段（前半段 + 后半段）
        # 防御：重复日程按约定必有 repeat_end_date；万一没有，兜底成开始日期，
        # 避免下面 `next_occ > original_end` 对 None 做比较抛 TypeError。
        original_end = tpl.repeat_end_date or tpl.start_time.date()
        original_start_date = tpl.start_time.date()
        start_time = tpl.start_time.time()
        end_time = tpl.end_time.time()

        prev_date = instance_date - timedelta(days=1)
        next_date = instance_date + timedelta(days=1)

        is_first = instance_date == original_start_date
        # 判断是不是最后一次：下一次之后有没有了
        next_occ = _next_occurrence(tpl, next_date)
        is_last = next_occ is None or next_occ > original_end

        if is_first and is_last:
            # 唯一的一次：直接改成不重复的单次日程，再删掉
            db.delete(tpl)
        elif is_first:
            # 是第一次：起始跳到下一次
            tpl.start_time = datetime.combine(next_occ, start_time)
            tpl.end_time = datetime.combine(next_occ, end_time)
        elif is_last:
            # 是最后一次：结束日期提前到上一次（prev_date 之前的那个发生日）
            # 找 prev_date 及之前的最后一个发生日
            prev_occ = _prev_occurrence(tpl, prev_date)
            if prev_occ:
                tpl.repeat_end_date = prev_occ
            else:
                tpl.repeat_end_date = prev_date  # 兜底
        else:
            # 中间的：拆成两段
            # 前半段：原模板，结束日期 = 上一次
            prev_occ = _prev_occurrence(tpl, prev_date)
            if prev_occ:
                tpl.repeat_end_date = prev_occ
            else:
                tpl.repeat_end_date = prev_date

            # 后半段：新建一条模板，起始 = 下一次，结束 = original_end
            new_data = {
                "title": tpl.title,
                "event_type": tpl.event_type or "",
                "location": tpl.location or "",
                "description": tpl.description or "",
                "start_time": datetime.combine(next_occ, start_time),
                "end_time": datetime.combine(next_occ, end_time),
                "all_day": tpl.all_day,
                "repeat_type": tpl.repeat_type,
                "repeat_end_date": original_end,
                "notify_enabled": tpl.notify_enabled,
                "notify_minutes_before": tpl.notify_minutes_before or 10,
            }
            create_schedule(
                db, student_id=student_id, data=new_data,
                source_type=tpl.source_type, source_batch_id=tpl.source_batch_id,
                created_by=tpl.created_by,
                source_series_id=tpl.source_series_id,  # 后半段同属一条原始日程
            )

        db.flush()
        return 1

    if scope == SCOPE_FORWARD:
        # 删除本次及以后：原模板结束日期 = 前一天
        tpl.repeat_end_date = instance_date - timedelta(days=1)
        db.flush()
        return 1

    return 0


# ---------- 跨学生下发 ----------

def share_counts(
    db: Session,
    templates: list[Schedule],
    student_id: int,
) -> dict[str, int]:
    """分组 ID → 这条原始日程在几个学生的表里（只算自己分配出去的）

    用实际查出来的条数，不用 ScheduleBatch.target_count：那是创建时的快照，
    有人删了自己那份之后就不准了。别人发给你的那份不计入 —— 你没资格再往下发，
    前端也不该出现这一档。缺席的分组由调用方按 1 处理。
    """
    group_ids = [
        t.source_series_id
        for t in templates
        if t.source_series_id and t.source_batch_id and t.created_by == student_id
    ]
    if not group_ids:
        return {}

    rows = (
        db.query(
            Schedule.source_series_id,
            func.count(func.distinct(Schedule.student_id)),
        )
        .filter(Schedule.source_series_id.in_(group_ids))
        .group_by(Schedule.source_series_id)
        .all()
    )
    return {group_id: count for group_id, count in rows}


def can_share(tpl: Schedule, student_id: int) -> bool:
    """这条日程的副本能不能由当前学生下发 —— 只有分配它的那个人可以"""
    return bool(tpl.source_batch_id) and tpl.created_by == student_id


def _share_copies(db: Session, tpl: Schedule) -> list[Schedule]:
    """同一条原始日程在其他学生表里的副本（不含自己那份）

    返回的是「行」不是「学生」：同一个学生在同一分组里可能不止一行（他自己用
    「本次及以后」拆过就成了两条模板），这些都要照顾到，所以不能按学生去重。
    """
    if not tpl.source_series_id:
        # 老数据没有分组 ID，认不出副本，当作只有自己一条
        return []
    return (
        db.query(Schedule)
        .filter(
            Schedule.source_series_id == tpl.source_series_id,
            Schedule.student_id != tpl.student_id,
        )
        .all()
    )


def _occurs_on(tpl: Schedule, d: date) -> bool:
    """d 是不是这条日程的一个发生日"""
    if tpl.repeat_type == REPEAT_NONE:
        return tpl.start_time.date() == d
    return _next_occurrence(tpl, d) == d


def update_shared(
    db: Session,
    tpl: Schedule,
    update_data: dict,
    scope: str = SCOPE_ALL,
    instance_date: Optional[date] = None,
) -> int:
    """改这条日程，并下发到同一条原始日程的其他副本。返回受影响的条数。

    scope=single/forward 是「针对某一次」的操作，只对确实包含这一次的副本生效，
    别人自己改过的那部分不碰：硬套的话 forward 会把他的结束日期截到开始日期之前，
    展开成空区间等于静默删掉他的日程；single 更会凭空造一个他从没有过的日期。
    """
    copies = _share_copies(db, tpl)
    if scope != SCOPE_ALL and instance_date is not None:
        copies = [c for c in copies if _occurs_on(c, instance_date)]

    # 先取好副本再动手：single/forward 会在同一分组里新建记录，不能被卷进这一轮
    total = update_schedule(db, tpl.id, tpl.student_id, update_data, scope, instance_date)
    for copy in copies:
        total += update_schedule(
            db, copy.id, copy.student_id, update_data, scope, instance_date
        )
    return total


def delete_shared(
    db: Session,
    tpl: Schedule,
    scope: str = SCOPE_ALL,
    instance_date: Optional[date] = None,
) -> int:
    """删这条日程，并下发到同一条原始日程的其他副本。返回删除的条数（守卫同上）"""
    copies = _share_copies(db, tpl)
    if scope != SCOPE_ALL and instance_date is not None:
        copies = [c for c in copies if _occurs_on(c, instance_date)]

    total = delete_schedule(db, tpl.id, tpl.student_id, scope, instance_date)
    for copy in copies:
        total += delete_schedule(db, copy.id, copy.student_id, scope, instance_date)
    return total


# ---------- 批量管理 ----------

def delete_batch(db: Session, batch_id: int, operator_id: int) -> int:
    """撤销整个批次（删除该批次下所有学生的所有日程）

    返回删除的日程条数。operator_id 用于校验权限。
    """
    batch = db.query(ScheduleBatch).filter(ScheduleBatch.id == batch_id).first()
    if not batch:
        return 0
    if batch.operator_id != operator_id:
        # 不是自己创建的批次：管理员也不允许删（简单原则）
        return 0

    count = (
        db.query(Schedule)
        .filter(Schedule.source_batch_id == batch_id)
        .delete(synchronize_session=False)
    )
    db.delete(batch)
    db.flush()
    return count


def list_batches(db: Session, operator_id: int, limit: int = 50) -> list[ScheduleBatch]:
    """查看自己创建的导入批次列表"""
    return (
        db.query(ScheduleBatch)
        .filter(ScheduleBatch.operator_id == operator_id)
        .order_by(ScheduleBatch.created_at.desc())
        .limit(limit)
        .all()
    )


# ---------- iCal token ----------

def get_or_create_ical_token(db: Session, student_id: int) -> tuple[str, str]:
    """获取学生的 iCal 订阅 token（没有就创建）

    返回 (token, url_path) —— URL 路径形如 /api/schedules/ical/{token}.ics
    """
    from ..models.schedule import ICalToken

    row = (
        db.query(ICalToken)
        .filter(
            ICalToken.student_id == student_id,
            ICalToken.is_active == True,  # noqa: E712
        )
        .first()
    )
    if row:
        return row.token, f"/api/schedules/ical/{row.token}.ics"

    token = uuid.uuid4().hex
    row = ICalToken(student_id=student_id, token=token)
    db.add(row)
    db.flush()
    return token, f"/api/schedules/ical/{token}.ics"


def reset_ical_token(db: Session, student_id: int) -> tuple[str, str]:
    """重置 iCal 订阅 token（旧的立即失效，生成新的）

    返回 (新 token, 新 URL)
    """
    from ..models.schedule import ICalToken

    # 旧 token 全部置为无效
    (
        db.query(ICalToken)
        .filter(
            ICalToken.student_id == student_id,
            ICalToken.is_active == True,  # noqa: E712
        )
        .update({ICalToken.is_active: False}, synchronize_session=False)
    )

    token = uuid.uuid4().hex
    row = ICalToken(student_id=student_id, token=token)
    db.add(row)
    db.flush()
    return token, f"/api/schedules/ical/{token}.ics"


def get_student_by_ical_token(db: Session, token: str) -> Optional[tuple[int, ICalToken]]:
    """通过 iCal token 查学生 ID 和 token 记录

    返回 (student_id, token_row) 或 None。
    同时更新 last_accessed_at（节流：每 5 分钟更新一次，避免每次都写库）。
    """
    from ..models.schedule import ICalToken

    row = (
        db.query(ICalToken)
        .filter(
            ICalToken.token == token,
            ICalToken.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not row:
        return None

    # 节流更新最后访问时间（每 5 分钟一次）
    now = datetime.now()
    if row.last_accessed_at is None or (now - row.last_accessed_at).total_seconds() > 300:
        row.last_accessed_at = now
        db.flush()

    return row.student_id, row


# ---------- 通知调度用 ----------

def list_upcoming_notifications(
    db: Session,
    from_time: datetime,
    to_time: datetime,
) -> list[tuple[Schedule, Student, datetime]]:
    """查询 [from_time, to_time] 时间段内需要触发的日程提醒。

    返回列表：[(日程模板, 学生对象, 本次实例的开始时间), ...]

    只返回 notify_enabled=True 的日程。
    每条日程每天最多触发一次（同一天同一重复日程不会重复提醒）。
    """
    # 取所有开启通知的日程模板
    templates = (
        db.query(Schedule)
        .filter(Schedule.notify_enabled == True)  # noqa: E712
        .all()
    )

    results = []
    # 记录已经加进去的 (schedule_id, date)，避免重复
    seen = set()

    for tpl in templates:
        minutes_before = tpl.notify_minutes_before or 10
        # 提醒触发时间 = 开始时间 - 提前量
        # 我们需要找「提醒时间落在 [from_time, to_time] 内」的实例
        # 即「开始时间落在 [from_time + minutes_before, to_time + minutes_before]」内
        range_start = from_time + timedelta(minutes=minutes_before)
        range_end = to_time + timedelta(minutes=minutes_before)

        # 只看范围内的日期
        start_date = range_start.date()
        end_date = range_end.date()

        if tpl.repeat_type == REPEAT_NONE:
            d = tpl.start_time.date()
            if start_date <= d <= end_date:
                notify_time = datetime.combine(d, tpl.start_time.time()) - timedelta(minutes=minutes_before)
                if from_time <= notify_time <= to_time:
                    key = (tpl.id, d)
                    if key not in seen:
                        seen.add(key)
                        student = db.query(Student).filter(Student.id == tpl.student_id).first()
                        if student:
                            results.append((tpl, student, notify_time))
        else:
            effective_end = tpl.repeat_end_date or tpl.start_time.date()
            range_end_date = min(end_date, effective_end)
            if range_end_date < start_date:
                continue
            occ = _next_occurrence(tpl, start_date)
            while occ is not None and occ <= range_end_date:
                notify_time = datetime.combine(occ, tpl.start_time.time()) - timedelta(minutes=minutes_before)
                if from_time <= notify_time <= to_time:
                    key = (tpl.id, occ)
                    if key not in seen:
                        seen.add(key)
                        student = db.query(Student).filter(Student.id == tpl.student_id).first()
                        if student:
                            results.append((tpl, student, notify_time))
                occ = _next_occurrence(tpl, occ + timedelta(days=1))

    return results
