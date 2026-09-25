from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Announcement


def list_announcements(
    db: Session,
    title: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    public_only: bool = False,
) -> list[Announcement]:
    """文件列表：按发布时间降序，支持标题模糊、时间区间搜索

    public_only=True 时只返回「向班委以外公开」的文件，供普通学生查看。
    """
    query = db.query(Announcement)

    if public_only:
        query = query.filter(Announcement.is_public.is_(True))
    if title:
        query = query.filter(Announcement.title.like(f"%{title}%"))
    if start_date:
        query = query.filter(Announcement.publish_date >= start_date)
    if end_date:
        query = query.filter(Announcement.publish_date <= end_date)

    return query.order_by(
        Announcement.publish_date.desc(), Announcement.id.desc()
    ).all()


def create_announcement(
    db: Session,
    title: str,
    doc_number: Optional[str],
    publish_date: date,
    file_path: str,
    file_name: str,
    publisher: str = "",
    is_public: bool = True,
) -> Announcement:
    """新建公告（publisher 由服务端按登录账号传入）"""
    announcement = Announcement(
        title=title,
        doc_number=doc_number,
        publish_date=publish_date,
        file_path=file_path,
        file_name=file_name,
        publisher=publisher,
        is_public=is_public,
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    return announcement


def delete_announcement(db: Session, announcement_id: int, file_path: Optional[str] = None) -> bool:
    """删除公告（同时删除文件）"""
    announcement = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not announcement:
        return False
    db.delete(announcement)
    db.commit()
    return True


def get_announcement(db: Session, announcement_id: int) -> Optional[Announcement]:
    """获取单个公告"""
    return db.query(Announcement).filter(Announcement.id == announcement_id).first()
