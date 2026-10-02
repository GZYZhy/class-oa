from sqlalchemy import Boolean, Column, Date, Integer, Text, text

from ..database import Base


class BirthdaySettings(Base):
    """生日关怀设置（单行表，id 恒为 1）

    **为什么是单行表，而不是「一张设置表 + 一堆 key-value 行」**：项目里没有
    key-value 设置的先例，管理员能改的东西一律「一个功能一张表」（范例见
    models/resource.py）。这组设置天然是一起读、一起写的，单行表比 key-value
    少一层「取不到就建默认值」的间接；固定主键也天然防止出现第二行。

    单行是刻意的：三个开关都是全局的，没有「按人配置」的诉求。
    """

    __tablename__ = "birthday_settings"

    id = Column(Integer, primary_key=True)
    # 首页条幅。默认开：匿名只暴露人数（见 api/birthday.py），是三个功能里
    # 唯一没有打扰性的，开着才有人知道这个功能存在
    banner_enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("1"),
        comment="首页是否显示生日条幅",
    )
    # 条幅显不显姓名。**只对已登录用户生效** —— 匿名永远只看得到人数，
    # 这一列管不到匿名分支（那边压根不返回姓名）
    banner_show_names = Column(
        Boolean, nullable=False, default=True, server_default=text("1"),
        comment="条幅是否显示寿星姓名（仅登录用户）",
    )
    # 是否给寿星本人推祝福。默认关：和 webhook / 邮件同一条约定 ——
    # 会往别人设备上发东西的渠道一律默认关闭，由管理员明确打开
    greet_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否给寿星本人推送祝福语",
    )
    # 祝福语模板，占位符 {{name}} {{age}} {{class}}。空 = 用内置默认文案
    # （同 users.webhook_template 的约定：空表示用默认）
    # ⚠ 默认值那对括号不能省：MySQL 不允许 TEXT 列带裸的 DEFAULT ''（错误 1101），
    # 写成表达式 DEFAULT ('') 才收（8.0.13 起）。SQLite 两种写法都认
    greet_template = Column(
        Text, nullable=False, default="", server_default=text("('')"),
        comment="祝福语模板，空表示用内置默认文案",
    )
    notify_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否把生日汇总通知给指定账号",
    )
    # 勾选的账号学号（JSON 数组串），照抄 OperationLog.target_student_nos 的做法。
    # **存学号不存 users.id**：账号以学号为业务主键，删号重建后学号不变，
    # 而且 recipients(only_no=...) 过滤的正是 User.student_no
    # ⚠ 同上：TEXT 列的默认值必须写成 DEFAULT ('')
    notify_student_nos = Column(
        Text, nullable=False, default="", server_default=text("('')"),
        comment="接收生日汇总通知的学号（JSON 数组）",
    )
    # 幂等标记：哪一天跑过每日任务。可空 = 一次都没跑过
    last_run_date = Column(Date, nullable=True, comment="每日任务最近一次运行的日期")
