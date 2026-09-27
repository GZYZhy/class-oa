from sqlalchemy import Column, Integer, String, Boolean, DateTime, func, text

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
    created_at = Column(DateTime, server_default=func.now())
