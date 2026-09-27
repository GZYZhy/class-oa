"""Bark 推送服务

把「跟你有关系的事」推到手机上：自己的办件状态变了、有新通知公告、
有新的办件等自己审核。用户在自己账号里填一个 Bark 设备 key 就能收到。

这里只管 Bark 这一个渠道：`bark_keys` 查收件人、`push` 真正发送。
「这件事该走哪几个渠道」的路由在 notify_service，业务代码只跟那一层打交道。

**本模块任何函数都不许把异常抛出去** —— 推送是锦上添花，绝不能因为 Bark
挂了就让请假提交、公告发布这些主流程跟着失败。
"""

import json
import time
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from ..config import settings
from ..models import User

# Bark 单次请求最多推 100 个设备，超了要分批（全班几十人够用，防的是以后人多）
MAX_DEVICE_KEYS = 100
# 单次请求超时秒数。推送不值得让线程干等。
# 注意别调到 15 秒以上：前端 axios 的超时是 15 秒，测试推送会先被前端掐断，
# 用户看到的就成了「网络错误」而不是真实原因
TIMEOUT = 5
# 批量失败后逐条重发的总时间预算，防止一堆坏 key 把线程占死
FALLBACK_BUDGET = 20
# 通知正文长度上限：手机通知栏就那么点地方，太长会被系统截断，不如我们自己截
BODY_LIMIT = 120
TITLE_LIMIT = 40


def bark_keys(
    db: Session,
    roles: list[str] | None = None,
    only_no: str | None = None,
    exclude_no: str | None = None,
) -> list[str]:
    """查收件人的设备 key

    必须在请求处理过程中调用：返回值是纯字符串列表，交给后台任务就能直接发，
    后台任务因此完全不需要数据库会话（响应发出后会话可能已经关了）。

    roles 为空表示不限角色；only_no 只推给某一个人（如办件的申请人）；
    exclude_no 用来把操作人自己排除掉（自己发起的事不用推给自己）。
    """
    query = db.query(User.bark_key).filter(User.bark_key.isnot(None), User.bark_key != "")
    if roles:
        query = query.filter(User.role.in_(roles))
    if only_no:
        query = query.filter(User.student_no == only_no)
    if exclude_no:
        query = query.filter(User.student_no != exclude_no)
    return [key for (key,) in query.all()]


def clip(text: str, limit: int = 60) -> str:
    """把用户输入的文字截短，超出部分用省略号收尾

    通知栏就那么宽。与其让 _send 从尾巴硬切（屏幕上出现半句话，还看不出被截过），
    不如调用方先截好、明确告诉用户后面还有。
    """
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def icon_url() -> str | None:
    """推送通知里的校徽地址；没配 public_base_url 时返回 None（推送就不带图标）

    只此一处定义，设置界面的预览和真正发出去的推送必须完全一致。
    ?v=1 是历史遗留：nginx 原本给 .png 打 1 年 immutable，靠它破缓存。现在 nginx 已对
    /logo.png 改成 no-cache，换校徽不用再动这个版本号；留着只是为了兼容老客户端
    已经按这个 URL 建好的缓存键。
    """
    base = settings.public_base_url.rstrip("/")
    return f"{base}/logo.png?v=1" if base else None


def push(
    keys: list[str], title: str, body: str,
    level: str = "active", page: str | None = None,
) -> bool:
    """真正把通知发出去；失败只打印一行日志，绝不抛出

    调用方是 Starlette 的后台任务，异常抛出去没人接，只会污染日志。
    推送失败对用户而言只是没收到通知，业务数据是对的，所以不用惊动任何人。

    返回值只给「测试推送」用 —— 那个场景用户正等着看结果，需要如实告诉他成没成。
    """
    try:
        ok = True
        for i in range(0, len(keys), MAX_DEVICE_KEYS):
            batch = keys[i : i + MAX_DEVICE_KEYS]
            if _send(batch, title, body, level, page):
                continue
            # 批量失败时逐条重发。只要有一个人的 key 失效（比如他重装了 Bark），
            # 整批就可能全被拒 —— 那等于全班静默失联，所以宁可慢一点也要把好的挑出来
            ok = _resend_each(batch, title, body, level, page) and ok
        return ok
    except Exception as exc:
        # 最外层兜底。Starlette 的后台任务**不会**吞异常：漏出去就是 uvicorn 打一整段
        # traceback，而且是在响应已经发完之后 —— 对用户毫无意义，只是污染日志。
        # _send 内部已经各自兜过一次，这里防的是循环和分批本身出意外。
        print(f"[Bark] 推送异常：{exc!r}", flush=True)
        return False


def _resend_each(keys: list[str], title: str, body: str, level: str, page: str | None) -> bool:
    """逐条重发（批量失败后的兜底），带总时间预算

    没有预算的话，一堆坏 key 会把线程占死几十秒，拖累共用线程池的其他同步接口。
    """
    deadline = time.monotonic() + FALLBACK_BUDGET
    ok = True
    for key in keys:
        if time.monotonic() > deadline:
            print("[Bark] 逐条重发超时，放弃剩余设备", flush=True)
            return False
        ok = _send([key], title, body, level, page) and ok
    return ok


def _send(keys: list[str], title: str, body: str, level: str, page: str | None) -> bool:
    """发一批（不超过 MAX_DEVICE_KEYS 个）设备，返回是否成功"""
    payload = {
        "device_keys": keys,
        "title": title[:TITLE_LIMIT],
        "body": body[:BODY_LIMIT],
        # passive 只在通知中心 / active 正常提醒 / timeSensitive 穿透专注模式。
        # critical 需要苹果单独审批的权限，申请不到会静默失败，所以不用
        "level": level,
        "group": settings.app_name,  # 同一类通知在手机上归到一组，不会刷屏
    }

    base = settings.public_base_url.rstrip("/")
    icon = icon_url()
    if base and icon:
        payload["icon"] = icon
        # 点通知跳到站内对应页面。路由是 hash 模式，所以是 /#/xxx
        payload["url"] = f"{base}/#{page}" if page else base

    try:
        # Request 构造时会解析 URL：配置里少写 https:// 会抛 ValueError。
        # 所以必须放在 try 里面，否则异常会穿到后台任务之外变成一堆 traceback
        request = urllib.request.Request(
            f"{settings.bark_server.rstrip('/')}/push",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            text = response.read().decode("utf-8", errors="replace")
        # 光看 HTTP 状态不够：设备 key 不对时 Bark 会回 200 但把 code 放在正文里
        if json.loads(text).get("code") == 200:
            return True
        print(f"[Bark] 推送被拒绝：{text[:200]}", flush=True)
        return False
    except urllib.error.HTTPError as exc:
        # 失败原因在响应正文里（如 failed to get device token），
        # 只打 str(exc) 会丢掉它，线上就只剩「HTTP Error 400」这种没法查的日志
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        print(f"[Bark] 推送被拒绝：HTTP {exc.code} {detail}", flush=True)
        return False
    except Exception as exc:
        # 网络不通、域名解析不了、超时、配置写错都会走到这里，一律只记一行
        print(f"[Bark] 推送失败：{exc!r}", flush=True)
        return False
