from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from starlette.middleware.sessions import SessionMiddleware

from .config import (
    SMTP_SECURITY_MODES,
    fail_window_minutes,
    login_ban_values,
    settings,
    resolve_session_secret,
    smtp_enabled,
    smtp_port,
    smtp_security,
    smtp_sender,
)
from .middleware import RejectEarlyDataMiddleware, RememberMeMiddleware
from .api import api_router
from .database import Base, database_kind, engine, SessionLocal
from .database_migrate import backfill_notice_reads, run_migrations
from .services import ensure_default_users, purge_expired, seed_from_catalog
from .services.birthday_service import ensure_settings
from .services.scheduler import start as start_birthday_scheduler
from .utils.ip import parse_cidrs

# 确保数据目录存在
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PHOTO_DIR = DATA_DIR / "photos"
# 域外账号的头像单独一个目录，不和学生的照片混在一起
AVATAR_DIR = DATA_DIR / "avatars"
DATA_DIR.mkdir(exist_ok=True)
PHOTO_DIR.mkdir(exist_ok=True)
AVATAR_DIR.mkdir(exist_ok=True)

# 第一行日志就把「实际连的是哪个库」打出来，且**抢在任何一次连库之前** ——
# 换库之后最怕的是「以为在跑 MySQL、其实还在往 SQLite 文件里写」，数据进了哪个库、
# 备份该打包什么全看这一行；库连不上的时候，这条日志也已经说清它想连的是哪。
# 密码必须打码：日志会被 docker logs 收走，也可能被贴进 issue。
# 打码用 SQLAlchemy 自带的 render_as_string，不要自己写替换
print(
    f"[启动] 数据库：{database_kind()}（"
    f"{make_url(settings.database_url).render_as_string(hide_password=True)}）",
    flush=True,
)

# 「通知未读」功能新增了 notice_reads 表。建表**之前**先看一眼它在不在：
# 不在，说明这次是从老版本升级上来的 —— 建完表要把既有通知补成「全员已读」，
# 否则大家一登录就会看到「未读 30 条」，而那些通知早就看过了。
# 这个判断必须抢在 create_all 前面，建完就分不清「刚建的」和「本来就有」了。
NOTICE_READS_IS_NEW = not inspect(engine).has_table("notice_reads")

# 创建数据库表（只建新表）
Base.metadata.create_all(bind=engine)

# 再给老表补上新增的列（create_all 不会做这件事），必须在任何查询之前
run_migrations()

# 平滑升级：只在 notice_reads 刚建出来的这一次补，之后每次启动都不会再跑
if NOTICE_READS_IS_NEW:
    backfill_notice_reads()


def init_login_accounts() -> None:
    """首次启动时按学生名单自动建号（账号=学号，默认密码=身份证号后6位）

    已存在的账号不会被重置，重复启动无副作用。
    """
    db = SessionLocal()
    try:
        result = ensure_default_users(db)
        if result["created"]:
            print(f"[初始化] 已创建 {result['created']} 个登录账号")
        for student_no, name, password in result["fallback"]:
            print(f"[初始化] {name}（{student_no}）无身份证号，默认密码为学号后6位：{password}")
    finally:
        db.close()


init_login_accounts()


def init_resources() -> None:
    """首次启动时从旧版 RESOURCE_CATALOG 导入资料清单（无损迁移）

    老版本资料清单是写死在代码里的。改成数据库存之后，首次启动自动导过去，
    之后就以数据库为准。幂等：表非空就什么都不做。
    """
    # 旧版的清单数组，作为迁移的来源。迁移完之后这行就只是历史参考了。
    from .api.resources_legacy import RESOURCE_CATALOG

    db = SessionLocal()
    try:
        n = seed_from_catalog(db, RESOURCE_CATALOG)
        if n:
            db.commit()
            print(f"[初始化] 已导入 {n} 条资料下载条目（从旧版 RESOURCE_CATALOG）")
    finally:
        db.close()


init_resources()


def init_birthday_settings() -> None:
    """首次启动时把「生日关怀」的单行设置补出来（幂等：已有行就不动）

    先补行、再起调度线程：线程一上来就会读这张表。
    """
    db = SessionLocal()
    try:
        ensure_settings(db)
    finally:
        db.close()


init_birthday_settings()


def warn_turnstile() -> None:
    """TURNSTILE 只配了一个 key 时提示一句

    这时 turnstile_enabled() 是 False，登录页走的还是内置算术验证码。
    不提示的话，配了 site key 的人会一直以为 Turnstile 已经生效了。
    """
    if bool(settings.turnstile_site_key) != bool(settings.turnstile_secret_key):
        print(
            "[初始化] TURNSTILE 的 SITE_KEY / SECRET_KEY 只配了一个，"
            "已退回内置算术验证码（两个都填齐才启用）",
            flush=True,
        )


warn_turnstile()


def warn_security_config() -> None:
    """把这次启动生效的登录安全配置打在日志里

    这三行是排查 IP 相关问题最省事的入口：
    - 操作日志里所有人的 IP 都变成同一个私网地址 → 可信网段没覆盖到实际网络
    - 自动封禁「该封的没封」→ 看一眼可信网段是不是空的（空 = 自动封禁已关闭）
    """
    # 可信网段要先算出来：它同时决定「自动封禁开不开得起来」——
    # 网段为空时 is_ban_candidate 会拒绝一切地址（分不清代理和真实客户端），
    # 光看阈值配了就说「已开启」是在骗运维
    nets = parse_cidrs(settings.trusted_proxies)
    threshold, ban_minutes = login_ban_values()

    if threshold > 0 and nets:
        print(
            f"[安全] 登录失败 {threshold} 次/{fail_window_minutes()} 分钟 "
            f"→ 自动封禁该 IP {ban_minutes} 分钟",
            flush=True,
        )
    elif threshold > 0:
        # 原因由下面那条「可信代理网段」的日志展开说，这里只点一句，不重复
        print("[安全] 自动封禁不生效：没有可用的可信代理网段（详见下一行）", flush=True)
    else:
        # 配成 0 是关闭，配成负数 / 0 分钟是配错，两种都说清楚
        raw = (
            f"（配置值 LOGIN_BAN_THRESHOLD={settings.login_ban_threshold}、"
            f"LOGIN_BAN_MINUTES={settings.login_ban_minutes}）"
            if settings.login_ban_threshold < 0 or settings.login_ban_minutes <= 0
            else ""
        )
        print(f"[安全] 自动封禁已关闭{raw}", flush=True)

    if nets:
        print(
            f"[安全] 可信代理网段（{len(nets)} 个）："
            + ", ".join(str(n) for n in nets),
            flush=True,
        )
    else:
        print(
            "[安全] TRUSTED_PROXIES 为空或全部解析失败：X-Forwarded-For 一律不采信，"
            "所有请求看起来都来自代理 IP —— 自动封禁已关闭以免误封全体。"
            "反向代理部署下请把它配成代理所在的网段",
            flush=True,
        )

    # 通开密码是三态，横幅得说清是哪一种。只判白名单的话，功能关着的时候
    # 会打出「未限制来源 IP」——读起来像有个危险开关正敞着，其实它根本没启用，
    # 排查安全问题的第一眼就会被这行带偏。
    if not settings.master_password:
        note = (
            "；MASTER_PASSWORD_ALLOW_IPS 已配置但当前不生效"
            if settings.master_password_allow_ips.strip()
            else ""
        )
        print(f"[安全] 通开密码未启用（MASTER_PASSWORD 为空）{note}", flush=True)
    elif settings.master_password_allow_ips.strip():
        print(
            f"[安全] 通开密码已启用，仅限白名单 IP：{settings.master_password_allow_ips}",
            flush=True,
        )
    else:
        print("[安全] 通开密码已启用且未限制来源 IP", flush=True)


def warn_notify_channels() -> None:
    """把邮件渠道的生效状态打在日志里

    这一行的用途和上面的安全横幅一样：出了「怎么没收到邮件」的时候，
    先看这里就知道是没配、配了一半、还是配好了但那个人自己没开。
    """
    if not smtp_enabled():
        # 区分「压根没配」和「配了一半 / 配错了」—— 后两种是运维以为配好了的情况，
        # 不说清楚就会被当成功能坏了来排查
        partial = any(
            (settings.smtp_host.strip(), settings.smtp_user.strip(), settings.smtp_password)
        )
        if partial or settings.smtp_security.strip().lower() not in SMTP_SECURITY_MODES:
            print(
                "[通知] 邮件渠道未启用：SMTP_HOST / SMTP_USER / SMTP_PASSWORD 没配齐，"
                f"或 SMTP_SECURITY={settings.smtp_security!r} 不是 ssl/starttls/none 之一",
                flush=True,
            )
        else:
            print("[通知] 邮件渠道未配置，已关闭", flush=True)
        return

    mode = smtp_security()
    print(
        f"[通知] 邮件渠道已启用：{settings.smtp_host}:{smtp_port()}（{mode}），"
        f"发件人 {smtp_sender()}。用户各自在「账户设置」里开启后才会收到",
        flush=True,
    )
    if mode == "none":
        print(
            "[通知] 警告：SMTP_SECURITY=none 是明文连接，登录密码会裸奔。仅供内网调试，"
            "公网部署请改成 ssl 或 starttls",
            flush=True,
        )


warn_security_config()
warn_notify_channels()


def purge_ip_bans() -> None:
    """启动时清掉已经过期的封禁行

    平时不清理（列表接口在 SQL 里过滤过期行就够了），只在启动时清一次 ——
    这里能显式 commit，而放在任何 GET 接口里都容易变成「写库还忘了提交」的静默无效。
    """
    db = SessionLocal()
    try:
        n = purge_expired(db)
        db.commit()
        if n:
            print(f"[初始化] 已清理 {n} 条过期的 IP 封禁记录")
    finally:
        db.close()


purge_ip_bans()

# 每日生日任务：进程内起一个守护线程（项目唯一的定时任务）。
# 后端是单进程（Dockerfile 的 uvicorn 没带 --workers），所以进程内定时是安全的。
# 必须放在 create_all 之后 —— 它要读写 birthday_settings 表。
start_birthday_scheduler()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="班级学生信息管理系统，支持分类查询、统计检索",
    # 关掉交互式文档：/docs、/redoc、/openapi.json 默认对**未登录访客**返回 200，
    # 等于把全部接口清单（路径、参数、字段名）白送给扫描器，省得它一个个猜。
    # 本地开发要看文档，就把下面三行注释掉。
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注意中间件顺序：**后加的在外层**（add_middleware 把新中间件插到列表最前，
# 构建时又从后往前包，净效果是最后注册的那个最先拿到请求、最后拿到响应）。

# 内层：会话中间件，负责读/写签名会话
# 全局 max_age 设成 7 天（签名层面的上限），
# 具体 cookie 有效期由外层的 RememberMeMiddleware 根据「保持登录」勾选动态调整
app.add_middleware(
    SessionMiddleware,
    secret_key=resolve_session_secret(),
    session_cookie="oa_session",
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.session_cookie_secure,
)

# 外层：调整 cookie 有效期
# 必须排在 SessionMiddleware **之后**：oa_session 那个 Set-Cookie 是它在响应阶段
# 才追加的，注册成内层就永远读不到（那样「不保持登录」会静默失效，所有人都拿到
# 7 天的持久 Cookie）。详见 middleware.RememberMeMiddleware 的注释。
app.add_middleware(RememberMeMiddleware)

# 最后注册 = 最外层：0-RTT 写请求在这里当场回 425，
# 不再往下走到会话、鉴权和数据库。nginx 那边配合 proxy_set_header Early-Data
app.add_middleware(RejectEarlyDataMiddleware)

# 不挂载 /static：照片、资料、公告文件一律经带鉴权的接口下发，避免绕过登录直接猜 URL 拿到隐私文件

# 注册路由
app.include_router(api_router)


@app.get("/api/health", summary="健康检查")
def health_check():
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}
