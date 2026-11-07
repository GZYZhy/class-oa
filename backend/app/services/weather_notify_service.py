"""天气提醒：按每个人的订阅条件，每 N 分钟检查一次预报

设计上的几条线：

  · **预报是概率型，预警是权威信息**。数据源是 Open-Meteo 时只能判断预报阈值
    （降雨概率、是否下雪/雷暴、高温、低温、大风），文案必须写成「可能有雨
    （概率 80%）」这种口径。换成和风天气后多一类「官方预警」条件：那是气象台
    发布的正式预警，文案直接引用，不和阈值混在一起。

  · **每人一份设置**（models/weather_notify.py）：开不开、盯哪几种天气、
    阈值多少、关注今天还是明天、夜间免打扰时段，都是个人偏好。

  · **夜间免打扰的时段管两件事**：这段时间不推送；落在这一时段里的降水 /
    降雪 / 雷暴也不计入判断（凌晨三点的雨不该写成白天要处理的事）。
    原先另有一个「忽略夜间天气」开关，讲的是同一件事，已合并成时段一个口径。

  · **一次外呼服务所有人**：预报数据由 weather_service 统一取、统一缓存，
    这个模块只做判断和分发。

  · **去重**：同一个人、同一时段、同一天最多一条**预报**提醒；只订阅官方预警时
    按预警 id 去重。数据源在 Open-Meteo / 和风之间切换、官方预警多一条少一条，
    都不该让同一天的预报重发 —— 线上出现过一小时连推三次的情况，就是
    「带预警」和「不带预警」的 key 来回变造成的。
"""

import hashlib
import json
import os
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from ..models import WeatherNotifySettings
from . import weather_service
from .notify_service import deliver_now, recipients

# 可订阅的天气条件。顺序即前端展示顺序。
# 「官方预警」只有和风天气数据源才有数据；Open-Meteo 下勾了也不会触发
CONDITIONS = {
    "rain": "降雨",
    "snow": "降雪",
    "storm": "雷暴",
    "heat": "高温",
    "cold": "低温",
    "wind": "大风",
    "alert": "官方预警",
}
# 新用户默认勾这几项：降雨是最高频、最有用的一条
DEFAULT_CONDITIONS = ["rain"]

WINDOWS = {"today": "今天", "tomorrow": "明天", "next24h": "未来 24 小时"}

# 巡检间隔（分钟）：默认 10，范围 1–1440。常量在 weather_service 里 ——
# 缓存 TTL 要读同一个值，而本模块已经反过来 import 了它
DEFAULT_INTERVAL_MINUTES = weather_service.DEFAULT_INTERVAL_MINUTES
DEFAULT_RAIN_THRESHOLD = 60
DEFAULT_HEAT_THRESHOLD = 35
DEFAULT_COLD_THRESHOLD = 0
DEFAULT_WIND_THRESHOLD = 39
DEFAULT_QUIET_START = 22
DEFAULT_QUIET_END = 7


# ---------------------------------------------------------------- 配置读写


def parse_conditions(raw) -> list[str]:
    """JSON 数组 → 合法条件列表。坏值当空，不认识的名字直接丢掉"""
    if isinstance(raw, list):
        data = raw
    elif not raw:
        return []
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(data, list):
        return []
    # 去重保序：库里如果有重复项，前端会渲染出重复的勾选项
    return [
        item for item in dict.fromkeys(str(x) for x in data)
        if item in CONDITIONS
    ]


def dump_conditions(items) -> str:
    """去重保序；不认识的一律丢掉"""
    return json.dumps([x for x in dict.fromkeys(items or []) if x in CONDITIONS], ensure_ascii=False)


def _default_notify_row(student_no: str) -> WeatherNotifySettings:
    """未入库的默认值对象

    ⚠ Column 上的 default 只在 **INSERT** 时生效，直接构造出来的对象那些字段是
    None —— 拿去渲染接口会 500（pydantic 要 int）。所以这里把默认值写全。
    """
    return WeatherNotifySettings(
        student_no=student_no,
        enabled=False,
        conditions=dump_conditions(DEFAULT_CONDITIONS),
        rain_threshold=DEFAULT_RAIN_THRESHOLD,
        heat_threshold=DEFAULT_HEAT_THRESHOLD,
        cold_threshold=DEFAULT_COLD_THRESHOLD,
        wind_threshold=DEFAULT_WIND_THRESHOLD,
        window="tomorrow",
        quiet_start=DEFAULT_QUIET_START,
        quiet_end=DEFAULT_QUIET_END,
        last_key="",
    )


def get_settings(db: Session, student_no: str) -> WeatherNotifySettings:
    """读某个人的设置。没有行时返回一个填好默认值的对象（不写库）"""
    row = (
        db.query(WeatherNotifySettings)
        .filter(WeatherNotifySettings.student_no == student_no)
        .first()
    )
    return row if row is not None else _default_notify_row(student_no)


def put_settings(db: Session, student_no: str, data) -> WeatherNotifySettings:
    """保存（整体覆盖）。阈值做一次夹紧，防止前端传进越界值"""
    row = (
        db.query(WeatherNotifySettings)
        .filter(WeatherNotifySettings.student_no == student_no)
        .first()
    )
    if row is None:
        row = WeatherNotifySettings(student_no=student_no)
        db.add(row)

    row.enabled = bool(data.enabled)
    row.conditions = dump_conditions(data.conditions)
    row.rain_threshold = _clamp(getattr(data, "rain_threshold", DEFAULT_RAIN_THRESHOLD), 10, 100)
    row.heat_threshold = _clamp(getattr(data, "heat_threshold", DEFAULT_HEAT_THRESHOLD), 20, 45)
    row.cold_threshold = _clamp(getattr(data, "cold_threshold", DEFAULT_COLD_THRESHOLD), -40, 15)
    row.wind_threshold = _clamp(getattr(data, "wind_threshold", DEFAULT_WIND_THRESHOLD), 10, 120)
    window = getattr(data, "window", "tomorrow")
    row.window = window if window in WINDOWS else "tomorrow"
    row.quiet_start = _clamp(getattr(data, "quiet_start", DEFAULT_QUIET_START), 0, 23)
    row.quiet_end = _clamp(getattr(data, "quiet_end", DEFAULT_QUIET_END), 0, 23)

    db.commit()
    db.refresh(row)
    return row


def _clamp(value, low, high) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


# ---------------------------------------------------------------- 判断


def _window_bounds(window: str, now: datetime) -> tuple[datetime, datetime, str]:
    """关注时段 → (起, 止, 用于去重的日期串)"""
    if window == "today":
        start = now
        end = datetime.combine(now.date(), time(23, 59))
        return start, end, now.date().isoformat()
    if window == "next24h":
        return now, now + timedelta(hours=24), now.date().isoformat()
    # 默认明天
    tomorrow = now.date() + timedelta(days=1)
    return (
        datetime.combine(tomorrow, time(0, 0)),
        datetime.combine(tomorrow, time(23, 59)),
        tomorrow.isoformat(),
    )


def _parse_hour(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def evaluate(data: dict, row: WeatherNotifySettings, now: datetime) -> tuple[list[dict], str]:
    """按订阅条件判断这段时间有没有值得提醒的事

    返回 (命中列表, 日期串)。命中列表里每项是 {code, title, detail}。
    """
    window = row.window if row.window in WINDOWS else "tomorrow"
    start, end, date_key = _window_bounds(window, now)
    label = WINDOWS[window]
    # 「未来 24 小时」比「今天 / 明天」长一截，放进每一条详情开头很容易折行；
    # 横幅标题里已经写了时段，详情里就省掉这个前缀。今天 / 明天仍保留，
    # 文案和以前逐字一致。
    label_prefix = "" if window == "next24h" else label
    time_prefix = "" if window == "next24h" else f"{label} "

    hours = []
    for item in data.get("hourly") or []:
        moment = _parse_hour(item.get("time"))
        if moment is not None and start <= moment <= end:
            hours.append((moment, item))

    # 夜间免打扰时段内的降水/降雪/雷暴不计入：凌晨三点的雨不该写成白天要处理的事。
    # 时段来自设置本身（个人是免打扰；横幅是管理员配的夜间时段），起止相等 = 不过滤。
    # 日级的高温/低温/大风没有具体小时，仍按全天数据判断；官方预警是权威信息，
    # 也不受这个过滤影响（它没有「发生在几点」这一说）
    if _has_quiet(row):
        hours = [
            (moment, item) for moment, item in hours
            if not in_quiet_hours(row, moment)
        ]

    # 日级数据只覆盖今天和明天；next24h 可能跨两天，两头都看
    days = data.get("days") or []
    scope_days = days if window != "today" else days[:1]
    if window == "tomorrow":
        scope_days = days[1:2] if len(days) > 1 else []

    wanted = set(parse_conditions(row.conditions))
    hits: list[dict] = []

    if "rain" in wanted and hours:
        peaked = [(m, h) for m, h in hours if int(h.get("pop") or 0) >= row.rain_threshold]
        if peaked:
            best = max(peaked, key=lambda pair: int(pair[1].get("pop") or 0))
            # 只命中一个小时时别写成「00:00–00:00」，那个读起来像出错了
            if len(peaked) == 1:
                span = f"{peaked[0][0]:%H:%M} 前后"
            else:
                span = f"{peaked[0][0]:%H:%M}–{peaked[-1][0]:%H:%M}"
            hits.append({
                "code": "rain",
                "title": f"{label}可能有雨",
                "detail": f"{time_prefix}{span} 降雨概率最高 {best[1].get('pop')}%，记得带伞。",
            })

    if "snow" in wanted and hours:
        snowy = [(m, h) for m, h in hours if weather_service.is_snow(int(h.get("code") or 0))]
        if snowy:
            hits.append({
                "code": "snow",
                "title": f"{label}有降雪",
                "detail": f"{time_prefix}{snowy[0][0]:%H:%M} 起有降雪，注意路面结冰。",
            })

    if "storm" in wanted and hours:
        stormy = [(m, h) for m, h in hours if weather_service.is_storm(int(h.get("code") or 0))]
        if stormy:
            hits.append({
                "code": "storm",
                "title": f"{label}有雷阵雨",
                "detail": f"{time_prefix}{stormy[0][0]:%H:%M} 前后有雷阵雨，尽量减少户外停留。",
            })

    if "heat" in wanted:
        highs = [d.get("high") for d in scope_days if d.get("high") is not None]
        if highs and max(highs) >= row.heat_threshold:
            hits.append({
                "code": "heat",
                "title": f"{label}高温",
                "detail": f"{label_prefix}最高 {max(highs)}°，注意防暑补水。",
            })

    if "cold" in wanted:
        lows = [d.get("low") for d in scope_days if d.get("low") is not None]
        if lows and min(lows) <= row.cold_threshold:
            hits.append({
                "code": "cold",
                "title": f"{label}低温",
                "detail": f"{label_prefix}最低 {min(lows)}°，注意保暖。",
            })

    if "wind" in wanted:
        winds = [d.get("wind_kmh") for d in scope_days if d.get("wind_kmh") is not None]
        if winds and max(winds) >= row.wind_threshold:
            hits.append({
                "code": "wind",
                "title": f"{label}大风",
                "detail": f"{label_prefix}阵风可达 {max(winds)} km/h，注意防风。",
            })

    # 官方预警：只有和风数据源会给 alerts，Open-Meteo 下这里是空表。
    # 不套「关注时段」——预警是「现在正生效」的信息，不是某天的预报；
    # 也不受夜间过滤影响（见上面那段说明）
    if "alert" in wanted:
        # 区、市两级气象台常对同一件事各发一条，标题都是「大雾黄色预警」。
        # 不合并的话横幅标题会变成「大雾预警、大雾预警」（线上就这么出现过），
        # 正文也是两段几乎一样的话。按标题合并，同一件事留**最新发布**的那条
        merged: dict[str, dict] = {}
        for alert in data.get("alerts") or []:
            kind = (alert.get("type") or "").strip() or "气象"
            level = weather_service.alert_level(alert)
            headline = f"{kind}{level}预警" if level else f"{kind}预警"
            latest = merged.get(headline)
            if latest is None or str(alert.get("pub_time") or "") > str(
                latest.get("pub_time") or ""
            ):
                merged[headline] = alert

        for headline, alert in list(merged.items())[:3]:
            sender = (alert.get("sender") or "").strip()
            # 正文固定以「某台某时发布某预警」开头，和标题重复，先砍掉再说
            text = _alert_excerpt(_strip_alert_lead(alert.get("text")))
            detail = f"{sender}：{text}" if sender and text else (text or sender or headline)
            hits.append({
                "code": "alert",
                # 去重要用到：同一条预警只提一次，换一条（新 id）才继续提
                "alert_id": str(alert.get("id") or headline),
                "alert_color": weather_service.alert_color(alert),
                "title": headline,
                "detail": detail,
            })

    return hits, date_key


def _alert_excerpt(text, limit: int = 80) -> str:
    """预警正文摘一句：官方原文动辄几百字，塞进通知栏只会被折叠掉"""
    plain = " ".join(str(text or "").split())
    return plain[:limit] + "…" if len(plain) > limit else plain


def _strip_alert_lead(text) -> str:
    """砍掉预警正文开头那句「某台某时发布某预警」

    和风的 description 是「石景山区气象台04日22时10分发布大雾黄色预警，
    预计，当前至5日早晨…」。前半句和标题、发布单位完全重复，留着只是噪音；
    砍完如果太短（整段就这么点内容），原样保留 —— 宁可重复也别只剩半句。
    """
    plain = " ".join(str(text or "").split())
    index = plain[:60].find("发布")
    if index < 0:
        return plain
    for mark in ("，", "。", "；", "：", ",", ":"):
        pos = plain.find(mark, index)
        if 0 <= pos <= index + 40:
            rest = plain[pos + 1:].lstrip(" ：:，,")
            if len(rest) >= 10:
                return rest
    return plain


def _has_quiet(row) -> bool:
    """有没有设夜间时段。起止相等 = 不启用（与 in_quiet_hours 同一口径）"""
    return getattr(row, "quiet_start", DEFAULT_QUIET_START) != getattr(
        row, "quiet_end", DEFAULT_QUIET_END
    )


def in_quiet_hours(row: WeatherNotifySettings, now: datetime) -> bool:
    """夜间免打扰判断（支持跨零点，如 22 → 7）"""
    start, end = row.quiet_start, row.quiet_end
    if start == end:
        return False
    hour = now.hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


# ---------------------------------------------------------------- 定时任务


def scheduler_enabled() -> bool:
    return os.environ.get("WEATHER_NOTIFY_SCHEDULER", "1") != "0"


def interval_minutes(db=None) -> int:
    """巡检间隔（分钟，1–1440）。管理员在「系统管理 → 天气」里配

    默认 10 分钟。下限 1 分钟：再密没有意义（对方的数据也不是每分钟更新）；
    上限 1440（24 小时）：避免手滑填成天文数字变成「再也不提醒」。

    db=None 只给单元测试 / 旧部署用：先读 WEATHER_NOTIFY_INTERVAL_MINUTES，
    没有再看老变量 WEATHER_NOTIFY_INTERVAL_HOURS（×60），都没有就用默认值。
    """
    if db is None:
        raw = os.environ.get("WEATHER_NOTIFY_INTERVAL_MINUTES")
        if not raw:
            legacy = os.environ.get("WEATHER_NOTIFY_INTERVAL_HOURS")
            if legacy:
                try:
                    raw = float(legacy) * 60
                except (TypeError, ValueError):
                    raw = DEFAULT_INTERVAL_MINUTES
            else:
                raw = DEFAULT_INTERVAL_MINUTES
    else:
        raw = getattr(get_banner(db), "notify_interval_minutes", DEFAULT_INTERVAL_MINUTES)
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_MINUTES
    return max(
        weather_service.MIN_INTERVAL_MINUTES,
        min(weather_service.MAX_INTERVAL_MINUTES, value),
    )


def _notification_key(hits: list[dict], window: str, date_key: str) -> str:
    """去重键：预报一天一条，官方预警按 id 一条

    不能把 ``codes`` 直接拼进 key：和风超时会回退 Open-Meteo，两个数据源
    一个有官方预警、一个没有，key 就会在「rain,cold,alert」和「rain,cold」
    之间来回翻，同一件事一小时推三次。预报只按「时段 + 日期」去重；
    只订阅预警的人才按预警 id 区分，保证新预警还能提醒。
    """
    forecast_codes = sorted({h["code"] for h in hits if h.get("code") != "alert"})
    if forecast_codes:
        return f"{window}:{date_key}:forecast"
    alert_ids = ",".join(sorted(str(h["alert_id"]) for h in hits if h.get("alert_id")))
    # last_key 只有 64 个字符，几条预警 id 串起来就超了；取摘要足够区分
    digest = hashlib.md5(alert_ids.encode()).hexdigest()[:8]
    return f"{window}:{date_key}:alert:{digest}"


def run_once(db: Session, now: datetime | None = None) -> int:
    """跑一轮：给所有开了提醒的人各判断一次，命中就发。返回发出的条数

    由 scheduler 的线程调用，所以这里**同步发**（deliver_now），并且必须用
    调用方传进来的会话 —— 线程里自开第二个连接会和主请求撞 SQLite 的写锁。
    """
    now = now or datetime.now()
    rows = db.query(WeatherNotifySettings).filter(WeatherNotifySettings.enabled.is_(True)).all()
    if not rows:
        return 0

    data = weather_service.forecast(db)
    if not data:
        # 取不到预报就整轮跳过：宁可这次不提醒，也不要发一条「猜的」
        return 0

    sent = 0
    for row in rows:
        try:
            if in_quiet_hours(row, now):
                continue
            hits, date_key = evaluate(data, row, now)
            if not hits:
                continue
            key = _notification_key(hits, row.window, date_key)
            if key == row.last_key:
                continue  # 同一件事已经提醒过
            if key.endswith(":forecast") and row.last_key.startswith(
                f"{row.window}:{date_key}:"
            ):
                # 旧版 key 是「时段:日期:条件」；升级后第一次巡检不要补发一条
                # 同一天的预报，只把旧 key 迁移成新格式。
                row.last_key = key
                db.commit()
                continue

            title = "天气提醒：" + "、".join(h["title"] for h in hits)
            source = data.get("source_label") or "Open-Meteo"
            body = "\n".join(h["detail"] for h in hits) + f"\n（数据：{source}）"
            targets = recipients(db, only_no=row.student_no)
            if not targets:
                continue
            deliver_now(db, targets, title, body, level="active", page="/dashboard")
            row.last_key = key
            db.commit()
            sent += 1
        except Exception as exc:  # noqa: BLE001 — 一个人失败不能拖垮整轮
            db.rollback()
            print(f"[天气提醒] {row.student_no} 发送失败：{exc}", flush=True)
    return sent


# ---------------------------------------------------------------- 广播横幅（管理员）
#
# 判断逻辑和上面完全一样（同一个 evaluate），区别只在于：
#   · 设置是全局单行表，管理员配；
#   · 命中后不是发推送，而是让首页显示一条横幅 —— 所以不需要去重，
#     条件成立期间看到的人都该看到。


def get_banner(db: Session):
    from ..models import WeatherBannerSettings

    row = db.get(WeatherBannerSettings, 1)
    if row is not None:
        return row
    # 未入库的默认值：Column default 只在 INSERT 时生效，构造出来的字段是 None
    return WeatherBannerSettings(
        id=1,
        name="",
        lat=None,
        lng=None,
        site_url="",
        notify_interval_minutes=DEFAULT_INTERVAL_MINUTES,
        source=weather_service.SOURCE_OPEN_METEO,
        qweather_key="",
        qweather_host="",
        enabled=False,
        conditions=dump_conditions(DEFAULT_CONDITIONS),
        rain_threshold=DEFAULT_RAIN_THRESHOLD,
        heat_threshold=DEFAULT_HEAT_THRESHOLD,
        cold_threshold=DEFAULT_COLD_THRESHOLD,
        wind_threshold=DEFAULT_WIND_THRESHOLD,
        window="today",
        quiet_start=DEFAULT_QUIET_START,
        quiet_end=DEFAULT_QUIET_END,
    )


def put_banner(db: Session, data):
    from ..models import WeatherBannerSettings

    row = db.get(WeatherBannerSettings, 1)
    if row is None:
        row = WeatherBannerSettings(id=1)
        db.add(row)

    row.name = (getattr(data, "name", "") or "").strip()
    row.lat = getattr(data, "lat", None)
    row.lng = getattr(data, "lng", None)
    row.site_url = (getattr(data, "site_url", "") or "").strip()
    row.notify_interval_minutes = _clamp(
        getattr(data, "notify_interval_minutes", DEFAULT_INTERVAL_MINUTES),
        weather_service.MIN_INTERVAL_MINUTES,
        weather_service.MAX_INTERVAL_MINUTES,
    )
    # 数据源：不认识的值一律退回 Open-Meteo（默认那档），不要留一个谁也不认识的串
    source = (getattr(data, "source", "") or "").strip()
    row.source = (
        source if source in weather_service.SOURCE_LABELS
        else weather_service.SOURCE_OPEN_METEO
    )
    row.qweather_key = (getattr(data, "qweather_key", "") or "").strip()
    row.qweather_host = (getattr(data, "qweather_host", "") or "").strip()
    row.enabled = bool(data.enabled)
    row.conditions = dump_conditions(data.conditions)
    row.rain_threshold = _clamp(getattr(data, "rain_threshold", DEFAULT_RAIN_THRESHOLD), 10, 100)
    row.heat_threshold = _clamp(getattr(data, "heat_threshold", DEFAULT_HEAT_THRESHOLD), 20, 45)
    row.cold_threshold = _clamp(getattr(data, "cold_threshold", DEFAULT_COLD_THRESHOLD), -40, 15)
    row.wind_threshold = _clamp(getattr(data, "wind_threshold", DEFAULT_WIND_THRESHOLD), 10, 120)
    window = getattr(data, "window", "today")
    row.window = window if window in WINDOWS else "today"
    row.quiet_start = _clamp(getattr(data, "quiet_start", DEFAULT_QUIET_START), 0, 23)
    row.quiet_end = _clamp(getattr(data, "quiet_end", DEFAULT_QUIET_END), 0, 23)

    db.commit()
    db.refresh(row)
    return row


def banner_state(db: Session, data: dict | None, now: datetime | None = None) -> dict:
    """首页横幅当前该不该显示、显示什么

    没开、没配条件、预报取不到，一律 {active: False} —— 横幅是给满站人看的，
    任何不确定的情况都宁可不显示。
    """
    if not data:
        return {"active": False}
    row = get_banner(db)
    if not row.enabled or not parse_conditions(row.conditions):
        return {"active": False}

    hits, _ = evaluate(data, row, now or datetime.now())
    if not hits:
        return {"active": False}
    # 有官方预警时用最高的那档颜色给首页横幅换肤；没有预警就用默认天青
    alert_colors = [
        h.get("alert_color") for h in hits
        if h.get("code") == "alert" and h.get("alert_color")
    ]
    rank = {"blue": 1, "yellow": 2, "orange": 3, "red": 4}
    alert_color = max(alert_colors, key=lambda c: rank.get(c, 0), default="")

    return {
        "active": True,
        "title": "、".join(h["title"] for h in hits),
        "lines": [h["detail"] for h in hits],
        "codes": [h["code"] for h in hits],
        "alert_color": alert_color,
    }
