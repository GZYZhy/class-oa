import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import Student, User
from ..schemas import (
    StudentResponse,
    StudentListResponse,
    StudentCreate,
    StudentUpdate,
    RollCallLogRequest,
    student_response,
)
from ..services import (
    get_student,
    get_student_by_no,
    get_students,
    get_statistics,
    get_filter_options,
    create_student,
    update_student,
    delete_student,
    log_operation,
)
from .deps import (
    get_current_user,
    get_current_student,
    committee_required,
    admin_required,
    is_committee,
    get_client_ip,
)

router = APIRouter(prefix="/api/students", tags=["学生信息"])

# 照片目录
PHOTO_DIR = BASE_DIR / "data" / "photos"

# 班委能改的字段：只有备注。姓名、学号、身份证号这些只能由管理员改
COMMITTEE_EDITABLE_FIELDS = {"remark"}


def _ensure_can_view(user: User, student: Student) -> None:
    """班委及以上能看任何人的信息，普通学生只能看自己"""
    if not is_committee(user) and student.student_no != user.student_no:
        raise HTTPException(status_code=403, detail="只能查看自己的信息")


@router.get("", response_model=StudentListResponse, summary="学生列表（支持筛选、搜索、排序）")
def list_students(
    _: User = Depends(committee_required),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    keyword: str | None = None,
    gender: str | None = None,
    ethnicity: str | None = None,
    political_status: str | None = None,
    hometown: str | None = None,
    dormitory: str | None = None,
    class_position: str | None = None,
    league_position: str | None = None,
    is_poor: str | None = None,
    school_status: str | None = None,
    birthday_days: int | None = Query(None, ge=1, le=365),
    sort_by: str | None = None,
    sort_order: str = Query("asc"),
    db: Session = Depends(get_db),
):
    items, total = get_students(
        db,
        skip=(page - 1) * page_size,
        limit=page_size,
        keyword=keyword,
        gender=gender,
        ethnicity=ethnicity,
        political_status=political_status,
        hometown=hometown,
        dormitory=dormitory,
        class_position=class_position,
        league_position=league_position,
        is_poor=is_poor,
        school_status=school_status,
        birthday_days=birthday_days,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {"total": total, "items": items}


@router.get("/statistics", summary="统计数据")
def statistics(_: User = Depends(committee_required), db: Session = Depends(get_db)):
    return get_statistics(db)


@router.get("/filter-options", summary="筛选下拉选项")
def filter_options(_: User = Depends(committee_required), db: Session = Depends(get_db)):
    return get_filter_options(db)


# 和 /statistics、/me 一样属于固定路径，必须定义在 /{student_id} 之前
@router.post("/roll-call", summary="上报点名结果（写操作日志）")
def log_roll_call(
    data: RollCallLogRequest,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """点名结束后记一条日志

    权限沿用列表接口的 committee_required：看得到名单的人才点得了名。
    点名结果不落库，只留痕 —— 这几行日志就是全部的留存。
    """
    names = "、".join(f"{a.name}({a.student_no})" for a in data.absent)
    log_operation(
        db,
        user,
        action="点名",
        target=data.scope,
        # log_operation 内部会把 detail 截断到 500 字，这里不用自己处理
        detail=f"共 {data.total} 人，无应答 {len(data.absent)} 人"
        + (f"：{names}" if names else "（全部到齐）"),
        ip=get_client_ip(request),
    )
    db.commit()
    return {"message": "已记录"}


@router.get("/me/photo", summary="当前用户头像（自己的高考照片）")
def my_photo(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    u: str = "",
):
    """u 参数仅用于前端绕过浏览器缓存（切换账号时 URL 不同），后端不使用"""
    student = (
        db.query(Student).filter(Student.student_no == current_user.student_no).first()
    )
    return _serve_photo(student, "gaokao")


# 注意：/me 必须定义在 /{student_id} 之前，否则会被后者当成学号解析而报 422
@router.get("/me", response_model=StudentResponse, summary="我的信息（当前登录者自己那条）")
def read_my_info(
    user: User = Depends(get_current_user),
    student: Student = Depends(get_current_student),
):
    return student_response(student, user.role or "student")


@router.get("/{student_id}/photo", summary="指定学生照片")
def student_photo(
    student_id: int,
    type: str = Query("gaokao", description="gaokao=高考照片, on_site=实地采集"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    _ensure_can_view(user, student)
    return _serve_photo(student, type)


def _serve_photo(student: Student, photo_type: str) -> FileResponse:
    """返回照片文件；路径只取数据库字段中的文件名，杜绝路径穿越"""
    field = student.gaokao_photo if photo_type == "gaokao" else student.on_site_photo
    if not field:
        raise HTTPException(status_code=404, detail="照片不存在")

    file_path = PHOTO_DIR / os.path.basename(field)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="照片文件丢失")

    media_type = "image/png" if file_path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(str(file_path), media_type=media_type)


@router.get("/{student_id}", response_model=StudentResponse, summary="学生详情")
def read_student(
    student_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    _ensure_can_view(user, student)
    return student_response(student, user.role or "student")


@router.post("", response_model=StudentResponse, summary="新增学生（仅管理员）")
def create_student_api(
    student: StudentCreate,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    if get_student_by_no(db, student.student_no):
        raise HTTPException(status_code=400, detail="学号已存在")
    created = create_student(db, student)
    log_operation(db, user, "新增学生", target=f"{created.student_no} {created.name}", ip=ip)
    db.commit()
    return created


@router.put("/{student_id}", response_model=StudentResponse, summary="更新学生信息")
def update_student_api(
    student_id: int,
    student: StudentUpdate,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """管理员可改所有字段；班委只能改备注，其余的字段静静忽略（不是报错）"""
    allowed = None if user.role == "admin" else COMMITTEE_EDITABLE_FIELDS
    updated = update_student(db, student_id, student, allowed_fields=allowed)
    if not updated:
        raise HTTPException(status_code=404, detail="学生不存在")

    fields = student.model_dump(exclude_unset=True)
    if allowed is not None:
        fields = {k: v for k, v in fields.items() if k in allowed}
    if fields:
        log_operation(
            db, user, "修改学生信息", target=f"{updated.student_no} {updated.name}",
            detail="；".join(f"{k}={v}" for k, v in fields.items()),
            ip=ip,
        )
        db.commit()
    return updated


@router.delete("/{student_id}", summary="删除学生（仅管理员）")
def delete_student_api(
    student_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    # 先取出标识：删除并 commit 后再访问属性会报 ObjectDeletedError
    target = f"{student.student_no} {student.name}"
    delete_student(db, student_id)
    log_operation(db, user, "删除学生", target=target, ip=ip)
    db.commit()
    return {"message": "删除成功"}
