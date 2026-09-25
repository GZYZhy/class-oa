from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import settings, resolve_session_secret
from .middleware import RememberMeMiddleware
from .api import api_router
from .database import Base, engine, SessionLocal
from .database_migrate import run_migrations
from .services import ensure_default_users, seed_from_catalog

# 确保数据目录存在
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PHOTO_DIR = DATA_DIR / "photos"
DATA_DIR.mkdir(exist_ok=True)
PHOTO_DIR.mkdir(exist_ok=True)

# 创建数据库表（只建新表）
Base.metadata.create_all(bind=engine)

# 再给老表补上新增的列（create_all 不会做这件事），必须在任何查询之前
run_migrations()


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
