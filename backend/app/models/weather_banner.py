from sqlalchemy import Boolean, Column, Float, Integer, String, Text, text

from ..database import Base


class WeatherBannerSettings(Base):
    """天气广播横幅（单行表，id 恒为 1）

    和「个人天气提醒」用的是同一套判断（services/weather_notify_service.py 的
    evaluate），区别只在于这份是**管理员给全站开的**：命中就显示在首页，
    和生日条幅并列，不发推送、也不需要去重。

    字段名刻意和 WeatherNotifySettings 保持一致 —— evaluate() 按属性名取值，
    两张表能用同一个函数判断，不必写两套逻辑。
    """

    __tablename__ = "weather_banner_settings"

    id = Column(Integer, primary_key=True)

    # ---- 天气卡地点（原先是 .env 的 WEATHER_NAME / LAT / LON）----
    # 两列都可空：都空 = 天气卡显示「未配置」；只填一个算脏数据，接口层会拒。
    # 名称只用于卡片上的显示，不影响取数。
    name = Column(
        String(100), nullable=False, default="", server_default=text("('')"),
        comment="天气卡显示的地点名称",
    )
    lat = Column(Float, nullable=True, comment="纬度，空=未配置")
    lng = Column(Float, nullable=True, comment="经度，空=未配置")
    # 天气卡点开的网站；空 = 卡片不可点
    site_url = Column(
        String(500), nullable=False, default="", server_default=text("('')"),
        comment="天气卡跳转的网站地址",
    )

    # ---- 巡检频率 ----
    # 单位是**分钟**（默认 10），取值 1–1440（24 小时）。原先存小时、默认 6，
    # 对「明天下雨」够用，但管理员想把提醒做得跟天气一样勤时就卡在 1 小时的下限上。
    # 老库的小时值在迁移里 ×60 回填（见 database_migrate._backfill_weather_interval）。
    notify_interval_minutes = Column(
        Integer, nullable=False, default=10, server_default=text("10"),
        comment="天气巡检间隔（分钟，1–1440）",
    )

    # ---- 数据源 ----
    # open_meteo：免费、无需 Key，没有官方预警；
    # qweather：和风天气，需要 Key，附带官方气象预警。
    # 选了 qweather 但 Key 为空时，保存会被拒（不做静默降级）；
    # 运行期和风接口出错时才回退 Open-Meteo，正文里会写明实际用的数据源。
    source = Column(
        String(20), nullable=False, default="open_meteo", server_default="open_meteo",
        comment="天气数据源：open_meteo / qweather",
    )
    qweather_key = Column(
        String(200), nullable=False, default="", server_default=text("('')"),
        comment="和风天气 API Key（仅后端使用）",
    )
    # 和风新版要在控制台拿形如 xxxx.re.qweatherapi.com 的专属 API Host；
    # 留空 = 用老的 devapi.qweather.com（老账号仍可用）
    qweather_host = Column(
        String(200), nullable=False, default="", server_default=text("('')"),
        comment="和风天气 API Host，留空用默认域名",
    )

    # 默认关：横幅是给所有人看的，管理员明确打开才显示
    enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否在首页显示天气横幅",
    )
    # JSON 数组，取值 rain / snow / storm / heat / cold / wind / alert
    conditions = Column(
        Text, nullable=False, default="", server_default=text("('')"),
        comment="触发横幅的天气条件（JSON 数组）",
    )

    rain_threshold = Column(
        Integer, nullable=False, default=60, server_default=text("60"),
        comment="降雨横幅的概率阈值（%）",
    )
    heat_threshold = Column(
        Integer, nullable=False, default=35, server_default=text("35"),
        comment="高温横幅的阈值（℃）",
    )
    cold_threshold = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="低温横幅的阈值（℃）",
    )
    wind_threshold = Column(
        Integer, nullable=False, default=39, server_default=text("39"),
        comment="大风横幅的阈值（km/h）",
    )

    # 关注时段：today / tomorrow / next24h（与个人提醒同一套取值）
    window = Column(
        String(10), nullable=False, default="today", server_default="today",
        comment="横幅关注哪段时间的天气",
    )

    # ---- 夜间时段 ----
    # 和个人提醒同一套含义：落在这一时段里的降水 / 降雪 / 雷暴不计入判断，
    # 免得横幅把凌晨三点的雨写成一件白天要处理的事。**官方预警不受它影响**。
    # 原先有个 ignore_night 开关，和个人提醒的「免打扰」讲的是同一件事，已合并：
    # 时段就是开关，起止相等 = 不过滤。
    quiet_start = Column(
        Integer, nullable=False, default=22, server_default=text("22"),
        comment="夜间时段开始（0-23）",
    )
    quiet_end = Column(
        Integer, nullable=False, default=7, server_default=text("7"),
        comment="夜间时段结束（0-23）",
    )
