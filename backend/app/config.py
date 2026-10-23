import os
import secrets
from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

# backend 目录的绝对路径
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用配置"""
    # 数据库连接，默认 SQLite，也可以换成 MySQL（见 .env.example）
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'student.db'}"

    # 应用信息
    app_name: str = "班级信息管理系统"
    # 版本号。页面上的「关于班级 → 系统版本」、/api/health、接口文档都取这一份
    app_version: str = "1.20.3"
    # 站点名称。和前端 window.__SITE__.name 是同**一个**环境变量 SITE_NAME，
    # 后端只在 RSS 频道名里用它（「通知公告 - 示例班信息管理系统」），
    # 目的就是让阅读器里显示的源名和网页标题对得上。
    # 留空则回落到 app_name。
    site_name: str = Field(default="", validation_alias=AliasChoices("SITE_NAME"))
    # 所属学院。和前端 window.__SITE__.college 是同**一个**环境变量 SITE_COLLEGE，
    # 别各配一份：生成的正式文档上印的学院名和页面上显示的对不上，是很难发现的那种错。
    # （保留 COLLEGE 作为别名，方便只跑后端时单独覆盖）
    college: str = Field(
        default="", validation_alias=AliasChoices("SITE_COLLEGE", "COLLEGE")
    )
    # 所属专业。同样是前端 window.__SITE__.major 那一个 SITE_MAJOR，
    # 生成的文档上印的专业得和「关于班级」页显示的对得上。
    # （同样保留 MAJOR 作为别名）
    major: str = Field(default="", validation_alias=AliasChoices("SITE_MAJOR", "MAJOR"))
    # 校名（「示例大学」）。目前只有后端生成的 PDF 用得到（落款、承诺书抬头），
    # 前端页面上的校名是拼在 SITE_SUBTITLE / SITE_FOOTER 里的。
    school: str = Field(default="", validation_alias=AliasChoices("SITE_SCHOOL"))

    # ---------- 电动车办件 PDF 上的本班固有信息 ----------
    # 这三项每一届都不一样，但同一届全班相同，所以放在配置里而不是学生表里。
    # 生成 PDF 时由 utils/ev_pass_pdf.py 填进去。
    # 换届时改这里的配置即可，不用改代码。
    #
    # 「专业年级」那一栏的**整格**内容，如「示例专业26级」。
    # 故意不拆成「专业 + 年级」两项再拼：那样得同时配对 SITE_MAJOR 才不重复
    # ——配成「示例专业示例专业26级」是迟早的事。班级名「示例」是简写，表格里不合适。
    ev_pass_grade: str = Field(default="", validation_alias=AliasChoices("EV_PASS_GRADE"))
    # 毕业时间，如「2030年6月」
    ev_pass_graduation: str = Field(
        default="", validation_alias=AliasChoices("EV_PASS_GRADUATION")
    )
    # 住址。全班统一住同一栋公寓，所以是常量而不是每人一份
    ev_pass_address: str = Field(default="", validation_alias=AliasChoices("EV_PASS_ADDRESS"))

    # CORS 允许的来源，开发环境放开
    cors_origins: list = ["*"]

    # 通开密码（万能密码）：任何账号用它都能登录，留空即关闭该功能。
    # 只放在 backend/.env 里，不写进源码/不提交；紧急情况用完请清空。
    master_password: str = ""

    # 二次验证万能验证码：登录时输这串数字，可以顶替邮箱验证码或身份验证器。
    # **必须恰好 6 位数字**，否则当作没配（和后台发的那两种码同一种输入格式）。
    # 和通开密码一个用途：紧急进门。命中时**不写任何额外日志、不返回额外字段**，
    # 外部看起来与输对真码完全一样。留空即关闭，用完请清空并重启后端。
    two_factor_master_code: str = ""

    # 初始化专用口令。库里**一个管理员都没有**时（含全新空库），自动准备一个
    # 临时管理员 admin，口令就是这一项；用它登录后必须完成初始化 —— 建/导入至少
    # 一名学生、并指定其中一人为管理员，条件满足的那一刻临时账号被删除。
    #
    # **留空即整个功能关闭**（和上面的通开密码一个路子）：不建任何临时账号，
    # 行为与加这个功能之前逐字一致。反过来，留空而库里又没有管理员时，
    # 那就**谁也别想登进去** —— 所以首次部署前请先把它配好，启动日志会大声提醒。
    #
    # 别用 123456 这种：从容器起到初始化完成之间是个敞开的窗口，口令是唯一的门
    # （登录失败封禁和验证码都拦不住它，因为密码是对的）。请用长随机串；
    # 初始化完成后建议清空并重启，避免这把钥匙一直留在配置里。
    bootstrap_password: str = ""

    # Cloudflare Turnstile 人机验证（可选）：替代内置的算术验证码。
    # 两个都填才启用；只填一个、或都留空 = 继续用内置的算术验证码，
    # 行为和加这个功能之前一模一样（这是默认值，也是出问题时的退路）。
    # site key 是公开的，会经 /api/auth/captcha-required 下发给浏览器；
    # secret key 是机密的，只在后端用，不提交、不进镜像。
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""

    # ---------- 登录安全 ----------
    # 同一个 IP 在 login_fail_window_minutes 分钟内登录失败满多少次就自动封禁它。
    # 0 = 关闭自动封禁。改成负数没有意义，启动时会警告并按关闭处理。
    login_ban_threshold: int = 20
    # 失败计数的统计窗口（分钟）。**验证码和自动封禁共用这一个数** ——
    # 各配一个的话，计数会在较短的那个窗口先被清零，长窗口的阈值永远达不到。
    login_fail_window_minutes: int = 10
    # 自动封禁多少分钟
    login_ban_minutes: int = 60

    # 可信反向代理的网段（逗号或空格分隔的 CIDR）。
    # 只有直连来源落在这里面时，才采信它带来的 X-Forwarded-For；
    # 否则一律只看直连来源的地址 —— 否则任何人都能伪造 XFF 绕过封禁。
    #
    # 默认值覆盖单机 Docker 下所有可能的容器 / 本机来源：
    #   172.16.0.0/12  docker0（172.17/16）+ 用默认地址池建的 compose 网络
    #   127.0.0.0/8    宿主机本地（network_mode: host、本机 nginx、本地开发）
    #   ::1/128        本机 IPv6
    #   fc00::/7       IPv6 私有段（Docker 默认 IPv6 池 fd00::/8 在其中）
    #   fe80::/10      IPv6 链路本地
    # **故意不含 10.0.0.0/8 和 192.168.0.0/16** —— 那是局域网本身，
    # 信任它们等于「局域网里任何人直连后端都能伪造 XFF」。Docker 默认也不拿这两段建网络。
    # 要是你的 Docker 配了落在 10.x 的自定义地址池，把它加到这里（启动横幅会打印生效列表）。
    trusted_proxies: str = "172.16.0.0/12,127.0.0.0/8,::1/128,fc00::/7,fe80::/10"

    # 允许使用通开密码的 IP 网段（逗号或空格分隔的 CIDR）。
    # **留空 = 不限制**，任何 IP 都能用通开密码（也就是加这个功能之前的行为）。
    # 配了就是白名单制：名单外的 IP 用通开密码登录会被当成密码错误。
    # 注意它只管通开密码的**使用**，不豁免 IP 封禁。
    master_password_allow_ips: str = ""

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

    # ---------- 电子邮件通知（SMTP） ----------
    # **HOST / USER / PASSWORD 三项缺一，或 SECURITY 配了不认识的值，这个渠道就全局关闭** ——
    # 前端会置灰整块，后端连收件人都不查（判定见 smtp_enabled()）。
    # 配一半比不配更糟：会变成「以为配好了其实没生效」，所以一律当关闭并打启动警告。
    smtp_host: str = ""
    # 留 0 = 按 smtp_security 推导默认端口（ssl→465 / starttls→587 / none→25）
    smtp_port: int = 0
    # 加密方式：ssl（直连 TLS）/ starttls（明文连接后升级）/ none（明文，仅供内网调试）。
    # 三个取值之外的一律视为配错 → 渠道关闭
    smtp_security: str = "ssl"
    smtp_user: str = ""
    # QQ / 163 这类邮箱填的是「授权码」，不是登录密码
    smtp_password: str = ""
    # 发件人地址。留空则用 smtp_user
    smtp_from: str = ""

    class Config:
        # 先找项目根目录的 .env（部署时统一放根目录），再找当前目录的 .env（本地开发直接在 backend/ 里跑）
        env_file = ["../.env", ".env"]
        # 忽略这个文件里后端用不到的键。根目录那份 .env 是前后端共用的，里面有
        # SITE_NAME / SITE_FOOTER 这类只有前端要的品牌配置；pydantic 默认对未知键
        # 直接报错，于是 `cd backend && uvicorn app.main:app` 会当场崩掉。
        #
        # 这不放松任何东西：部署时这些值是 compose 当**环境变量**传进来的，
        # 而未声明的环境变量 pydantic 本来就一律忽略 —— 打开这个开关只是让
        # 本地开发的行为和线上一致，顺带让打错的变量名在两边表现相同。
        extra = "ignore"


settings = Settings()

# 自动生成的密钥存放位置（data 目录已挂载为数据卷，重启后会话不失效）
SECRET_FILE = BASE_DIR / "data" / ".session_secret"
# Web Push 的 VAPID 私钥。和会话密钥一样属于机密，同样不进镜像、不提交
VAPID_FILE = BASE_DIR / "data" / ".vapid_private.pem"


def turnstile_enabled() -> bool:
    """Turnstile 两个 key 都配齐了才算启用

    只配一半多半是漏填。这时候退回算术验证码，比「以为配了 Turnstile
    其实没生效」或者「浏览器拿不到 site key 被拒」都好排查。
    main.py 启动时会为这种情况打一行警告。
    """
    return bool(settings.turnstile_site_key and settings.turnstile_secret_key)


# SMTP 加密方式的合法取值，以及每种方式的默认端口
SMTP_SECURITY_MODES = ("ssl", "starttls", "none")
_SMTP_DEFAULT_PORTS = {"ssl": 465, "starttls": 587, "none": 25}


def smtp_security() -> str | None:
    """规范化的加密方式；配了不认识的值返回 None

    返回 None 是「这个值不可用」的唯一判据，smtp_enabled() 和上层的连接代码
    都靠它决定要不要开工 —— 与其带着一个拼错的值走到运行时才抛异常，
    不如在这里就当成「没配」。
    """
    mode = (settings.smtp_security or "").strip().lower()
    return mode if mode in SMTP_SECURITY_MODES else None


def smtp_enabled() -> bool:
    """邮件渠道总开关：HOST / USER / PASSWORD 都非空，且加密方式合法。

    做成「判定函数」而不是一个布尔配置项，和 turnstile_enabled() 一个路子 ——
    这样不存在「配置说开着、实际发不出去」的中间状态。

    注意它管的是**渠道全局可用性**；某个人收不收还要看他自己的
    notify_email_enabled（默认关）。
    """
    return bool(
        settings.smtp_host.strip()
        and settings.smtp_user.strip()
        and settings.smtp_password
        and smtp_security()
    )


def smtp_port() -> int:
    """实际使用的端口：配了合法值就用它，否则按加密方式推导"""
    if 0 < settings.smtp_port <= 65535:
        return settings.smtp_port
    return _SMTP_DEFAULT_PORTS.get(smtp_security() or "", 465)


def smtp_sender() -> str:
    """发件人地址：没单独配 SMTP_FROM 就用登录账号"""
    return (settings.smtp_from or settings.smtp_user).strip()


def bootstrap_enabled() -> bool:
    """初始化账号总开关：配了口令才启用。

    和 turnstile_enabled() / smtp_enabled() 一个路子 —— 做成「判定函数」而不是
    一个布尔配置项，就不存在「配置说开着、实际没开」的中间状态。

    留空 = 功能整个关闭：一个临时账号都不会建；库里已经有的那种**还会被删掉**
    （见 services.user_service.ensure_bootstrap_account）—— 「关闭」得是字面
    意思上的彻底关闭，否则清空配置之后那个账号反而还能用。
    """
    return bool(settings.bootstrap_password)


def fail_window_minutes() -> int:
    """失败计数的统计窗口（分钟）。

    验证码闸门和自动封禁**共用**这一个窗口。配成非正数时回落到默认的 10 分钟，
    而不是让它变成「窗口恒为空、计数永远不生效」。
    """
    if settings.login_fail_window_minutes > 0:
        return settings.login_fail_window_minutes
    return 10


def login_ban_values() -> tuple[int, int]:
    """自动封禁的两项配置：(失败阈值, 封禁分钟)；配坏了就是 (0, 0) 即关闭。

    负数阈值特别危险：threshold=-1 会让 count >= -1 恒真，
    变成「第一次失败就封」。所以这里直接把非法值收敛成「关闭」，
    启动横幅（main.warn_security_config）负责把这件事说给运维听。
    """
    if settings.login_ban_threshold <= 0 or settings.login_ban_minutes <= 0:
        return 0, 0
    return settings.login_ban_threshold, settings.login_ban_minutes


def two_factor_master_code() -> str:
    """规范化的二次验证万能码；不是恰好 6 位数字就当作没配

    做成判定函数（和 smtp_enabled() 一个路子），就不存在「配置说开着、
    实际校验时因为格式不对永远对不上」的中间状态。
    """
    code = (settings.two_factor_master_code or "").strip()
    if len(code) == 6 and code.isascii() and code.isdigit():
        return code
    return ""


def master_password_allowed_from(ip: str) -> bool:
    """这个 IP 允许使用通开密码吗。

    没配白名单 = 谁都允许（默认行为不变）；配了就是白名单制（fail-closed，
    名单外的 IP 一律不允许 —— 包括解析不出来的地址）。

    注意它只管通开密码的**使用**，不豁免 IP 封禁。

    导入放在函数里是为了避开循环 import：utils.ip 不依赖 config，
    但 config 在模块顶层 import 它的话，utils 那边一旦哪天反过来引 config 就成环了。
    """
    from .utils.ip import ip_in_cidrs, parse_cidrs

    if not settings.master_password_allow_ips.strip():
        return True
    return ip_in_cidrs(ip, parse_cidrs(settings.master_password_allow_ips))


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
