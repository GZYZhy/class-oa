"""天气提醒：按每个人的订阅条件，每 N 小时检查一次预报

设计上的几条线：

  · **只提醒，不做预警**。数据源（Open-Meteo）没有中国的官方预警接口，
    所以这里判断的全是「预报阈值」：降雨概率、是否下雪/雷暴、高温、低温、大风。
    文案也必须写成「可能有雨（概率 80%）」这种口径，不能写成断言。

  · **每人一份设置**（models/weather_notify.py）：开不开、盯哪几种天气、
    阈值多少、关注今天还是明天、几点到几点别吵，都是个人偏好。

  · **一次外呼服务所有人**：预报数据由 weather_service 统一取、统一缓存，
    这个模块只做判断和分发。

  · **去重**：同一个人、同一段时间、同一组条件只发一次（last_key）。
    条件变多了（比如先报下雨、后来加上雷暴）算新事件，会再发一条。
"""

import json
import os
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from ..models import WeatherNotifySettings
from . import weather_service
from .notify_service import deliver_now, recipients

# 可订阅的天气条件。顺序即前端展示顺序
CONDITIONS = {
    "rain": "降雨",
    "snow": "降雪",
    "storm": "雷暴",
    "heat": "高温",
    "cold": "低温",
    "wind": "大风",
}
# 新用户默认勾这几项：降雨是最高频、最有用的一条
DEFAULT_CONDITIONS = ["rain"]

WINDOWS = {"today": "今天", "tomorrow": "明天", "next24h": "未来 24 小时"}

DEFAULT_INTERVAL_HOURS = 6.0
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

    hours = []
    for item in data.get("hourly") or []:
        moment = _parse_hour(item.get("time"))
        if moment is not None and start <= moment <= end:
            hours.append((moment, item))

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
                "detail": f"{label} {span} 降雨概率最高 {best[1].get('pop')}%，记得带伞。",
            })

    if "snow" in wanted and hours:
        snowy = [(m, h) for m, h in hours if weather_service.is_snow(int(h.get("code") or 0))]
        if snowy:
            hits.append({
                "code": "snow",
                "title": f"{label}有降雪",
                "detail": f"{label} {snowy[0][0]:%H:%M} 起有降雪，注意路面结冰。",
            })

    if "storm" in wanted and hours:
        stormy = [(m, h) for m, h in hours if weather_service.is_storm(int(h.get("code") or 0))]
        if stormy:
            hits.append({
                "code": "storm",
                "title": f"{label}有雷阵雨",
                "detail": f"{label} {stormy[0][0]:%H:%M} 前后有雷阵雨，尽量减少户外停留。",
            })

    if "heat" in wanted:
        highs = [d.get("high") for d in scope_days if d.get("high") is not None]
        if highs and max(highs) >= row.heat_threshold:
            hits.append({
                "code": "heat",
                "title": f"{label}高温",
                "detail": f"{label}最高 {max(highs)}°，注意防暑补水。",
            })

    if "cold" in wanted:
        lows = [d.get("low") for d in scope_days if d.get("low") is not None]
        if lows and min(lows) <= row.cold_threshold:
            hits.append({
                "code": "cold",
                "title": f"{label}低温",
                "detail": f"{label}最低 {min(lows)}°，注意保暖。",
            })

    if "wind" in wanted:
        winds = [d.get("wind_kmh") for d in scope_days if d.get("wind_kmh") is not None]
        if winds and max(winds) >= row.wind_threshold:
            hits.append({
                "code": "wind",
                "title": f"{label}大风",
                "detail": f"{label}阵风可达 {max(winds)} km/h，注意防风。",
            })

    return hits, date_key


def in_quiet_hours(row: WeatherNotifySettings, now: datetime) -> bool:
    """静默时段判断（支持跨零点，如 22 → 7）"""
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


def interval_hours() -> float:
    try:
        value = float(os.environ.get("WEATHER_NOTIFY_INTERVAL_HOURS", DEFAULT_INTERVAL_HOURS))
    except ValueError:
        return DEFAULT_INTERVAL_HOURS
    # 太小的值没有意义（预报本身也只按 10 分钟缓存），下限给 1 小时
    return max(1.0, value)


def run_once(db: Session, now: datetime | None = None) -> int:
    """跑一轮：给所有开了提醒的人各判断一次，命中就发。返回发出的条数

    由 scheduler 的线程调用，所以这里**同步发**（deliver_now），并且必须用
    调用方传进来的会话 —— 线程里自开第二个连接会和主请求撞 SQLite 的写锁。
    """
    now = now or datetime.now()
    rows = db.query(WeatherNotifySettings).filter(WeatherNotifySettings.enabled.is_(True)).all()
    if not rows:
        return 0

    data = weather_service.forecast()
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
            key = f"{row.window}:{date_key}:{','.join(sorted(h['code'] for h in hits))}"
            if key == row.last_key:
                continue  # 同一件事已经提醒过

            title = "天气提醒：" + "、".join(h["title"] for h in hits)
            body = "\n".join(h["detail"] for h in hits) + "\n（数据：Open-Meteo）"
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
        enabled=False,
        conditions=dump_conditions(DEFAULT_CONDITIONS),
        rain_threshold=DEFAULT_RAIN_THRESHOLD,
        heat_threshold=DEFAULT_HEAT_THRESHOLD,
        cold_threshold=DEFAULT_COLD_THRESHOLD,
        wind_threshold=DEFAULT_WIND_THRESHOLD,
        window="today",
    )


def put_banner(db: Session, data):
    from ..models import WeatherBannerSettings

    row = db.get(WeatherBannerSettings, 1)
    if row is None:
        row = WeatherBannerSettings(id=1)
        db.add(row)

    row.enabled = bool(data.enabled)
    row.conditions = dump_conditions(data.conditions)
    row.rain_threshold = _clamp(getattr(data, "rain_threshold", DEFAULT_RAIN_THRESHOLD), 10, 100)
    row.heat_threshold = _clamp(getattr(data, "heat_threshold", DEFAULT_HEAT_THRESHOLD), 20, 45)
    row.cold_threshold = _clamp(getattr(data, "cold_threshold", DEFAULT_COLD_THRESHOLD), -40, 15)
    row.wind_threshold = _clamp(getattr(data, "wind_threshold", DEFAULT_WIND_THRESHOLD), 10, 120)
    window = getattr(data, "window", "today")
    row.window = window if window in WINDOWS else "today"

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
    return {
        "active": True,
        "title": "、".join(h["title"] for h in hits),
        "lines": [h["detail"] for h in hits],
        "codes": [h["code"] for h in hits],
    }
