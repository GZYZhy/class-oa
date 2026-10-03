"""通知分发服务

把「这件事跟谁有关」翻译成「往哪些地方发」，再路由给五个渠道：
Bark（要用户自己装 App、填设备 key）、浏览器推送（用户在本站点一下就行）、
自定义 webhook（用户填地址，我们 POST 过去）、电子邮件（默认用学生档案里的邮箱）、
以及**站内信**（写进本库，登录就能看到）。

渠道自己的实现分别在 bark_service / webpush_service / webhook_service /
email_service 里，这里只管路由，业务代码只跟这一层打交道。
**加渠道只改这个文件，业务调用点一行都不用动。**

站内信和另外四个不是一类东西，所以走单独一条路径（见 notify 里的说明）：
那四个都是「往外发」，发不发得出去取决于用户自己配没配；站内信是「往库里写」，
有账号就有一份。**它是唯一一个不需要用户做任何事就必达的渠道** ——
也正因如此，它把「发了通知但谁都没收到」这个原本完全不可见的情况兜住了。
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..config import smtp_enabled
from .bark_service import bark_keys
from .bark_service import push as bark_push
from .email_service import email_recipients
from .email_service import push as email_push
from .inbox_service import recipient_nos, save_messages
from .webhook_service import push as webhook_push
from .webhook_service import webhook_targets
from .webpush_service import push as web_push
from .webpush_service import web_subscriptions


# (Recipients 上的属性名, 该渠道的发送函数)。notify() 和 deliver_now() 共用这一份，
# 以后加渠道只改这一行，两边不会漏掉同一边
#
# **站内信刻意不在这里**：这张表的每一项都是「交给后台任务去发」+「签名是
# (targets, title, body, level, page)」，而站内信是写本库、要 db、还必须同步做完。
# 硬塞进来两个函数都得为它开特例，不如让它走一条自己的路（见 notify）。
_CHANNELS = (
    ("bark", bark_push),
    ("web", web_push),
    ("webhook", webhook_push),
    ("email", email_push),
)


@dataclass
class Recipients:
    """一次通知的收件人，每个渠道各一份

    存的是纯数据（字符串 / dict），不含 ORM 对象 —— 后台任务拿到就能直接发，
    不需要再碰数据库会话。
    """

    bark: list[str] = field(default_factory=list)
    web: list[dict] = field(default_factory=list)
    webhook: list[dict] = field(default_factory=list)
    email: list[str] = field(default_factory=list)
    # 站内信收件人（学号列表）。和上面四个的区别：**这里不看任何开关**，有账号就有。
    # 它也是唯一不交给后台任务的渠道（见 notify），但把学号放这里，
    # 「这次通知实际会落到谁手里」就有了一处准确的答案。
    inbox: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """所有渠道都没人才算空

        dataclass 默认恒为真，不写这个方法的话 notify() 里的空判断永远不成立，
        没人订阅的事件也会白挂一个后台任务（现在的写法是故意要短路的）。

        遍历 _CHANNELS 而不是手写 or 长链：以后加渠道只改那一处，这里自动跟上，
        不会再出现「忘了往这里补一个 or」那种不报错、不留痕迹的静默失效。
        inbox 单独 or 一次，因为它不在 _CHANNELS 里（见那个常量的说明）。
        """
        return any(getattr(self, attr) for attr, _ in _CHANNELS) or bool(self.inbox)


def recipients(
    db: Session,
    roles: list[str] | None = None,
    only_no: str | None = None,
    exclude_no: str | None = None,
) -> Recipients:
    """查这次通知该发给谁

    必须在请求处理过程中调用：响应发出去之后 get_db 会把会话关掉。
    roles 为空表示不限角色；only_no 只推给某一个人（如办件的申请人）；
    exclude_no 用来把操作人自己排除掉。

    **只有「我自己刚做完的事」才该传 exclude_no** —— 发布通知、发起投票、
    录入成绩，以及「某人的成绩录好了」这种逐人推送：推给自己是纯噪音。

    **待办 / 审批类的一律不传**：提交人自己就在审批人名单里，说明这件确实等着他处理。
    把他排掉，班里只有一个管理员（或只有一个班委）时**就没人收得到待办提醒了** ——
    待办提醒的全部价值就在这一条上。四个办件提交接口（请假 / 证明 / 通行证 /
    信息修改）都按这条口径不传，api/exports.py 的导出申请本来就是这么写的。

    前四个渠道都是「用户配置过才发得出去」，返回空列表是常态；inbox 不看任何开关，
    它返回的才是这次通知**实际会落到谁手里**的名单（角色筛选口径与那几个完全一致）。
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
        inbox=recipient_nos(db, roles=roles, only_no=only_no, exclude_no=exclude_no),
    )


def notify(
    db: Session, background, targets: Recipients, title: str, body: str,
    level: str = "active", page: str | None = None,
) -> None:
    """把这次通知存档（站内信）并挂推送任务（在请求里用这个）

    推送之所以走后台：发推送要走外网，放在请求里会让接口白白慢几百毫秒。
    **每个渠道各挂各的任务，不能合并成一个循环去跑**：一个渠道挂了
    （对方服务器不回话、DNS 解析卡住）不拖累另一个，也不影响已经返回给用户的响应。
    targets 为空直接跳过，不给没人订阅的事件白跑一趟网络。

    **站内信不走后台，就在这里同步写**（所以第一个参数是 db）：
    后台任务在响应发出去之后才跑，那时 get_db 已经把会话关了；而它只是写本库、
    不碰网络，没有「拖慢接口」的顾虑。先存档再挂推送 —— 存档是必达的，
    推送是「有则更好」，万一下面某个渠道把线程卡很久，库里那份已经在了。

    后台线程里没有 background，请用下面的 deliver_now()。
    """
    if not targets:
        return
    _save_inbox(db, targets, title, body, level, page)
    for attr, send in _CHANNELS:
        target = getattr(targets, attr)
        if target:
            background.add_task(send, target, title, body, level, page)


def _save_inbox(
    db: Session, targets: Recipients, title: str, body: str,
    level: str, page: str | None,
) -> None:
    """写站内信存档。**异常必须在这里吞掉**

    它只是「顺手存一份」，不能因为写库失败（SQLite 写锁被长请求占着之类）
    把请假提交、公告发布这些主流程带崩。丢了存档比丢了这个请求好得多，
    所以打印一行日志就够，不往外抛。
    """
    try:
        save_messages(db, targets.inbox, title, body, level=level, page=page)
    except Exception as exc:
        print(f"[站内信] 保存失败：{exc!r}", flush=True)


def deliver_now(
    db: Session, targets: Recipients, title: str, body: str,
    level: str = "active", page: str | None = None,
) -> bool:
    """同步把各渠道发完；返回「有人的渠道是不是都发成功了」

    **只给后台线程用，请求里请用 notify()**：定时任务线程里没有 Starlette 的
    BackgroundTasks（也不该为了发个通知去伪造一个 —— 伪造出来的任务只会挂在内存里
    永远不跑，是静默失效），而且线程本来就该等它跑完。所以这里按顺序直接调各渠道的 push。

    要传 db 的理由和 notify 一样：站内信得同步写。调度线程自己开的那张会话
    （见 scheduler.tick）传进来就行，**不要在这里自开一个** —— 两个连接同时写
    SQLite 会撞「database is locked」。

    各渠道 push 内部都已经吞掉自己的异常（见各 *_service 的模块注释），这里再兜一层：
    一个渠道的代码万一炸了不能拖累后面几个，**更不能把调度线程带崩** ——
    线程一死，此后所有日期的通知都会静默消失。

    targets 为空返回 True（没有任何失败）；调用方若要区分「没人可发」，
    自己先判 `if not targets`。
    """
    if not targets:
        return True
    _save_inbox(db, targets, title, body, level, page)
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
