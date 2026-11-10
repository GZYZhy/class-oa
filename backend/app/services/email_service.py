"""电子邮件通知服务

把通知发到用户邮箱。和 Bark / 浏览器推送相比，这条渠道的价值在于**不需要用户
做任何准备**：学生档案里本来就存着邮箱（全班 36 人都有），所以它对偶尔才登录
的同学最有用。

这里只管邮件这一个渠道：`email_targets` / `email_recipients` 查收件人、`push` 真正发送。
「这件事该走哪几个渠道」的路由在 notify_service。

**本模块任何函数都不许把异常抛出去** —— 同 bark_service，发信失败绝不能连累
请假提交、公告发布这些主流程。

整条渠道受 config.smtp_enabled() 全局门控：SMTP 没配齐时，连收件人都不查。
"""

import html as html_lib
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate

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


@dataclass(frozen=True)
class EmailTarget:
    """一个邮件收件人

    比纯地址多带三样东西，都是为了邮件里的已读能力：
    student_nos 是共用这个地址的账号（一个地址可能被多名学生填了），
    read_url 是「标记为已读」按钮的签名链接，open_url 是给非重要通知用的
    唯一校徽地址。后台任务拿着它就能直接发，不需要数据库会话。
    """

    address: str
    student_nos: tuple[str, ...] = ()
    read_url: str | None = None
    # 唯一校徽地址：非「重要」通知加载它时自动标已读。重要通知不填这个字段。
    open_url: str | None = None


def _address_rows(
    db: Session,
    roles: list[str] | None = None,
    only_no: str | None = None,
    exclude_no: str | None = None,
) -> list[tuple[str, str]]:
    """查 (学号, 邮箱) 对，保留每个账号一行（同一地址可能对应多人）"""
    query = (
        db.query(User.student_no, User.notify_email, Student.email)
        .outerjoin(Student, Student.student_no == User.student_no)
        .filter(User.notify_email_enabled.is_(True))
    )
    if roles:
        query = query.filter(User.role.in_(roles))
    if only_no:
        query = query.filter(User.student_no == only_no)
    if exclude_no:
        query = query.filter(User.student_no != exclude_no)

    rows: list[tuple[str, str]] = []
    for student_no, notify_email, student_email in query.all():
        # 覆盖值优先，空则回退档案邮箱（两边都要 strip，库里可能存着空格）
        addr = (notify_email or "").strip() or (student_email or "").strip()
        if is_valid_email(addr):
            rows.append((student_no, addr))
        # 格式不合法就跳过，不打印：查询是每次通知都会走的路径，脏地址会反复刷屏
    return rows


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
    return _dedupe_addresses(addr for _, addr in _address_rows(
        db, roles=roles, only_no=only_no, exclude_no=exclude_no
    ))


def email_targets(
    db: Session,
    roles: list[str] | None = None,
    only_no: str | None = None,
    exclude_no: str | None = None,
) -> list[EmailTarget]:
    """和 email_recipients 同一套取址规则，但把共用一个邮箱的学号归到一起

    邮件是每人一封，地址去重后只发一封；可这一封里得能同时标记多个人的站内信，
    所以不能像 email_recipients 那样只留地址。read_url 此时还不填 —— 它依赖
    站内信写库后的消息 id，由 notify_service 补上。
    """
    grouped: dict[str, dict] = {}
    for student_no, addr in _address_rows(
        db, roles=roles, only_no=only_no, exclude_no=exclude_no
    ):
        key = addr.lower()
        entry = grouped.setdefault(key, {"address": addr, "nos": []})
        entry["nos"].append(student_no)
    return [
        EmailTarget(entry["address"], tuple(entry["nos"]))
        for entry in grouped.values()
    ]


def _dedupe_addresses(addresses) -> list[str]:
    """地址去重（不区分大小写），保留第一次出现的写法"""
    seen: set[str] = set()
    result: list[str] = []
    for addr in addresses:
        key = addr.lower()
        if key not in seen:
            seen.add(key)
            result.append(addr)
    return result


def push(
    addresses: list[str | EmailTarget], title: str, body: str,
    level: str = "active", page: str | None = None,
    timeout: int = TIMEOUT, budget: int = BUDGET,
    code: str | None = None,
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

    targets = _clean_targets(addresses)
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
        for target in targets:
            if time.monotonic() > deadline:
                # 不静默截断：剩几个人没发到要留在日志里，否则「有人没收到」无从查起
                print(
                    f"[Email] 超出 {budget} 秒预算，剩余 {len(targets) - sent} 人未发送",
                    flush=True,
                )
                break
            # 重要通知不走图片自动已读：它们的 open_url 即便存在也不使用
            open_url = target.open_url if level != "timeSensitive" else None
            if _send(
                server, target.address, title, body, page,
                code=code, read_url=target.read_url, open_url=open_url,
            ):
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


def _send(
    server: smtplib.SMTP, address: str, title: str, body: str,
    page: str | None, code: str | None = None,
    read_url: str | None = None, open_url: str | None = None,
) -> bool:
    """发一封，返回是否成功

    每人一封而不是一封多收件人：库里那两个坏地址（和以后可能会有更多）必然被拒，
    混在批量里只会得到一个「部分被拒」的返回值，分不清是谁坏了；单独发时
    它是一条清晰的、可跳过并记录的失败。顺带也不会把全班邮箱挂进同一个 To: 头。
    """
    try:
        message = EmailMessage()
        # 主题必须过 clip()：它会把 \r\n 换成空格，这就是邮件头的第一道防线
        message["Subject"] = clip(title, TITLE_LIMIT)
        # 发件人显示名用站名：收件箱里看到的是「统1办」而不是一串邮箱地址。
        # 地址本身仍用 SMTP_FROM / SMTP_USER，显示名不影响投递。
        message["From"] = formataddr(
            ((settings.site_name.strip() or settings.app_name), smtp_sender())
        )
        message["To"] = address
        message["Date"] = formatdate(localtime=True)
        # 纯文本与 HTML 同时发。老客户端/纯文本模式看前者，现代客户端看后者；
        # 两者内容一致，HTML 只是把同样的字排成站点主题的卡片。
        message.set_content(_body_text(body, page, read_url=read_url))
        message.add_alternative(
            _body_html(
                title, body, page, code=code, read_url=read_url, open_url=open_url
            ),
            subtype="html",
        )
        server.send_message(message)
        return True
    except Exception as exc:
        # 单个地址坏（被对方拒收、超时）不影响其余收件人
        print(f"[Email] 发送失败（已跳过 {address}）：{exc!r}", flush=True)
        return False


def _body_text(
    body: str, page: str | None, read_url: str | None = None,
) -> str:
    """邮件正文 = 通知正文 + 回站内的链接 + 标记已读链接

    链接的拼法和 Bark 完全一致（都是 hash 路由的 /#/xxx），
    没配 public_base_url 时就不带链接 —— 相对路径在邮件里点不开，宁可不给。
    read_url 是带签名的绝对地址，点一下就把这次通知标为已读，不用登录。
    """
    text = f"{body[:BODY_LIMIT]}\n\n—— 本邮件由「{settings.app_name}」自动发出，请勿直接回复。"
    base = settings.public_base_url.rstrip("/")
    if base:
        text += f"\n\n在站内查看：{base}/#{page}" if page else f"\n\n{base}"
    if read_url:
        text += f"\n\n标记为已读：{read_url}"
    return text


def _logo_url() -> str:
    """邮件里引用的校徽地址；没配 public_base_url 时返回空串

    邮箱客户端默认可能不加载远程图片，所以 <img> 上必须写 alt；
    即使被拦，旁边仍有站名和标题，不影响阅读。
    """
    base = settings.public_base_url.rstrip("/")
    return f"{base}/logo.png?v=1" if base else ""


def _body_html(
    title: str, body: str, page: str | None, code: str | None = None,
    read_url: str | None = None, open_url: str | None = None,
) -> str:
    """邮件 HTML 正文：站点主题的卡片，不依赖外部 CSS

    邮件客户端对 CSS 的支持很有限：`<style>` 常被剥掉、flex/grid 不可用、
    远程图片默认不加载。所以这里用 table 布局 + 全部内联样式，配色取自站点
    的靛蓝 / 浅紫主题。校徽是远程图片，带 alt，被拦截时也不影响阅读。

    验证码类邮件单独排版：把验证码从正文里提出来，放大、加字距、放进浅紫卡片，
    并去掉「在站内查看」按钮（用户正在登录页，按钮没有意义）。

    read_url 非空时多一个「标记为已读」按钮：它带签名、不要求登录，
    用户不必打开站点就能清掉对应站内信的未读状态。

    open_url 是给非重要通知用的唯一校徽地址：客户端加载校徽时请求它，
    接口会顺手把站内信标为已读。重要通知的 open_url 由调用方置空，
    所以这里不用再判断等级。
    """
    site = html_lib.escape(settings.site_name.strip() or settings.app_name)
    safe_title = html_lib.escape(title)
    logo = open_url or _logo_url()
    logo_cell = ""
    if logo:
        logo_cell = (
            '<td width="50" valign="middle" style="padding-right:12px;">'
            f'<img src="{html_lib.escape(logo, quote=True)}" width="44" height="44" '
            # 站点和邮件里的校徽都取正圆；open_url 只是带令牌的同一张图
            'alt="校徽" style="display:block;border-radius:50%;background:#ffffff;">'
            "</td>"
        )

    if code and code in body:
        before, _, after = body.partition(code)
        intro = html_lib.escape(before.strip()) or "你的验证码是"
        tail = html_lib.escape(after.lstrip("，。 ,")).replace(chr(10), "<br>")
        content = (
            '<p style="margin:0 0 4px;color:#2f3447;font-size:14px;line-height:1.8;">'
            f"{intro}</p>"
            '<div style="margin:14px 0 16px;padding:16px 8px;text-align:center;'
            "background:#f4f5ff;border:1px solid #e2e3f7;border-radius:12px;"
            "color:#343a66;font-size:30px;line-height:1.2;font-weight:700;"
            f'letter-spacing:8px;">{html_lib.escape(code)}</div>'
            f'<p style="margin:0;color:#2f3447;font-size:14px;line-height:1.85;">{tail}</p>'
        )
        action = ""
    else:
        content = (
            '<p style="margin:0;color:#2f3447;font-size:14px;line-height:1.85;">'
            f'{html_lib.escape(body[:BODY_LIMIT]).replace(chr(10), "<br>")}</p>'
        )
        base = settings.public_base_url.rstrip("/")
        link = f"{base}/#{page}" if base and page else (base or "")
        action = ""
        if link or read_url:
            buttons = []
            if link:
                buttons.append(
                    f'<a href="{html_lib.escape(link, quote=True)}" '
                    'style="display:inline-block;background:#5b5bd6;color:#ffffff;'
                    'text-decoration:none;font-size:14px;font-weight:600;'
                    'padding:12px 22px;border-radius:10px;">在站内查看</a>'
                )
            if read_url:
                read_style = (
                    "background:#eef0ff;color:#4b4bc4;border:1px solid #d9daf5;"
                    if link
                    else "background:#5b5bd6;color:#ffffff;"
                )
                gap = "margin-left:10px;" if link else ""
                buttons.append(
                    f'<a href="{html_lib.escape(read_url, quote=True)}" '
                    f'style="display:inline-block;{read_style}text-decoration:none;'
                    'font-size:14px;font-weight:600;padding:12px 22px;'
                    f'border-radius:10px;{gap}">标记为已读</a>'
                )
            hint = (
                '<div style="margin-top:10px;color:#8a90a5;font-size:12px;'
                'line-height:1.6;">不想打开站点？点「标记为已读」即可清除这次的'
                '站内未读。</div>'
                if link and read_url
                else ""
            )
            action = (
                '<tr><td style="padding:6px 32px 26px;">'
                + "".join(buttons) + hint + "</td></tr>"
            )

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title></head>
<body style="margin:0;padding:0;background:#eef0f7;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
{html_lib.escape(body[:80])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
  style="background:#eef0f7;padding:26px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
  style="max-width:560px;background:#ffffff;border:1px solid #e2e4f2;
  border-radius:16px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,
  'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif;">
<tr><td style="background:#5b5bd6;background-image:linear-gradient(135deg,#5b5bd6,#8b7cf6);
  padding:20px 30px 18px;color:#ffffff;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
  {logo_cell}
  <td valign="middle">
    <div style="font-size:11px;letter-spacing:.12em;opacity:.78;margin-bottom:5px;">{site}</div>
    <div style="font-size:19px;line-height:1.4;font-weight:700;">{safe_title}</div>
  </td>
  </tr></table>
</td></tr>
<tr><td style="padding:24px 32px 18px;">{content}</td></tr>
{action}
<tr><td style="background:#f7f8fd;border-top:1px solid #e8eaf5;padding:14px 32px;
  color:#8a90a5;font-size:12px;line-height:1.6;">
  本邮件由「{site}」自动发出，请勿直接回复。<br>
  如不想继续收到邮件，可在站内「我的信息 → 账户设置 → 通知设置」关闭邮件通知。
</td></tr>
</table>
<div style="max-width:560px;margin:12px auto 0;color:#a0a5b8;font-size:11px;
  line-height:1.6;text-align:center;font-family:-apple-system,BlinkMacSystemFont,
  'PingFang SC','Microsoft YaHei',Arial,sans-serif;">
  这是一封系统通知，不需要回复。
</div>
</td></tr></table>
</body></html>'''


def _clean_targets(items: list[str | EmailTarget]) -> list[EmailTarget]:
    """发信前再过一遍：去重 + 丢掉格式不合法的

    收件人查询里已经过滤过一次，这里不是重复劳动：`push` 也会被「发送测试」
    直接调用（那里传入的是用户刚填的地址），而且以后有别的调用方时这层兜底还在。

    同一地址出现多次时合并 student_nos，并保留先拿到的 read_url：
    一个邮箱只发一封，链接里必须能带上共用该邮箱的所有人的消息令牌。
    """
    seen: dict[str, int] = {}
    cleaned: list[EmailTarget] = []
    for raw in items:
        target = raw if isinstance(raw, EmailTarget) else EmailTarget(str(raw or ""))
        addr = target.address.strip()
        if not is_valid_email(addr):
            if addr:
                # 打完整地址是有意的：不知道是哪个地址坏了，这条日志就没有价值。
                # 邮箱不是密钥，不进日志的只有密码
                print(f"[Email] 跳过格式不合法的收件地址：{addr}", flush=True)
            continue
        key = addr.lower()
        if key in seen:
            prev = cleaned[seen[key]]
            merged = tuple(dict.fromkeys(prev.student_nos + target.student_nos))
            cleaned[seen[key]] = EmailTarget(
                prev.address, merged, prev.read_url or target.read_url,
                prev.open_url or target.open_url,
            )
            continue
        seen[key] = len(cleaned)
        cleaned.append(
            EmailTarget(
                addr, tuple(target.student_nos), target.read_url, target.open_url
            )
        )
    if len(cleaned) > MAX_RECIPIENTS:
        print(
            f"[Email] 收件人多于 {MAX_RECIPIENTS} 个，只发前 {MAX_RECIPIENTS} 个"
            f"（共 {len(cleaned)} 个）",
            flush=True,
        )
    return cleaned[:MAX_RECIPIENTS]
