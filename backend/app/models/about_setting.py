from sqlalchemy import Boolean, Column, Integer, Text, text

from ..database import Base


class AboutSettings(Base):
    """「关于班级」页的可配置项（单行表，id 恒为 1）

    为什么是单行表而不是 key-value：这三项天然一起读、一起写（打开页面取一次、
    管理员保存一次），单行表少一层「取不到就建默认值」的间接，固定主键也
    天然防止出现第二行。同样的取舍见 models/birthday.py 顶部那段说明。
    """

    __tablename__ = "about_settings"

    id = Column(Integer, primary_key=True)

    # 班级简介卡片。默认关：没写内容时不该在页面上留一张空卡片
    intro_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="关于班级页是否显示「班级简介」卡片",
    )
    # 正文是 Markdown，渲染时前端过一遍 DOMPurify（同通知公告的做法）。
    # ⚠ MySQL 的 TEXT 列不允许裸的 DEFAULT ''（错误 1101），要写成表达式 ('')
    intro_markdown = Column(
        Text, nullable=False, default="", server_default=text("('')"),
        comment="班级简介正文（Markdown）",
    )

    # 任职表默认开：这一页原本就有它，升级后不该凭空消失
    roster_enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("1"),
        comment="关于班级页是否显示任职表",
    )
    # 只决定展示顺序，不改学生表。存学号不存主键：账号以学号为业务主键，
    # 删号重建后学号不变（同 OperationLog.target_student_nos 的约定）
    roster_order = Column(
        Text, nullable=False, default="", server_default=text("('')"),
        comment="任职表的显示顺序（学号 JSON 数组）",
    )
