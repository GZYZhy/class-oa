"""iCal (ICS) 日历订阅生成

生成标准 iCalendar 格式文件，支持：
- VEVENT 事件
- 重复日程按 RRULE 输出（FREQ=WEEKLY / MONTHLY 等）
- VALARM 提醒（仅开启通知的日程）
"""

from datetime import datetime, timedelta
from io import StringIO

from sqlalchemy.orm import Session

from ..models.schedule import (
    REPEAT_EVEN_WEEK,
    REPEAT_MONTHLY,
    REPEAT_NONE,
    REPEAT_ODD_WEEK,
    REPEAT_WEEKLY,
)
from .schedule_service import list_by_range


def generate_ical(
    db: Session,
    student_id: int,
    student_name: str,
    range_days: int = 365,
) -> str:
    """生成指定学生的 iCal 文件内容

    range_days：向前/向后各看多少天（默认 365 天，即一年范围）
    """
    from datetime import date

    today = date.today()
    start_date = today - timedelta(days=range_days)
    end_date = today + timedelta(days=range_days)

    # 拿到所有模板（不展开，重复日程直接输出 RRULE）
    # 但 list_by_range 返回的是展开后的 —— 我们需要直接拿模板
    from ..models import Schedule

    templates = (
        db.query(Schedule)
        .filter(Schedule.student_id == student_id)
        .order_by(Schedule.start_time)
        .all()
    )

    buf = StringIO()
    # 日历头部
    buf.write("BEGIN:VCALENDAR\r\n")
    buf.write("VERSION:2.0\r\n")
    buf.write("PRODID:-//class-oa//My Schedule//CN\r\n")
    buf.write(f"X-WR-CALNAME:{_escape_text(student_name)}的日程\r\n")
    buf.write("X-WR-TIMEZONE:Asia/Shanghai\r\n")
    buf.write("CALSCALE:GREGORIAN\r\n")
    buf.write("METHOD:PUBLISH\r\n")

    for tpl in templates:
        _write_event(buf, tpl)

    buf.write("END:VCALENDAR\r\n")
    return buf.getvalue()


def _write_event(buf: StringIO, tpl) -> None:
    """写一个 VEVENT"""
    buf.write("BEGIN:VEVENT\r\n")

    # UID：用 schedule id + 域名后缀
    uid = f"schedule-{tpl.id}@class-oa"
    buf.write(f"UID:{uid}\r\n")

    # 时间戳（创建时间）
    dtstamp = _format_dt(tpl.created_at or datetime.now())
    buf.write(f"DTSTAMP:{dtstamp}\r\n")

    # 开始/结束时间
    if tpl.all_day:
        # 全天事件：DATE 格式
        d = tpl.start_time.date()
        buf.write(f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}\r\n")
        # 全天事件的 DTEND 是「第二天」（iCal 全天事件是半开区间）
        end_d = tpl.end_time.date() + timedelta(days=1)
        buf.write(f"DTEND;VALUE=DATE:{end_d.strftime('%Y%m%d')}\r\n")
    else:
        buf.write(f"DTSTART:{_format_dt(tpl.start_time)}\r\n")
        buf.write(f"DTEND:{_format_dt(tpl.end_time)}\r\n")

    # 标题
    buf.write(f"SUMMARY:{_escape_text(tpl.title)}\r\n")

    # 地点
    if tpl.location:
        buf.write(f"LOCATION:{_escape_text(tpl.location)}\r\n")

    # 描述：优先放备注；导入的事件没有备注时，用「类型：X」补一条，信息不丢
    desc_parts = []
    if tpl.description:
        desc_parts.append(tpl.description)
    elif tpl.event_type:
        desc_parts.append(f"类型：{tpl.event_type}")
    if tpl.source_type == "batch":
        desc_parts.append("（班委分配）")
    if desc_parts:
        buf.write(f"DESCRIPTION:{_escape_text('\\n'.join(desc_parts))}\r\n")

    # 重复规则
    if tpl.repeat_type != REPEAT_NONE and tpl.repeat_type is not None:
        rrule = _build_rrule(tpl)
        if rrule:
            buf.write(f"RRULE:{rrule}\r\n")

    # 提醒（仅开启通知的日程）
    if tpl.notify_enabled and not tpl.all_day:
        minutes = tpl.notify_minutes_before or 10
        buf.write("BEGIN:VALARM\r\n")
        buf.write("ACTION:DISPLAY\r\n")
        buf.write(f"DESCRIPTION:{_escape_text(tpl.title)}\r\n")
        buf.write(f"TRIGGER:-PT{minutes}M\r\n")
        buf.write("END:VALARM\r\n")

    buf.write("END:VEVENT\r\n")


def _build_rrule(tpl) -> str:
    """构建 RRULE 字符串

    iCal 标准：FREQ=WEEKLY;INTERVAL=1;BYDAY=MO;UNTIL=...
    """
    if not tpl.repeat_end_date:
        return ""

    parts = []

    if tpl.repeat_type == REPEAT_WEEKLY:
        parts.append("FREQ=WEEKLY")
        parts.append("INTERVAL=1")
        # 星期几
        weekday = tpl.start_time.weekday()  # 0=周一
        day_codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        parts.append(f"BYDAY={day_codes[weekday]}")
    elif tpl.repeat_type == REPEAT_MONTHLY:
        parts.append("FREQ=MONTHLY")
        parts.append("INTERVAL=1")
        # 每月第 N 天
        day = tpl.start_time.day
        parts.append(f"BYMONTHDAY={day}")
    elif tpl.repeat_type in (REPEAT_ODD_WEEK, REPEAT_EVEN_WEEK):
        # 单双周用 INTERVAL=2 模拟（近似）
        # 严格来说单双周需要知道学期第一周是单周还是双周，
        # 这里退化为每两周重复一次（INTERVAL=2），能覆盖大部分场景
        parts.append("FREQ=WEEKLY")
        parts.append("INTERVAL=2")
        weekday = tpl.start_time.weekday()
        day_codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        parts.append(f"BYDAY={day_codes[weekday]}")
    else:
        return ""

    # 结束日期：UNTIL 要求 UTC 时间，格式 YYYYMMDDTHHMMSSZ
    # iCal 的 UNTIL 是含的，所以用结束日期当天的结束时间
    until_dt = datetime.combine(tpl.repeat_end_date, tpl.end_time.time())
    parts.append(f"UNTIL={_format_dt_utc(until_dt)}")

    return ";".join(parts)


def _format_dt(dt: datetime) -> str:
    """格式化 datetime 为 iCal 的本地时间格式 YYYYMMDDTHHMMSS"""
    return dt.strftime("%Y%m%dT%H%M%S")


def _format_dt_utc(dt: datetime) -> str:
    """格式化 datetime 为 iCal 的 UTC 时间格式 YYYYMMDDTHHMMSSZ

    注意：这里简单按本地时间当 UTC 处理（项目用 Asia/Shanghai 时区），
    实际订阅时苹果日历等客户端会按本地时区解析。
    对于 RRULE 的 UNTIL，iCal 标准要求是 UTC，这里做 +8 小时转换。
    """
    # 北京时间转 UTC：减 8 小时
    utc_dt = dt - timedelta(hours=8)
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")


def _escape_text(text: str) -> str:
    """iCal 文本转义：逗号、分号、反斜杠、换行"""
    if not text:
        return ""
    # 顺序很重要：先转义反斜杠
    text = text.replace("\\", "\\\\")
    text = text.replace(",", "\\,")
    text = text.replace(";", "\\;")
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "")
    return text
