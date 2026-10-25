from sqlalchemy import Boolean, Column, Integer, String, Text, text

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

    # 默认关：横幅是给所有人看的，管理员明确打开才显示
    enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否在首页显示天气横幅",
    )
    # JSON 数组，取值 rain / snow / storm / heat / cold / wind
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
