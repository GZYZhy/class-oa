from sqlalchemy import Boolean, Column, Integer, String, Text, text

from ..database import Base


class WeatherNotifySettings(Base):
    """天气提醒：**每人一份**订阅设置

    和 birthday_settings 那种「全局单行表」不一样 —— 那份是管理员给全站开的开关，
    这份是每个人的个人偏好（开不开、盯哪些天气、几点到几点别吵），所以按学号存。

    学号而不是 users.id：账号以学号为业务主键，删号重建后学号不变
    （同 OperationLog / BirthdaySettings.notify_student_nos 的约定）。
    """

    __tablename__ = "weather_notify_settings"

    id = Column(Integer, primary_key=True)
    student_no = Column(String(20), nullable=False, unique=True, index=True, comment="学号")

    # 默认关：会往设备上推东西的功能一律默认关，由用户自己打开
    enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否订阅天气提醒",
    )
    # JSON 数组，取值 rain / snow / storm / heat / cold / wind
    # ⚠ MySQL 的 TEXT 列不允许裸的 DEFAULT ''，要写成表达式 ('')
    conditions = Column(
        Text, nullable=False, default="", server_default=text("('')"),
        comment="订阅的天气条件（JSON 数组）",
    )

    # 阈值：可定制化主要就体现在这几个数上
    rain_threshold = Column(
        Integer, nullable=False, default=60, server_default=text("60"),
        comment="降雨提醒的概率阈值（%）",
    )
    heat_threshold = Column(
        Integer, nullable=False, default=35, server_default=text("35"),
        comment="高温提醒的阈值（℃）",
    )
    cold_threshold = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="低温提醒的阈值（℃）",
    )
    wind_threshold = Column(
        Integer, nullable=False, default=39, server_default=text("39"),
        comment="大风提醒的阈值（km/h，39≈6级）",
    )

    # 关注时段：today（今天剩余）/ tomorrow（明天整天）/ next24h（未来 24 小时）
    window = Column(
        String(10), nullable=False, default="tomorrow", server_default="tomorrow",
        comment="关注哪段时间的天气",
    )

    # 静默时段：这段时间内不推送（跨零点，如 22 → 7）
    quiet_start = Column(
        Integer, nullable=False, default=22, server_default=text("22"),
        comment="静默开始时刻（0-23）",
    )
    quiet_end = Column(
        Integer, nullable=False, default=7, server_default=text("7"),
        comment="静默结束时刻（0-23）",
    )

    # 夜间天气：默认忽略 22:00–06:00 的降水/降雪/雷暴，避免半夜或清晨被叫醒
    ignore_night = Column(
        Boolean, nullable=False, default=True, server_default=text("1"),
        comment="是否忽略 22:00–06:00 的夜间天气",
    )

    # 去重：上一次发出去的提醒标识（形如 tomorrow:2026-10-26:rain）。同一件事不重复推
    last_key = Column(
        String(64), nullable=False, default="", server_default=text("('')"),
        comment="上次已发送的提醒标识，用于去重",
    )
