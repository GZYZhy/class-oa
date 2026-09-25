from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Notice


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


def create_notice(db: Session, data: dict) -> Notice:
    """新建通知"""
    notice = Notice(**data)
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


def update_notice(db: Session, notice_id: int, data: dict) -> Optional[Notice]:
    """编辑通知：更新内容并记录编辑时间（用于"已于xxxx更新"标识）

    发布人不在可编辑范围内 —— 改内容不等于换发布人，保留原值（编辑者记入操作日志）。
    """
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        return None
    notice.title = data["title"]
    notice.publish_date = data["publish_date"]
    notice.content = data["content"]
    notice.updated_at = datetime.now()
    db.commit()
    db.refresh(notice)
    return notice


def delete_notice(db: Session, notice_id: int) -> bool:
    """删除通知"""
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        return False
    db.delete(notice)
    db.commit()
    return True
