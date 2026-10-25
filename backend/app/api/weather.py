"""天气：首页卡片（公开）+ 每个人的天气提醒设置（登录）

首页那张卡游客也看得到，所以 `GET /api/weather` 不加登录依赖 —— 它只吐天气本身，
不涉及任何班级/个人信息。提醒设置是个人偏好，必须登录。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import (
    WeatherNotifyOption,
    WeatherNotifySettingsResponse,
    WeatherNotifySettingsUpdate,
)
from ..services import weather_notify_service, weather_service
from .deps import get_current_user

router = APIRouter(prefix="/api/weather", tags=["天气"])


@router.get("", summary="当前天气（首页卡片 + 广播横幅）")
def current_weather(db: Session = Depends(get_db)):
    payload = weather_service.current(db)
    # 横幅挂在同一个响应里：首页只发一次请求，不额外多打一个接口
    payload["banner"] = weather_notify_service.banner_state(
        db, weather_service.forecast(db), None
    )
    return payload


def _notify_payload(row) -> WeatherNotifySettingsResponse:
    return WeatherNotifySettingsResponse(
        enabled=bool(row.enabled),
        conditions=weather_notify_service.parse_conditions(row.conditions),
        rain_threshold=row.rain_threshold,
        heat_threshold=row.heat_threshold,
        cold_threshold=row.cold_threshold,
        wind_threshold=row.wind_threshold,
        window=row.window,
        quiet_start=row.quiet_start,
        quiet_end=row.quiet_end,
        ignore_night=bool(row.ignore_night),
        # 标签由后端给一份，前端不另写中文 —— 加条件时只改 services/weather_notify_service.py
        available_conditions=[
            WeatherNotifyOption(code=code, label=label)
            for code, label in weather_notify_service.CONDITIONS.items()
        ],
        windows=[
            WeatherNotifyOption(code=code, label=label)
            for code, label in weather_notify_service.WINDOWS.items()
        ],
    )


@router.get(
    "/notify",
    response_model=WeatherNotifySettingsResponse,
    summary="我的天气提醒设置",
)
def read_notify_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _notify_payload(weather_notify_service.get_settings(db, user.student_no))


@router.put("/notify", summary="保存我的天气提醒设置")
def save_notify_settings(
    data: WeatherNotifySettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = weather_notify_service.put_settings(db, user.student_no, data)
    return {"message": "已保存", "enabled": bool(row.enabled)}
