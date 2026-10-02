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

        **加了新渠道一定要记得往这里补一个 or** —— 忘了的话表现是「功能是好的，
        但每次通知都白挂一个空任务跑一趟」，不报错、不留痕迹，很难发现。
        """
        return bool(self.bark or self.web or self.webhook or self.email)


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
    """把推送挂到后台任务上

    之所以走后台：发推送要走外网，放在请求里会让接口白白慢几百毫秒。
    每个渠道各挂各的任务，一个渠道挂了（对方服务器不回话、DNS 解析卡住）
    不拖累另一个，也不影响已经返回给用户的响应。
    targets 为空直接跳过，不给没人订阅的事件白跑一趟网络。
    """
    if not targets:
        return
    if targets.bark:
        background.add_task(bark_push, targets.bark, title, body, level, page)
    if targets.web:
        background.add_task(web_push, targets.web, title, body, level, page)
    if targets.webhook:
        background.add_task(webhook_push, targets.webhook, title, body, level, page)
    if targets.email:
        background.add_task(email_push, targets.email, title, body, level, page)
