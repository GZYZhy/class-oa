"""意见反馈：学生提交，班委查看/标记已读/回复"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Feedback, Student, User
from ..schemas import FeedbackCreate, FeedbackReply, FeedbackResponse
from ..services import display_name
from .deps import (
    committee_required,
    get_current_student,
    get_current_user,
)

router = APIRouter(prefix="/api/feedback", tags=["意见反馈"])

# 状态：unread 未读 / read 已读 / replied 已回复
VALID_STATUSES = {"unread", "read", "replied"}


def _to_response(fb: Feedback) -> FeedbackResponse:
    return FeedbackResponse.model_validate(fb)


# ---------- 学生端 ----------

@router.get("/my", response_model=list[FeedbackResponse], summary="我的反馈")
def my_feedback(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """当前登录学生自己的反馈列表，按时间倒序"""
    rows = (
        db.query(Feedback)
        .filter(Feedback.student_id == student.id)
        .order_by(desc(Feedback.id))
        .all()
    )
    return [_to_response(r) for r in rows]


@router.post("", response_model=FeedbackResponse, summary="提交意见反馈")
def submit_feedback(
    data: FeedbackCreate,
    user: User = Depends(get_current_user),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    fb = Feedback(
        student_id=student.id,
        student_no=student.student_no,
        student_name=student.name,
        title=data.title.strip(),
        content=data.content.strip(),
        status="unread",
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return _to_response(fb)


@router.get("/{feedback_id}", response_model=FeedbackResponse, summary="查看我的反馈详情")
def my_feedback_detail(
    feedback_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """学生只能看自己的"""
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb or fb.student_id != student.id:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return _to_response(fb)


# ---------- 班委端 ----------

@router.get("", response_model=list[FeedbackResponse], summary="反馈列表（班委及以上）")
def list_feedback(
    status: str | None = Query(None, description="unread/read/replied，不传为全部"),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    query = db.query(Feedback)
    if status and status in VALID_STATUSES:
        query = query.filter(Feedback.status == status)
    rows = query.order_by(desc(Feedback.id)).all()
    return [_to_response(r) for r in rows]


@router.get("/{feedback_id}/detail", response_model=FeedbackResponse, summary="反馈详情（班委）")
def feedback_detail(
    feedback_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """班委查看详情。如果状态是 unread，自动标记为已读。"""
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")

    # 查看即标为已读（但不覆盖 replied 状态）
    if fb.status == "unread":
        fb.status = "read"
        db.commit()
        db.refresh(fb)

    return _to_response(fb)


@router.post("/{feedback_id}/mark-read", response_model=FeedbackResponse, summary="标记已读（班委）")
def mark_read(
    feedback_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")
    if fb.status == "unread":
        fb.status = "read"
        db.commit()
        db.refresh(fb)
    return _to_response(fb)


@router.post("/{feedback_id}/reply", response_model=FeedbackResponse, summary="回复反馈（班委）")
def reply_feedback(
    feedback_id: int,
    data: FeedbackReply,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")

    fb.reply_content = data.content.strip()
    fb.reply_name = display_name(db, user)
    fb.reply_no = user.student_no
    fb.reply_at = datetime.now()
    fb.status = "replied"
    db.commit()
    db.refresh(fb)
    return _to_response(fb)
