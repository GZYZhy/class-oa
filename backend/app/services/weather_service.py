"""天气数据源

用 **Open-Meteo**：免费、无需注册和 Key、支持 HTTPS + JSON、非商业自用没有调用门槛。
地理位置的经纬度和显示名全部来自配置（WEATHER_LAT / WEATHER_LON / WEATHER_NAME），
换校区只改 .env，不用动代码。

为什么是后端取数而不是浏览器直连：
  ① CSP 的 connect-src 只允许自家后端，前端直连会被浏览器拦掉；
  ② 服务端缓存的收益很实在 —— 全班几十个人打开首页，10 分钟内只算一次外呼，
     弱网和手机流量下这是最省的；定时提醒任务和白天的页面共用同一份缓存；
  ③ 以后要换成需要 Key 的供应商（和风、OpenWeatherMap 等），只改这一个文件。

一次取数同时服务两件事：首页那张卡（当前 + 逐小时 + 明天）和天气提醒（条件判断）。
缓存里存的是**完整**的逐小时/日级数据，接口层再裁成前端要的那 12 条 ——
省得为了提醒再单独拉一次。
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from ..config import settings
from ..models import WeatherBannerSettings

API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 3
# 正常数据缓存 10 分钟：天气的分钟级变化对首页那张卡没有意义，而 10 分钟能把
# 全班访问压成个位数的外呼次数
CACHE_SECONDS = 600
# 失败也要缓存一会儿（短一点）：对方挂了的时候，不能让每次刷新都去撞一次 3 秒超时
RETRY_SECONDS = 60
# 首页只展示未来 12 小时，再多一条横条也塞不下
HOURLY_SHOWN = 12

# WMO 天气代码 → (中文描述, 前端图标组件名)
# 图标名要和 main.js 里那份全局注册表对得上，否则页面那个位置是空的
_WMO = {
    0: ("晴", "Sunny"),
    1: ("晴间多云", "PartlyCloudy"),
    2: ("多云", "PartlyCloudy"),
    3: ("阴", "Cloudy"),
    45: ("雾", "Cloudy"),
    48: ("雾凇", "Cloudy"),
    51: ("毛毛雨", "Drizzling"),
    53: ("小雨", "Drizzling"),
    55: ("中雨", "Pouring"),
    56: ("冻毛毛雨", "Drizzling"),
    57: ("冻雨", "Pouring"),
    61: ("小雨", "Drizzling"),
    63: ("中雨", "Pouring"),
    65: ("大雨", "Pouring"),
    66: ("冻雨", "Pouring"),
    67: ("强冻雨", "Pouring"),
    71: ("小雪", "Cloudy"),
    73: ("中雪", "Cloudy"),
    75: ("大雪", "Cloudy"),
    77: ("米雪", "Cloudy"),
    80: ("阵雨", "Drizzling"),
    81: ("强阵雨", "Pouring"),
    82: ("暴雨", "Pouring"),
    85: ("阵雪", "Cloudy"),
    86: ("强阵雪", "Cloudy"),
    95: ("雷阵雨", "Lightning"),
    96: ("雷阵雨伴冰雹", "Lightning"),
    99: ("强雷阵雨伴冰雹", "Lightning"),
}

# 雪 / 雷暴的代码集合，提醒判断用
_SNOW_CODES = {71, 73, 75, 77, 85, 86}
_STORM_CODES = {95, 96, 99}

_cache: dict = {"at": 0.0, "payload": None}
_lock = threading.Lock()


def _place(db=None) -> tuple[str, object, object]:
    """天气卡地点：名称、纬度、经度

    管理员配置在 weather_banner_settings 单行表里（原先是 .env 的三项）。
    **db=None 只给单元测试用**，这时退回 env；生产调用一律传 db，管理员保存即生效。
    """
    if db is None:
        return (
            (settings.weather_name or "").strip(),
            (settings.weather_lat or "").strip(),
            (settings.weather_lon or "").strip(),
        )
    row = db.get(WeatherBannerSettings, 1)
    if row is None:
        return "", None, None
    return (row.name or "").strip(), row.lat, row.lng


def _coords(db=None) -> Optional[tuple[float, float]]:
    """有效的经纬度；没配或写错都返回 None

    「没配」和「配错了」在接口上要分开告诉前端（见 state_of）：
    前者是管理员还没开这个功能，后者是填了但值不对，页面提示不该一样。
    """
    _, lat_raw, lon_raw = _place(db)
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def state_of(db=None) -> str:
    """配置状态：unconfigured（两个都空）/ invalid（填了但不合法）/ ok"""
    _, lat_raw, lon_raw = _place(db)
    if db is None:
        # env 是字符串，空串算没填
        if not lat_raw and not lon_raw:
            return "unconfigured"
    else:
        # 数据库是 NULL/浮点数；0 是合法坐标，不能用真值判断
        if lat_raw is None and lon_raw is None:
            return "unconfigured"
        if lat_raw is None or lon_raw is None:
            return "invalid"
    return "ok" if _coords(db) is not None else "invalid"


def enabled(db=None) -> bool:
    return state_of(db) == "ok"


def site_url() -> str:
    return (settings.weather_site_url or "").strip()


def weather_text(code: int) -> tuple[str, str]:
    """WMO 代码 → (中文, 图标名)"""
    return _WMO.get(code, ("未知", "Cloudy"))


def is_snow(code: int) -> bool:
    return code in _SNOW_CODES


def is_storm(code: int) -> bool:
    return code in _STORM_CODES


def _fetch(lat: float, lon: float) -> dict:
    """真正的外呼。异常一律往上抛，由 _load() 收成「取不到」

    返回的是**完整**数据（逐小时 48 条 + 日级 2 天），缓存原样存这一份：
    首页只取前 12 小时，提醒任务要按时间窗口遍历，两边共用。
    """
    resp = requests.get(
        API_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code",
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,precipitation_sum,wind_speed_10m_max"
            ),
            "timezone": "Asia/Shanghai",
            # 两天：今天（剩余部分）+ 明天。提醒的「明天」窗口跑不出这个范围
            "forecast_days": 2,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    hourly_raw = data.get("hourly") or {}
    times = hourly_raw.get("time") or []
    temps = hourly_raw.get("temperature_2m") or []
    pops = hourly_raw.get("precipitation_probability") or []
    codes = hourly_raw.get("weather_code") or []

    hourly = []
    for i, t in enumerate(times):
        code = int(codes[i] or 0) if i < len(codes) else 0
        text, icon = weather_text(code)
        hourly.append({
            "time": t,                                  # 2026-10-25T08:00
            "temp": round(float(temps[i])) if i < len(temps) and temps[i] is not None else None,
            "pop": int(pops[i] or 0) if i < len(pops) and pops[i] is not None else 0,
            "code": code,
            "text": text,
            "icon": icon,
        })

    daily_raw = data.get("daily") or {}

    def _at(key, index):
        values = daily_raw.get(key) or []
        return values[index] if index < len(values) else None

    days = []
    for index in range(min(2, len(daily_raw.get("time") or []))):
        code = int(_at("weather_code", index) or 0)
        text, icon = weather_text(code)
        days.append({
            "date": (_at("time", index) or "")[:10],
            "code": code,
            "text": text,
            "icon": icon,
            "high": round(float(_at("temperature_2m_max", index)))
            if _at("temperature_2m_max", index) is not None else None,
            "low": round(float(_at("temperature_2m_min", index)))
            if _at("temperature_2m_min", index) is not None else None,
            "pop": int(_at("precipitation_probability_max", index) or 0),
            "rain_mm": float(_at("precipitation_sum", index) or 0),
            "wind_kmh": round(float(_at("wind_speed_10m_max", index) or 0)),
        })

    current = data.get("current") or {}
    code = int(current.get("weather_code") or 0)
    text, icon = weather_text(code)

    return {
        "current": {
            "temp": round(float(current.get("temperature_2m"))),
            "feels_like": round(float(current.get("apparent_temperature"))),
            "code": code,
            "text": text,
            "icon": icon,
            "updated_at": current.get("time") or "",
        },
        "hourly": hourly,
        "days": days,
    }


def _load(db=None) -> dict:
    """取数（带缓存）。返回 {"ok": True, "data": ...} 或 {"ok": False}"""
    now = time.time()
    with _lock:
        cached = _cache["payload"]
        if cached is not None and now - _cache["at"] < cached["ttl"]:
            return cached["data"]

    coords = _coords(db)
    # 没配 / 配错时不去外呼。**这个判断必须在 try 外面单独做**：以前写在
    # `lat, lon = _coords()` 里，None 一解包就抛 TypeError，首页的横幅判断
    # 调 forecast() 时整页 500 —— 恰恰是「还没配置天气」的默认状态。
    if coords is None:
        return {"ok": False}
    lat, lon = coords
    try:
        payload = {"ok": True, "data": _fetch(lat, lon)}
        ttl = CACHE_SECONDS
    except Exception:  # noqa: BLE001 — 任何异常都只是「这次没取到」，不该冒到接口外
        payload = {"ok": False}
        ttl = RETRY_SECONDS

    with _lock:
        _cache["at"] = now
        _cache["payload"] = {"ttl": ttl, "data": payload}
    return payload


def forecast(db=None) -> Optional[dict]:
    """给提醒任务用的完整预报；取不到返回 None"""
    result = _load(db)
    return result["data"] if result["ok"] else None


def _slim_hourly(hourly: list[dict], now: datetime) -> list[dict]:
    """从「当前小时」开始取 12 条，时间裁成 HH:00 给前端直接用"""
    if not hourly:
        return []
    start = 0
    for i, item in enumerate(hourly):
        try:
            if datetime.strptime(item["time"], "%Y-%m-%dT%H:%M") >= now.replace(
                minute=0, second=0, microsecond=0
            ):
                start = i
                break
        except (ValueError, TypeError):
            start = 0
            break
    out = []
    for item in hourly[start:start + HOURLY_SHOWN]:
        out.append({**item, "time": item["time"][11:16]})
    return out


def current(db=None) -> dict:
    """首页天气卡（带缓存）

    永远返回一个能直接渲染的 dict，用 `state` 区分四种情况：
      · unconfigured —— 经纬度没配（管理员还没开这个功能）
      · invalid      —— 填了但不合法（非数字、超范围、只填了一个）
      · ok           —— 正常
      · error        —— 配置没问题，但这会儿没取到（对方超时 / 断网）
    前端按 state 显示不同文案；后两种都仍带 site_url，卡片照样能点开天气网站。
    """
    base = {
        "name": _place(db)[0],
        "site_url": site_url(),
    }

    state = state_of(db)
    if state != "ok":
        # 配置层面的问题：不缓存、不外呼（配错了再刷也不会变好）
        return {"state": state, **base}

    result = _load(db)
    if not result["ok"]:
        return {"state": "error", **base}

    data = result["data"]
    now = datetime.now()
    days = data.get("days") or []
    today = days[0] if days else {}
    return {
        "state": "ok",
        **base,
        **data["current"],
        # 今天的最低/最高：当前天气只有瞬时温度，日级数据里的这两个值
        # 是首页「最低 ° · 最高 °」那一行唯一的来源
        "low": today.get("low"),
        "high": today.get("high"),
        # 逐小时（前端横条）：时间已经裁成 HH:00
        "hourly": _slim_hourly(data.get("hourly") or [], now),
        # 明天：days[1]。取不到就 None，前端整块不显示
        "tomorrow": days[1] if len(days) > 1 else None,
    }


def reset_cache() -> None:
    """测试用：把缓存清掉，避免用例之间互相影响"""
    with _lock:
        _cache["at"] = 0.0
        _cache["payload"] = None
