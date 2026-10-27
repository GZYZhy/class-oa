from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text, text

from ..database import Base


class RuntimeSetting(Base):
    """运维在「系统管理 → 运维」里改的运行时配置（键值表）

    键就是 config.Settings 里的字段名（app_name / smtp_host / ...），值以字符串
    存；读取由 services/runtime_config.py 统一换算成对应的类型再写回 settings。

    为什么用一张通用键值表而不是给每类配置建表：这些项彼此无关、都只是一两个
    标量，建十来张单行表除了多一堆迁移没有别的好处。天气那份单独建表是因为它
    还要存条件阈值、开关这一组结构化字段，性质不一样。

    **只存「运维可改、改了立刻生效」的项**。机密与安全边界（通开密码、会话密钥、
    可信代理网段等）一律只认环境变量 —— 后台一旦能被改成后门，管理员账号失守就
    等于整站失守（清单见 runtime_config.ENV_ONLY）。
    """

    __tablename__ = "runtime_settings"

    key = Column(String(50), primary_key=True, comment="配置项，等于 Settings 字段名")
    value = Column(Text, nullable=False, default="", server_default=text("('')"), comment="配置值")
    # 用 Python 端时间，同 operation_logs.created_at（SQLite 的 CURRENT_TIMESTAMP 是 UTC）
    updated_at = Column(DateTime, default=datetime.now, comment="最后修改时间")
    updated_by_no = Column(String(20), nullable=False, default="", server_default=text("''"), comment="最后修改人账号")
    updated_by_name = Column(String(50), nullable=False, default="", server_default=text("''"), comment="最后修改人姓名")
