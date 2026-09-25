"""系统管理：仅管理员可用（账号角色、重置密码、资料下载、操作日志）"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import OperationLog, Resource, Student, User
from ..schemas import (
    AdminUserResponse,
    OperationLogListResponse,
    ResetPasswordResponse,
    RoleUpdateRequest,
)
from ..services import (
    add_resource,
    default_password,
    delete_resource,
    list_all_resources,
    log_operation,
    reorder_category,
    update_resource,
)
from ..utils.security import hash_password
from .deps import admin_required, get_client_ip

router = APIRouter(prefix="/api/admin", tags=["系统管理"])

ROLES = ("student", "committee", "admin")
ROLE_LABELS = {"student": "普通学生", "committee": "班委", "admin": "管理员"}


@router.get("/users", response_model=list[AdminUserResponse], summary="账号列表")
def list_users(_: User = Depends(admin_required), db: Session = Depends(get_db)):
    rows = (
        db.query(User, Student)
        .outerjoin(Student, Student.student_no == User.student_no)
        .order_by(User.student_no)
        .all()
    )
    return [
        AdminUserResponse(
            student_no=user.student_no,
            name=student.name if student else user.student_no,
            role=user.role or "student",
            must_change_password=user.must_change_password,
            has_id_card=bool(student and (student.id_card or "").strip()),
            last_login_at=user.last_login_at,
            last_login_ip=user.last_login_ip,
        )
        for user, student in rows
    ]


@router.put("/users/{student_no}/role", summary="设置角色")
def set_role(
    student_no: str,
    payload: RoleUpdateRequest,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    if payload.role not in ROLES:
        raise HTTPException(
            status_code=400,
            detail="角色只能是 " + " / ".join(f"{r}（{ROLE_LABELS[r]}）" for r in ROLES),
        )
    target = db.query(User).filter(User.student_no == student_no).first()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    if target.role == payload.role:
        return {"message": "角色未变化"}

    old_label = ROLE_LABELS.get(target.role or "student", target.role)
    target.role = payload.role
    log_operation(
        db, user, "修改角色", target=student_no,
        detail=f"{old_label} → {ROLE_LABELS[payload.role]}",
        ip=ip,
    )
    db.commit()
    return {"message": "角色已更新"}


@router.post(
    "/users/{student_no}/reset-password",
    response_model=ResetPasswordResponse,
    summary="重置为原始密码",
)
def reset_password(
    student_no: str,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """重置成「身份证号后 6 位」并重新要求首次登录改密

    学生若没有身份证号，则退回学号后 6 位 —— 那种情况下接口会把密码回带给管理员，
    好让管理员转告学生（学号后 6 位本来就不是秘密）。
    """
    target = db.query(User).filter(User.student_no == student_no).first()
    student = db.query(Student).filter(Student.student_no == student_no).first()
    if not target or not student:
        raise HTTPException(status_code=404, detail="账号不存在")

    password, is_fallback = default_password(student)
    new_hash, new_salt = hash_password(password)
    target.password_hash = new_hash
    target.password_salt = new_salt
    target.must_change_password = True  # 重置后第一次登录仍要改密码

    log_operation(
        db, user, "重置密码", target=f"{student_no} {student.name}",
        detail="无身份证号，重置为学号后 6 位" if is_fallback else "重置为身份证号后 6 位",
        ip=ip,
    )
    db.commit()
    return ResetPasswordResponse(
        message="已重置为原始密码，该生下次登录需修改密码",
        password=password if is_fallback else None,
        fallback=is_fallback,
    )


@router.get("/logs", response_model=OperationLogListResponse, summary="操作日志")
def list_logs(
    _: User = Depends(admin_required),
    operator: str | None = Query(None, description="按操作人姓名或学号模糊搜索"),
    action: str | None = Query(None, description="按动作模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(OperationLog)
    if operator:
        query = query.filter(
            or_(
                OperationLog.operator_name.like(f"%{operator}%"),
                OperationLog.operator_no.like(f"%{operator}%"),
            )
        )
    if action:
        query = query.filter(OperationLog.action.like(f"%{action}%"))

    total = query.count()
    items = (
        query.order_by(OperationLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": items}


@router.delete("/logs", summary="清空操作日志")
def clear_logs(_: User = Depends(admin_required), db: Session = Depends(get_db)):
    """删除全部操作日志

    刻意不记「谁清空了日志」—— 清空就是归零，留一条尾巴反而让人以为没清干净。
    代价是清空这个动作本身也不可追溯，所以前端加了二次确认。
    """
    deleted = db.query(OperationLog).delete()
    db.commit()
    return {"message": f"已清空 {deleted} 条日志", "deleted": deleted}


# ==================== 资料下载管理 ====================
# 只有管理员能改资料清单；普通用户读的接口在 resources.py 里。


@router.get("/resources", summary="资料列表（管理员用）")
def admin_list_resources(
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """返回所有资料条目，不分组，按分类+排序。
    管理界面用，方便做拖拽排序和增删改。
    """
    rows = list_all_resources(db)
    return [
        {
            "id": r.id,
            "name": r.name,
            "file_name": r.file_name,
            "original_name": r.original_name,
            "category": r.category,
            "sort_order": r.sort_order,
            "size": 0,  # 前端暂时不用
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/resources", summary="上传新资料")
async def upload_resource(
    user: User = Depends(admin_required),
    name: str = Form(..., min_length=1, max_length=200, description="显示名称"),
    category: str = Form(..., min_length=1, max_length=50, description="分类名称"),
    file: UploadFile = File(..., description="资料文件"),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """上传一个新资料到指定分类

    文件存到 data/downloads/，文件名用 UUID 前缀（防路径穿越和重名覆盖）。
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件不能为空")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 50MB")

    original = file.filename or name
    row = add_resource(db, name, category, content, original)
    log_operation(
        db, user, "上传资料", target=f"{category}/{name}",
        detail=f"文件：{original}，{len(content)} 字节",
        ip=ip,
    )
    db.commit()
    db.refresh(row)
    return {"message": "上传成功", "id": row.id}


@router.put("/resources/{resource_id}", summary="修改资料信息")
def update_resource_api(
    resource_id: int,
    user: User = Depends(admin_required),
    name: str = Form(None, max_length=200, description="新的显示名称"),
    category: str = Form(None, max_length=50, description="新的分类"),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """只改名称和/或分类，不改文件本身"""
    if name is None and category is None:
        raise HTTPException(status_code=400, detail="至少改一项")

    row = update_resource(db, resource_id, name=name, category=category)
    if not row:
        raise HTTPException(status_code=404, detail="资料不存在")

    detail_parts = []
    if name is not None:
        detail_parts.append(f"名称→{name}")
    if category is not None:
        detail_parts.append(f"分类→{category}")
    log_operation(
        db, user, "修改资料", target=f"{row.category}/{row.name}",
        detail="，".join(detail_parts),
        ip=ip,
    )
    db.commit()
    return {"message": "已更新"}


@router.put("/resources/reorder/{category}", summary="重排某分类下的资料顺序")
def reorder_resources(
    category: str,
    order: list[int],
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """按给定的 ID 列表重排某个分类内的资料顺序"""
    reorder_category(db, category, order)
    log_operation(
        db, user, "重排资料", target=category,
        detail=f"调整 {len(order)} 项的顺序",
        ip=ip,
    )
    db.commit()
    return {"message": "已更新顺序"}


@router.delete("/resources/{resource_id}", summary="删除资料")
def remove_resource(
    resource_id: int,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """同时删除数据库记录和磁盘文件。不可恢复。"""
    row = db.query(Resource).filter(Resource.id == resource_id).first()
    target_label = f"{row.category}/{row.name}" if row else f"id={resource_id}"

    ok = delete_resource(db, resource_id)
    if not ok:
        raise HTTPException(status_code=404, detail="资料不存在")

    log_operation(
        db, user, "删除资料", target=target_label,
        ip=ip,
    )
    db.commit()
    return {"message": "已删除"}
