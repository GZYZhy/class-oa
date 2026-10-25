from pydantic import BaseModel, Field


class WeatherNotifyOption(BaseModel):
    """可选项（条件 / 时段）：标签由后端给，前端不另写一份中文"""
    code: str
    label: str


class WeatherNotifySettingsResponse(BaseModel):
    enabled: bool
    conditions: list[str]
    rain_threshold: int
    heat_threshold: int
    cold_threshold: int
    wind_threshold: int
    window: str
    quiet_start: int
    quiet_end: int
    # 默认忽略 22:00–06:00 的降水/降雪/雷暴
    ignore_night: bool = True
    # 下面两项是静态元数据，省得前端再抄一遍中文
    available_conditions: list[WeatherNotifyOption] = Field(default_factory=list)
    windows: list[WeatherNotifyOption] = Field(default_factory=list)


class WeatherNotifySettingsUpdate(BaseModel):
    enabled: bool = False
    conditions: list[str] = Field(default_factory=list)
    rain_threshold: int = 60
    heat_threshold: int = 35
    cold_threshold: int = 0
    wind_threshold: int = 39
    window: str = "tomorrow"
    quiet_start: int = 22
    quiet_end: int = 7
    ignore_night: bool = True


class WeatherBannerSettingsUpdate(BaseModel):
    """管理员配置首页天气横幅与天气卡地点

    地点三件套原先在 .env（WEATHER_NAME / LAT / LON），现在改成管理员保存；
    两个坐标要么都给、要么都空，成对校验在 api/admin.py 里做。
    """
    name: str = Field("", max_length=100, description="天气卡显示的地点名称")
    lat: float | None = Field(None, description="纬度；与 lng 同时给")
    lng: float | None = Field(None, description="经度；与 lat 同时给")
    site_url: str = Field("", max_length=500, description="天气卡跳转的网站，空=不可点")
    notify_interval_hours: float = Field(6.0, description="天气提醒巡检间隔（小时）")
    enabled: bool = False
    conditions: list[str] = Field(default_factory=list)
    rain_threshold: int = 60
    heat_threshold: int = 35
    cold_threshold: int = 0
    wind_threshold: int = 39
    window: str = "today"
    ignore_night: bool = True


class WeatherBannerResponse(BaseModel):
    name: str = ""
    lat: float | None = None
    lng: float | None = None
    site_url: str = ""
    notify_interval_hours: float = 6.0
    enabled: bool
    conditions: list[str]
    rain_threshold: int
    heat_threshold: int
    cold_threshold: int
    wind_threshold: int
    window: str
    ignore_night: bool = True
    available_conditions: list[WeatherNotifyOption] = Field(default_factory=list)
    windows: list[WeatherNotifyOption] = Field(default_factory=list)
    # 「按现在的预报，横幅会不会显示」—— 管理员保存后能立刻看到判断结果
    preview_active: bool = False
    preview_lines: list[str] = Field(default_factory=list)
