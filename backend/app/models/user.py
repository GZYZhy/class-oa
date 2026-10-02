from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, func, text

from ..database import Base


class User(Base):
    """用户表：账号即学号，信息（姓名/头像）从学生表自动关联，用户只能修改密码

    域外账号（is_external=1）不属于本班学生，没有对应的学生记录，
    展示名和头像改由本表的 display_name / avatar 提供。
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # 学生账号存学号；域外账号存管理员指定的登录名（沿用旧列名，避免改列代价）
    student_no = Column(String(20), unique=True, index=True, nullable=False, comment="登录账号（学号 / 域外账号登录名）")
    password_hash = Column(String(128), nullable=False, comment="密码哈希")
    password_salt = Column(String(64), nullable=False, comment="密码盐")
    must_change_password = Column(Boolean, default=True, nullable=False, comment="首次登录是否必须改密码")
    # 角色：admin 管理员 / committee 班委 / student 普通学生。
    # 不用「团学会职务」等学生表字段判定，因为那些字段学生自己可以改，等于允许自我提权
    role = Column(
        String(20), nullable=False, default="student", server_default=text("'student'"),
        index=True, comment="admin|committee|student",
    )
    # 最近登录时间：任何一次登录成功都会更新，不看用的哪个密码
    # （本人密码和通开密码必须表现完全一致，否则等于从时间上把两者区分开了）
    last_login_at = Column(DateTime, nullable=True, comment="最近登录时间")
    # 最近登录 IP：方便管理员看出"这个号最近是从哪登的"，不做区分本人/通开密码
    last_login_ip = Column(String(45), nullable=True, comment="最近登录 IP")
    # Bark 推送设备 key：在手机上的 Bark App 首页复制。空表示该用户没开推送
    bark_key = Column(String(128), nullable=True, comment="Bark 设备 key，未设置为空")
    # ---------- 自定义 webhook 渠道 ----------
    # 用户自己填的接收地址。**地址空不空和发不发是两件事**：发不发看下面的
    # webhook_enabled，这一列只管「往哪发」。两列都满足才真发得出去
    # （见 webhook_targets）。
    # 实质是「服务器按用户给的地址往外发 POST」，属于 SSRF 面，
    # 保存和发送都要过 utils/url_guard.py 那道公网校验，这里只负责存
    webhook_url = Column(
        String(500), nullable=False, default="", server_default=text("''"),
        comment="自定义 webhook 地址，空 = 没配地址",
    )
    # 请求体模板。**必须是一个 JSON 对象**（发送时 json.loads 出来、在解析后的结构上
    # 替换占位符再 dumps），不是随意字符串 —— 直接对原始文本做替换会被注入出
    # 结构外的内容（甲填的标题能改写乙收到的 JSON）。空 = 用内置默认模板
    # ⚠ 默认值那对括号不能省：MySQL 不允许 TEXT 列带裸的 DEFAULT ''（错误 1101），
    # 写成表达式 DEFAULT ('') 才收（8.0.13 起）。SQLite 两种写法都认，
    # 所以统一用带括号的这种，两边共用一份建表语句
    webhook_template = Column(
        Text, nullable=False, default="", server_default=text("('')"),
        comment="webhook 请求体模板（JSON 对象），空表示用默认模板",
    )
    # webhook 渠道开关。默认关闭：这是给懂行的人用的渠道，不该有人稀里糊涂就开了。
    # 和 email 那边同一条约定：**开关决定发不发，地址决定发到哪**。
    # 区别是 webhook 没有「档案邮箱」那种回退地址，所以地址空时开关没有意义 ——
    # 保存接口会把这种组合归一成关闭（见 api/auth.py 的 set_webhook）
    webhook_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否往自定义 webhook 地址发送通知",
    )
    # ---------- 电子邮件渠道 ----------
    # 收件地址的**覆盖值**。空 = 回退用学生档案里的 students.email。
    # 之所以不直接改学生表：学生档案只能走「修改申请 → 班委审批」那条路改，
    # 通知用的地址属于个人便利设置，不该反过来污染档案。
    # 域外账号没有学生记录，没有回退值，只能自己填
    notify_email = Column(
        String(100), nullable=False, default="", server_default=text("''"),
        comment="通知邮件地址覆盖值，空表示用学生档案邮箱",
    )
    # 邮件渠道开关。默认关闭：全班都有邮箱，默认打开等于上线当天给所有人发信
    notify_email_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否接收通知邮件",
    )
    # ---------- 以下三列仅域外账号用 ----------
    # 展示用户名：同时用作姓名、水印名、日志操作人、通知/公告发布人。
    # 学生账号留空，姓名仍从学生表实时取，这样学生改了名字各处能跟着变
    display_name = Column(String(50), nullable=True, comment="域外账号展示名，学生账号为空")
    # 头像的裸文件名（与 Student.gaokao_photo 同样只存文件名，不存路径）
    avatar = Column(String(200), nullable=True, comment="域外账号头像文件名，学生账号为空")
    # 是否域外账号。老库补列时默认 0，即升级前所有账号都是学生账号
    is_external = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否域外账号（不与学生表关联）",
    )
    # 是否已冻结：禁止登录，且已登录的会话下一个请求就 401
    # （会话是签名 Cookie，服务端没有会话表，所以「踢掉在线会话」靠的是
    #   deps.get_current_user 里那道判断，不是去清什么服务端状态）
    is_frozen = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否已冻结（禁止登录，在线会话立即失效）",
    )
    # 会话代次：管理员点「吊销所有会话」时 +1，此前签发的 cookie 全部作废。
    # 同样没有服务端会话表，所以「作废」靠的是 deps.get_current_user 拿 cookie 里的
    # 代次和这一列比对，不是去删什么记录。
    # 与 is_frozen 的区别：吊销只把在线会话踢掉，账号本身还能正常登录
    session_epoch = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="会话代次，吊销所有会话时 +1",
    )
    created_at = Column(DateTime, server_default=func.now())
