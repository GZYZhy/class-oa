"""浏览器推送订阅模型

用户在「通知设置」里开启浏览器通知后，浏览器会给出一份订阅信息：
推送服务地址（endpoint）+ 两颗用于加密 payload 的公钥（p256dh/auth）。
后端拿这三样就能往那台设备发通知，不需要 APNs/FCM 的账号。

一个账号可以有多台设备（手机 + 电脑），所以是「一个学号 → 多行」。
"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime

from ..database import Base


class PushSubscription(Base):
    """浏览器推送订阅（一个浏览器一份）"""
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    # 只存学号不存 user_id：账号重建（数据重置脚本）后学号仍然对得上
    student_no = Column(String(20), index=True, nullable=False, comment="所属账号（学号）")

    # 推送服务地址。天然唯一（浏览器每次订阅都不同），所以拿它当 upsert 的键：
    # 同一台电脑换人登录时，改的是这一行的 student_no，而不是插一行新的
    endpoint = Column(String(500), unique=True, nullable=False, comment="推送服务地址")
    # 以下两颗是 RFC 8291 的加密公钥，原样从浏览器来，不做校验（格式由推送服务兜底）
    p256dh = Column(String(200), nullable=False, comment="客户端公钥")
    auth = Column(String(64), nullable=False, comment="认证密钥")

    # 用 datetime.now（北京时间）而不是 func.now()：SQLite 的 CURRENT_TIMESTAMP 是 UTC，会差 8 小时
    created_at = Column(DateTime, default=datetime.now, comment="订阅时间")
