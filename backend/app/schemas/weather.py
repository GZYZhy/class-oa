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
    # 夜间免打扰：这段时间不推送，落在里面的降水/降雪/雷暴也不计入判断
    quiet_start: int
    quiet_end: int
    # 当前数据源的中文名（和风天气 / Open-Meteo），页面说明照着写
    source_label: str = ""
    # 下面几项是静态元数据，省得前端再抄一遍中文
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


class WeatherBannerSettingsUpdate(BaseModel):
    """管理员配置首页天气横幅、天气卡地点与数据源

    地点三件套原先在 .env（WEATHER_NAME / LAT / LON），现在改成管理员保存；
    两个坐标要么都给、要么都空，成对校验在 api/admin.py 里做。
    """

    name: str = Field("", max_length=100, description="天气卡显示的地点名称")
    lat: float | None = Field(None, description="纬度；与 lng 同时给")
    lng: float | None = Field(None, description="经度；与 lat 同时给")
    site_url: str = Field("", max_length=500, description="天气卡跳转的网站，空=不可点")

    # 巡检间隔（分钟）：1–1440。默认 10 分钟，改小会更及时，但外呼也更频繁。
    # 范围在 api/admin.py 里校验（返回 400 + 中文说明），不用 pydantic 的 ge/le：
    # 那样越界会变成 422，和经纬度那几条的报错形态不一致
    notify_interval_minutes: int = Field(
        default=10, description="天气巡检间隔（分钟，1–1440）"
    )

    # ---- 数据源 ----
    source: str = Field(
        "open_meteo", description="数据源：open_meteo（默认）/ qweather（和风天气）"
    )
    qweather_key: str = Field(
        "", max_length=200, description="和风天气 API Key；选 qweather 时必填"
    )
    qweather_host: str = Field(
        "", max_length=200,
        description="和风 API Host，留空用 devapi.qweather.com",
    )

    enabled: bool = False
    conditions: list[str] = Field(default_factory=list)
    rain_threshold: int = 60
    heat_threshold: int = 35
    cold_threshold: int = 0
    wind_threshold: int = 39
    window: str = "today"
    # 夜间时段：这段时间里的降水/降雪/雷暴不计入横幅判断（官方预警不受影响）
    quiet_start: int = 22
    quiet_end: int = 7


class WeatherBannerResponse(BaseModel):
    name: str = ""
    lat: float | None = None
    lng: float | None = None
    site_url: str = ""
    notify_interval_minutes: int = 10
    source: str = "open_meteo"
    # 中文名与「配没配好」都由后端算，前端不自己判空
    source_label: str = "Open-Meteo"
    qweather_key: str = ""
    qweather_key_set: bool = False
    qweather_host: str = ""
    enabled: bool
    conditions: list[str]
    rain_threshold: int
    heat_threshold: int
    cold_threshold: int
    wind_threshold: int
    window: str
    quiet_start: int = 22
    quiet_end: int = 7
    available_conditions: list[WeatherNotifyOption] = Field(default_factory=list)
    windows: list[WeatherNotifyOption] = Field(default_factory=list)
    # 「按现在的预报，横幅会不会显示」—— 管理员保存后能立刻看到判断结果
    preview_active: bool = False
    preview_lines: list[str] = Field(default_factory=list)
