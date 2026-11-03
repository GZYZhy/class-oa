"""完整档案查看申请：班委申请 → 管理员审批 → 批准后一小时内可看敏感字段

流程与签字图申请（api/sign_photos.py）一致，但授权对象不同：
- 签字申请批准后只放开一张签字图；
- 档案申请批准后，GET /api/students/{id} 才会返回身份证号、家庭电话、
  高考分数、出生日期、实地采集照片等被裁剪掉的字段。

**只有提出申请的那一个班委、只有一小时**。管理员直接看，不需要申请；
学生本人看自己的档案也不受裁剪。普通学生看不了别人（students.py 已拦）。
"""

from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ArchiveViewRequest, Student, User
from ..schemas import (
    ArchiveViewRequestCreate,
    ArchiveViewRequestListResponse,
    ArchiveViewRequestResponse,
    ArchiveViewStatusResponse,
    RejectRequest,
)
from ..services import (
    clip,
    display_name,
    get_student,
    log_operation,
    notify,
    recipients,
    settle_topic,
)
from ..services.archive_access_service import (
    ST_APPROVED,
    ST_PENDING,
    archive_expires_at,
    archive_state,
    is_own_record,
)
from ..services.list_filters import created_between, keyword_like
from .deps import (
    admin_required,
    committee_required,
    get_client_ip,
    is_admin,
)

router = APIRouter(prefix="/api/archive-views", tags=["档案查看"])


def _get_pending(db: Session, request_id: int) -> ArchiveViewRequest:
    req = db.query(ArchiveViewRequest).filter(ArchiveViewRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理过")
    return req


def _applicant_text(req: ArchiveViewRequest) -> str:
    return f"{req.applicant_name}（{req.applicant_no}）"


def _finish(
    db: Session,
    req: ArchiveViewRequest,
    user: User,
    status: str,
    action: str,
    reason: str | None = None,
    detail: str = "",
    ip: str | None = None,
) -> ArchiveViewRequest:
    """记审批人与审批时间，写日志，一起提交（照签字申请的 _finish）"""
    req.status = status
    req.reason = reason
    req.reviewed_at = datetime.now()
    req.reviewer_no = user.student_no
    req.reviewer_name = display_name(db, user)
    log_operation(
        db, user, action,
        target=f"{req.student_no} {req.student_name}",
        detail=detail, ip=ip,
        target_student_nos=[req.student_no],
    )
    db.commit()
    db.refresh(req)
    return req


# ==================== 申请与审批 ====================


@router.post("/requests", response_model=ArchiveViewRequestResponse,
             summary="申请查看完整档案（班委及以上）")
def create_request(
    data: ArchiveViewRequestCreate,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """班委申请看某个学生的完整档案，等管理员批

    同一个学生对同一个申请人只留一条有效的：待审的不许重复提交，批下来还没过期的
    也不必再申请（否则自己反复申请就能把有效期无限往后滚）。
    """
    student = get_student(db, data.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    if is_admin(user):
        raise HTTPException(status_code=400, detail="管理员可以直接查看完整档案，无需申请")
    if is_own_record(user, student):
        raise HTTPException(status_code=400, detail="查看自己的档案无需申请")

    state, req = archive_state(db, student.id, user.student_no)
    if state == ST_PENDING:
        raise HTTPException(status_code=400, detail="已有一条待审核的申请，等管理员处理后再提交")
    if state == ST_APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"你已有完整档案查看权限，有效期至 {archive_expires_at(req):%H:%M}，无需重复申请",
        )

    new = ArchiveViewRequest(
        student_id=student.id,
        student_no=student.student_no,
        student_name=student.name,
        applicant_no=user.student_no,
        applicant_name=display_name(db, user),
    )
    db.add(new)
    log_operation(
        db, user, "申请查看完整档案",
        target=f"{student.student_no} {student.name}",
        ip=ip,
        target_student_nos=[student.student_no],
    )
    db.commit()
    db.refresh(new)

    # 提醒管理员来批。待办性质，用 timeSensitive 让它能穿透专注模式
    notify(
        db, background, recipients(db, roles=["admin"]),
        "有新的完整档案查看申请",
        f"{new.applicant_name} 申请查看 {new.student_name} 的完整档案",
        level="timeSensitive", page="/review?tab=archive",
        topic=f"archive:{new.id}",
    )
    return new


@router.get("/requests", response_model=ArchiveViewRequestListResponse,
            summary="完整档案查看申请列表（仅管理员）")
def list_requests(
    status: str | None = Query(None, description="按状态筛选：pending / approved / rejected"),
    keyword: str | None = Query(None, description="按提交人姓名或学号模糊搜索"),
    start: date | None = Query(None, description="提交日期起始，含当天"),
    end: date | None = Query(None, description="提交日期结束，含当天"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """审批用的列表。待审的排前面，其余按时间倒序"""
    query = db.query(ArchiveViewRequest)
    if status:
        query = query.filter(ArchiveViewRequest.status == status)
    # 「提交人」是发起申请的那个班委，不是被查看档案的学生
    person_match = keyword_like(
        keyword, ArchiveViewRequest.applicant_name, ArchiveViewRequest.applicant_no
    )
    if person_match is not None:
        query = query.filter(person_match)
    query = created_between(query, ArchiveViewRequest.created_at, start, end)
    total = query.count()
    items = (
        query.order_by(ArchiveViewRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": items}


@router.get("/status/{student_id}", response_model=ArchiveViewStatusResponse,
            summary="我对某学生完整档案的状态（班委及以上）")
def archive_status(
    student_id: int,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """详情页「申请查看完整档案」按钮的状态

    管理员不用申请：状态直接是 approved。
    """
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")

    if is_admin(user) or is_own_record(user, student):
        return ArchiveViewStatusResponse(status=ST_APPROVED)

    state, req = archive_state(db, student.id, user.student_no)
    return ArchiveViewStatusResponse(
        status=state,
        expires_at=archive_expires_at(req) if state == ST_APPROVED else None,
    )


@router.post("/requests/{request_id}/approve", response_model=ArchiveViewRequestResponse,
             summary="通过完整档案查看申请（仅管理员）")
def approve_request(
    request_id: int,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = _get_pending(db, request_id)
    student = db.query(Student).filter(Student.id == req.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")

    # 先取收件人再收尾：_finish 只负责数据库，通知不该混进它里面
    targets = recipients(db, only_no=req.applicant_no)
    result = _finish(
        db, req, user, "approved", "通过完整档案查看申请",
        detail=_applicant_text(req), ip=ip,
    )
    # 审这一下就把待办了结了，先清再发（新消息得保持未读）
    settle_topic(db, f"archive:{req.id}")
    notify(
        db, background, targets, "完整档案查看申请已通过",
        f"你可以在 1 小时内查看 {req.student_name} 的完整档案",
        level="timeSensitive", page=f"/students?open={req.student_id}",
        topic=f"archive:{req.id}",
    )
    return result


@router.post("/requests/{request_id}/reject", response_model=ArchiveViewRequestResponse,
             summary="驳回完整档案查看申请（仅管理员）")
def reject_request(
    request_id: int,
    payload: RejectRequest,
    background: BackgroundTasks,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = _get_pending(db, request_id)
    targets = recipients(db, only_no=req.applicant_no)
    result = _finish(
        db, req, user, "rejected", "驳回完整档案查看申请",
        reason=payload.reason, detail=_applicant_text(req), ip=ip,
    )
    settle_topic(db, f"archive:{req.id}")
    notify(
        db, background, targets, "完整档案查看申请被驳回",
        f"理由：{clip(payload.reason)}",
        level="timeSensitive", page=f"/students?open={req.student_id}",
        topic=f"archive:{req.id}",
    )
    return result
