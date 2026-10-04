"""站内信的读写

写入只有一个入口（notify_service 里 notify / deliver_now 调 save_messages），
所以「谁的收件箱里有什么」和「推送发给了谁」永远是同一份名单 —— 不会出现
推送发给了 A、存档却记在 B 名下这种事。
"""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import InboxMessage, User


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
) -> int:
    """给这批人各存一条，返回写入条数

    **同步落库、就地 commit**：调用方是请求里的 notify()，这次不写就没有第二次机会。
    推送那条链是后台任务，失败了顶多少收一条手机通知；站内信是**存档**，
    丢了就是永久缺一条。

    就地 commit 安全：19 处 notify 调用点都是「先改状态、commit、再通知」这个写法，
    所以这里不会替谁提交半截事务。
    """
    if not student_nos:
        return 0
    now = datetime.now()
    db.add_all([
        InboxMessage(
            student_no=no,
            title=title,
            body=body or "",
            level=level,
            page=page,
            created_at=now,
        )
        for no in student_nos
    ])
    db.commit()
    return len(student_nos)


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


def mark_read(db: Session, student_no: str, message_id: int) -> bool:
    """标记一条为已读；不是自己的消息返回 False（接口据此报 404）

    重复调用无副作用：已经读过的不再改时间，保留「第一次看到」的那一刻。
    """
    message = (
        db.query(InboxMessage)
        .filter(InboxMessage.id == message_id, InboxMessage.student_no == student_no)
        .first()
    )
    if message is None:
        return False
    if message.read_at is None:
        message.read_at = datetime.now()
        db.commit()
    return True


def mark_all_read(db: Session, student_no: str) -> int:
    """全部标为已读，返回这次标了几条"""
    updated = (
        db.query(InboxMessage)
        .filter(InboxMessage.student_no == student_no, InboxMessage.read_at.is_(None))
        .update({InboxMessage.read_at: datetime.now()})
    )
    db.commit()
    return updated
