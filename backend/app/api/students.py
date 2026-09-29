import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import ChangeRequest, LeaveRequest, PushSubscription, Student, User
from ..schemas import (
    StudentResponse,
    StudentListResponse,
    StudentCreate,
    StudentCreateResponse,
    StudentUpdate,
    RollCallLogRequest,
    BatchDeleteRequest,
    student_response,
)
from ..services import (
    get_student,
    get_student_by_no,
    get_students,
    get_statistics,
    get_filter_options,
    create_account_for,
    create_student,
    update_student,
    delete_student,
    log_operation,
)
from ..utils.media_type import guess_media_type
from ..services.student_import_service import (
    parse_excel,
    save_preview,
    load_preview,
    import_students,
    cleanup_expired_previews,
)
from ..schemas import (
    ImportPreviewResponse,
    ImportConfirmRequest,
    ImportResultResponse,
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

# 上传学生照片：后缀白名单 + UUID 文件名，与域外账号头像、请假证明的做法一致
ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB，手机拍的实地采集照片也不会更大
# 前端传的类型 → 列名。两种照片各占一列，取法统一走 _photo_field
PHOTO_FIELDS = {"gaokao": "gaokao_photo", "on_site": "on_site_photo"}


def _photo_field(photo_type: str) -> str:
    """把前端传的 type 映射成列名，非法值直接拒绝"""
    field = PHOTO_FIELDS.get(photo_type)
    if not field:
        raise HTTPException(status_code=400, detail="照片类型只能是 gaokao 或 on_site")
    return field


def _save_photo(file: UploadFile) -> str:
    """把上传的照片写到磁盘，返回裸文件名（库里只存文件名，不存路径）"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        allowed = " / ".join(sorted(e.lstrip(".") for e in ALLOWED_PHOTO_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"照片只支持 {allowed} 格式")

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传的文件是空的")
    if len(content) > MAX_PHOTO_SIZE:
        raise HTTPException(status_code=400, detail="照片不能超过 10MB")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    (PHOTO_DIR / safe_name).write_bytes(content)
    return safe_name


def _remove_photo(file_name: str | None) -> None:
    """删照片文件。文件已经不在了也不报错（手工清理过、换过盘都可能）"""
    if not file_name:
        return
    try:
        (PHOTO_DIR / os.path.basename(file_name)).unlink(missing_ok=True)
    except OSError:
        pass


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
    if not student:
        # 域外账号没有学生记录，头像走 /api/auth/avatar，这里直接说没有
        raise HTTPException(status_code=404, detail="照片不存在")
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
    # 版本号：只用于让浏览器别拿缓存里的旧图，后端不用（换照片后文件名会变）
    v: str = "",
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

    # 照片是在 <img> 里内联显示的（StudentList.vue），类型会真的被用上。
    # 这里原先是「非 png 一律当 jpeg」，而上传白名单里还有 gif / bmp / webp ——
    # 那三种被标成 image/jpeg。浏览器嗅探一般能救回来，但类型本来就不该错，
    # 统一交给 guess_media_type（它认识白名单里的全部后缀）
    return FileResponse(str(file_path), media_type=guess_media_type(file_path.name))


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


@router.post("", response_model=StudentCreateResponse, summary="新增学生（仅管理员）")
def create_student_api(
    student: StudentCreate,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """新增学生，并同步给他开一个登录账号

    密码规则与批量建号（`scripts/init_users.py`）完全一致，共用 `default_password`：
    身份证号后 6 位；还没有身份证号的新生（刚入学常见）退化成学号后 6 位 ——
    那种情况下接口会把明文回带，因为学号后 6 位本来就不是秘密，回带是为了让
    管理员知道要单独提醒谁去改密。账号建成即带「首次登录必须改密」标记。

    注意：管理员事后补录身份证号**不会**改动已设的密码 —— 密码只在建号、
    重置这两个时点确定，避免改个资料就把人的密码悄悄换掉。
    """
    student.student_no = (student.student_no or "").strip()
    student.name = (student.name or "").strip()
    if not student.student_no or not student.name:
        raise HTTPException(status_code=400, detail="学号和姓名不能为空")
    if get_student_by_no(db, student.student_no):
        raise HTTPException(status_code=400, detail="学号已存在")
    # 域外账号可能正占着这个登录名，那会建出一个重名账号
    if db.query(User).filter(User.student_no == student.student_no).first():
        raise HTTPException(status_code=400, detail="该学号已被域外账号占用，请先处理那个账号")

    # 学生和账号在同一个事务里提交，不会出现「学生建好了、账号没建上」
    created = create_student(db, student, commit=False)
    password, is_fallback = create_account_for(db, created)
    log_operation(
        db, user, "新增学生", target=f"{created.student_no} {created.name}",
        detail="已开通登录账号" + ("（无身份证号，密码为学号后6位）" if is_fallback else ""),
        ip=ip,
    )
    db.commit()
    return StudentCreateResponse(
        message="新增成功，登录账号已开通，首次登录需修改密码",
        student=student_response(created, user.role or "student"),
        password=password if is_fallback else None,
        fallback=is_fallback,
    )


@router.put("/{student_id}", response_model=StudentResponse, summary="更新学生信息")
def update_student_api(
    student_id: int,
    student: StudentUpdate,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """管理员可改所有字段；班委只能改备注，其余的字段静静忽略（不是报错）"""
    current = get_student(db, student_id)
    if not current:
        raise HTTPException(status_code=404, detail="学生不存在")

    # 学号就是登录账号：改了它，这个学生立刻登不上，请假/反馈里存的学号也对不上号。
    # 前端那个输入框是灰的，这里是防手敲和防旧版前端
    if student.student_no and student.student_no != current.student_no:
        raise HTTPException(status_code=400, detail="学号不能修改；确实要换号，请删除后重新新增")

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
    """删除学生，连同他的登录账号和照片文件一起清掉

    两道闸：
    1. 不能删当前登录的账号 —— 管理员本人也是学生，删了就没人管这个系统了
    2. 还有待审核的请假 / 信息修改申请时拒绝 —— 否则班委点「通过」会撞上
       「学生不存在」，那些待办也没法收尾了

    已审核过的请假、反馈、修改申请**原样保留**：它们存的是姓名学号的快照，
    不依赖学生表，属于历史记录，不该因为删人而消失。
    """
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    if student.student_no == user.student_no:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号")

    pending = []
    for model, label in ((LeaveRequest, "待审核的请假申请"), (ChangeRequest, "待审核的信息修改申请")):
        n = (
            db.query(model)
            .filter(model.student_no == student.student_no, model.status == "pending")
            .count()
        )
        if n:
            pending.append(f"{n} 条{label}")
    if pending:
        raise HTTPException(
            status_code=400,
            detail="该生还有" + "、".join(pending) + "，请先在「审核审批」里处理完再删除",
        )

    # 先取出后面要用的值：删除并 commit 之后再访问属性会报 ObjectDeletedError
    target = f"{student.student_no} {student.name}"
    photo_names = [student.gaokao_photo, student.on_site_photo]

    # 账号和推送订阅跟着学生走：人没了就别再留着账号，也别再往下推
    db.query(PushSubscription).filter(PushSubscription.student_no == student.student_no).delete()
    db.query(User).filter(User.student_no == student.student_no).delete()
    delete_student(db, student_id, commit=False)
    log_operation(db, user, "删除学生", target=target, detail="已注销登录账号", ip=ip)
    db.commit()

    # 提交成功后再删照片文件，中途失败也不会两头空
    for name in photo_names:
        _remove_photo(name)
    return {"message": "删除成功"}


@router.post("/{student_id}/photo", summary="上传/替换学生照片（仅管理员）")
def upload_student_photo(
    student_id: int,
    file: UploadFile = File(..., description="照片文件"),
    type: str = Query("gaokao", description="gaokao=高考照片, on_site=实地采集"),
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """传新照片就换掉旧的；旧文件在提交成功之后才删"""
    field = _photo_field(type)
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")

    old_name = getattr(student, field)
    new_name = _save_photo(file)
    setattr(student, field, new_name)
    log_operation(
        db, user, "更新学生照片", target=f"{student.student_no} {student.name}",
        detail="高考照片" if type == "gaokao" else "实地采集照片", ip=ip,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        _remove_photo(new_name)
        raise
    # 只有真的换了才删旧文件：文件名变了，旧图不会再被任何地方引用
    _remove_photo(old_name)
    return {"message": "照片已更新", "photo": new_name}


@router.delete("/{student_id}/photo", summary="删除学生照片（仅管理员）")
def delete_student_photo(
    student_id: int,
    type: str = Query("gaokao", description="gaokao=高考照片, on_site=实地采集"),
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    field = _photo_field(type)
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")

    old_name = getattr(student, field)
    if not old_name:
        return {"message": "本来就没有照片"}

    setattr(student, field, None)
    log_operation(
        db, user, "删除学生照片", target=f"{student.student_no} {student.name}",
        detail="高考照片" if type == "gaokao" else "实地采集照片", ip=ip,
    )
    db.commit()
    _remove_photo(old_name)
    return {"message": "照片已删除"}



# ---------- Excel 批量导入（仅管理员） ----------

# 单文件大小上限（跟通知附件取同一个值：20MB）
# nginx 的 client_max_body_size 是 70MB，这里 20MB 在它之内
_MAX_IMPORT_SIZE = 20 * 1024 * 1024
_ALLOWED_IMPORT_EXT = {".xlsx"}


@router.post("/import/preview", response_model=ImportPreviewResponse,
             summary="解析 Excel 并预览（仅管理员，不写库）")
async def import_preview(
    file: UploadFile = File(..., description="Excel 文件"),
    sheet_name: str | None = Query(None, description="工作表名，留空自动选「全部信息」或第一张"),
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    """上传 Excel，解析后返回预览统计（不写库、不写照片文件）

    返回里带一个 token，确认导入时再传回来。token 对应服务端临时文件，10 分钟过期。
    """
    # 扩展名校验
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_IMPORT_EXT:
        allowed = " / ".join(sorted(e.lstrip(".") for e in _ALLOWED_IMPORT_EXT))
        raise HTTPException(status_code=400, detail=f"只支持 {allowed} 格式")

    # 大小校验（先全读进来，Excel 不会太大）
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件不能为空")
    if len(content) > _MAX_IMPORT_SIZE:
        raise HTTPException(status_code=400, detail=f"文件不能超过 {_MAX_IMPORT_SIZE // 1024 // 1024}MB")

    try:
        preview = parse_excel(content, sheet_name=sheet_name, db=db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Excel 格式损坏之类的
        raise HTTPException(status_code=400, detail=f"解析失败：{e}")

    # 把预览存成临时文件，返回 token
    token = save_preview(preview)

    result = preview.to_public()
    result["token"] = token
    return ImportPreviewResponse(**result)


@router.post("/import/preview/token", response_model=ImportPreviewResponse,
             summary="用 token 重新取预览（仅管理员）", include_in_schema=False)
def import_preview_by_token(
    token: str = Query(..., description="预览令牌"),
    _: User = Depends(admin_required),
):
    """前端切换工作表后，或者想再看一眼预览时，调这个不用重新上传。"""
    preview = load_preview(token)
    if not preview:
        raise HTTPException(status_code=404, detail="预览已过期或不存在，请重新上传")
    return ImportPreviewResponse(**preview.to_public())


@router.post("/import", response_model=ImportResultResponse,
             summary="确认导入（仅管理员）")
def import_excel_confirm(
    body: ImportConfirmRequest,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """根据预览令牌，真正把数据写入数据库

    覆盖规则：学号已存在的学生，只更新 students 表字段，不动账号密码/角色/冻结状态/推送订阅。
    学号被域外账号占用的行，在预览阶段就跳过了，不会到这里。
    """
    preview = load_preview(body.token)
    if not preview:
        raise HTTPException(status_code=404, detail="预览已过期或不存在，请重新上传")

    try:
        result = import_students(db, preview, user, ip)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败：{e}")
    finally:
        # 不管成功失败，用完就清掉预览缓存
        try:
            from pathlib import Path as _P
            import tempfile as _T
            (_P(_T.gettempdir()) / "class-oa-import-preview" / f"preview_{body.token}.json").unlink(missing_ok=True)
        except Exception:
            pass

    message = (
        f"导入完成：新增 {result['created']} 人，"
        f"覆盖 {result['updated']} 人，"
        f"跳过 {result['skipped']} 行"
    )
    return ImportResultResponse(
        created=result["created"],
        updated=result["updated"],
        skipped=result["skipped"],
        warnings=result["warnings"],
        message=message,
    )


@router.post("/batch-delete", summary="批量删除学生（仅管理员）")
def delete_students_batch(
    data: BatchDeleteRequest,
    user: User = Depends(admin_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """批量删除学生：能删就删，不能删的返回理由

    逐条判断，互不影响：删自己、有待审核的申请、学生不存在都算失败。
    返回 { success, failed: [{student_no, name, reason}], message }。

    历史记录（已审核的请假/反馈/改信息申请）原样保留，跟单条删除一致。
    """
    ids = list(dict.fromkeys(data.ids))  # 去重，保持顺序
    if not ids:
        raise HTTPException(status_code=400, detail="请先选择要删除的学生")
    if len(ids) > 100:
        raise HTTPException(status_code=400, detail="一次最多删除 100 人")

    students = {s.id: s for s in db.query(Student).filter(Student.id.in_(ids)).all()}

    success_count = 0
    failed_list: list[dict] = []
    deleted_photos: list[str] = []
    deleted_nos: list[str] = []
    deleted_names: list[str] = []

    for sid in ids:
        s = students.get(sid)
        if not s:
            failed_list.append({"student_no": "", "name": "", "reason": "学生不存在"})
            continue

        # 第一道闸：不能删自己
        if s.student_no == user.student_no:
            failed_list.append({
                "student_no": s.student_no, "name": s.name,
                "reason": "不能删除当前登录的账号",
            })
            continue

        # 第二道闸：有待审核的请假 / 信息修改申请
        pending = []
        for model, label in (
            (LeaveRequest, "待审核请假"),
            (ChangeRequest, "待审核信息修改"),
        ):
            n = (
                db.query(model)
                .filter(model.student_no == s.student_no, model.status == "pending")
                .count()
            )
            if n:
                pending.append(f"{n} 条{label}")
        if pending:
            failed_list.append({
                "student_no": s.student_no, "name": s.name,
                "reason": "、".join(pending),
            })
            continue

        # 收集照片文件名，commit 成功后再删文件
        if s.gaokao_photo:
            deleted_photos.append(s.gaokao_photo)
        if s.on_site_photo:
            deleted_photos.append(s.on_site_photo)
        deleted_nos.append(s.student_no)
        deleted_names.append(s.name)

        # 删账号、推送订阅、学生行
        db.query(PushSubscription).filter(PushSubscription.student_no == s.student_no).delete()
        db.query(User).filter(User.student_no == s.student_no).delete()
        db.delete(s)
        success_count += 1

    # 记一条操作日志（只覆盖成功删除的人）
    if deleted_nos:
        target = f"{deleted_nos[0]} {deleted_names[0]} 等{len(deleted_nos)}人"
        log_operation(
            db, user, "删除学生",
            target=target,
            detail=(
                f"批量删除 {len(deleted_nos)} 人"
                + (f"，{len(failed_list)} 人未删除" if failed_list else "")
            ),
            ip=ip,
            target_student_nos=deleted_nos,
        )

    db.commit()

    # 提交成功后删照片文件
    for name in deleted_photos:
        _remove_photo(name)

    return {
        "success": success_count,
        "failed": failed_list,
        "message": (
            f"已删除 {success_count} 人"
            + (f"，{len(failed_list)} 人未删除" if failed_list else "")
        ),
    }
