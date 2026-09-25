"""通知分发服务

把「这件事跟谁有关」翻译成「往哪些设备发」，再路由给两个渠道：
Bark（要用户自己装 App、填设备 key）和浏览器推送（用户在本站点一下就行）。

渠道自己的实现分别在 bark_service 和 webpush_service 里，这里只管路由，
业务代码只跟这一层打交道。
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .bark_service import bark_keys
from .bark_service import push as bark_push
from .webpush_service import push as web_push
from .webpush_service import web_subscriptions


@dataclass
class Recipients:
    """一次通知的收件人，两个渠道各一份

    存的是纯数据（字符串 / dict），不含 ORM 对象 —— 后台任务拿到就能直接发，
    不需要再碰数据库会话。
    """

    bark: list[str] = field(default_factory=list)
    web: list[dict] = field(default_factory=list)

    def __bool__(self) -> bool:
        """两边都没人订阅才算空

        dataclass 默认恒为真，不写这个方法的话 notify() 里的空判断永远不成立，
        没人订阅的事件也会白挂一个后台任务（现在的写法是故意要短路的）。
        """
        return bool(self.bark or self.web)


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
    )


def notify(
    background, targets: Recipients, title: str, body: str,
    level: str = "active", page: str | None = None,
) -> None:
    """把推送挂到后台任务上

    之所以走后台：发推送要走外网，放在请求里会让接口白白慢几百毫秒。
    两个渠道各挂各的任务，一个渠道挂了不拖累另一个。
    targets 为空直接跳过，不给没人订阅的事件白跑一趟网络。
    """
    if not targets:
        return
    if targets.bark:
        background.add_task(bark_push, targets.bark, title, body, level, page)
    if targets.web:
        background.add_task(web_push, targets.web, title, body, level, page)
