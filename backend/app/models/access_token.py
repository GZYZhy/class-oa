from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from ..database import Base


class AccessToken(Base):
    """个人访问令牌：给脚本 / MCP 这类外部程序用的长期凭据

    浏览器里用的是签名 Cookie，绑死在浏览器上，脚本没法用（塞 Cookie 既不安全
    也不稳定，改一次密码就失效）。这张表存的是一把能在
    `Authorization: Bearer oa_pat_…` 头里用的长期凭据。

    **令牌在权限上等同于「该账号的学生身份」**：请求进来时会把角色降级成
    student 再交给路由（见 api/deps.py 的 _user_from_pat），所以哪怕持有人是管理员，
    用令牌也只能读到、操作自己相关的数据，班委及以上的功能一律 403。

    存的是**明文令牌的 sha256**，不存明文：
    - 明文只在创建那一次的响应里出现，之后谁也拿不回来（包括管理员）
    - 为什么不用 utils/security.py 那套 pbkdf2：明文是 256 位随机串，没有字典空间
      可攻；而慢哈希会让**每一个 API 请求**都跑 10 万次迭代，是纯性能损耗。
      （密码用 pbkdf2 是因为人选的密码字典空间很小，两者不是一回事。）

    **刻意不定义 relationship()**：一是跟 User 模型的风格一致（那边也没有），
    二是 deps.py 里要把 User 对象 expunge 出 session 做降级，
    有关系的话容易在脱离后触发 lazy load 而报 DetachedInstanceError。
    """
    __tablename__ = "access_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="持有人")
    name = Column(String(50), nullable=False, comment="用户起的备注名，用来区分用途")
    # sha256 十六进制固定 64 位，加 unique 索引让每次请求的查表是 O(1)
    token_hash = Column(String(64), unique=True, index=True, nullable=False, comment="明文令牌的 sha256")
    # 明文开头一小段，只用于列表里让人认出是哪把。
    # 取的是**随机部分的**前 8 位，不是整串前 8 位 —— 整串前 7 位是固定的 "oa_pat_"，
    # 那样每把令牌看起来都一模一样。8 位只泄露 48 位熵，剩余 208 位仍然安全。
    prefix = Column(String(20), nullable=False, comment="明文开头片段（仅展示用）")
    # 用 Python 端时间而不是 func.now()：SQLite 的 CURRENT_TIMESTAMP 是 UTC，
    # 会比北京时间早 8 小时（同 operation_logs.created_at）
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True, comment="创建时间")
    # NULL = 不限期
    expires_at = Column(DateTime, nullable=True, comment="过期时间，NULL 表示不限期")
    last_used_at = Column(DateTime, nullable=True, comment="最后一次使用时间")
    revoked_at = Column(DateTime, nullable=True, comment="吊销时间，非空即已失效")
