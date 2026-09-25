from sqlalchemy import Column, Integer, String, Boolean, DateTime, func, text

from ..database import Base


class User(Base):
    """用户表：账号即学号，信息（姓名/头像）从学生表自动关联，用户只能修改密码"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    student_no = Column(String(20), unique=True, index=True, nullable=False, comment="登录账号（学号）")
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
    created_at = Column(DateTime, server_default=func.now())
