"""侧边菜单红点的计数接口

两类红点（通知未读 / 待我审核）合成一个接口返回：前端每换一次页面都要刷一次，
合成一个省掉一半请求；更要紧的是「哪些算待办」这个口径是按角色分叉的，
集中在一处写清楚，比散在通知、审核两个模块里各写一半好维护。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ChangeRequest, EvPassRequest, Feedback, LeaveRequest, User
from ..services import unread_count
from .deps import get_current_user

router = APIRouter(prefix="/api/badges", tags=["未读红点"])


@router.get("", summary="菜单红点计数")
def get_badges(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回 {"notice_unread": 通知未读数, "review_pending": 待我处理数}

    review_pending **只算当前角色真能处理的**：请假只有管理员能批
    （leaves.py 的 approve/reject 都是 admin_required），给班委也算上的话，
    红点数字虚高、点进去却批不了。

    三个计数直接 COUNT 出数，不走各家的列表接口 —— 那三个列表都没有分页、
    一次返回全部行，为了拿一个数字拉全表不划算。
    """
    review_pending = _count(db, ChangeRequest, "pending") + _count(db, Feedback, "unread")
    if user.role == "admin":
        review_pending += _count(db, LeaveRequest, "pending")
        # 电动车通行证也走管理员审批（ev_passes.py 的 approve/reject 都是 admin_required）
        review_pending += _count(db, EvPassRequest, "pending")

    return {
        "notice_unread": unread_count(db, user.student_no),
        "review_pending": review_pending,
    }


def _count(db: Session, model, status: str) -> int:
    """数某个模型里处于某状态的行数（模型自己的 status 列）"""
    return (
        db.query(func.count(model.id)).filter(model.status == status).scalar() or 0
    )
