"""成绩管理：班委传 Excel 录一次成绩，学生在「我的信息」里按测试查

四条贯穿全模块的口径：

1. **权限是纯角色门禁**：班委及以上看全部、改全部，学生只能看自己的。
   查不到的测试回 404，但那是「真没有」，不是拿 404 遮越权 —— 角色不够就是
   403（`committee_required` 的既有分工，同 api/attendance.py）。
2. **上传分两步**：先预览（不写库）再确认（写库）。预览里认不出的人和填错的格子
   都摆出来给班委看，**但不阻断入库** —— 一格填错只丢那一格，「一列学号录错就整班上不了分」
   是比漏一格严重得多的事故。
3. **写库只有一处**：录入走 services.grade_service.import_grade，补格子走 set_cell，
   接口只做校验、拼中文错误、发通知、记日志。
4. **通知只在整场录入后发一次**，且只发给这次真有成绩记录的人。补录一个格子、
   加一科都不发 —— 否则班里随便补个人就骚扰全班一遍。
"""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GradeItem, GradeSubject, GradeTest, Student, User
from ..schemas import (
    GradeDetailResponse,
    GradeImportConfirm,
    GradeImportResultResponse,
    GradeListResponse,
    GradePreviewResponse,
    GradeScoreIn,
    GradeScoreResponse,
    GradeSubjectCreate,
    GradeSubjectResponse,
    GradeTestUpdate,
    MyGradeItem,
)
from ..services import log_operation, notify, recipients
from ..services.grade_service import (
    MAX_SUBJECTS,
    detail,
    drop_preview,
    import_grade,
    list_items,
    load_preview,
    my_grades,
    parse_grade_excel,
    save_preview,
    set_cell,
    subjects_of,
)
from .deps import committee_required, get_client_ip, get_current_student

router = APIRouter(prefix="/api/grades", tags=["成绩"])

# 前端固定传 20（同站内信、考勤），这个上限只是防手工构造请求一次拉全表
MAX_PAGE_SIZE = 100

# 上传文件的上限与扩展名，跟学生导入同一套值（nginx 的 client_max_body_size 是 70MB）
_MAX_IMPORT_SIZE = 20 * 1024 * 1024
_ALLOWED_IMPORT_EXT = {".xlsx"}


# ---------- 取测试 ----------

def _get_test(db: Session, test_id: int) -> GradeTest:
    test = db.query(GradeTest).filter(GradeTest.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="成绩记录不存在")
    return test


def _get_subject(db: Session, test_id: int, subject_id: int) -> GradeSubject:
    """取本次测试下的一科。**必须带 test_id 一起过滤**

    只按 subject_id 查的话，在 A 测试的明细里传 B 测试的科目 id 也能写进去，
    库里就出现「这条成绩属于别的测试的科目」这种对不上的数据。
    """
    subject = (
        db.query(GradeSubject)
        .filter(GradeSubject.id == subject_id, GradeSubject.test_id == test_id)
        .first()
    )
    if not subject:
        raise HTTPException(status_code=404, detail="科目不存在")
    return subject


# ---------- 上传：先预览，再确认 ----------
# 固定路径必须定义在 /{test_id} 之前，否则 /mine 会被当成 test_id 解析直接 422
# （同 api/attendance.py 里那条注释所指的坑）

@router.post("/import/preview", response_model=GradePreviewResponse,
             summary="解析成绩 Excel 并预览（班委及以上，不写库）")
async def import_preview(
    file: UploadFile = File(..., description="Excel 文件"),
    sheet_name: str | None = Query(None, description="工作表名，留空用第一张"),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """上传 Excel，返回识别结果与逐行结论（不写库，10 分钟内有效）

    认不出的人、填错的格子都在返回里；确认入库时不再重新解析。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_IMPORT_EXT:
        allowed = " / ".join(sorted(e.lstrip(".") for e in _ALLOWED_IMPORT_EXT))
        raise HTTPException(status_code=400, detail=f"只支持 {allowed} 格式")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件不能为空")
    if len(content) > _MAX_IMPORT_SIZE:
        raise HTTPException(
            status_code=400, detail=f"文件不能超过 {_MAX_IMPORT_SIZE // 1024 // 1024}MB"
        )

    try:
        preview = parse_grade_excel(content, sheet_name=sheet_name, db=db)
    except ValueError as e:
        # 缺「学号」列、没有科目列、行数超限这类：文案是给人看的，直接透出去
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Excel 损坏之类的
        raise HTTPException(status_code=400, detail=f"解析失败：{e}")

    return GradePreviewResponse(token=save_preview(preview), **preview.to_public())


@router.post("/import/preview/token", response_model=GradePreviewResponse,
             summary="用 token 重新取预览（班委及以上）", include_in_schema=False)
def import_preview_by_token(
    token: str = Query(..., description="预览令牌"),
    _: User = Depends(committee_required),
):
    """班委在确认页想回头再看一眼预览时调它，不用重新上传"""
    preview = load_preview(token)
    if not preview:
        raise HTTPException(status_code=404, detail="预览已过期或不存在，请重新上传")
    return GradePreviewResponse(token=token, **preview.to_public())


@router.post("/import", response_model=GradeImportResultResponse,
             summary="确认录入成绩（班委及以上）")
def import_confirm(
    body: GradeImportConfirm,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """按预览令牌把成绩写进库，然后给有成绩的学生发通知

    subjects 是**保留**的科目名（勾掉的列连数据一起不要）：必须是预览里出现过的，
    瞎传一个名字会让那一列静默变成 0 条成绩。
    """
    preview = load_preview(body.token)
    if not preview:
        raise HTTPException(status_code=404, detail="预览已过期或不存在，请重新上传")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写测试名称")

    unknown = [text for text in body.subjects if text not in preview.column_names]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"科目「{unknown[0]}」不在上传的表格里，请重新上传"
        )
    # 同一场测试里科目名唯一（grade_subjects 上有唯一约束）。正常界面出不来重复项，
    # 但构造请求能传进来 —— 不拦的话就是一条 IntegrityError 变成 500，
    # 而约束的落点本该是一句中文提示
    if len(set(body.subjects)) != len(body.subjects):
        repeated = next(t for t in body.subjects if body.subjects.count(t) > 1)
        raise HTTPException(status_code=400, detail=f"科目「{repeated}」重复了，请重新选择")
    if not preview.matched_count:
        raise HTTPException(status_code=400, detail="没有一行学号能对上班级名单，请检查表格")

    try:
        result = import_grade(
            db,
            preview,
            name=name,
            tested_at=body.tested_at,
            remark=body.remark.strip(),
            subjects=body.subjects,
            operator=user,
            ip=ip,
        )
    finally:
        # 用完就删，不等 TTL；失败也一样删（同 api/students.py 的导入）
        drop_preview(body.token)

    # 同名同日期多半是「上传了两次」——提醒一句，但不拦：同一天两场同名小测是合理的
    warnings = list(preview.warnings)
    same = (
        db.query(GradeTest)
        .filter(
            GradeTest.id != result["test_id"],
            GradeTest.name == name,
            GradeTest.tested_at == body.tested_at,
        )
        .count()
    )
    if same:
        warnings.append(f"之前已经有一场同名的「{name}」，请确认不是重复录入")

    # 通知放在 commit 之后（import_grade 里已提交）：notify 的站内信会自己 commit，
    # 不能让它替我们提交「建测试」那笔半截事务（同 api/polls.py）
    if body.notify:
        nos = [
            row[0]
            for row in db.query(GradeItem.student_no)
            .filter(GradeItem.test_id == result["test_id"])
            .distinct()
            .all()
        ]
        notice_body = f"共 {result['subject_count']} 科，{body.tested_at:%Y-%m-%d}"
        if body.remark.strip():
            notice_body += f"（{body.remark.strip()}）"
        for student_no in nos:
            notify(
                db,
                background,
                # 逐个人调 recipients：范围是任意子集，recipients 没有「批量学号」参数，
                # 要加就得同时改四个渠道服务；几十人的循环更简单（同 api/polls.py）。
                # exclude_no 把录入人自己排除掉 —— 他刚录完
                recipients(db, only_no=student_no, exclude_no=user.student_no),
                f"{name} 成绩已录入",
                notice_body,
                # active 而不是 timeSensitive：成绩不是待办，不该进「待我处理」
                level="active",
                page="/my-info?tab=grades",
            )

    return GradeImportResultResponse(
        **result,
        message=(
            f"录入完成：{result['student_count']} 人 {result['subject_count']} 科，"
            f"共 {result['cell_count']} 条成绩"
            + (f"，跳过 {result['skipped']} 行" if result["skipped"] else "")
        ),
        warnings=warnings,
    )


# ---------- 列表与学生自查 ----------

@router.get("", response_model=GradeListResponse, summary="成绩列表（班委及以上）")
def list_grades(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """列表只带两个聚合计数，不带明细（明细走 GET /{test_id}）"""
    query = db.query(GradeTest)
    total = query.count()
    tests = (
        query.order_by(GradeTest.tested_at.desc(), GradeTest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return GradeListResponse(
        total=total, page=page, page_size=page_size, items=list_items(db, tests)
    )


@router.get("/mine", response_model=list[MyGradeItem], summary="我的成绩（学生）")
def my_grades_api(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """只看自己的。**接口里没有任何能带别人学号的参数** —— 越权在形状上就不可能"""
    return my_grades(db, student.student_no)


# ---------- 明细与编辑 ----------

@router.get("/{test_id}", response_model=GradeDetailResponse, summary="成绩明细（班委及以上）")
def get_detail(
    test_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """测试信息 + 科目列表 + 每个学生每格的成绩（每行每科都给键，空串 = 没录）"""
    return detail(db, _get_test(db, test_id))


@router.patch("/{test_id}", response_model=GradeDetailResponse, summary="改测试信息（班委及以上）")
def update_test(
    test_id: int,
    body: GradeTestUpdate,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """名称 / 日期 / 备注，传了才改（明细页改完就地刷新，所以回整个明细）"""
    test = _get_test(db, test_id)
    changes = []

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="测试名称不能为空")
        if name != test.name:
            changes.append(f"名称：{test.name} → {name}")
            test.name = name

    if body.tested_at is not None and body.tested_at != test.tested_at:
        changes.append(f"日期：{test.tested_at} → {body.tested_at}")
        test.tested_at = body.tested_at

    if body.remark is not None and body.remark.strip() != (test.remark or ""):
        changes.append("备注已改")
        test.remark = body.remark.strip()

    # 什么都没变就不写库、不记日志（同考勤改状态那条口径）
    if changes:
        log_operation(
            db, user, action="修改成绩信息",
            target=f"{test.tested_at} {test.name}", detail="；".join(changes), ip=ip,
        )
        db.commit()

    return detail(db, test)


@router.delete("/{test_id}", summary="删除整次测试（班委及以上）")
def delete_test(
    test_id: int,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """删整次测试：明细 → 科目 → 测试，一次提交

    **顺序不能动**：SQLite 默认不开外键约束（database.py 没开 PRAGMA），
    先删父行的话子行就留在库里成了孤儿 —— 谁也删不掉、还占着「录入人数」的聚合。
    同 api/polls.py 删投票的写法（那边也是逐表 delete 再删主表）。
    """
    test = _get_test(db, test_id)
    cells = db.query(GradeItem).filter(GradeItem.test_id == test.id).count()
    people = (
        db.query(GradeItem.student_no).filter(GradeItem.test_id == test.id).distinct().count()
    )
    label = f"{test.tested_at} {test.name}"

    db.query(GradeItem).filter(GradeItem.test_id == test.id).delete(synchronize_session=False)
    db.query(GradeSubject).filter(GradeSubject.test_id == test.id).delete(synchronize_session=False)
    db.delete(test)
    log_operation(
        db, user, action="删除成绩记录", target=label,
        detail=f"{people} 人 {cells} 条成绩", ip=ip,
    )
    db.commit()
    return {"message": "已删除"}


@router.post("/{test_id}/subjects", response_model=GradeSubjectResponse,
             summary="加一科（班委及以上）")
def add_subject(
    test_id: int,
    body: GradeSubjectCreate,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """只建一行科目，格子按需补（新科目下所有人都还没成绩）"""
    test = _get_test(db, test_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="科目名不能为空")

    exists = (
        db.query(GradeSubject)
        .filter(GradeSubject.test_id == test.id, GradeSubject.name == name)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail=f"已经有「{name}」这一科了")
    if len(subjects_of(db, test.id)) >= MAX_SUBJECTS:
        raise HTTPException(status_code=400, detail=f"科目最多 {MAX_SUBJECTS} 个")

    subject = GradeSubject(
        test_id=test.id,
        name=name,
        sort=(db.query(GradeSubject).filter(GradeSubject.test_id == test.id).count()),
    )
    db.add(subject)
    log_operation(
        db, user, action="成绩加科目",
        target=f"{test.tested_at} {test.name}", detail=f"新增「{name}」", ip=ip,
    )
    db.commit()
    return GradeSubjectResponse(id=subject.id, name=subject.name, sort=subject.sort or 0)


@router.delete("/{test_id}/subjects/{subject_id}", summary="删一科（班委及以上）")
def remove_subject(
    test_id: int,
    subject_id: int,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """删一科，连带它下面所有格子（先明细后科目，理由同删整次测试）"""
    test = _get_test(db, test_id)
    subject = _get_subject(db, test_id, subject_id)
    cells = db.query(GradeItem).filter(GradeItem.subject_id == subject.id).count()

    db.query(GradeItem).filter(GradeItem.subject_id == subject.id).delete(
        synchronize_session=False
    )
    db.delete(subject)
    log_operation(
        db, user, action="成绩删科目",
        target=f"{test.tested_at} {test.name}",
        detail=f"删除「{subject.name}」（含 {cells} 条成绩）", ip=ip,
    )
    db.commit()
    return {"message": "已删除"}


def _write_cell(db: Session, test: GradeTest, subject: GradeSubject, student_no: str, value: str):
    """写一个格子；撞上唯一约束就回滚重来一次

    set_cell 是「先查、没有就插」，两个请求同时发现这格没记录时，只有一个插得进去，
    另一个撞 uq_grade_item。同一格快速失焦两次、客户端超时重试、两个人同时补录
    都会走到这儿 —— 回滚后重来这次会查到刚插进去的那行，自然改走 update 分支，
    于是「并发写同一格」的结果是后到的赢，而不是 500。
    """
    try:
        return set_cell(db, test, subject, student_no, value)
    except IntegrityError:
        db.rollback()
        return set_cell(db, test, subject, student_no, value)


@router.put("/{test_id}/scores", response_model=GradeScoreResponse,
            summary="写一个格子（班委及以上）")
def put_score(
    test_id: int,
    body: GradeScoreIn,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """upsert 一个格子：没有记录就新建，清空（空串）就删除

    按 (测试, 科目, 学号) 定位而不是按记录 id —— 这样「补录一个 Excel 里没有的学生」
    才做得成（没有记录也有得写）。值不合法回 400 带一句具体的中文。
    """
    test = _get_test(db, test_id)
    subject = _get_subject(db, test_id, body.subject_id)

    student = db.query(Student).filter(Student.student_no == body.student_no).first()
    if student is not None:
        name = student.name or student.student_no
    else:
        # 名单里没有的人**本场已经有成绩**时放行：学生是物理删除，毕业删档的人
        # 在明细里只剩下 grade_items 上的名字快照，格子照旧得能改（明细页也照样
        # 给他出格子）。但不能凭空造一个新学号 —— 那多半是敲错了，
        # 只会留下一行谁也认不出的成绩
        snapshot = (
            db.query(GradeItem.student_name)
            .filter(GradeItem.test_id == test.id, GradeItem.student_no == body.student_no)
            .first()
        )
        if snapshot is None:
            raise HTTPException(status_code=400, detail="这个学号不在班级名单里")
        name = snapshot[0] or body.student_no

    try:
        item, old, new = _write_cell(db, test, subject, body.student_no, body.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if old != new:
        # 快照名字为空时顺手补全（新建的记录就靠它带名字）
        if item is not None and not item.student_name:
            item.student_name = name
        log_operation(
            db, user, action="修改成绩",
            target=f"{body.student_no} {name}".strip(),
            detail=f"{test.name} {subject.name}：{old or '空'} → {new or '空'}", ip=ip,
        )
        db.commit()
    # 值没变就什么都不写：不 commit、不记日志（同考勤改状态那条口径）

    return GradeScoreResponse(student_no=body.student_no, subject_id=subject.id, value=new)
