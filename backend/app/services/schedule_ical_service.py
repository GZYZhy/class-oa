"""iCal (ICS) 日历订阅生成

生成标准 iCalendar 格式文件，支持：
- VEVENT 事件
- 重复日程：只有「每周重复」用 RRULE（它和网页逐日等价），其余按网页的口径
  逐次展开成独立事件 —— 见 _write_schedule
- VALARM 提醒（仅开启通知的日程）

**订阅里的事件必须和网页上看到的一模一样**：学生手机上多出网页上没有的日程，
比少一条更糟（他不会知道那是假的）。
"""

from datetime import date, datetime, timedelta
from io import StringIO

from sqlalchemy.orm import Session

from ..models.schedule import REPEAT_WEEKLY
from .schedule_service import list_semester_periods, occurrences_between

# 校园常用坐标 → Apple 结构化地点的显示名。
#
# 为什么按坐标反查、不用 location 文本：多地点日程的 location 是一整串分组教室
# （如「a:浩301,广501 b:广…」），直接塞进 X-TITLE 又长又容易被 Apple 再拿去
# 地理编码；而坐标是补库时已经定好的主地点，用它反查出的名字才和 pin 一致。
# 以后新增地点在补库时一并补这里；查不到就用原 location 文本兜底。
_GEO_TITLES = {
    (39.927123, 116.207772): "教学楼A",
    (39.927924, 116.205482): "教学楼B",
    (39.929579, 116.206914): "教学楼C",
    (39.930125, 116.206675): "教学楼D",
    (39.928333, 116.206833): "办公楼",
    (39.925710, 116.206417): "实验楼",
    (39.928886, 116.209249): "服务中心",
    (39.929464, 116.206248): "礼堂",
    (39.926145, 116.205461): "示例大学新操场",
    (39.926277, 116.205735): "示例大学西区",
    (39.927424, 116.190589): "示例大学示例园大学生公寓",
    (39.927225, 116.209075): "示例大学南门",
    (39.927332, 116.209858): "示例大学宿舍楼",
}


def _apple_location_title(lat: float, lng: float, fallback: str) -> str:
    """结构化地点的显示名：先按坐标找，找不到退回 location 文本"""
    title = _GEO_TITLES.get((round(float(lat), 6), round(float(lng), 6)))
    return title or (fallback or "地点")


def _apple_param_text(value: str) -> str:
    """iCal 参数值：压成一行并加引号，按 RFC 6868 处理 ^ 和双引号

    地点名里可能有逗号、分号、斜杠（分组教室串），引号包起来才不会被当成
    参数分隔符；Apple 对带引号的 X-TITLE 解析是正常的。
    """
    text = " ".join(str(value or "").split())
    text = text.replace("^", "^^").replace('"', "^'")
    return f'"{text}"'


def generate_ical(
    db: Session,
    student_id: int,
    student_name: str,
) -> str:
    """生成指定学生的 iCal 文件内容

    时间范围就是每条日程自己的生命周期（从 start_time 那天到 repeat_end_date
    为止），不做额外的窗口裁剪 —— 重复日程逐次展开，撑不起几千天的量
    （导入的课表每条都是单次日程，本来就一条一条的）。
    """
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

    # 单双周的奇偶要按学期周次算，得用和网页同一份区间
    periods = list_semester_periods(db, student_id)

    for tpl in templates:
        _write_schedule(buf, tpl, periods)

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


def _write_schedule(buf: StringIO, tpl, periods: list) -> None:
    """按这条日程的重复类型，把它该有的 VEVENT 都写出来

    只有「每周重复」能用 RRULE 精确表达：页面口径就是「从开始日每 7 天一次，
    到 repeat_end_date 为止」，与 FREQ=WEEKLY;INTERVAL=1;BYDAY=.. 逐日等价。
    其余类型都表达不了 —— 单双周的奇偶由学期周次号定（没有周次号的周一条都不
    出现，也可能一条都没有），每月是「当月没有那一天就取月末」，RRULE 写不出来。
    这些一律按网页那套口径逐次展开成独立事件：宁可多几条 VEVENT，也不能让学生
    手机上出现网页上没有的日程。

    展开用的是 occurrences_between —— 和网页查询同一个函数。
    """
    start = tpl.start_time.date()
    # 上界取到 repeat_end_date 为止（_next_occurrence 自己也会收口，这里只是别把
    # 循环放出去）。要 max 一下：单次日程的 repeat_end_date 是脏数据时可能早于开始日，
    # 直接拿它当上界会把这条本来该有的日程整条滤掉
    until = max(start, tpl.repeat_end_date or start)
    days = occurrences_between(tpl, periods, start, until)

    # 一条都不发生就整条不写。老代码这里用 first_occurrence 的「兜底成开始日」
    # 硬造一个网页上没有的日子：单周日程的覆盖范围里没有它的周次号时，
    # 页面是空的，订阅里却照发一条
    if not days:
        return

    if tpl.repeat_type == REPEAT_WEEKLY:
        _write_event(buf, tpl, days[0], _uid(tpl.id))
        return

    for day in days:
        # 只写一个 VEVENT 时沿用老的 UID（一次性日程、课表的每一格都是这样），
        # 展开成多条才逐条加日期 —— 内容变了本就该换 UID，没变的不给订阅端
        # 制造无谓的「删了再加」
        _write_event(buf, tpl, day, _uid(tpl.id) if len(days) == 1 else _uid(tpl.id, day))


def _uid(schedule_id: int, day: date | None = None) -> str:
    """事件的 UID。day 为空 = 这个模板只写一个 VEVENT（见 _write_schedule）"""
    if day is None:
        return f"schedule-{schedule_id}@class-oa"
    return f"schedule-{schedule_id}-{day.strftime('%Y%m%d')}@class-oa"


def _write_event(buf: StringIO, tpl, day: date, uid: str) -> None:
    """写一个 VEVENT。day 是它的发生日，uid 由调用方定（见 _write_schedule）"""
    buf.write("BEGIN:VEVENT\r\n")
    buf.write(f"UID:{uid}\r\n")

    # 时间戳：RFC5545 要求 DTSTAMP 是 UTC
    buf.write(f"DTSTAMP:{_format_dt_utc(tpl.created_at or datetime.now())}\r\n")

    # 开始/结束时间。时刻用模板的，日期用传进来的发生日（单双周可能不在开始日那天）
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

    # 坐标：RFC5545 的 GEO 是「纬度;经度」，分号本身不能转义（它是结构分隔符）。
    # 只在成对存在时写 —— 接口层已经保证不会有单个坐标落库，这里再挡一道
    if tpl.lat is not None and tpl.lng is not None:
        buf.write(f"GEO:{tpl.lat};{tpl.lng}\r\n")
        # Apple 日历的地图和「出发时间」认的是这个私有属性，不写它的话
        # 标准 GEO 可能被忽略，仍按 LOCATION 短语重新地理编码（「篮球场」
        # 会被猜到校外同名场地）。geo: 后面是「纬度,经度」，与标准 GEO 相反
        title = _apple_location_title(tpl.lat, tpl.lng, tpl.location)
        buf.write(
            "X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-APPLE-RADIUS=100;"
            f"X-TITLE={_apple_param_text(title)}:geo:{tpl.lat},{tpl.lng}\r\n"
        )

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

    # 重复规则。只有每周重复才写 RRULE，别的类型都是逐次展开出来的独立事件
    # （见 _write_schedule）—— 对展开出来的事件再写一条 RRULE 等于让客户端
    # 自己又长出一堆网页上没有的日子
    if tpl.repeat_type == REPEAT_WEEKLY:
        rrule = _build_rrule(tpl)
        if rrule:
            buf.write(f"RRULE:{rrule}\r\n")

    # 提醒（仅开启通知的日程）
    if tpl.notify_enabled:
        minutes = tpl.notify_minutes_before or 10
        buf.write("BEGIN:VALARM\r\n")
        buf.write("ACTION:DISPLAY\r\n")
        buf.write(f"DESCRIPTION:{_escape_text(tpl.title)}\r\n")
        if tpl.all_day:
            # 全天事件的 DTSTART 是 DATE（当天 00:00），写相对的 `-PT10M` 就是
            # 「当天零点前十来分钟」，但各客户端对全天事件里的相对闹钟解释不一
            # （不少干脆忽略全天事件的闹钟）。写成**绝对时刻**，和 App 推送是
            # 同一个瞬间（schedule_notify_service 那边算的也是「当天 00:00 − 提前量」）
            trigger_at = start_dt - timedelta(minutes=minutes)
            buf.write(f"TRIGGER;VALUE=DATE-TIME:{_format_dt_utc(trigger_at)}\r\n")
        else:
            buf.write(f"TRIGGER:-PT{minutes}M\r\n")
        buf.write("END:VALARM\r\n")

    buf.write("END:VEVENT\r\n")


def _build_rrule(tpl) -> str:
    """每周重复的 RRULE，形如 FREQ=WEEKLY;INTERVAL=1;BYDAY=MO;UNTIL=...

    只对每周重复调用（见 _write_schedule）：页面口径就是「从开始日每 7 天一次」，
    和它逐日等价。别的重复类型走展开，不经过这里。
    """
    if not tpl.repeat_end_date:
        return ""
    if tpl.repeat_type != REPEAT_WEEKLY:
        return ""

    weekday = tpl.start_time.weekday()  # 0=周一
    day_codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    parts = ["FREQ=WEEKLY", "INTERVAL=1", f"BYDAY={day_codes[weekday]}"]

    # 结束日期。UNTIL 的取值类型必须和 DTSTART 一致：DTSTART 是浮动本地时间
    # （不带 Z、不带 TZID），全天事件则是 DATE，所以 UNTIL 也得是这两种之一，
    # 给浮动时间配一个 UTC 的 UNTIL 是不合 RFC5545 的（会被当成「UTC 的某一刻」）。
    #
    # 用**开始**时刻而不是结束时刻：RRULE 里每一次发生的时间就是 DTSTART 的时刻。
    # 跨天日程（22:00–次日 1:00）拿结束时刻当 UNTIL 的话，最后一天 22:00 那次
    # 会落在 UNTIL 之后被客户端丢掉，而网页上还有。
    if tpl.all_day:
        parts.append(f"UNTIL={tpl.repeat_end_date.strftime('%Y%m%d')}")
    else:
        until_dt = datetime.combine(tpl.repeat_end_date, tpl.start_time.time())
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
