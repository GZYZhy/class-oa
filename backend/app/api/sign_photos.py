"""签字图：管理员上传，班委申请、管理员批准后才看得到

签字和另外三张照片（高考照、实地采集、自备证件照）敏感度不在一个量级 —— 签字能
被拿去伪造请假条和证明材料，所以不能沿用照片那条「班委看得见这个学生就能看他的
照片」的规则，这里是一条完整的申请-审批链：

    管理员上传（admin_required）
    → 班委申请（committee_required）
    → 管理员批准
    → **只有提出申请的那一个班委**在 1 小时内能取图；管理员自己不受限

学生完全不参与：StudentResponse 里没有签字字段，取图接口对非班委一律 403，
前端也只在 isCommittee 时才渲染那个按钮，学生端连「签字」两个字都不出现。

查看行为不写操作日志 —— operation_logs 的原则是「只记内容变更、不记查询」
（见 models/file_access_log.py 的注释）。「谁被批准看谁的签字」由本表自身的
申请人 / 被看学生 / 审批人 / 审批时间留痕。

打包导入（zip）走的是 api/students.py 那条照片链路，它认 sign 类型（管理员操作）；
但**取图**只走这里的 GET /image/{student_id}，通用照片接口认不到 sign，
于是 GET /api/students/{id}/photo?type=sign 天然报「未知的照片类型」。
"""

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SignPhotoRequest, Student, User
from ..schemas import (
    RejectRequest,
    SignPhotoRequestCreate,
    SignPhotoRequestListResponse,
    SignPhotoRequestResponse,
    SignPhotoStatusResponse,
)
from ..services import clip, display_name, get_student, log_operation, notify, recipients
from ..services.student_photo_service import photo_path, photo_response, remove_photo, save_photo
from .deps import (
    admin_required,
    committee_required,
    get_client_ip,
    get_current_user,
    is_admin,
    is_committee,
)

router = APIRouter(prefix="/api/sign-photos", tags=["签字"])

# 批准之后能看多久。过期要重新申请 —— 一次批准不是永久授权。
# 只此一处：状态接口和取图接口用的是同一个判断，走散了就会出现「按钮说能看、
# 点开 403」这种自相矛盾
SIGN_VIEW_TTL = timedelta(hours=1)

# 给前端那个按钮用的状态
ST_NONE = "none"          # 没申请过，或被驳回了
ST_PENDING = "pending"    # 等管理员批
ST_APPROVED = "approved"  # 能看
ST_EXPIRED = "expired"    # 批过但过期了，要重新申请


def _state(db: Session, student_id: int, applicant_no: str) -> tuple[str, SignPhotoRequest | None]:
    """某人对某学生的状态，只看**最近一条**申请

    返回「给前端的那个状态字符串」+「可用的那条申请（没有就是 None）」，两件事由
    同一个函数算出来 —— 前端按钮和后端取图就不会各算一份、各说各话。

    已驳回的和没申请过的都归成 none：对使用者来说都是「点一下申请就行」。
    """
    req = (
        db.query(SignPhotoRequest)
        .filter(
            SignPhotoRequest.student_id == student_id,
            SignPhotoRequest.applicant_no == applicant_no,
        )
        .order_by(SignPhotoRequest.id.desc())
        .first()
    )
    if not req:
        return ST_NONE, None
    if req.status == "pending":
        return ST_PENDING, None
    if req.status != "approved":
        return ST_NONE, None
    # approved 但没写 reviewed_at 是不可能的；真出现了就当过期，宁可拒绝
    if not req.reviewed_at or datetime.now() - req.reviewed_at > SIGN_VIEW_TTL:
        return ST_EXPIRED, None
    return ST_APPROVED, req


def _expires_at(req: SignPhotoRequest) -> datetime:
    return req.reviewed_at + SIGN_VIEW_TTL


def _download_name(student: Student) -> str:
    """拼一个能直接存盘的下载文件名

    **库里那个裸文件名一个字符都不出网** —— 它是内部命名（单张上传是 uuid4 hex），
    给前端没有半点用处。但后缀要留着：预览组件靠文件名后缀决定按图片还是 PDF 渲染，
    少了它签字图会被当成 PDF 打开。
    """
    if not student.sign_photo:
        return ""
    return f"{student.name}_签字{Path(student.sign_photo).suffix}"


def _applicant_text(req: SignPhotoRequest) -> str:
    """日志里那个「谁在申请」的括号写法，与项目其它日志一致"""
    return f"{req.applicant_name}（{req.applicant_no}）"


def _get_pending(db: Session, request_id: int) -> SignPhotoRequest:
    req = db.query(SignPhotoRequest).filter(SignPhotoRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理过")
    return req


def _finish(
    db: Session, req: SignPhotoRequest, user: User, status: str, action: str,
    reason: str | None = None, detail: str = "", ip: str | None = None,
) -> SignPhotoRequest:
    """记审批人与审批时间，写日志，一起提交（照 change_requests._finish）"""
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


@router.post("/requests", response_model=SignPhotoRequestResponse,
             summary="申请查看签字（班委及以上）")
def create_request(
    data: SignPhotoRequestCreate,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """班委申请看某个学生的签字图，等管理员批

    同一个学生对同一个申请人只留一条有效的：待审的不许重复提交，批下来还没过期的
    也不必再申请（否则自己反复申请就能把有效期无限往后滚）。过期或已被驳回的可以重来。
    """
    student = get_student(db, data.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    if not student.sign_photo:
        raise HTTPException(status_code=400, detail="该学生还没有签字图片，无需申请")

    state, req = _state(db, student.id, user.student_no)
    if state == ST_PENDING:
        raise HTTPException(status_code=400, detail="已有一条待审核的申请，等管理员处理后再提交")
    if state == ST_APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"你已有查看权限，有效期至 {_expires_at(req):%H:%M}，无需重复申请",
        )

    new = SignPhotoRequest(
        student_id=student.id,
        student_no=student.student_no,
        student_name=student.name,
        applicant_no=user.student_no,
        applicant_name=display_name(db, user),
    )
    db.add(new)
    log_operation(
        db, user, "申请查看签字",
        target=f"{student.student_no} {student.name}",
        ip=ip,
        target_student_nos=[student.student_no],
    )
    db.commit()
    db.refresh(new)

    # 提醒管理员来批。待办性质，用 timeSensitive 让它能穿透专注模式
    notify(
        db, background, recipients(db, roles=["admin"]),
        "有新的签字查看申请",
        f"{new.applicant_name} 申请查看 {new.student_name} 的签字",
        level="timeSensitive", page="/review?tab=signphoto",
    )
    return new


@router.get("/requests", response_model=SignPhotoRequestListResponse,
            summary="签字查看申请列表（仅管理员）")
def list_requests(
    status: str | None = Query(None, description="按状态筛选：pending / approved / rejected"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """审批用的列表。待审的排前面，其余按时间倒序"""
    query = db.query(SignPhotoRequest)
    if status:
        query = query.filter(SignPhotoRequest.status == status)
    total = query.count()
    items = (
        query.order_by(SignPhotoRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": items}


@router.get("/status/{student_id}", response_model=SignPhotoStatusResponse,
            summary="我对某学生签字的状态（班委及以上）")
def sign_status(
    student_id: int,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """详情页那个按钮的状态，顺带给出预览要用的下载名

    管理员不用申请：有图就是能看，状态直接是 approved。

    **有图就一定有 download_name**，哪怕当前状态是「没申请过」—— 前端靠它区分
    「这学生根本没有签字图」（不渲染按钮）和「有图但我还没申请」（渲染「申请签署」）。
    只有 download_name 一个信号，状态字符串不够用。
    """
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    # 没有签字图时连 download_name 都不给 —— 前端据此整个不渲染那个按钮
    if not student.sign_photo:
        return SignPhotoStatusResponse(status=ST_NONE)

    if is_admin(user):
        return SignPhotoStatusResponse(status=ST_APPROVED, download_name=_download_name(student))

    state, req = _state(db, student.id, user.student_no)
    return SignPhotoStatusResponse(
        status=state,
        # 只有 approved 才给到期时间（其余状态给了也没意义，前端只在能看时用它）
        expires_at=_expires_at(req) if state == ST_APPROVED else None,
        download_name=_download_name(student),
    )


@router.post("/requests/{request_id}/approve", response_model=SignPhotoRequestResponse,
             summary="通过签字查看申请（仅管理员）")
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
    # 图没了还批，申请人点开只会看到 404 —— 不如在这里就说清楚
    if not student.sign_photo:
        raise HTTPException(status_code=400, detail="该学生没有签字图片，通过了他也看不到东西")

    # 先取收件人再收尾：_finish 只负责数据库，通知不该混进它里面
    targets = recipients(db, only_no=req.applicant_no)
    result = _finish(
        db, req, user, "approved", "通过签字查看申请",
        detail=_applicant_text(req), ip=ip,
    )
    notify(
        db, background, targets, "签字查看申请已通过",
        f"你可以在 1 小时内查看 {req.student_name} 的签字",
        level="timeSensitive", page="/students",
    )
    return result


@router.post("/requests/{request_id}/reject", response_model=SignPhotoRequestResponse,
             summary="驳回签字查看申请（仅管理员）")
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
        db, req, user, "rejected", "驳回签字查看申请",
        reason=payload.reason, detail=_applicant_text(req), ip=ip,
    )
    notify(
        db, background, targets, "签字查看申请被驳回",
        f"理由：{clip(payload.reason)}",
        level="timeSensitive", page="/students",
    )
    return result


# ==================== 签字图本身 ====================


@router.get("/image/{student_id}", summary="取签字图（管理员，或获批的那个班委）")
def get_sign_image(
    student_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """签字图的唯一出口

    判定顺序是有意排的：先看「你是谁」（学生和外部用户直接 403，不让他们知道
    有这么个东西），再看「你有没有权限」，最后才碰文件。管理员短路放行，不需要申请。
    """
    if not is_committee(user):
        raise HTTPException(status_code=403, detail="无权查看")

    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    if not student.sign_photo:
        raise HTTPException(status_code=404, detail="该学生还没有签字图片")

    if not is_admin(user):
        state, _ = _state(db, student.id, user.student_no)
        if state == ST_EXPIRED:
            raise HTTPException(status_code=403, detail="查看签字权限已过期，请重新申请")
        if state != ST_APPROVED:
            raise HTTPException(status_code=403, detail="需先申请查看签字，并经管理员同意")

    # 文件可能在盘上被手工清掉了（换过盘、误删），那时 FileResponse 会 500
    if not photo_path(student.sign_photo).exists():
        raise HTTPException(status_code=404, detail="签字图片文件丢失")

    # 图会被管理员换掉、权限会过期，而地址是固定的 —— 绝不能缓存
    return photo_response(student.sign_photo, cache="no-store")


@router.post("/image/{student_id}", summary="上传/替换签字图（仅管理员）")
def upload_sign_image(
    student_id: int,
    file: UploadFile = File(..., description="签字图片"),
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """管理员传签字图。**前端编辑弹窗里不显示这张图**，只显示「已上传 / 未上传」

    落盘顺序照项目既有约定：新文件先写盘 → 写库 → 提交成功后才删旧文件。任何一步
    失败，库里那行指向的文件都还在（宁可留一个没人引用的孤儿文件，也不能让档案
    指向一张不存在的图）。

    换图之后**已批准的班委自动看到新图**，旧的有效期不作废 —— 权限是「看这个学生的
    签字」，不是「看这一版签字」。要作废得另说。
    """
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")

    try:
        new_name = save_photo(file)
    except ValueError as e:
        # save_photo 的文案是照照片写的（「照片不能超过 10MB」），签字场景下换成签字
        raise HTTPException(status_code=400, detail=str(e).replace("照片", "签字图片"))

    old_name = student.sign_photo
    student.sign_photo = new_name
    log_operation(
        db, user, "上传签字图片",
        target=f"{student.student_no} {student.name}",
        detail="替换了原有签字" if old_name else "",
        ip=ip,
        target_student_nos=[student.student_no],
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        # 数据库回滚了，刚落的这张新图成了孤儿：占磁盘但没人引用，删掉
        remove_photo(new_name)
        raise

    if old_name and old_name != new_name:
        remove_photo(old_name)
    return {"message": "签字图片已上传"}


@router.delete("/image/{student_id}", summary="删除签字图（仅管理员）")
def delete_sign_image(
    student_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    old_name = student.sign_photo
    if not old_name:
        return {"message": "该学生本来就没有签字图片"}

    student.sign_photo = None
    log_operation(
        db, user, "删除签字图片",
        target=f"{student.student_no} {student.name}",
        ip=ip,
        target_student_nos=[student.student_no],
    )
    db.commit()
    # 提交成功后才删文件（失败时库里还指着它）
    remove_photo(old_name)
    # 已批准的申请不用作废：没有图可取，取图接口自然 404
    return {"message": "签字图片已删除"}
