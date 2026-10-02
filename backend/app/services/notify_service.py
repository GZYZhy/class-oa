"""通知分发服务

把「这件事跟谁有关」翻译成「往哪些地方发」，再路由给四个渠道：
Bark（要用户自己装 App、填设备 key）、浏览器推送（用户在本站点一下就行）、
自定义 webhook（用户填地址，我们 POST 过去）、电子邮件（默认用学生档案里的邮箱）。

渠道自己的实现分别在 bark_service / webpush_service / webhook_service /
email_service 里，这里只管路由，业务代码只跟这一层打交道。
**加渠道只改这个文件，18 个业务调用点一行都不用动。**
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..config import smtp_enabled
from .bark_service import bark_keys
from .bark_service import push as bark_push
from .email_service import email_recipients
from .email_service import push as email_push
from .webhook_service import push as webhook_push
from .webhook_service import webhook_targets
from .webpush_service import push as web_push
from .webpush_service import web_subscriptions


# (Recipients 上的属性名, 该渠道的发送函数)。notify() 和 deliver_now() 共用这一份，
# 以后加渠道只改这一行，两边不会漏掉同一边
_CHANNELS = (
    ("bark", bark_push),
    ("web", web_push),
    ("webhook", webhook_push),
    ("email", email_push),
)


@dataclass
class Recipients:
    """一次通知的收件人，四个渠道各一份

    存的是纯数据（字符串 / dict），不含 ORM 对象 —— 后台任务拿到就能直接发，
    不需要再碰数据库会话。
    """

    bark: list[str] = field(default_factory=list)
    web: list[dict] = field(default_factory=list)
    webhook: list[dict] = field(default_factory=list)
    email: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """四个渠道都没人才算空

        dataclass 默认恒为真，不写这个方法的话 notify() 里的空判断永远不成立，
        没人订阅的事件也会白挂一个后台任务（现在的写法是故意要短路的）。

        遍历 _CHANNELS 而不是手写 or 长链：以后加渠道只改那一处，这里自动跟上，
        不会再出现「忘了往这里补一个 or」那种不报错、不留痕迹的静默失效。
        """
        return any(getattr(self, attr) for attr, _ in _CHANNELS)


def recipients(
    db: Session,
    roles: list[str] | None = None,
    only_no: str | None = None,
    exclude_no: str | None = None,
) -> Recipients:
    """查这次通知该发给谁

    必须在请求处理过程中调用：响应发出去之后 get_db 会把会话关掉。
    roles 为空表示不限角色；only_no 只推给某一个人（如办件的申请人）；
    exclude_no 用来把操作人自己排除掉（自己发起的事不用推给自己）。
    """
    return Recipients(
        bark=bark_keys(db, roles=roles, only_no=only_no, exclude_no=exclude_no),
        web=web_subscriptions(db, roles=roles, only_no=only_no, exclude_no=exclude_no),
        webhook=webhook_targets(db, roles=roles, only_no=only_no, exclude_no=exclude_no),
        # 邮件那路多一道全局闸门：SMTP 没配齐时**连查都不查**。
        # 不光是省一次查询 —— 查出来的地址交给后台任务也发不出去，
        # 白白让人以为「有人会收到」
        email=(
            email_recipients(db, roles=roles, only_no=only_no, exclude_no=exclude_no)
            if smtp_enabled()
            else []
        ),
    )


def notify(
    background, targets: Recipients, title: str, body: str,
    level: str = "active", page: str | None = None,
) -> None:
    """把推送挂到后台任务上（在请求里用这个）

    之所以走后台：发推送要走外网，放在请求里会让接口白白慢几百毫秒。
    **每个渠道各挂各的任务，不能合并成一个循环去跑**：一个渠道挂了
    （对方服务器不回话、DNS 解析卡住）不拖累另一个，也不影响已经返回给用户的响应。
    targets 为空直接跳过，不给没人订阅的事件白跑一趟网络。

    后台线程里没有 background，请用下面的 deliver_now()。
    """
    if not targets:
        return
    for attr, send in _CHANNELS:
        target = getattr(targets, attr)
        if target:
            background.add_task(send, target, title, body, level, page)


def deliver_now(
    targets: Recipients, title: str, body: str,
    level: str = "active", page: str | None = None,
) -> bool:
    """同步把各渠道发完；返回「有人的渠道是不是都发成功了」

    **只给后台线程用，请求里请用 notify()**：定时任务线程里没有 Starlette 的
    BackgroundTasks（也不该为了发个通知去伪造一个 —— 伪造出来的任务只会挂在内存里
    永远不跑，是静默失效），而且线程本来就该等它跑完。所以这里按顺序直接调各渠道的 push。

    各渠道 push 内部都已经吞掉自己的异常（见各 *_service 的模块注释），这里再兜一层：
    一个渠道的代码万一炸了不能拖累后面几个，**更不能把调度线程带崩** ——
    线程一死，此后所有日期的通知都会静默消失。

    targets 为空返回 True（没有任何失败）；调用方若要区分「没人可发」，
    自己先判 `if not targets`。
    """
    if not targets:
        return True
    ok = True
    for attr, send in _CHANNELS:
        target = getattr(targets, attr)
        if not target:
            continue
        try:
            ok = bool(send(target, title, body, level, page)) and ok
        except Exception as exc:
            print(f"[通知] 后台渠道 {attr} 发送异常：{exc!r}", flush=True)
            ok = False
    return ok
