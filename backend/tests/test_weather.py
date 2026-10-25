"""天气：数据源、提醒判断、接口权限

    cd backend && python -m pytest tests/test_weather.py -q

天气这条线有三块最容易出问题：

1. **配置状态**：经纬度没配 / 填错 / 正常，首页要给出不同的占位，而且
   「没配」时绝不能去外呼 Open-Meteo。
2. **判断口径**：降雨看概率阈值、雪和雷暴看天气代码、高温/低温/大风看日级数据；
   关注时段是今天 / 明天 / 未来 24 小时，跨零点必须算对。
3. **隐私边界**：首页天气是公开的；个人提醒设置必须登录，改别人的设置不可能
   （接口按当前登录人取学号，不接受请求体里的学号）。
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models import WeatherBannerSettings
from app.schemas import WeatherBannerSettingsUpdate
from app.services import weather_notify_service as wn
from app.services import weather_service as ws

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"
STUDENT = "2024000002"


# ---------------------------------------------------------------- 纯逻辑


def _forecast():
    """一份覆盖所有判断分支的假预报：今天和明天各一天"""
    hourly = []
    for day, rows in (
        ("2026-10-25", [
            ("08:00", 20, 0),   # 晴
            ("09:00", 80, 61),  # 小雨
            ("10:00", 30, 95),  # 雷阵雨
            ("11:00", 10, 71),  # 小雪
        ]),
        ("2026-10-26", [
            ("09:00", 90, 61),  # 明天也有雨
        ]),
    ):
        for clock, pop, code in rows:
            text, icon = ws.weather_text(code)
            hourly.append({
                "time": f"{day}T{clock}", "temp": 18, "pop": pop,
                "code": code, "text": text, "icon": icon,
            })
    return {
        "current": {
            "temp": 18, "feels_like": 17, "code": 0, "text": "晴",
            "icon": "Sunny", "updated_at": "2026-10-25T08:00",
        },
        "hourly": hourly,
        "days": [
            {"date": "2026-10-25", "code": 61, "text": "小雨", "icon": "Drizzling",
             "high": 36, "low": 10, "pop": 80, "rain_mm": 3.2, "wind_kmh": 20},
            {"date": "2026-10-26", "code": 71, "text": "小雪", "icon": "Cloudy",
             "high": 25, "low": -3, "pop": 90, "rain_mm": 1.0, "wind_kmh": 45},
        ],
    }


def _rule(**overrides):
    row = wn._default_notify_row(STUDENT)
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


@pytest.fixture(autouse=True)
def _clear_weather_cache():
    ws.reset_cache()
    yield
    ws.reset_cache()


def test_config_state_distinguishes_unconfigured_and_invalid(monkeypatch):
    monkeypatch.setattr(settings, "weather_lat", "")
    monkeypatch.setattr(settings, "weather_lon", "")
    assert ws.state_of() == "unconfigured"
    assert ws.enabled() is False

    # 只填一个也算 invalid：半套坐标不该悄悄按 0 处理
    monkeypatch.setattr(settings, "weather_lat", "39.9")
    assert ws.state_of() == "invalid"

    monkeypatch.setattr(settings, "weather_lon", "abc")
    assert ws.state_of() == "invalid"

    monkeypatch.setattr(settings, "weather_lon", "116.2")
    assert ws.state_of() == "ok"
    assert ws.enabled() is True


def test_current_never_calls_out_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "weather_lat", "")
    monkeypatch.setattr(settings, "weather_lon", "")

    def boom(*_args, **_kwargs):
        raise AssertionError("没配坐标时不应该外呼")

    monkeypatch.setattr(ws, "_fetch", boom)
    data = ws.current()
    # 前端靠 state 判断，不要求这里带 hourly；关键是没去外呼
    assert data["state"] == "unconfigured"


def test_current_returns_error_instead_of_raising(monkeypatch):
    monkeypatch.setattr(settings, "weather_lat", "39.9")
    monkeypatch.setattr(settings, "weather_lon", "116.2")
    monkeypatch.setattr(settings, "weather_site_url", "https://example.com/weather")

    def fail(*_args, **_kwargs):
        raise TimeoutError("上游超时")

    monkeypatch.setattr(ws, "_fetch", fail)
    data = ws.current()
    assert data["state"] == "error"
    assert data["site_url"] == "https://example.com/weather"


def test_current_ok_slims_hourly_and_keeps_tomorrow(monkeypatch):
    monkeypatch.setattr(settings, "weather_lat", "39.9")
    monkeypatch.setattr(settings, "weather_lon", "116.2")
    monkeypatch.setattr(ws, "_fetch", lambda lat, lon: _forecast())

    # 固定「现在」为 07:30：否则测试在 09:00 之后跑会跳过 08:00 那条，
    # 条数随执行时刻变化。这里断的是裁剪逻辑，不该看钟。
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 25, 7, 30)

    monkeypatch.setattr(ws, "datetime", _FixedDateTime)
    data = ws.current()
    assert data["state"] == "ok"
    assert data["temp"] == 18 and data["feels_like"] == 17
    # 首页「最低 / 最高」来自今天那条日级数据，不能只有明天有
    assert (data["low"], data["high"]) == (10, 36)
    assert data["tomorrow"]["date"] == "2026-10-26"
    assert (data["tomorrow"]["low"], data["tomorrow"]["high"]) == (-3, 25)
    assert len(data["hourly"]) == 5  # 假数据一共 5 条，不超过 12
    assert all(len(item["time"]) == 5 for item in data["hourly"])


def test_current_tolerates_missing_daily_data(monkeypatch):
    """日级数组缺失时 low/high 是 None，接口不炸，前端那一行整行不显示"""
    monkeypatch.setattr(settings, "weather_lat", "39.9")
    monkeypatch.setattr(settings, "weather_lon", "116.2")
    monkeypatch.setattr(ws, "_fetch", lambda lat, lon: {
        "current": {"temp": 18, "feels_like": 17, "code": 0,
                    "text": "晴", "icon": "Sunny", "updated_at": ""},
        "hourly": [],
        "days": [],
    })
    data = ws.current()
    assert data["state"] == "ok"
    assert data["low"] is None and data["high"] is None
    assert data["tomorrow"] is None


def test_place_comes_from_admin_settings(tmp_path, monkeypatch):
    """地点/显示名读管理员配置（weather_banner_settings），不再读 env"""
    engine = create_engine(f"sqlite:///{tmp_path / 'weather.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        db.add(WeatherBannerSettings(
            id=1, name="测试地点", lat=39.9, lng=116.2,
            enabled=False, conditions="", window="today", ignore_night=True,
        ))
        db.commit()
        monkeypatch.setattr(ws, "_fetch", lambda lat, lon: _forecast())
        ws.reset_cache()
        data = ws.current(db)
        assert data["state"] == "ok"
        assert data["name"] == "测试地点"
        assert (data["low"], data["high"]) == (10, 36)

        # 只填一个坐标：invalid；两个都清空：unconfigured
        row = db.get(WeatherBannerSettings, 1)
        row.lng = None
        db.commit()
        ws.reset_cache()
        assert ws.current(db)["state"] == "invalid"

        row.lat = None
        db.commit()
        ws.reset_cache()
        assert ws.current(db)["state"] == "unconfigured"
    finally:
        db.close()


def test_put_banner_persists_place(tmp_path):
    """管理员保存时把地点三项写进单行表，供天气服务和横幅共用"""
    engine = create_engine(f"sqlite:///{tmp_path / 'weather_set.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        wn.put_banner(db, WeatherBannerSettingsUpdate(
            name="示例大学", lat=39.9273, lng=116.1998,
            enabled=False, window="today",
        ))
        row = db.get(WeatherBannerSettings, 1)
        assert (row.name, row.lat, row.lng) == ("示例大学", 39.9273, 116.1998)
    finally:
        db.close()


def test_parse_conditions_drops_unknown_and_dedupes():
    assert wn.parse_conditions(None) == []
    assert wn.parse_conditions("不是 JSON") == []
    assert wn.parse_conditions('["rain","bogus","rain","snow"]') == ["rain", "snow"]
    assert wn.parse_conditions(["rain", "bogus"]) == ["rain"]


def test_rain_uses_probability_threshold_and_reports_peak():
    data = _forecast()
    row = _rule(window="today", conditions=wn.dump_conditions(["rain"]), rain_threshold=70)
    hits, date_key = wn.evaluate(data, row, datetime(2026, 10, 25, 8, 0))
    assert date_key == "2026-10-25"
    assert [h["code"] for h in hits] == ["rain"]
    assert "80%" in hits[0]["detail"]


def test_all_conditions_cross_the_today_and_tomorrow_windows():
    data = _forecast()
    row = _rule(
        window="next24h",
        conditions=wn.dump_conditions(["rain", "snow", "storm", "heat", "cold", "wind"]),
    )
    hits, _ = wn.evaluate(data, row, datetime(2026, 10, 25, 8, 0))
    assert [h["code"] for h in hits] == ["rain", "snow", "storm", "heat", "cold", "wind"]
    # 「未来 24 小时」只在标题里出现一次；详情里不再重复，避免横幅折行
    assert all("未来 24 小时" not in h["detail"] for h in hits)
    assert all(h["title"].startswith("未来 24 小时") for h in hits)

    # 明天窗口只能看明天的日期，今天的高温不能算进来
    row.window = "tomorrow"
    hits, date_key = wn.evaluate(data, row, datetime(2026, 10, 25, 8, 0))
    assert date_key == "2026-10-26"
    codes = [h["code"] for h in hits]
    assert "rain" in codes and "cold" in codes and "wind" in codes
    assert "heat" not in codes
    # 明天窗口的详情仍保留「明天」，和以前逐字一致
    assert all(h["detail"].startswith("明天") for h in hits)


def test_ignore_night_filters_only_hourly_conditions():
    """默认忽略 22:00–06:00 的降水/降雪；关掉开关后照常计入"""
    data = {
        "hourly": [
            {"time": "2026-10-25T23:00", "temp": 5, "pop": 90, "code": 61,
             "text": "小雨", "icon": "Drizzling"},
            {"time": "2026-10-26T02:00", "temp": -1, "pop": 90, "code": 71,
             "text": "小雪", "icon": "Cloudy"},
        ],
        "days": [
            {"date": "2026-10-25", "high": 20, "low": 10, "wind_kmh": 10},
            {"date": "2026-10-26", "high": 20, "low": 10, "wind_kmh": 10},
        ],
    }
    now = datetime(2026, 10, 25, 21, 0)
    row = _rule(window="next24h", conditions=wn.dump_conditions(["rain", "snow"]))

    assert wn.evaluate(data, row, now)[0] == []

    row.ignore_night = False
    hits, _ = wn.evaluate(data, row, now)
    assert [h["code"] for h in hits] == ["rain", "snow"]


def test_quiet_hours_handle_midnight():
    row = _rule(quiet_start=22, quiet_end=7)
    assert wn.in_quiet_hours(row, datetime(2026, 10, 25, 23, 0)) is True
    assert wn.in_quiet_hours(row, datetime(2026, 10, 25, 6, 59)) is True
    assert wn.in_quiet_hours(row, datetime(2026, 10, 25, 7, 0)) is False
    assert wn.in_quiet_hours(row, datetime(2026, 10, 25, 12, 0)) is False

    row.quiet_start = row.quiet_end = 12
    assert wn.in_quiet_hours(row, datetime(2026, 10, 25, 12, 0)) is False


# ---------------------------------------------------------------- 接口


def _world(backend, db_name="weather.db"):
    b = backend(db=db_name, BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200
    r = b.client.post("/api/students", json={
        "student_no": ADMIN, "name": "甲", "id_card": "110101200501010001",
    })
    assert r.status_code < 300, r.text
    r = b.client.post("/api/students", json={
        "student_no": STUDENT, "name": "乙", "id_card": "110101200501010002",
    })
    assert r.status_code < 300, r.text
    assert b.client.post("/api/setup/finish", json={
        "admin_student_no": ADMIN
    }).status_code == 200
    b.logout()
    return b


@pytest.fixture
def wb(backend):
    return _world(backend)


def test_weather_tables_are_created_and_public_card_degrades_to_placeholder(wb):
    assert wb.rows(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'weather_notify_settings'"
    )[0][0] == 1
    assert wb.rows(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'weather_banner_settings'"
    )[0][0] == 1

    # 游客也能看首页天气；测试环境把经纬度清空了，所以是 unconfigured
    r = wb.client.get("/api/weather")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["state"] == "unconfigured"
    assert data["banner"] == {"active": False}


def test_notify_settings_require_login_and_are_personal(wb):
    assert wb.client.get("/api/weather/notify").status_code == 401
    assert wb.client.put("/api/weather/notify", json={"enabled": True}).status_code == 401

    assert wb.login(student_no=STUDENT, password="010002").status_code == 200
    default = wb.client.get("/api/weather/notify").json()
    assert default["enabled"] is False
    assert default["conditions"] == ["rain"]
    assert default["window"] == "tomorrow"
    assert default["quiet_start"] == 22 and default["quiet_end"] == 7
    assert default["ignore_night"] is True, "夜间天气默认忽略"
    # 中文标签由后端下发，前端不另写一份
    assert {item["code"] for item in default["available_conditions"]} >= {
        "rain", "snow", "storm", "heat", "cold", "wind",
    }

    r = wb.client.put("/api/weather/notify", json={
        "enabled": True,
        "conditions": ["rain", "bogus", "snow"],
        "rain_threshold": 999,
        "heat_threshold": -5,
        "cold_threshold": 99,
        "wind_threshold": 0,
        "window": "不存在的时段",
        "quiet_start": 99,
        "quiet_end": -1,
        "ignore_night": False,
    })
    assert r.status_code == 200, r.text
    saved = wb.client.get("/api/weather/notify").json()
    assert saved["enabled"] is True
    assert saved["conditions"] == ["rain", "snow"]
    assert saved["rain_threshold"] == 100      # 夹到 10–100
    assert saved["heat_threshold"] == 20       # 夹到 20–45
    assert saved["cold_threshold"] == 15       # 夹到 -40–15
    assert saved["wind_threshold"] == 10       # 夹到 10–120
    assert saved["window"] == "tomorrow"       # 非法值回默认
    assert saved["quiet_start"] == 23 and saved["quiet_end"] == 0
    assert saved["ignore_night"] is False


def test_banner_settings_are_admin_only_and_persist(wb):
    assert wb.login(student_no=STUDENT, password="010002").status_code == 200
    assert wb.client.get("/api/admin/weather-banner").status_code == 403
    assert wb.client.put("/api/admin/weather-banner", json={"enabled": True}).status_code == 403

    wb.logout()
    assert wb.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200
    default = wb.client.get("/api/admin/weather-banner").json()
    assert default["enabled"] is False
    assert default["name"] == ""
    assert default["lat"] is None and default["lng"] is None
    assert default["window"] == "today"
    assert default["ignore_night"] is True, "横幅也默认忽略夜间天气"
    assert default["preview_active"] is False  # 没配坐标，取不到预报就不显示

    # 坐标必须成对、范围合法；校验在保存前完成，不会去外呼
    r = wb.client.put("/api/admin/weather-banner", json={"lat": 39.9})
    assert r.status_code == 400
    r = wb.client.put("/api/admin/weather-banner", json={"lat": 91, "lng": 116})
    assert r.status_code == 400
    r = wb.client.put("/api/admin/weather-banner", json={"lat": 39.9, "lng": 181})
    assert r.status_code == 400

    r = wb.client.put("/api/admin/weather-banner", json={
        "name": "示例大学",
        "enabled": True,
        "conditions": ["rain", "heat"],
        "rain_threshold": 75,
        "heat_threshold": 33,
        "cold_threshold": 0,
        "wind_threshold": 39,
        "window": "today",
        "ignore_night": False,
    })
    assert r.status_code == 200, r.text
    saved = wb.client.get("/api/admin/weather-banner").json()
    assert saved["name"] == "示例大学"
    assert saved["enabled"] is True
    assert saved["conditions"] == ["rain", "heat"]
    assert saved["rain_threshold"] == 75
    assert saved["heat_threshold"] == 33
    assert saved["window"] == "today"
    assert saved["ignore_night"] is False
