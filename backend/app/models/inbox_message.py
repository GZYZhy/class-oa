"""站内信：一次推送给每个收件人各存一行

**为什么要做这个**：另外四个渠道都要求用户先做点什么才能收到 —— Bark 要装 App
填 key、浏览器推送要授权订阅、邮件要开开关（服务端默认还是关的）、webhook 要填地址。
默认配置下四条一个都不通，而 notify() 在没人可发时直接 return，不报错、不留痕。
于是「班委发了通知，全班一个字都没收到」这件事在系统里完全不可见。
站内信是唯一一个**登录了就能看到、不需要任何配置**的渠道，所以它是兜底的那一条。

**为什么一人一行**：已读状态本来就是「一人一条」一份，直接放在行上，查询不用 join。
NoticeRead 要加唯一约束兜底，是因为那里「通知」和「已读」分属两张表、展开通知会
重复触发标记；这里一行就是一条消息，不存在重复标记的问题。

用学号而不是 user_id 关联，和 NoticeRead / PushSubscription 同一个理由：
数据重置脚本会重建账号，重建之后学号仍然对得上。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from ..database import Base


class InboxMessage(Base):
    """收件箱里的一条消息"""
    __tablename__ = "inbox_messages"

    id = Column(Integer, primary_key=True, index=True)
    # 收件人账号。字段名与 NoticeRead.student_no 保持一致（域外账号也存在这里）
    student_no = Column(String(20), nullable=False, comment="收件人账号")
    # 标题正文**原样存**，不套 clip()：那是给对外发送用的长度限制（对方服务器未必
    # 受得了长文本），自己库里存档没必要截断
    title = Column(String(200), nullable=False, comment="标题")
    body = Column(Text, default="", comment="正文，纯文本，前端按文本渲染")
    # active / timeSensitive，与 notify() 的 level 同源。只用来在列表里标一下轻重，
    # 不影响送达 —— 站内信不做「免打扰」，存档缺一条就是缺一条
    level = Column(String(20), default="active", comment="通知等级")
    page = Column(String(200), nullable=True, comment="点开跳到哪（前端路由路径，可空）")
    # 用 datetime.now（北京时间）而不是 func.now()：SQLite 的 CURRENT_TIMESTAMP 是 UTC，差 8 小时
    created_at = Column(DateTime, default=datetime.now, comment="收到时间")
    # 首次打开的时间，空=未读。**自动已读也写这一列**：办件推进时 settle_topic 会
    # 把关联消息标成已读，那一刻不是「打开」，是「这消息不用看了」——但未读判定
    # 只认 read_at 是否为空，分开存就得每处查询都多算一层，不值得
    read_at = Column(DateTime, nullable=True, comment="首次打开（或被自动判定为已读）的时间，空=未读")
    # 关联的办件，形如 "leave:12"（kind:id），空=普通消息不参与自动已读。
    # 只有这个字段能让「办件处理完了，对应的消息自动算已读」成立 ——
    # 消息正文是给人看的，机器没法从「有新的请假申请待审核」里反推出是哪一单。
    # 办件被删（学生撤回待受理的申请）也不影响：这里存的是字符串，不设外键
    topic = Column(String(64), nullable=True, comment="关联的办件 kind:id；办件推进时对应未读消息自动已读")

    # 两个热查询都走这个索引：按人倒序翻列表、按人数未读（read_at 为空）
    __table_args__ = (
        Index("ix_inbox_user_read", "student_no", "read_at"),
    )
