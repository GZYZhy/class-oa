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
    """管理员配置首页天气横幅（和栏位名与个人提醒一致，判断逻辑复用同一套）"""
    enabled: bool = False
    conditions: list[str] = Field(default_factory=list)
    rain_threshold: int = 60
    heat_threshold: int = 35
    cold_threshold: int = 0
    wind_threshold: int = 39
    window: str = "today"
    ignore_night: bool = True


class WeatherBannerResponse(BaseModel):
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
