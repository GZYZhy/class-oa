"""电子邮件通知服务

把通知发到用户邮箱。和 Bark / 浏览器推送相比，这条渠道的价值在于**不需要用户
做任何准备**：学生档案里本来就存着邮箱（全班 36 人都有），所以它对偶尔才登录
的同学最有用。

这里只管邮件这一个渠道：`email_recipients` 查收件地址、`push` 真正发送。
「这件事该走哪几个渠道」的路由在 notify_service。

**本模块任何函数都不许把异常抛出去** —— 同 bark_service，发信失败绝不能连累
请假提交、公告发布这些主流程。

整条渠道受 config.smtp_enabled() 全局门控：SMTP 没配齐时，连收件人都不查。
"""

import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formatdate

from sqlalchemy.orm import Session

from ..config import settings, smtp_enabled, smtp_port, smtp_security, smtp_sender
from ..models import Student, User
# 格式判定放在 utils 里（保存接口和变更申请那边也要用同一个），这里再导出一次，
# 是为了让 `from .email_service import is_valid_email` 这类写法继续能用
from ..utils.email_addr import is_valid_email  # noqa: F401
from ..utils.notify_text import BODY_LIMIT, TITLE_LIMIT, clip

# 单次 socket 操作的超时。注意 smtplib 的 timeout **不是整个会话**的超时，
# 而是连接、每条命令各算一次 —— 所以下面循环里那个总预算不能省
TIMEOUT = 15
# 一次通知里所有收件人的总时间预算。没有它的话，一个卡住的 SMTP 服务器
# 能把线程池里的一条线程按住到 TCP 超时，拖累共用这个池子的其他同步接口
BUDGET = 60
# 单次通知最多发多少封。全班几十人够用，防的是以后人多或调用方出错时刷爆邮箱
MAX_RECIPIENTS = 100

# 「发送测试」专用的短预算（照 webpush_service 的 TEST_BUDGET）。
# 后台发送没人等，超时就超时；但测试是用户正盯着屏幕看结果的操作，
# 而 TIMEOUT 是**每步各算一次**的，连接 + 登录 + 发信最坏能叠到 45 秒 ——
# 那时候前端早断了，用户看到的是「网络错误」而不是「你密码填错了」。
# 5 秒对一个正常的 SMTP 服务器绰绰有余，只有真出问题才会用到这个上限。
TEST_TIMEOUT = 5
TEST_BUDGET = 15


def email_recipients(
    db: Session,
    roles: list[str] | None = None,
    only_no: str | None = None,
    exclude_no: str | None = None,
) -> list[str]:
    """查该收邮件的地址

    必须在请求处理过程中调用：返回的是纯字符串列表，交给后台任务就能直接发，
    后台任务因此不需要数据库会话（响应发出后会话可能已经关了）。

    地址的取法（和「账户设置」页面上写的是同一句话）：
    **`notify_email` 非空就用它，否则回退用学生档案里的邮箱。**

    - 必须先按用户自己的开关 notify_email_enabled 过滤，默认是关的；
    - **必须 outerjoin**：域外账号没有学生记录，inner join 会让「只填了
      notify_email 的域外账号」静默收不到邮件；
    - roles 过滤要 JOIN users 才拿得到角色，这点和 web_subscriptions 是同一个坑。
    """
    query = (
        db.query(User.notify_email, Student.email)
        .outerjoin(Student, Student.student_no == User.student_no)
        .filter(User.notify_email_enabled.is_(True))
    )
    if roles:
        query = query.filter(User.role.in_(roles))
    if only_no:
        query = query.filter(User.student_no == only_no)
    if exclude_no:
        query = query.filter(User.student_no != exclude_no)

    seen: set[str] = set()
    addresses: list[str] = []
    for notify_email, student_email in query.all():
        # 覆盖值优先，空则回退档案邮箱（两边都要 strip，库里可能存着空格）
        addr = (notify_email or "").strip() or (student_email or "").strip()
        if not is_valid_email(addr):
            # 格式不合法就跳过。这里不打印：查询是每次通知都会走的路径，
            # 脏地址会反复刷屏。真正发信时的跳过会有日志（见 _clean_addresses）
            continue
        key = addr.lower()
        if key in seen:
            # 两个人可能填了同一个地址（比如共用一个邮箱），去重免得收两封
            continue
        seen.add(key)
        addresses.append(addr)
    return addresses


def push(
    addresses: list[str], title: str, body: str,
    level: str = "active", page: str | None = None,
    timeout: int = TIMEOUT, budget: int = BUDGET,
) -> bool:
    """真正把邮件发出去；失败只打印日志，绝不抛出

    调用方是 Starlette 的后台任务，异常抛出去没人接。
    返回值只给「发送测试」用 —— 那个场景用户正等着看结果，所以那边会传
    更短的 timeout / budget（见 TEST_TIMEOUT）。

    level 参数收下但不用：邮件渠道的口径是「所有通知都发」，不分等级。
    保留它是为了和 bark_push / web_push 签名一致，将来要按等级过滤时不用改调用方。
    """
    if not smtp_enabled():
        return False

    targets = _clean_addresses(addresses)
    if not targets:
        return False

    server = None
    try:
        # 一次连接发完所有人：TLS 握手和登录都很慢，一人一条连接既慢又容易被
        # 对方服务器当成滥发。但下面仍然是**每人一封**，不是一封挂多个收件人 ——
        # 见 _send 的注释
        server = _connect(timeout)
        deadline = time.monotonic() + budget
        sent = 0
        for address in targets:
            if time.monotonic() > deadline:
                # 不静默截断：剩几个人没发到要留在日志里，否则「有人没收到」无从查起
                print(
                    f"[Email] 超出 {budget} 秒预算，剩余 {len(targets) - sent} 人未发送",
                    flush=True,
                )
                break
            if _send(server, address, title, body, page):
                sent += 1
        return sent > 0
    except Exception as exc:
        # 连不上、登录被拒、证书校验失败、配置写错都会落这里，一律只记一行
        print(f"[Email] 发送失败：{exc!r}", flush=True)
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                # 断开已经被对方关掉的连接会抛异常。这里绝不能再抛 ——
                # 它会盖掉上面返回的成功/失败结果
                pass


def _connect(timeout: int = TIMEOUT) -> smtplib.SMTP:
    """按配置建一条已登录的连接

    **context 必须显式传**：smtplib 在 context=None 时用的是
    ssl._create_stdlib_context()，实测 check_hostname=False、verify_mode=CERT_NONE，
    也就是**根本不校验证书** —— 照默认写法，SMTP 密码可以被中间人直接拿走。
    """
    host = settings.smtp_host.strip()
    port = smtp_port()
    mode = smtp_security()
    context = ssl.create_default_context()

    if mode == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
        if mode == "starttls":
            server.starttls(context=context)

    server.login(settings.smtp_user, settings.smtp_password)
    return server


def _send(server: smtplib.SMTP, address: str, title: str, body: str, page: str | None) -> bool:
    """发一封，返回是否成功

    每人一封而不是一封多收件人：库里那两个坏地址（和以后可能会有更多）必然被拒，
    混在批量里只会得到一个「部分被拒」的返回值，分不清是谁坏了；单独发时
    它是一条清晰的、可跳过并记录的失败。顺带也不会把全班邮箱挂进同一个 To: 头。
    """
    try:
        message = EmailMessage()
        # 主题必须过 clip()：它会把 \r\n 换成空格，这就是邮件头的第一道防线
        message["Subject"] = clip(title, TITLE_LIMIT)
        message["From"] = smtp_sender()
        message["To"] = address
        message["Date"] = formatdate(localtime=True)
        message.set_content(_body_text(body, page))
        server.send_message(message)
        return True
    except Exception as exc:
        # 单个地址坏（被对方拒收、超时）不影响其余收件人
        print(f"[Email] 发送失败（已跳过 {address}）：{exc!r}", flush=True)
        return False


def _body_text(body: str, page: str | None) -> str:
    """邮件正文 = 通知正文 + 回站内的链接

    链接的拼法和 Bark 完全一致（都是 hash 路由的 /#/xxx），
    没配 public_base_url 时就不带链接 —— 相对路径在邮件里点不开，宁可不给。
    """
    text = f"{body[:BODY_LIMIT]}\n\n—— 本邮件由「{settings.app_name}」自动发出，请勿直接回复。"
    base = settings.public_base_url.rstrip("/")
    if base:
        text += f"\n\n在站内查看：{base}/#{page}" if page else f"\n\n{base}"
    return text


def _clean_addresses(addresses: list[str]) -> list[str]:
    """发信前再过一遍：去重 + 丢掉格式不合法的

    收件人查询里已经过滤过一次，这里不是重复劳动：`push` 也会被「发送测试」
    直接调用（那里传入的是用户刚填的地址），而且以后有别的调用方时这层兜底还在。
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in addresses:
        addr = (raw or "").strip()
        if not is_valid_email(addr):
            if addr:
                # 打完整地址是有意的：不知道是哪个地址坏了，这条日志就没有价值。
                # 邮箱不是密钥，不进日志的只有密码
                print(f"[Email] 跳过格式不合法的收件地址：{addr}", flush=True)
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(addr)
    if len(cleaned) > MAX_RECIPIENTS:
        print(
            f"[Email] 收件人多于 {MAX_RECIPIENTS} 个，只发前 {MAX_RECIPIENTS} 个"
            f"（共 {len(cleaned)} 个）",
            flush=True,
        )
    return cleaned[:MAX_RECIPIENTS]
