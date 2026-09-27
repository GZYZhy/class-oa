from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect
from starlette.middleware.sessions import SessionMiddleware

from .config import fail_window_minutes, login_ban_values, settings, resolve_session_secret
from .middleware import RememberMeMiddleware
from .api import api_router
from .database import Base, engine, SessionLocal
from .database_migrate import backfill_notice_reads, run_migrations
from .services import ensure_default_users, purge_expired, seed_from_catalog
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

    if settings.master_password_allow_ips.strip():
        print(
            f"[安全] 通开密码仅限白名单 IP：{settings.master_password_allow_ips}",
            flush=True,
        )
    else:
        print("[安全] 通开密码未限制来源 IP", flush=True)


warn_security_config()


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

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="班级学生信息管理系统，支持分类查询、统计检索",
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注意中间件顺序：后加的在内层，before 先执行、after 后执行。
# RememberMeMiddleware 必须在外层：等 SessionMiddleware 把 cookie 写进响应头之后，
# 它再根据 session["_remember"] 调整 Max-Age。

# 外层：调整 cookie 有效期（最后执行 after）
app.add_middleware(RememberMeMiddleware)

# 内层：会话中间件，负责读/写签名会话
# 全局 max_age 设成 7 天（签名层面的上限），
# 具体 cookie 有效期由外层 RememberMeMiddleware 根据「保持登录」勾选动态调整
app.add_middleware(
    SessionMiddleware,
    secret_key=resolve_session_secret(),
    session_cookie="oa_session",
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.session_cookie_secure,
)

# 不挂载 /static：照片、资料、公告文件一律经带鉴权的接口下发，避免绕过登录直接猜 URL 拿到隐私文件

# 注册路由
app.include_router(api_router)


@app.get("/api/health", summary="健康检查")
def health_check():
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}
