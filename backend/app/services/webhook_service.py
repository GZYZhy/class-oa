"""自定义 Webhook 通知渠道

用户填一个地址，我们把通知 POST 过去 —— 接企业微信/钉钉/飞书的群机器人、
自建的接收端都行。相比 Bark（要装 App）和浏览器推送（要订阅），它的好处是
不挑接收方；坏处是**这是全项目唯一一处让普通账号指挥服务器发起请求的地方**，
所以地址判定格外严（见 utils/url_guard）。

这里只管 webhook 这一个渠道：`webhook_targets` 查收件配置、`push` 真正发送。
「这件事该走哪几个渠道」的路由在 notify_service。

**本模块任何函数都不许把异常抛出去** —— 同 bark_service，对方服务器不回话
绝不能连累请假提交、公告发布这些主流程。

「防错配阻塞系统」靠三件事：单条请求 5 秒超时（DNS 解析不受它保护，所以还要
总预算兜底）、整轮 20 秒总预算、以及下面那个**不跟随重定向**的 opener。
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from sqlalchemy.orm import Session

from ..config import settings
from ..models import User
from ..utils.notify_text import BODY_LIMIT, TITLE_LIMIT, clip
from ..utils.url_guard import is_allowed_webhook_url

# 单条请求超时秒数。和 Bark 保持一致，别调到 15 秒以上：前端 axios 超时就是
# 15 秒，「发送测试」会先被前端掐断，用户看到的是「网络错误」而不是真实原因
TIMEOUT = 5
# 整轮的总时间预算。TIMEOUT 管不住 DNS 解析（那一步是 libc 在做，不看 socket
# 超时），一堆解析不出来的域名照样能把线程占很久
BUDGET = 20
# 单次通知最多发给几个 webhook 地址。用户表一共几十行，防的是以后人多或调用方出错
MAX_TARGETS = 100
# 模板长度上限。给足空间写嵌套结构，同时挡住「把整个文件塞进这个字段」
MAX_TEMPLATE_LEN = 4000

# 模板里认的占位符。只认这 4 个，**值全部由服务端生成，绝不接受用户模板传变量值**
_PLACEHOLDER = re.compile(r"\{\{(title|content|page|time)\}\}")

# 没填模板时用的默认结构。挑这四个键是因为企微/钉钉/飞书/Slack 的群机器人
# 都能靠改键名对上（飞书 msg_type+content.text、钉钉 msgtype+text.content、
# Slack/Discord text），用户照着改比从零写容易
DEFAULT_TEMPLATE = {
    "title": "{{title}}",
    "content": "{{content}}",
    "page": "{{page}}",
    "time": "{{time}}",
}
# 给前端当 placeholder / 说明用，和上面必须同一份，别在两处各写一遍
DEFAULT_TEMPLATE_TEXT = json.dumps(DEFAULT_TEMPLATE, ensure_ascii=False, indent=2)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """拒绝跟随任何重定向（3xx 直接当失败）

    这是**必须**的，不是洁癖。默认的 HTTPRedirectHandler 会真的跟过去 ——
    实测起一个回 302、Location 指向 169.254.169.254 的地址，urlopen 确实跟了
    过去并挂到超时。也就是说「只校验用户填的那个地址」根本挡不住 SSRF：
    攻击者让公网那台机器回一个 Location: http://169.254.169.254/... 就绕过了
    全部校验，而那个地址本身是合法的公网地址。

    redirect_request 返回 None，urllib 就会抛 HTTPError(3xx)，落进我们自己的
    错误分支，用户能看到「对方要跳转，出于安全没跟」这句人话。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# 模块级私有 opener：**绝不能调 install_opener()**，那是全局的，
# 会把 bark_service 里的 urlopen 一起改掉（那边依赖默认行为）。
#
# ProxyHandler({}) 那个空 dict 是故意的：只要环境里有 http_proxy/https_proxy，
# 默认 handler 就会走代理，而**代理负责解析域名** —— 我们在 url_guard 里
# 校验的那个 IP 和实际连过去的完全不是一回事，DNS 校验形同虚设。
# 代价：部署如果必须靠代理才能出网，webhook 渠道会不通（Bark 也同理不受影响，
# 因为它走的是各自独立的 opener）。
_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def webhook_targets(
    db: Session,
    roles: list[str] | None = None,
    only_no: str | None = None,
    exclude_no: str | None = None,
) -> list[dict]:
    """查收件配置

    必须在请求处理过程中调用：返回的是纯数据（字符串 + 已解析的 dict），
    交给后台任务就能直接发，后台任务因此不需要数据库会话。

    模板在这里就解析成 dict 存进返回值，不留到发送时再解析 —— 那一层是后台任务，
    JSON 出错只能打日志，而保存接口（PUT）那边已经用 check_template() 拦过一次了。

    roles 为空表示不限角色；only_no 只发给某一个人（如办件的申请人）；
    exclude_no 用来把操作人自己排除掉。

    两个条件都要满足才发：**开关开着，且填了地址**。
    单独看开关会漏掉「开着但没地址」的空发；单独看地址会让用户没法在不丢掉
    地址和模板的情况下先停一阵子 —— 那正是加这个开关的原因。
    """
    query = db.query(User.webhook_url, User.webhook_template).filter(
        User.webhook_enabled.is_(True),
        User.webhook_url.isnot(None), User.webhook_url != "",
    )
    if roles:
        query = query.filter(User.role.in_(roles))
    if only_no:
        query = query.filter(User.student_no == only_no)
    if exclude_no:
        query = query.filter(User.student_no != exclude_no)

    targets = [
        {"url": url.strip(), "template": parse_template(template)}
        for url, template in query.all()
    ]
    if len(targets) > MAX_TARGETS:
        print(
            f"[Webhook] 收件人多于 {MAX_TARGETS} 个，只发前 {MAX_TARGETS} 个"
            f"（共 {len(targets)} 个）",
            flush=True,
        )
    return targets[:MAX_TARGETS]


def push(
    targets: list[dict], title: str, body: str,
    level: str = "active", page: str | None = None,
) -> bool:
    """把通知 POST 给每个地址；失败只打印一行日志，绝不抛出

    调用方是 Starlette 的后台任务，异常抛出去没人接，只会污染日志。
    返回值只给「发送测试」用 —— 那个场景用户正等着看结果。

    level 参数收下但不用：webhook 渠道的口径是「所有通知都发」，不分等级。
    保留是为了和 bark_push / web_push 签名一致，将来要按等级过滤时不用改调用方。
    """
    try:
        ok = True
        deadline = time.monotonic() + BUDGET
        for index, target in enumerate(targets):
            if time.monotonic() > deadline:
                # 不静默截断：剩几个没发到要留在日志里，否则「有人没收到」无从查起
                print(
                    f"[Webhook] 超出 {BUDGET} 秒预算，剩余 {len(targets) - index} 个地址未发送",
                    flush=True,
                )
                return False
            ok = _send(target, title, body, page) and ok
        return ok
    except Exception as exc:
        # 最外层兜底：后台任务的异常没人接，会变成响应发完之后的一整段 traceback
        print(f"[Webhook] 发送异常：{exc!r}", flush=True)
        return False


def _send(target: dict, title: str, body: str, page: str | None) -> bool:
    """发给一个地址，返回是否成功

    **发送前再判一次地址**（不是只在保存时判）：域名今天解析到公网、明天可能
    解析到内网（对方自己改的，或者被劫持）。只在保存时校验等于把信任永久固化。
    """
    url = target["url"]
    host = _host_of(url)

    allowed, reason = is_allowed_webhook_url(url)
    if not allowed:
        print(f"[Webhook] 跳过 {host}：{reason}", flush=True)
        return False

    payload = _render(target["template"], _context(title, body, page))
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with _OPENER.open(request, timeout=TIMEOUT) as response:
            code = response.status
            # 成功就到此为止，**不读响应体** —— 对方可能回一个几百兆的东西，
            # 而我们对它的内容没有任何用处
        if 200 <= code < 300:
            return True
        print(f"[Webhook] {host} 返回 HTTP {code}", flush=True)
        return False
    except urllib.error.HTTPError as exc:
        # 3xx 走这里（redirect_request 返回 None 时 urllib 抛 HTTPError）。
        # 必须和 4xx/5xx 分开说：用户看到「404」会去改地址，而真实原因是
        # 「对方要求跳转、我们出于安全没跟」，改地址是白费功夫
        if 300 <= exc.code < 400:
            print(
                f"[Webhook] {host} 要求跳转到别处（HTTP {exc.code}），"
                f"出于安全没有跟随。请直接填跳转后的最终地址",
                flush=True,
            )
        else:
            # 失败原因一般在响应正文里。只打状态码，线上就只剩「HTTP 400」这种没法查的日志
            detail = exc.read(200).decode("utf-8", errors="replace")
            print(f"[Webhook] {host} 返回 HTTP {exc.code}：{detail}", flush=True)
        return False
    except Exception as exc:
        # 连不上、解析不了、超时、对方回了非法响应都会走到这里，一律只记一行
        print(f"[Webhook] 发送到 {host} 失败：{exc!r}", flush=True)
        return False


def _host_of(url: str) -> str:
    """只取主机名用于日志

    **永远不打完整 URL**：webhook 地址里通常内嵌着密钥
    （飞书/钉钉/Server 酱的地址就是 /open-apis/bot/v2/hook/<一串 uuid>），
    打全等于把全班每一条密钥写进日志，而日志的可见范围比数据库宽得多。
    """
    try:
        return urllib.parse.urlsplit(url).hostname or "?"
    except ValueError:
        return "?"


def _context(title: str, body: str, page: str | None) -> dict[str, str]:
    """模板占位符的取值。**全部由服务端生成，用户模板只能引用、不能定义**"""
    base = settings.public_base_url.rstrip("/")
    return {
        "title": clip(title, TITLE_LIMIT),
        "content": clip(body, BODY_LIMIT),
        # 没配 public_base_url 时给空串而不是相对路径：相对路径在别人的服务器上
        # 毫无意义，给空串至少能让「用 if 判空」的模板自己处理
        "page": f"{base}/#{page}" if base and page else base,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _render(node, ctx: dict[str, str]):
    """递归替换模板里的占位符

    为什么是「解析成 JSON 之后在结构上替换」，而不是对原文做 str.replace：

    1. **str.replace 会二次替换**。先替换 {{title}}，如果这次进来的标题里恰好
       含 {{page}}（学生请假事由里完全可能写这个），下一轮替换会把它再展开一次 ——
       值被当成了模板。
    2. **它能注入 JSON 结构**。对原文替换时，标题里塞一段
       `"}}, "msgtype":"markdown", "content":{"text":"`  就能改变整个 payload 的
       结构 —— 甲填的请假事由会改写乙收到的 webhook 内容。

    re.sub 只扫一遍输入、不重扫替换进去的文本，且替换只发生在**字符串值**里，
    键名/数字/布尔一律不动，所以产出必然是合法 JSON，值也越不出字符串的边界。
    """
    if isinstance(node, str):
        return _PLACEHOLDER.sub(lambda m: ctx[m.group(1)], node)
    if isinstance(node, dict):
        return {key: _render(value, ctx) for key, value in node.items()}
    if isinstance(node, list):
        return [_render(value, ctx) for value in node]
    return node


def parse_template(text: str) -> dict:
    """把库里存的模板串解析成对象；空值或坏值一律回落到默认模板

    正常不该走到回落分支：保存接口用 check_template() 挡过一次。这里是给
    「手动改库」「以后接口改坏了」留的兜底 —— 宁可发默认结构，也不要因为
    一个字段把整条渠道弄失效。
    """
    raw = (text or "").strip()
    if not raw:
        return dict(DEFAULT_TEMPLATE)
    try:
        parsed = json.loads(raw)
    except ValueError:
        return dict(DEFAULT_TEMPLATE)
    return parsed if isinstance(parsed, dict) else dict(DEFAULT_TEMPLATE)


def check_template(text: str) -> str | None:
    """校验用户填的模板；返回错误原因，None 表示合法。空串合法（= 用默认模板）

    保存时就渲染一遍样例数据，是为了把「配错」暴露在**保存那一刻**：
    模板是自由文本，写错一个引号的话，等到某天真有通知时才在后台任务里报错，
    用户完全看不到反馈，只会觉得「我的 webhook 装了但从来没响过」。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if len(raw) > MAX_TEMPLATE_LEN:
        return f"模板太长了，请控制在 {MAX_TEMPLATE_LEN} 个字符以内"
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        return f"模板不是合法的 JSON：{exc}"
    if not isinstance(parsed, dict):
        # 必须是对象：数组/裸字符串做 payload 的平台几乎没有，
        # 而且顶层是对象才能让用户自己加 msgtype 这类平级字段
        return "模板必须是一个 JSON 对象（用一对花括号包起来）"
    try:
        json.dumps(_render(parsed, _context("测试标题", "测试内容", "/")), ensure_ascii=False)
    except Exception as exc:
        return f"模板渲染失败：{exc!r}"
    return None
