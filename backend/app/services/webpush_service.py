"""浏览器推送（Web Push）服务

和 Bark 是两条并行的渠道：Bark 需要用户自己装 App、填设备 key，
浏览器推送则是用户在本站点一下「开启通知」就行，不用装任何东西。
两者共用同一批事件，用户开哪个收哪个。

**本模块任何函数都不许把异常抛出去** —— 推送是锦上添花，绝不能因为推送服务
连不上就让请假提交、公告发布这些主流程跟着失败。
"""

import base64
import json
import os
import time

import requests
from pywebpush import WebPushException, webpush
from py_vapid import Vapid
from sqlalchemy.orm import Session

from ..config import resolve_vapid_key, settings
from ..models import PushSubscription, User
from .bark_service import BODY_LIMIT, TITLE_LIMIT

# 单条订阅的超时（连接秒数, 读取秒数）。**这个值必须显式传给 webpush()**：
# pywebpush 的 timeout 参数默认是 None（不是它源码里那个 10000 的兜底，
# 因为 webpush() 每回都会显式传参，兜底那份是死代码），
# 不传就等于 requests.post(timeout=None) —— 永久等待。
#
# 为什么是元组、为什么连接只给 2 秒：requests 的超时是**每个 IP 各算一次**的。
# 实测 fcm.googleapis.com 解析出 8 个地址，全都不通时要 8 × 连接超时 才抛错 ——
# 传 5 就是干等 40 秒（真机实测过）。卡在 2 秒，最坏 16 秒，落在前端超时之内。
# 正常推送服务连上只要 0.2~0.3 秒，2 秒足够。
TIMEOUT = (2, 5)
# 一次后台任务里所有订阅的总时间预算。Web Push **没有批量接口**，
# 一个订阅一个请求，全班都订阅就是几十个串行 HTTPS。没有预算会拖累共用线程池
BUDGET = 20
# 测试推送的预算。别超过前端 axios 的 15 秒超时，否则用户看到的是「网络错误」
TEST_BUDGET = 10
# 通知在推送服务那边保留多久（秒）。设备关机/断网时先存着，联网了再投。
# 不给的话 pywebpush 默认 ttl=0 = 此刻送不到就直接丢，
# 「有新的请假待审核」这类待办会在手机锁屏时静默消失
TTL = 12 * 3600

# 紧急程度：Bark 用 level 字段，浏览器这边对应 RFC 8030 的 Urgency 请求头。
# 注意 Urgency: high **不会**像 Bark 的 timeSensitive 那样穿透 iOS 专注模式，
# 这不是我们没配好，是平台差异，别在文案里对用户承诺
_URGENCY = {"timeSensitive": "high", "active": "normal"}


def vapid_public_key() -> str:
    """导出 VAPID 公钥给前端订阅用

    取的是未压缩点（65 字节），转成 base64url 并去掉结尾的 = ——
    这是 applicationServerKey 要求的格式，少一步 Safari 就不认。
    """
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = resolve_vapid_key()
    vapid = Vapid.from_file(key) if os.path.isfile(key) else Vapid.from_string(key)
    raw = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def subscribe(db: Session, student_no: str, endpoint: str, p256dh: str, auth: str) -> None:
    """登记一条订阅

    endpoint 是推送服务给这个浏览器的唯一地址，天然唯一，所以拿它当键做 upsert：
    同一台电脑换个人登录时，改的是这一行的 student_no，不会插出新行。
    共享电脑的串号问题就是靠这个语义解决的（见前端 App.vue 的登录监听）。
    """
    existing = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == endpoint)
        .first()
    )
    if existing:
        existing.student_no = student_no
        existing.p256dh = p256dh
        existing.auth = auth
    else:
        db.add(
            PushSubscription(
                student_no=student_no, endpoint=endpoint, p256dh=p256dh, auth=auth
            )
        )
    db.commit()


def unsubscribe(db: Session, student_no: str, endpoint: str) -> None:
    """解除一条订阅（只删自己的，动不了别人的设备）"""
    db.query(PushSubscription).filter(
        PushSubscription.student_no == student_no,
        PushSubscription.endpoint == endpoint,
    ).delete()
    db.commit()


def web_subscriptions(
    db: Session,
    roles: list[str] | None = None,
    only_no: str | None = None,
    exclude_no: str | None = None,
) -> list[dict]:
    """查收件人的订阅，语义与 bark_service.bark_keys 完全一致

    必须在请求处理过程中调用：返回的是纯 dict（不含 ORM 对象），
    交给后台任务就能直接发，后台任务因此不需要数据库会话。

    **必须 JOIN users**：push_subscriptions 表里只有学号，没有角色。
    不 JOIN 的话 roles 过滤会静默失效 —— 上传「仅班委可见」的公告时会推给全班，
    而且不报任何错。这是这条链路上最不该出错的地方。
    """
    query = db.query(
        PushSubscription.endpoint, PushSubscription.p256dh, PushSubscription.auth
    ).join(User, User.student_no == PushSubscription.student_no)

    # 空列表表示不限角色，和 bark_keys 保持一致（写成 IN () 会谁都不匹配）
    if roles:
        query = query.filter(User.role.in_(roles))
    if only_no:
        query = query.filter(User.student_no == only_no)
    if exclude_no:
        query = query.filter(User.student_no != exclude_no)

    # 这个形状既是 pywebpush 要的 subscription_info，
    # 也正好是浏览器 sub.toJSON() 的样子 —— 一份数据两处用
    return [
        {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}
        for endpoint, p256dh, auth in query.all()
    ]


def push(
    subscriptions: list[dict], title: str, body: str,
    level: str = "active", page: str | None = None, budget: int = BUDGET,
) -> bool:
    """真正把通知发出去；失败只打印一行日志，绝不抛出

    调用方是 Starlette 的后台任务，异常抛出去没人接，只会污染日志。
    """
    if not subscriptions:
        return True

    urgency = _URGENCY.get(level, "normal")
    payload = json.dumps(
        {
            "title": title[:TITLE_LIMIT],
            "body": body[:BODY_LIMIT],
            # Service Worker 就住在站点根目录下，用根相对地址即可。
            # 这里**不需要** PUBLIC_BASE_URL —— 那是 Bark 特有的需求（图标由手机去拉）
            "url": f"/#{page}" if page else "/",
            # 同一个 tag 的新通知会顶掉通知栏里的旧的。按页面归类：
            # 公告互相顶掉正合适（不会堆一片），不同页面的事各留各的
            "tag": page or "oa-notify",
        },
        ensure_ascii=False,
    )

    private_key = resolve_vapid_key()
    deadline = time.monotonic() + budget
    dead: list[str] = []  # 推送服务明确说已经失效的订阅
    ok = True

    # 单次任务内复用连接：全班几十条时要省掉重复的 TLS 握手。
    # 只在这一次任务里复用 —— requests.Session 不是线程安全的，不能放到模块级
    with requests.Session() as session:
        for info in subscriptions:
            if time.monotonic() > deadline:
                print("[WebPush] 总时间超预算，放弃剩余订阅", flush=True)
                ok = False
                break
            try:
                webpush(
                    subscription_info=info,
                    data=payload,
                    # vapid_claims 必须**每次新建**：pywebpush 会把 aud 就地写进传进来的
                    # 这个 dict（源码里那句 "passed structures are mutable in python"）。
                    # 复用同一个 dict 的话，第一个订阅的域名会被后面所有订阅带着走，
                    # 推送服务校验 JWT 后一律回 401 —— 表现为"有些人永远收不到推送"
                    vapid_claims={"sub": settings.vapid_subject},
                    vapid_private_key=private_key,
                    ttl=TTL,
                    headers={"Urgency": urgency},
                    timeout=TIMEOUT,
                    requests_session=session,
                )
            except WebPushException as exc:
                # 404/410 = 这个订阅已经不存在了（用户清了浏览器数据、卸载了 PWA）
                if exc.status_code in (404, 410):
                    dead.append(info["endpoint"])
                else:
                    print(f"[WebPush] 推送被拒绝：{exc.status_code} {str(exc)[:200]}", flush=True)
                ok = False
            except Exception as exc:
                # 网络不通、DNS 解析不了、VAPID 签名出错都会走到这里，一律只记一行
                print(f"[WebPush] 推送失败：{exc!r}", flush=True)
                ok = False

    if dead:
        _drop_dead(dead)
    return ok


def _drop_dead(endpoints: list[str]) -> None:
    """清理已失效的订阅

    不清的话，这些行会永久累积，之后每发一次通知都白跑一个请求。

    这里**新开**一个数据库会话：规矩是"不把请求的会话带进后台任务"
    （响应发出后 get_db 的 finally 可能已经把它关了），新开的没这个问题。
    整段兜死，清理失败不影响推送本身。
    """
    try:
        from ..database import SessionLocal

        with SessionLocal() as db:
            count = (
                db.query(PushSubscription)
                .filter(PushSubscription.endpoint.in_(endpoints))
                .delete(synchronize_session=False)
            )
            db.commit()
        print(f"[WebPush] 已清理 {count} 条失效订阅", flush=True)
    except Exception as exc:
        print(f"[WebPush] 清理失效订阅失败：{exc!r}", flush=True)
