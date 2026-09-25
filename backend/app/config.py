import os
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings

# backend 目录的绝对路径
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用配置"""
    # 数据库连接，默认 SQLite，后续可切换为 PostgreSQL/MySQL
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'student.db'}"

    # 应用信息
    app_name: str = "班级信息管理系统"
    app_version: str = "1.0.0"

    # CORS 允许的来源，开发环境放开
    cors_origins: list = ["*"]

    # 通开密码（万能密码）：任何账号用它都能登录，留空即关闭该功能。
    # 只放在 backend/.env 里，不写进源码/不提交；紧急情况用完请清空。
    master_password: str = ""

    # 会话 Cookie：签名密钥。留空则自动生成并保存到 data/.session_secret
    # 也可以用环境变量 SESSION_SECRET_KEY 显式指定
    session_secret_key: str = ""
    # 服务端签名有效期 7 天（签名层面的最长有效期，防用户手动改 cookie 延长会话）
    # 「不保持登录」的用户在浏览器关掉后 cookie 就没了，实际体验还是"关浏览器就失效"，
    # 具体逻辑见 app/middleware.py 的 RememberMeMiddleware
    session_max_age: int = 7 * 24 * 3600
    # HTTPS 下才发送 Cookie（本地开发为 HTTP，置 False；生产环境置 True）
    session_cookie_secure: bool = False

    # Bark 推送服务地址。默认官方服务器，自建（如 bark-server）时改这里
    bark_server: str = "https://api.day.app"

    # 本站对外的地址，例如 https://oa.example.com
    # 只用于推送通知里的校徽图标和点击跳转 —— 图标是**手机自己去拉**的，
    # 所以必须是手机能访问到的公网地址，局域网/localhost 填了也没用。
    # 留空则推送不带图标，其余一切照常（本地开发不配也能测推送本身）。
    public_base_url: str = ""

    # 浏览器推送（Web Push）的 VAPID 私钥。留空则自动生成并保存到 data/.vapid_private.pem
    # 也可以填 PEM 文本本身（pywebpush 会自己判断是路径还是内容）
    vapid_private_key: str = ""

    # VAPID 签名里的联系方式（contact URI）。推送服务只把它当作"出问题该找谁"的记录，
    # 不做投递校验，所以填个占位值也能用；但它**不能为空**，否则签名直接报错。
    # 格式必须是 mailto: 或 https:// 且带点号的域名，例如 mailto:admin@oa.example.com
    vapid_subject: str = "mailto:noreply@example.com"

    class Config:
        # 先找项目根目录的 .env（部署时统一放根目录），再找当前目录的 .env（本地开发直接在 backend/ 里跑）
        env_file = ["../.env", ".env"]


settings = Settings()

# 自动生成的密钥存放位置（data 目录已挂载为数据卷，重启后会话不失效）
SECRET_FILE = BASE_DIR / "data" / ".session_secret"
# Web Push 的 VAPID 私钥。和会话密钥一样属于机密，同样不进镜像、不提交
VAPID_FILE = BASE_DIR / "data" / ".vapid_private.pem"


def resolve_session_secret() -> str:
    """
    获取会话签名密钥。

    优先用环境变量；否则首次运行时生成一个随机密钥并落盘复用，
    避免代码里写死默认密钥导致的会话伪造风险。
    """
    if settings.session_secret_key:
        return settings.session_secret_key

    if SECRET_FILE.exists():
        saved = SECRET_FILE.read_text(encoding="utf-8").strip()
        if saved:
            return saved

    generated = secrets.token_urlsafe(48)
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(generated, encoding="utf-8")
    os.chmod(SECRET_FILE, 0o600)  # 仅属主可读写
    return generated


def resolve_vapid_key() -> str:
    """
    获取 Web Push 的 VAPID 私钥文件路径。

    形状和 resolve_session_secret 一样，但**不能**照抄它的内容生成方式：
    会话密钥是随机字符串，而这里必须是一份 EC 私钥的 PEM —— 写成随机串的话
    pywebpush 解析时会抛 VapidException。所以用 py_vapid 自己生成密钥对再落盘。

    返回的是**文件路径**：pywebpush 会先看这个路径存不存在，存在就按 PEM 文件读。

    这份私钥是和新会话密钥同级的机密：拿到它就能冒充本站向全班发推送。
    不进镜像（.dockerignore 已排除 data/）、不进版本库、不打印。
    """
    if settings.vapid_private_key:
        return settings.vapid_private_key

    if not VAPID_FILE.exists():
        # 延迟导入：没配浏览器推送的部署不该因为缺这个包而起不来
        from py_vapid import Vapid

        VAPID_FILE.parent.mkdir(parents=True, exist_ok=True)
        vapid = Vapid()
        vapid.generate_keys()
        # save_key 自己不做权限处理，0600 得我们设（和上面会话密钥一致）
        vapid.save_key(str(VAPID_FILE))
        os.chmod(VAPID_FILE, 0o600)

    return str(VAPID_FILE)
