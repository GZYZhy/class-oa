"""天气数据源

两个来源，管理员在「系统管理 → 天气」里选：

  · **Open-Meteo**（默认）：免费、无需注册和 Key、支持 HTTPS + JSON、
    非商业自用没有调用门槛。**没有中国的官方预警接口**。
  · **和风天气（QWeather）**：需要 Key，除预报外还提供官方气象预警
    （`/v7/warning/now`），「官方预警」这个提醒条件只在这个来源下才有数据。

地理位置（显示名、经纬度）和跳转网站都由管理员配置，存在 weather_banner_settings；
换校区在后台改，不用动代码。

为什么是后端取数而不是浏览器直连：
  ① CSP 的 connect-src 只允许自家后端，前端直连会被浏览器拦掉；
  ② 服务端缓存的收益很实在 —— 全班几十个人打开首页，一个缓存周期内只算一次外呼，
     弱网和手机流量下这是最省的；定时提醒任务和白天的页面共用同一份缓存；
  ③ 换供应商只改这一个文件（第一次换的时候就把这层收在这里了）。

一次取数同时服务两件事：首页那张卡（当前 + 逐小时 + 明天）和天气提醒（条件判断）。
缓存里存的是**完整**的逐小时/日级数据，接口层再裁成前端要的那 12 条 ——
省得为了提醒再单独拉一次。

两者都归一化成同一套内部结构（current / hourly / days / alerts），
`weather_notify_service.evaluate` 只认这套结构，不知道数据是从哪来的。
"""

import threading
import time
from datetime import datetime
from typing import Optional

import requests

from ..config import settings
from ..models import WeatherBannerSettings

# ---- 数据源 ----
SOURCE_OPEN_METEO = "open_meteo"
SOURCE_QWEATHER = "qweather"
SOURCE_LABELS = {
    SOURCE_OPEN_METEO: "Open-Meteo",
    SOURCE_QWEATHER: "和风天气",
}

API_URL = "https://api.open-meteo.com/v1/forecast"
# 和风新版给每个账号一个专属 API Host（形如 xxxx.re.qweatherapi.com）；
# 老账号/老套餐仍然用 devapi.qweather.com
QWEATHER_DEFAULT_HOST = "devapi.qweather.com"
TIMEOUT = 3
# 正常数据缓存上限：天气的分钟级变化对首页那张卡没有意义，10 分钟能把
# 全班访问压成个位数的外呼次数。**实际 TTL 会跟着巡检间隔缩**（见 _ttl_seconds）：
# 管理员把间隔调到 1 分钟，缓存也只剩 1 分钟，否则「提高外呼频率」就只是空转
CACHE_SECONDS = 600
# 失败也要缓存一会儿（短一点）：对方挂了的时候，不能让每次刷新都去撞一次 3 秒超时
RETRY_SECONDS = 60
# 首页只展示未来 12 小时，再多一条横条也塞不下
HOURLY_SHOWN = 12

# 巡检间隔的默认值与边界（管理员可配）。放在这里是因为缓存的 TTL 要读它，
# 而 weather_notify_service 会反过来 import 本模块 —— 常量只能放这一侧
DEFAULT_INTERVAL_MINUTES = 10
MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 24 * 60

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

# ---- 和风图标代码 → 内部类别 ----
# 和风有上百个图标代码，这里只需要三样：显示用的图标、是不是雪/雷暴（提醒判断）、
# 中文描述（直接用接口返回的 text，不再自己写一份）。
_QW_STORM = {302, 303, 304}          # 雷阵雨 / 雷阵雨伴有冰雹
_QW_HEAVY_RAIN = {307, 308, 310, 311, 312, 313, 314, 315, 316, 317, 318, 399}
_QW_FOG = set(range(500, 516))

_cache: dict = {"at": 0.0, "payload": None}
_lock = threading.Lock()


# ---------------------------------------------------------------- 管理员配置


def _settings_row(db=None):
    """weather_banner_settings 单行；db=None 只给单元测试用"""
    if db is None:
        return None
    return db.get(WeatherBannerSettings, 1)


def source_of(db=None) -> str:
    """配置的数据源；不认识的取值当 Open-Meteo

    选了和风但没填 Key 时**仍然返回 qweather**（配置就是它），
    运行期取数会退回 Open-Meteo —— 是「没配全」还是「临时故障」，
    管理员在设置页看得到，不该在这里悄悄改配置。
    """
    row = _settings_row(db)
    raw = (getattr(row, "source", "") or "").strip() if row is not None else ""
    return raw if raw in SOURCE_LABELS else SOURCE_OPEN_METEO


def source_label(db=None) -> str:
    return SOURCE_LABELS[source_of(db)]


def qweather_config(db=None) -> tuple[str, str]:
    """(Key, API Host)；Host 留空时用默认域名"""
    row = _settings_row(db)
    key = (getattr(row, "qweather_key", "") or "").strip() if row is not None else ""
    host = (getattr(row, "qweather_host", "") or "").strip() if row is not None else ""
    return key, (host or QWEATHER_DEFAULT_HOST)


def qweather_ready(db=None) -> bool:
    """选了和风、且真的填了 Key"""
    if source_of(db) != SOURCE_QWEATHER:
        return False
    return bool(qweather_config(db)[0])


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
    row = _settings_row(db)
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


def site_url(db=None) -> str:
    """天气卡点开的网站；db=None 只给单元测试用，生产读管理员配置"""
    if db is None:
        return (settings.weather_site_url or "").strip()
    row = _settings_row(db)
    return (row.site_url or "").strip() if row is not None else ""


def weather_text(code: int) -> tuple[str, str]:
    """WMO 代码 → (中文, 图标名)"""
    return _WMO.get(code, ("未知", "Cloudy"))


def is_snow(code: int) -> bool:
    return code in _SNOW_CODES


def is_storm(code: int) -> bool:
    return code in _STORM_CODES


def _ttl_seconds(db=None) -> int:
    """缓存时长：跟着巡检间隔缩，下限 1 分钟、上限 10 分钟

    不跟着缩的话，「把间隔调到 1 分钟」只在缓存到期后才真的多外呼一次 ——
    管理员看到的频率和实际外呼对不上，等于骗人。上限仍是 10 分钟：
    再长对首页那张卡也没意义。
    """
    row = _settings_row(db)
    try:
        minutes = int(getattr(row, "notify_interval_minutes", DEFAULT_INTERVAL_MINUTES))
    except (TypeError, ValueError):
        minutes = DEFAULT_INTERVAL_MINUTES
    minutes = max(MIN_INTERVAL_MINUTES, min(MAX_INTERVAL_MINUTES, minutes))
    return max(60, min(CACHE_SECONDS, minutes * 60))


# ---------------------------------------------------------------- Open-Meteo


def _fetch(lat: float, lon: float) -> dict:
    """真正的外呼（Open-Meteo）。异常一律往上抛，由 _load() 收成「取不到」

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
        "source": SOURCE_OPEN_METEO,
        "source_label": SOURCE_LABELS[SOURCE_OPEN_METEO],
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
        # Open-Meteo 没有官方预警；统一给空表，evaluate 不用分数据源
        "alerts": [],
    }


# ---------------------------------------------------------------- 和风天气


def _qweather_icon(icon) -> tuple[str, str, int]:
    """和风图标代码 → (前端图标名, 等价 WMO 代码, 中文兜底)

    中文描述优先用接口返回的 text（它比本地映射更准），这里的第三个值只是
    text 缺失时的兜底。WMO 代码只用来判断「是不是雪 / 雷暴」。
    """
    try:
        code = int(icon)
    except (TypeError, ValueError):
        return "Cloudy", 3, "阴"
    if code in _QW_STORM:
        return "Lightning", 95, "雷阵雨"
    if 300 <= code < 400:
        if code in _QW_HEAVY_RAIN:
            return "Pouring", 65, "大雨"
        return "Drizzling", 61, "小雨"
    if 400 <= code < 500:
        return "Cloudy", 71, "雪"
    if code in (100, 150):
        return "Sunny", 0, "晴"
    if code in (101, 102, 103, 151, 152, 153):
        return "PartlyCloudy", 2, "多云"
    if code in (104, 154):
        return "Cloudy", 3, "阴"
    if code in _QW_FOG:
        return "Cloudy", 45, "雾"
    return "Cloudy", 3, "阴"


def _qweather_get(host: str, path: str, key: str, params: dict | None = None) -> dict:
    """一次和风 GET。

    Key 走 `X-QW-Api-Key` 请求头，不再拼进 query：旧写法一旦请求失败，
    requests 的异常信息会把整个 URL 打进日志，等于把 Key 明文写进日志。

    v7 预报把业务错误（Key 错、额度用尽、参数不对）放在 HTTP 200 的
    响应体里，看 `code` 判定；新版 v1 预警没有这个字段，有就判、没有就
    交给 HTTP 状态码 —— 两种都兼容，只用一个入口。
    """
    resp = requests.get(
        f"https://{host}{path}",
        headers={"X-QW-Api-Key": key},
        params=params or {},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") is not None and str(data.get("code")) != "200":
        raise ValueError(f"和风返回 code={data.get('code')}")
    return data


# 和风预警的等级：颜色码和英文严重程度都要能翻成中文。
# 页面上摆一个「（moderate）」没人看得懂 —— 气象台的说法是「黄色预警」
_ALERT_LEVELS = {
    "blue": "蓝色",
    "yellow": "黄色",
    "orange": "橙色",
    "red": "红色",
    # 英文严重程度兜底（新版接口不一定给 color）
    "minor": "蓝色",
    "moderate": "黄色",
    "severe": "橙色",
    "extreme": "红色",
}


def alert_level(alert: dict) -> str:
    """预警等级的中文名：优先用颜色，其次用英文严重程度；都没有返回空串"""
    for key in ("severity_color", "severity"):
        value = str(alert.get(key) or "").strip().lower()
        if value in _ALERT_LEVELS:
            return _ALERT_LEVELS[value]
    return ""


def _fetch_qweather_alerts(host: str, key: str, lat: float, lon: float) -> list[dict]:
    """官方气象预警（没有就空表）。

    `/v7/warning/now` 已于 2026 年被和风下线（实测返回 403 deprecated），
    新版是 `/weatheralert/v1/current/{lat}/{lon}`，返回 `{metadata, alerts}`。
    新版每项字段也不同：title/typeName/text 变成 headline/eventType.name/description。

    **单独兜异常**：预警接口挂了不该让整个预报变成「取不到」——
    预报本身还在，用户至少能看到天气。
    """
    try:
        data = _qweather_get(
            host, f"/weatheralert/v1/current/{lat:.4f}/{lon:.4f}", key,
            params={"lang": "zh"},
        )
    except Exception as exc:  # noqa: BLE001 —— 预警是附加信息，失败就当作没有
        print(f"[天气] 和风预警取数失败（不影响预报）：{exc}", flush=True)
        return []
    alerts = []
    for item in data.get("alerts") or []:
        # messageType.code: alert / update / cancel；取消掉的不该再提醒
        message_type = item.get("messageType") or {}
        if str(message_type.get("code") or "").lower() == "cancel":
            continue
        event_type = item.get("eventType") or {}
        color = item.get("color") or {}
        alerts.append({
            "id": str(item.get("id") or ""),
            "title": item.get("headline") or "",
            "type": event_type.get("name") or "",
            "severity": item.get("severity") or "",
            "severity_color": color.get("code") or "",
            # 发布单位：「石景山区气象台」。区/市两级各发一条时，靠它区分
            "sender": item.get("senderName") or "",
            "text": item.get("description") or "",
            "pub_time": item.get("issuedTime") or "",
            "start": item.get("effectiveTime") or "",
            "end": item.get("expireTime") or "",
        })
    return alerts


def _fetch_qweather(lat: float, lon: float, key: str, host: str) -> dict:
    """和风取数，归一化成和 Open-Meteo 一样的内部结构

    三个接口：实况（now）、未来 24 小时（24h）、未来 3 天（3d），外加预警。
    时间字段是带时区的 ISO 串（`2026-11-05T08:00+08:00`），截前 16 位就是
    `2026-11-05T08:00` —— 和 Open-Meteo 的格式一致，下游不用判断来源。
    """
    location = f"{lon:.4f},{lat:.4f}"
    query = {"location": location, "lang": "zh", "unit": "m"}
    now_raw = _qweather_get(host, "/v7/weather/now", key, query).get("now") or {}
    hourly_raw = _qweather_get(host, "/v7/weather/24h", key, query).get("hourly") or []
    daily_raw = _qweather_get(host, "/v7/weather/3d", key, query).get("daily") or []

    def _num(value, default=0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    hourly = []
    for item in hourly_raw:
        icon, code, fallback_text = _qweather_icon(item.get("icon"))
        hourly.append({
            "time": str(item.get("fxTime") or "")[:16],
            "temp": round(_num(item.get("temp"), 0)) if item.get("temp") not in (None, "") else None,
            "pop": int(_num(item.get("pop"), 0)),
            "code": code,
            "text": item.get("text") or fallback_text,
            "icon": icon,
        })

    days = []
    for item in daily_raw[:2]:
        icon, code, fallback_text = _qweather_icon(item.get("iconDay"))
        days.append({
            "date": str(item.get("fxDate") or "")[:10],
            "code": code,
            "text": item.get("textDay") or fallback_text,
            "icon": icon,
            "high": round(_num(item.get("tempMax"), 0)) if item.get("tempMax") not in (None, "") else None,
            "low": round(_num(item.get("tempMin"), 0)) if item.get("tempMin") not in (None, "") else None,
            # 和风的日级数据没有「降雨概率」，只有降水量（mm）；概率留给逐小时
            "pop": 0,
            "rain_mm": _num(item.get("precip"), 0),
            "wind_kmh": round(_num(item.get("windSpeedDay"), 0)),
        })

    icon, code, fallback_text = _qweather_icon(now_raw.get("icon"))
    return {
        "source": SOURCE_QWEATHER,
        "source_label": SOURCE_LABELS[SOURCE_QWEATHER],
        "current": {
            "temp": round(_num(now_raw.get("temp"), 0)),
            "feels_like": round(_num(now_raw.get("feelsLike"), 0)),
            "code": code,
            "text": now_raw.get("text") or fallback_text,
            "icon": icon,
            "updated_at": str(now_raw.get("obsTime") or "")[:16],
        },
        "hourly": hourly,
        "days": days,
        "alerts": _fetch_qweather_alerts(host, key, lat, lon),
    }


# ---------------------------------------------------------------- 取数入口


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
        data = None
        if qweather_ready(db):
            key, host = qweather_config(db)
            try:
                data = _fetch_qweather(lat, lon, key, host)
            except Exception as exc:  # noqa: BLE001 —— 和风挂了要有兜底
                # 不静默：管理员可能填错了 Key，而页面上只看得到天气还是好的。
                # 正文里会标出实际用的数据源（source_label），不会张冠李戴
                print(f"[天气] 和风取数失败，本轮回退 Open-Meteo：{exc}", flush=True)
        if data is None:
            data = _fetch(lat, lon)
        payload = {"ok": True, "data": data}
        ttl = _ttl_seconds(db)
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
        "site_url": site_url(db),
        "source": source_of(db),
        "source_label": source_label(db),
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
        # 实际用的数据源（和风失败回退时会和配置不一致，正文/页面上按这个说）
        "source": data.get("source", base["source"]),
        "source_label": data.get("source_label", base["source_label"]),
        **data["current"],
        # 今天的最低/最高：当前天气只有瞬时温度，日级数据里的这两个值
        # 是首页「最低 ° · 最高 °」那一行唯一的来源
        "low": today.get("low"),
        "high": today.get("high"),
        # 逐小时（前端横条）：时间已经裁成 HH:00
        "hourly": _slim_hourly(data.get("hourly") or [], now),
        # 明天：days[1]。取不到就 None，前端整块不显示
        "tomorrow": days[1] if len(days) > 1 else None,
        # 官方预警（只有和风有）：首页/横幅之外，页面也能据此提示
        "alerts": data.get("alerts") or [],
    }


def reset_cache() -> None:
    """测试用 / 管理员保存配置后：把缓存清掉，避免按旧地点或旧数据源继续用"""
    with _lock:
        _cache["at"] = 0.0
        _cache["payload"] = None
