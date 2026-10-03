"""站内信：所有推送的存档

登录的人各看各的。写入不在这里 —— 那是 notify_service 的事（所有推送顺手存一份），
本模块只有「看」和「标记已读」。菜单红点用的未读数另有 /api/badges 一处，
不在这里重复开接口。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas.inbox import InboxListResponse
from ..services import inbox_service
from .deps import get_current_user

router = APIRouter(prefix="/api/inbox", tags=["站内信"])

# 每页条数上限。前端固定传 20，这个上限只是防手工构造请求一次拉全表
MAX_PAGE_SIZE = 100


@router.get("", response_model=InboxListResponse, summary="我的站内信")
def list_inbox(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按时间倒序分页；unread 是全量未读数（见 schema 里的说明）"""
    rows, total = inbox_service.list_messages(db, user.student_no, page, page_size)
    return InboxListResponse(
        total=total,
        page=page,
        page_size=page_size,
        unread=inbox_service.unread_count(db, user.student_no),
        items=rows,
    )


@router.post("/{message_id}/read", summary="标记一条为已读")
def read_message(
    message_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重复调用无副作用（前端点开就调，刷新后再点一次也不报错）

    不是自己的消息按「不存在」处理，不泄露「这个 id 存在但不归你」。
    """
    if not inbox_service.mark_read(db, user.student_no, message_id):
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"ok": True}


@router.post("/read-all", summary="全部标为已读")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"updated": inbox_service.mark_all_read(db, user.student_no)}
