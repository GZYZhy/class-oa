from sqlalchemy import create_engine, func
from sqlalchemy.engine import make_url
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from .config import settings

# 支持哪些数据库。sqlite 和 mysql（含 MariaDB）是实际验证过的，其余一律
# 在启动时直接报错 —— 理由见下面那段检查
SUPPORTED_DATABASES = ("sqlite", "mysql")


def database_kind() -> str:
    """实际在用的数据库类型

    走 SQLAlchemy 自己的 URL 解析，而不是「连接串里有没有 sqlite 这几个字」——
    后者靠字符串包含来判方言，连接串一换个写法就不靠谱了。

    MariaDB 归到 mysql：它的方言就是 MySQL 那一套，本项目的用法（日期函数、
    连接池、字符集）两边完全一致，没必要分家。
    """
    name = make_url(settings.database_url).get_backend_name()
    return "mysql" if name in ("mysql", "mariadb") else name


# 不支持的数据库**在启动时就拦住**，而不是让它带着能起、查询会错的半可用状态跑起来：
# 本项目里「近期生日」筛选、生日关怀的每日任务都用了方言相关的日期函数，
# 在别的库上不会建表失败、也不会启动失败，而是**跑到那一步才报错** ——
# 症状是首页偶尔 500、生日功能静默失灵，很容易被当成偶发 bug 查很久。
# 报错信息直接写出该怎么改，比让人对着 traceback 猜要省事。
if database_kind() not in SUPPORTED_DATABASES:
    raise RuntimeError(
        f"不支持的数据库：{database_kind()}。本项目只支持 SQLite 和 MySQL：\n"
        "  · 删掉 DATABASE_URL 这一行，会回到默认的 SQLite\n"
        "  · 或者改成 mysql+pymysql://用户:密码@主机:3306/库名（见 .env.example）"
    )

# 每种库要的引擎参数不一样，混着写会让两边都变差
_ENGINE_OPTIONS = {
    # SQLite：只要关掉「连接只能在创建它的线程里用」这个检查。
    # 单文件、没有服务端会主动掐断连接，别的参数都不需要
    "sqlite": {"connect_args": {"check_same_thread": False}},
    # MySQL 这三项各有一个具体的理由：
    #   charset       PyMySQL 自己默认就是 utf8mb4，这里显式写出来是防万一；
    #                 但要清楚**真正要紧的是库本身的字符集** —— 库如果建成了 latin1
    #                 （MySQL 5.7 的默认值），表跟着是 latin1，存中文名会直接报
    #                 「Incorrect string value」。那是建库时要定的，见 .env.example
    #   pool_recycle  服务端有 wait_timeout，到点就把连接掐了。而池里的连接可能已经
    #                 躺了好几个小时（生日定时线程每 5 分钟才用一次，夜里没人访问时
    #                 连接就一直闲着）。不回收的话症状是「MySQL server has gone away」
    #                 （2006），而且**只在下一个使用者那里偶发**，很难定位
    #   pool_pre_ping 兜住 pool_recycle 管不了的情况（比如 MySQL 重启过）：
    #                 从池里取连接时先探一下，坏了就悄悄换一条
    "mysql": {
        "connect_args": {"charset": "utf8mb4"},
        "pool_recycle": 3600,
        "pool_pre_ping": True,
    },
}

# 创建数据库引擎
engine = create_engine(settings.database_url, **_ENGINE_OPTIONS[database_kind()])

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 模型基类
Base = declarative_base()


def month_day_expr(column):
    """从日期列里取「月-日」的 SQL 表达式，结果是零填充的字符串（如 '10-03'）

    两个库的日期函数不一样（SQLite 是 strftime，MySQL 是 date_format），各写各的。
    之所以收成一个函数、不让调用方自己挑：调用点有两处（学生名单的「近期生日」筛选、
    生日关怀的每日任务），散开写的话以后换库很容易漏掉一处 —— 而漏掉的那处
    **只会在有人过生日那天才报错**，平时完全看不出来。

    返回的就是 SQLite 那套零填充格式，两边一致，所以拿它和 "10-03" 这样的字符串
    直接比大小是安全的。

    注：MySQL 的 '%m-%d' 会被 SQLAlchemy 当成绑定参数传下去，不会拼进 SQL 文本，
    所以不涉及 MySQL 字符串字面量里的百分号转义问题。
    """
    if database_kind() == "mysql":
        return func.date_format(column, "%m-%d")
    return func.strftime("%m-%d", column)


def get_db():
    """获取数据库会话的依赖注入函数"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
