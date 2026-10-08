import json
from datetime import date, datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Notice, NoticeRead, User
from .user_service import account_name, account_names


def list_notices(
    db: Session,
    title: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[Notice]:
    """通知列表：按发布时间降序，支持标题模糊、时间区间搜索"""
    query = db.query(Notice)

    if title:
        query = query.filter(Notice.title.like(f"%{title}%"))
    if start_date:
        query = query.filter(Notice.publish_date >= start_date)
    if end_date:
        query = query.filter(Notice.publish_date <= end_date)

    return query.order_by(Notice.publish_date.desc(), Notice.id.desc()).all()


def notice_attachments(notice: Notice) -> list:
    """把库里存的附件 JSON 串读成列表；读不出来就当没有

    RSS 摘要里要附上的附件链接（api/notices.py 的下载/编辑/删除也要用），
    所以解析放在这里共用，而不是各写一份 json.loads。
    """
    if not notice.attachments:
        return []
    try:
        items = json.loads(notice.attachments or "")
    except (ValueError, TypeError):
        return []
    return items if isinstance(items, list) else []


def _editors_list(notice: Notice) -> list:
    """读取编辑人列表（JSON → list）"""
    if not notice.editors:
        return []
    try:
        items = json.loads(notice.editors)
        return items if isinstance(items, list) else []
    except (ValueError, TypeError):
        return []


def _add_editor(db: Session, notice: Notice, user: User) -> str:
    """把一个编辑人加入列表（同一个人多次编辑只保留最新一条，放在最后）

    返回更新后的 JSON 串
    """
    items = _editors_list(notice)
    no = user.student_no
    name = account_name(db, user)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 去掉旧条目里同一个人的记录
    items = [e for e in items if e.get("no") != no]
    items.append({"no": no, "name": name, "time": now})
    return json.dumps(items, ensure_ascii=False)


def create_notice(db: Session, data: dict, user: User | None = None) -> Notice:
    """新建通知

    传入 user 时会同时初始化 editors（首发人作为第一个编辑者）。
    """
    notice = Notice(**data)
    db.add(notice)
    db.flush()  # flush 拿到 id，才能加 editors
    if user:
        notice.editors = _add_editor(db, notice, user)
    db.commit()
    db.refresh(notice)
    return notice


def update_notice(db: Session, notice_id: int, data: dict, user: User | None = None) -> Optional[Notice]:
    """编辑通知：更新内容并记录编辑时间（用于"已于xxxx更新"标识）

    发布人不在可编辑范围内 —— 改内容不等于换发布人，保留原值（编辑者记入操作日志）。
    传 user 时，把编辑者追加到 editors 列表（多人参与时都会列出来）。
    """
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        return None
    notice.title = data["title"]
    notice.publish_date = data["publish_date"]
    notice.content = data["content"]
    # 附件：传了就更新，不传就不动（编辑正文时可能不带附件字段）
    if "attachments" in data:
        notice.attachments = data["attachments"]
    # 把编辑者加进 editors 列表（同一个人多次编辑只保留最新一条）
    if user:
        notice.editors = _add_editor(db, notice, user)
    notice.updated_at = datetime.now()
    db.commit()
    db.refresh(notice)
    return notice


def delete_notice(db: Session, notice_id: int) -> bool:
    """删除通知（连同它的已读记录）"""
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        return False
    # 已读记录没有外键约束，不显式清掉就会留下孤儿行
    db.query(NoticeRead).filter(NoticeRead.notice_id == notice_id).delete()
    db.delete(notice)
    db.commit()
    return True


def mark_read(db: Session, notice_id: int, student_no: str) -> None:
    """把某条通知标记为「某人已读」

    展开/收起通知会重复触发，所以这里必须容忍重复调用：唯一约束撞了就当作成功，
    不能给前端一个 500。
    """
    exists = (
        db.query(NoticeRead.id)
        .filter(NoticeRead.notice_id == notice_id, NoticeRead.student_no == student_no)
        .first()
    )
    if exists:
        return

    db.add(NoticeRead(notice_id=notice_id, student_no=student_no))
    try:
        db.commit()
    except IntegrityError:
        # 两次请求几乎同时到达，另一条先把行插进去了 —— 结果是一样的，不必报错
        db.rollback()


def read_notice_ids(db: Session, student_no: str) -> set[int]:
    """某人读过的通知 id 集合"""
    return {
        row[0]
        for row in db.query(NoticeRead.notice_id)
        .filter(NoticeRead.student_no == student_no)
        .all()
    }


def unread_count(db: Session, student_no: str) -> int:
    """我没读过的通知条数

    用「全部通知」减去「我读过的」来数：即使有孤儿已读行（通知已删、记录没清），
    结果也不会算成负数。
    """
    read_ids = read_notice_ids(db, student_no)
    return db.query(Notice).filter(Notice.id.not_in(read_ids)).count()


def read_status(db: Session, notice_id: int) -> dict:
    """某条通知的已读情况：谁读了、谁没读

    分母取 users 表里的**全部账号**（含域外账号、含已冻结的）。冻结的不排除，
    否则「45 人里读了 23 个」对不上全班人数；冻结的单独标出来，班委一看就明白
    为什么这个人一直没读。名单从 users 出发还有一个好处：账号被删掉后残留的
    已读行不会冒出来。
    """
    read_at_map = {
        row.student_no: row.read_at
        for row in db.query(NoticeRead).filter(NoticeRead.notice_id == notice_id).all()
    }
    users = db.query(User).order_by(User.student_no).all()
    names = account_names(db, users)

    rows = [
        {
            "student_no": user.student_no,
            "name": names.get(user.student_no, user.student_no),
            "read_at": read_at_map.get(user.student_no),
            "frozen": bool(user.is_frozen),
        }
        for user in users
    ]
    # 未读的排前面 —— 班委打开这个名单就是为了找还没看的人
    rows.sort(key=lambda row: (row["read_at"] is not None, row["student_no"]))

    return {
        "total": len(rows),
        "read_count": sum(1 for row in rows if row["read_at"] is not None),
        "rows": rows,
    }
