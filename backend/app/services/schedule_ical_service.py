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
from .schedule_service import first_occurrence


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
    return _fold(buf.getvalue())


def _fold(raw: str) -> str:
    """把每行按 RFC5545 折到 75 字节以内（UTF-8 计），续行以一个空格开头

    中文一个字 3 字节，一条长备注整行能到两三百字节。不折的话多数客户端能忍，
    但严格按标准的（以及部分手机自带日历）会把整行丢掉。
    """
    out: list[str] = []
    for line in raw.split("\r\n"):
        if len(line.encode("utf-8")) <= 75:
            out.append(line)
            continue
        # 按字符累加：不能按字节切，会把一个汉字劈成两半
        chunk, size = "", 0
        for ch in line:
            n = len(ch.encode("utf-8"))
            if size + n > 75:
                out.append(chunk)
                chunk, size = " " + ch, 1 + n   # 续行的行首空格也算在这 75 字节里
            else:
                chunk += ch
                size += n
        out.append(chunk)
    return "\r\n".join(out)


def _write_event(buf: StringIO, tpl) -> None:
    """写一个 VEVENT"""
    buf.write("BEGIN:VEVENT\r\n")

    # UID：用 schedule id + 域名后缀
    uid = f"schedule-{tpl.id}@class-oa"
    buf.write(f"UID:{uid}\r\n")

    # 时间戳：RFC5545 要求 DTSTAMP 是 UTC
    buf.write(f"DTSTAMP:{_format_dt_utc(tpl.created_at or datetime.now())}\r\n")

    # 开始/结束时间。日期用**页面上那个第一个发生日**（见 first_occurrence）：
    # 单双周的模板开始日可能落在相反的一周，直接拿它当 DTSTART，整条订阅会和
    # 网页上看到的日子错开一周。时刻和时长照旧。
    day = first_occurrence(tpl)
    start_dt = datetime.combine(day, tpl.start_time.time())
    end_dt = start_dt + (tpl.end_time - tpl.start_time)

    if tpl.all_day:
        # 全天事件：DATE 格式
        buf.write(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}\r\n")
        # 全天事件的 DTEND 是「第二天」（iCal 全天事件是半开区间）
        buf.write(f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}\r\n")
    else:
        buf.write(f"DTSTART:{_format_dt(start_dt)}\r\n")
        buf.write(f"DTEND:{_format_dt(end_dt)}\r\n")

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
        # 这里必须用真正的换行符拼：_escape_text 会把它转成 iCal 的 \n。
        # 写成 '\\n' 的话那是一个「反斜杠 + n」的两字符串，再被转义成 \\n，
        # 客户端拿到的是字面的两个字符，而不是换行
        desc = _escape_text("\n".join(desc_parts))
        buf.write(f"DESCRIPTION:{desc}\r\n")

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
        # 每月第 N 天。31 号例外：页面那边没有 31 号的月份取月末（2 月落到 28），
        # 而 BYMONTHDAY=31 会把 2、4、6 月整个跳过 —— 用 -1（当月最后一天）才对得上
        day = tpl.start_time.day
        parts.append(f"BYMONTHDAY={-1 if day == 31 else day}")
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

    # 结束日期。UNTIL 的取值类型必须和 DTSTART 一致：上面写的 DTSTART 是浮动本地
    # 时间（不带 Z、不带 TZID），全天事件则是 DATE，所以 UNTIL 也得是这两种之一，
    # 给浮动时间配一个 UTC 的 UNTIL 是不合 RFC5545 的（会被当成「UTC 的某一刻」）
    if tpl.all_day:
        parts.append(f"UNTIL={tpl.repeat_end_date.strftime('%Y%m%d')}")
    else:
        until_dt = datetime.combine(tpl.repeat_end_date, tpl.end_time.time())
        parts.append(f"UNTIL={_format_dt(until_dt)}")

    return ";".join(parts)


def _format_dt(dt: datetime) -> str:
    """格式化 datetime 为 iCal 的本地时间格式 YYYYMMDDTHHMMSS"""
    return dt.strftime("%Y%m%dT%H%M%S")


def _format_dt_utc(dt: datetime) -> str:
    """格式化 datetime 为 iCal 的 UTC 时间格式 YYYYMMDDTHHMMSSZ

    库里存的是本地墙上时间（容器里 TZ=Asia/Shanghai），减 8 小时就是 UTC。
    只给 DTSTAMP 用 —— RRULE 的 UNTIL 必须和 DTSTART 同为浮动本地时间，不能带 Z。
    """
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
