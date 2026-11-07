"""站内信的读写

写入只有一个入口（notify_service 里 notify / deliver_now 调 save_messages），
所以「谁的收件箱里有什么」和「推送发给了谁」永远是同一份名单 —— 不会出现
推送发给了 A、存档却记在 B 名下这种事。
"""

import base64
import hashlib
import hmac
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import resolve_session_secret
from ..models import InboxMessage, Notice, NoticeRead, User

# 公告类站内信的关联标记：topic = "notice:<通知 id>"。
# 公告和站内信是同一条内容的两个入口，已读状态必须互相认 ——
# 从这里反解出通知 id，两边才能对上
NOTICE_TOPIC_PREFIX = "notice:"


def recipient_nos(
    db: Session,
    roles: list[str] | None = None,
    only_no: str | None = None,
    exclude_no: str | None = None,
) -> list[str]:
    """查这批人的账号

    角色筛选口径与 bark_keys / webhook_targets 完全一致（roles 为空表示不限角色），
    但**不看任何开关** —— 站内信对每个有账号的人都可达，这正是它存在的意义。

    对象是 User 而不是 Student：域外账号（is_external）也会收到通知，
    而 Student 表里根本没有他们。

    但**初始化临时账号（is_bootstrap）一律不发**：它是个马上就要被删掉的
    占位账号，给它存档只会让「收件人」这类计数莫名其妙地多一个人，
    而那个人是不存在的。
    """
    query = db.query(User.student_no).filter(User.is_bootstrap.is_(False))
    if roles:
        query = query.filter(User.role.in_(roles))
    if only_no:
        query = query.filter(User.student_no == only_no)
    if exclude_no:
        query = query.filter(User.student_no != exclude_no)
    return [row[0] for row in query.all()]


def save_messages(
    db: Session,
    student_nos: list[str],
    title: str,
    body: str,
    level: str = "active",
    page: str | None = None,
    topic: str | None = None,
) -> dict[str, int]:
    """给这批人各存一条，返回 {学号: 消息 id}

    **同步落库、就地 commit**：调用方是请求里的 notify()，这次不写就没有第二次机会。
    推送那条链是后台任务，失败了顶多少收一条手机通知；站内信是**存档**，
    丢了就是永久缺一条。

    就地 commit 安全：19 处 notify 调用点都是「先改状态、commit、再通知」这个写法，
    所以这里不会替谁提交半截事务。

    topic 是这批消息关联的办件（"leave:12" 这种），只由 notify() 透传，
    业务代码不直接调这里。
    """
    if not student_nos:
        return {}
    now = datetime.now()
    messages = [
        InboxMessage(
            student_no=no,
            title=title,
            body=body or "",
            level=level,
            page=page,
            topic=topic,
            created_at=now,
        )
        for no in student_nos
    ]
    db.add_all(messages)
    db.flush()  # 先拿 id：commit 默认会过期 ORM 属性，之后再读就是逐条重查
    ids = {m.student_no: m.id for m in messages}
    db.commit()
    # 返回 id 映射而不是条数：邮件渠道要拿每条消息的 id 生成「标记已读」链接
    return ids


def list_messages(
    db: Session, student_no: str, page: int = 1, page_size: int = 20
) -> tuple[list[InboxMessage], int]:
    """我的消息，按时间倒序。返回 (这一页, 总数)

    倒序直接按 id 排：id 自增，和创建时间同序，而 created_at 是一批一批写进去的
    （同一次通知的几十行时间戳完全相同），拿它排序结果不稳定。
    """
    query = db.query(InboxMessage).filter(InboxMessage.student_no == student_no)
    total = query.count()
    rows = (
        query.order_by(InboxMessage.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def unread_count(db: Session, student_no: str) -> int:
    """我的未读数，给菜单红点用"""
    return (
        db.query(func.count(InboxMessage.id))
        .filter(InboxMessage.student_no == student_no, InboxMessage.read_at.is_(None))
        .scalar()
        or 0
    )


def notice_id_from_topic(topic: str | None) -> int | None:
    """从 "notice:123" 里取出通知 id；不是公告类返回 None"""
    if not topic or not topic.startswith(NOTICE_TOPIC_PREFIX):
        return None
    raw = topic[len(NOTICE_TOPIC_PREFIX):]
    return int(raw) if raw.isdigit() else None


def _ensure_notice_read(db: Session, student_no: str, notice_id: int) -> bool:
    """补一条公告已读记录（已经读过 / 公告已删就不动），返回是否新增"""
    if not db.query(Notice.id).filter(Notice.id == notice_id).first():
        return False
    exists = (
        db.query(NoticeRead.id)
        .filter(
            NoticeRead.notice_id == notice_id,
            NoticeRead.student_no == student_no,
        )
        .first()
    )
    if exists:
        return False
    db.add(NoticeRead(notice_id=notice_id, student_no=student_no))
    return True


def mark_read(db: Session, student_no: str, message_id: int) -> bool:
    """标记一条为已读；不是自己的消息返回 False（接口据此报 404）

    重复调用无副作用：已经读过的不再改时间，保留「第一次看到」的那一刻。

    公告类消息（topic=notice:<id>）**同步写公告已读**：两个入口看的是同一件事，
    在这边点开、公告页的红点也得跟着消失。
    """
    message = (
        db.query(InboxMessage)
        .filter(InboxMessage.id == message_id, InboxMessage.student_no == student_no)
        .first()
    )
    if message is None:
        return False
    changed = False
    if message.read_at is None:
        message.read_at = datetime.now()
        changed = True
    notice_id = notice_id_from_topic(message.topic)
    if notice_id and _ensure_notice_read(db, student_no, notice_id):
        changed = True
    if changed:
        db.commit()
    return True


def settle_topic(db: Session, topic: str, student_no: str | None = None) -> int:
    """把关联某个办件的未读消息自动标为已读，返回标了几条（别人的、已读的不动）

    办件推进（批准 / 驳回 / 退回补正 / 撤销、申请人重交或撤回）之后，之前那条
    「有新的请假申请待审核」之类的消息就过时了 —— 这件已经有人处理了，不该再
    挂在谁的红点里。**对这单的所有收件人生效**：管理员 A 批了，管理员 B 收件箱里
    那条待办同样作废，审核中心页能看到，红点不必再提醒。

    student_no 传入时只标这一个人（下载类接口用）：管理员代下了学生的成品证明，
    不代表学生本人看过「已开好」那条。

    **必须在 notify() 之前调**：本次推进产生的新消息（如「已通过」）是同一 topic，
    先落库再清的话会把刚发的通知一并标掉。settle 自带 commit，各接口照
    「先改状态、commit、再 settle、再 notify」的次序写就行。

    只认 read_at 是否为空，自动已读写的是判定时刻，不是「打开」时刻 —— 见模型注释。
    """
    query = db.query(InboxMessage).filter(
        InboxMessage.topic == topic, InboxMessage.read_at.is_(None)
    )
    if student_no:
        query = query.filter(InboxMessage.student_no == student_no)
    # 先把收件人记下来：update 之后这些行就都 read_at 非空了，再查分不清是谁。
    # 公告类 topic 还要给这些人补 NoticeRead —— 否则公告页仍是未读
    recipients_before = [row[0] for row in query.with_entities(InboxMessage.student_no).all()]
    updated = query.update({InboxMessage.read_at: datetime.now()})
    notice_id = notice_id_from_topic(topic)
    if notice_id:
        for no in recipients_before:
            _ensure_notice_read(db, no, notice_id)
    db.commit()
    return updated


def mark_all_read(db: Session, student_no: str) -> int:
    """全部标为已读，返回这次标了几条

    公告类消息顺带把公告已读一起补上：用户点的是「全部已读」，
    没道理公告页还留着一排红点。
    """
    topics = [
        row[0]
        for row in db.query(InboxMessage.topic)
        .filter(
            InboxMessage.student_no == student_no,
            InboxMessage.read_at.is_(None),
            InboxMessage.topic.isnot(None),
        )
        .distinct()
        .all()
    ]
    updated = (
        db.query(InboxMessage)
        .filter(InboxMessage.student_no == student_no, InboxMessage.read_at.is_(None))
        .update({InboxMessage.read_at: datetime.now()})
    )
    for topic in topics:
        notice_id = notice_id_from_topic(topic)
        if notice_id:
            _ensure_notice_read(db, student_no, notice_id)
    db.commit()
    return updated


def delete_read(db: Session, student_no: str) -> int:
    """删除自己的**全部**已读消息（不分页），返回删除条数。

    判据只有 read_at 非空一条：未读的一条都不动，别人的消息也碰不到。
    删除后不可恢复，接口那边有确认框兜着。
    """
    deleted = (
        db.query(InboxMessage)
        .filter(InboxMessage.student_no == student_no, InboxMessage.read_at.isnot(None))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


# ---------------------------------------------------------------- 邮件「标记已读」链接

def read_token(message_id: int, student_no: str) -> str:
    """把「哪条消息、属于谁」签成一个 URL 安全令牌

    邮件里的已读按钮不能要求登录，所以链接必须自带凭证；HMAC 保证别人改不了
    message_id 或学号去看/改别人的消息。只签这两个字段，链接短、也不会把正文带出去。
    """
    payload = f"{message_id}:{student_no}"
    sig = hmac.new(
        resolve_session_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def parse_read_token(token: str) -> tuple[int, str] | None:
    """验邮件已读令牌，返回 (message_id, student_no)；不合法返回 None"""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit(":", 1)
        message_id, student_no = payload.split(":", 1)
        message_id_int = int(message_id)
    except (ValueError, UnicodeDecodeError, OverflowError):
        return None
    if message_id_int <= 0 or not student_no:
        return None
    expected = hmac.new(
        resolve_session_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    return message_id_int, student_no
