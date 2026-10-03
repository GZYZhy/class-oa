"""学生信息修改申请：学生提交 → 班委审核 → 通过后才写入学生表

白名单之外的字段不开放申请：学号、姓名、身份证号、班委职务属于身份标识（改了等于换个人），
「是否贫困生」属于内部认定事项 —— 都由班委/管理员在名单页直接维护，学生不能自己发起变更。
"""

import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ChangeRequest, Student, User
from ..schemas import ChangeRequestCreate, ChangeRequestResponse, RejectRequest
from ..services import clip, display_name, log_operation, notify, recipients
from ..utils.student_fields import describe_changes
from .deps import committee_required, get_current_student, get_current_user, get_client_ip

router = APIRouter(prefix="/api/change-requests", tags=["修改申请"])

# 审核人：申请要班委或管理员审，所以推送也只发给他们
REVIEWER_ROLES = ["admin", "committee"]

# 允许学生申请修改的字段。改这里就行，校验、落库、审核三处共用同一份
# 顺序与前端 utils/changeFields.js 的 CHANGE_FIELDS 保持一致（决定表单里的排列）
EDITABLE_FIELDS = (
    "qq",
    "email",
    # 两个电话不卡格式：真实档案里有座机（010-…）、有带区号/分机的写法，
    # 卡正则只会把合法号码挡在外面，而这两个字段既不进邮件头也不参与鉴权
    "phone",
    "family_phone",
    "family_address",
    "postal_code",
    "league_position",
    "bed",
)


def _to_response(req: ChangeRequest, student: Student | None) -> ChangeRequestResponse:
    """组装出参，并带上学生当前值供前端做「原值 → 新值」对照"""
    data = ChangeRequestResponse.model_validate(req)
    if student:
        data.current = {f: getattr(student, f, None) for f in EDITABLE_FIELDS}
    return data


@router.post("", response_model=ChangeRequestResponse, summary="提交信息修改申请")
def submit(
    payload: ChangeRequestCreate,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    # 按白名单过滤（与 approve 同口径）：不过滤的话，schema 里多一个字段、白名单里
    # 少一个，就会存进一条「提交成功但永远不会生效」的申请 —— changes 里有，审批时不认
    changes = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if key in EDITABLE_FIELDS
    }
    if not changes:
        raise HTTPException(status_code=400, detail="没有要修改的内容")

    # 不让申请叠着排队：一条还没审完，后面的改了也是白改
    pending = (
        db.query(ChangeRequest)
        .filter(ChangeRequest.student_id == student.id, ChangeRequest.status == "pending")
        .first()
    )
    if pending:
        raise HTTPException(status_code=400, detail="已有一条待审核的申请，等班委处理后再提交")

    req = ChangeRequest(
        student_id=student.id,
        student_no=student.student_no,
        student_name=student.name,
        changes=json.dumps(changes, ensure_ascii=False),
    )
    db.add(req)
    log_operation(
        db, user, "提交修改申请", target=f"{student.student_no} {student.name}",
        # 写成「本人电话：138… → 139…」，和通过申请时那条日志一个口径
        detail=describe_changes({k: getattr(student, k, None) for k in changes}, changes),
        ip=ip,
    )
    db.commit()
    db.refresh(req)

    # 提醒班委来处理。待办性质，用 timeSensitive 让它能穿透专注模式
    notify(
        background,
        recipients(db, roles=REVIEWER_ROLES, exclude_no=user.student_no),
        "有新的信息修改申请待审核",
        f"{student.name} 提交了 {len(changes)} 项修改，等待你审核",
        level="timeSensitive",
        page="/review",
    )
    return _to_response(req, student)


@router.get("/me", response_model=list[ChangeRequestResponse], summary="我的申请记录")
def my_requests(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ChangeRequest)
        .filter(ChangeRequest.student_id == student.id)
        .order_by(ChangeRequest.id.desc())
        .all()
    )
    return [_to_response(r, student) for r in rows]


@router.get("", response_model=list[ChangeRequestResponse], summary="申请列表（班委及以上）")
def list_requests(
    _: User = Depends(committee_required),
    status: str | None = Query(None, description="pending|approved|rejected，不传为全部"),
    db: Session = Depends(get_db),
):
    query = db.query(ChangeRequest)
    if status:
        query = query.filter(ChangeRequest.status == status)
    rows = query.order_by(ChangeRequest.id.desc()).all()

    # 一次把涉及的学生查出来，避免逐条查（N+1）
    student_ids = {r.student_id for r in rows}
    students = (
        {s.id: s for s in db.query(Student).filter(Student.id.in_(student_ids)).all()}
        if student_ids else {}
    )
    return [_to_response(r, students.get(r.student_id)) for r in rows]


def _get_pending(db: Session, request_id: int) -> ChangeRequest:
    """取出待审核的申请，不存在或已处理过就报错"""
    req = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理过")
    return req


def _finish(
    db: Session, req: ChangeRequest, user: User, status: str, action: str,
    reason: str | None = None, detail: str = "", ip: str | None = None,
) -> ChangeRequestResponse:
    """记录审核人与审核时间，写日志，一起提交"""
    req.status = status
    req.reason = reason
    req.reviewed_at = datetime.now()
    req.reviewer_no = user.student_no
    req.reviewer_name = display_name(db, user)
    log_operation(db, user, action, target=f"{req.student_no} {req.student_name}", detail=detail, ip=ip)
    db.commit()
    db.refresh(req)
    return _to_response(req, db.query(Student).filter(Student.id == req.student_id).first())


# 允许班委审自己的申请（不拦截），但每次都会写进操作日志
@router.post("/{request_id}/approve", response_model=ChangeRequestResponse, summary="通过申请")
def approve(
    request_id: int,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = _get_pending(db, request_id)
    student = db.query(Student).filter(Student.id == req.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")

    # 双保险：落库前再按白名单过滤一次，防止历史脏数据越权改字段
    changes = {
        key: value
        for key, value in json.loads(req.changes or "{}").items()
        if key in EDITABLE_FIELDS
    }
    # 详情要在 setattr 之前算：算完 student 就只剩新值了
    detail = describe_changes({k: getattr(student, k, None) for k in changes}, changes)
    for key, value in changes.items():
        setattr(student, key, value)

    # 先取收件人再收尾：_finish 只负责数据库，通知不该混进它里面
    targets = recipients(db, only_no=req.student_no)
    result = _finish(db, req, user, "approved", "通过修改申请", detail=detail, ip=ip)
    notify(
        background, targets, "信息修改申请已通过",
        f"你提交的 {len(changes)} 项修改已生效", level="timeSensitive", page="/my-info?tab=workspace&sub=submitted",
    )
    return result


@router.post("/{request_id}/reject", response_model=ChangeRequestResponse, summary="驳回申请")
def reject(
    request_id: int,
    payload: RejectRequest,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    req = _get_pending(db, request_id)
    targets = recipients(db, only_no=req.student_no)
    result = _finish(db, req, user, "rejected", "驳回修改申请", reason=payload.reason, ip=ip)
    notify(
        background, targets, "信息修改申请被驳回",
        f"理由：{clip(payload.reason)}", level="timeSensitive", page="/my-info?tab=workspace&sub=submitted",
    )
    return result
