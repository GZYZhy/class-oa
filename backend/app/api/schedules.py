"""我的日程 API

权限模型：
- 普通学生：只能看/建/改/删自己的日程
- 班委及以上：除个人日程外，还可以批量创建（选择目标学生）、导入 Excel、管理批次

严格约束：
- 通知默认关闭，未开启通知的日程一律不推送
- 批量导入的日程写入每个目标学生自己的日程表，不是全局表
"""

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Schedule, ScheduleBatch, Student, User
from ..models.schedule import (
    EDIT_SCOPES,
    REPEAT_NONE,
    REPEAT_TYPES,
    SCOPE_ALL,
    SOURCE_BATCH,
    SOURCE_PERSONAL,
)
from ..schemas import (
    ICalTokenResponse,
    ScheduleBatchResponse,
    ScheduleCreate,
    ScheduleImportConfirm,
    ScheduleImportResultResponse,
    ScheduleImportPreviewResponse,
    ScheduleResponse,
    ScheduleUpdate,
    SemesterInfoResponse,
)
from ..services import log_operation, notify, recipients
from ..services import schedule_service as ss
from ..services import schedule_import_service as sis
from ..services import schedule_ical_service as sics
from .deps import (
    committee_required,
    get_current_student,
    get_current_user,
    is_committee,
)

router = APIRouter(prefix="/api/schedules", tags=["日程"])

# 上传文件大小限制（20MB，同成绩导入）
_MAX_IMPORT_SIZE = 20 * 1024 * 1024
_ALLOWED_IMPORT_EXT = {".xlsx"}


# ---------- 工具函数 ----------

def _check_repeat_type(repeat_type: str) -> str:
    if repeat_type not in REPEAT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"重复类型只能是 {' / '.join(REPEAT_TYPES)}",
        )
    return repeat_type


def _check_scope(scope: str) -> str:
    if scope not in EDIT_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"编辑范围只能是 {' / '.join(EDIT_SCOPES)}",
        )
    return scope


def _validate_times(start_time: datetime, end_time: datetime) -> None:
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")


def _all_day_times(day: date) -> tuple[datetime, datetime]:
    """全天事件的起止时刻：当天 00:00 到 23:59 —— 全天就是不带时刻

    库里现有的全天事件（导入进来的）就是这个形状，iCal 导出也是按 DATE 给的。
    跨天的全天事件一律存成「一天一条」：模型里没有跨天日程这个概念，页面再按
    相邻同标题合回一条（见 Schedule.vue 的 allDayBars）。
    """
    return datetime.combine(day, time(0, 0)), datetime.combine(day, time(23, 59))


# ---------- 个人日程查询 ----------

@router.get("", response_model=list[ScheduleResponse])
def list_schedules(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """查询当前学生在指定日期范围内的日程（已展开重复日程）"""
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    # 限制最多查询 3 个月，防止一次拉太多
    if (end_date - start_date).days > 92:
        raise HTTPException(status_code=400, detail="查询范围不能超过 92 天")

    instances = ss.list_by_range(db, student.id, start_date, end_date)
    return instances


@router.get("/semester", response_model=SemesterInfoResponse)
def get_semester_info(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """学期第 1 周的周一 —— 页面上的「第几周」按它算

    优先取课表导入时写下的 week_start（由表名「第N周」折算，能对上真实学期）；
    老数据没写过这一列，退回「最早那条日程所在周的周一」—— 课表是从第 1 周
    导起的，退出来的正好是同一个基准。个人日程不会比它更早影响判断。

    一条日程都没有时返回空，前端就不显示周次（而不是硬估一个错的）。
    """
    monday = db.query(func.min(Schedule.week_start)).filter(
        Schedule.student_id == student.id,
    ).scalar()
    if not monday:
        earliest = db.query(func.min(Schedule.start_time)).filter(
            Schedule.student_id == student.id,
        ).scalar()
        if earliest:
            d = earliest.date()
            monday = d - timedelta(days=d.weekday())
    return {"week_start": monday}


@router.get("/item/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
    schedule_id: int,
    instance_date: date = Query(..., description="实例日期（重复日程用）"),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """获取单条日程详情"""
    tpl = ss.get_template(db, schedule_id, student.id)
    if not tpl:
        raise HTTPException(status_code=404, detail="日程不存在")
    # share_count 得自己算一遍：_to_instance 的默认值是 1，漏算的话这条日程
    # 在详情里永远显示成「只有自己」，拿着它去编辑就没有「改谁的表」这一档
    counts = ss.share_counts(db, [tpl], student.id)
    return ss._to_instance(tpl, instance_date, counts.get(tpl.source_series_id, 1))


# ---------- 新建日程 ----------

@router.post("", response_model=ScheduleResponse)
def create_schedule(
    data: ScheduleCreate,
    background: BackgroundTasks,
    student: Student = Depends(get_current_student),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新建日程

    普通学生：只能创建自己的日程（target_* 字段被忽略）
    班委及以上：可通过 target_all / target_student_ids 批量创建
    """
    _check_repeat_type(data.repeat_type)
    # 重复日程依赖 repeat_end_date 展开，缺了会在展开/删除时静默出错，强制必填。
    # 前端表单已拦一道，这里兜底挡掉直接调接口的路径。
    if data.repeat_type != REPEAT_NONE and not data.repeat_end_date:
        raise HTTPException(status_code=400, detail="重复日程必须设置结束日期")

    sched_data = data.model_dump(
        exclude={"target_all", "target_student_ids", "share_from"}
    )
    if sched_data["all_day"]:
        # 全天事件不给时刻：表单里干脆没有时间框，这里兜的是直接调接口的路径。
        # 不认跨天 —— 跨天请按天建多条（前端就是这么展开的）
        sched_data["start_time"], sched_data["end_time"] = _all_day_times(
            sched_data["start_time"].date()
        )
    else:
        _validate_times(data.start_time, data.end_time)

    # 沿用分组：编辑全天事件时补出来的那几天要发给原来那批人（见 _share_targets）
    share_ids = _share_targets(db, student, data.share_from) if is_committee(user) else []

    if not is_committee(user) or (
        not data.target_all and not data.target_student_ids and not share_ids
    ):
        # 普通学生，或班委选择「仅自己」
        tpl = ss.create_schedule(
            db, student_id=student.id, data=sched_data,
            source_type=SOURCE_PERSONAL, created_by=student.id,
        )
        db.commit()
        db.refresh(tpl)
        log_operation(db, user, f"新建日程：{tpl.title}")
        return ss._to_instance(tpl, tpl.start_time.date())

    # 班委批量创建
    if share_ids:
        target_ids = share_ids
    else:
        target_ids = _resolve_target_students(
            db, user, data.target_all, data.target_student_ids
        )
        if not target_ids:
            raise HTTPException(status_code=400, detail="目标学生不能为空")

    # 确保操作人自己也在目标里（班委创建的日程自己也应该能看到）
    if student.id not in target_ids:
        target_ids = [student.id] + target_ids

    batch = ss.create_batch(
        db,
        operator_id=student.id,
        operator_name=student.name,
        batch_name=data.title or "批量日程",
        schedules_data=[sched_data],
        target_student_ids=target_ids,
    )
    db.commit()

    log_operation(
        db, user,
        f"批量创建日程「{data.title}」，共 {len(target_ids)} 人",
    )

    # 返回操作人自己的那条
    tpl = (
        db.query(Schedule)
        .filter(
            Schedule.student_id == student.id,
            Schedule.source_batch_id == batch.id,
        )
        .order_by(Schedule.id.desc())
        .first()
    )
    if tpl:
        # 刚给这几个人各建了一条，人数就是学生数（target_ids 已去重）
        return ss._to_instance(tpl, tpl.start_time.date(), len(target_ids))
    # 极端情况：操作人那条没找到（不应该发生），返回第一条数据
    return {
        "id": 0,
        "template_id": 0,
        "title": data.title,
        "location": data.get("location", ""),
        "description": data.get("description", ""),
        "start_time": data.start_time,
        "end_time": data.end_time,
        "all_day": data.get("all_day", False),
        "repeat_type": data.repeat_type,
        "repeat_end_date": data.repeat_end_date,
        "notify_enabled": data.notify_enabled,
        "notify_minutes_before": data.notify_minutes_before,
        "source_type": SOURCE_BATCH,
        "source_batch_id": batch.id,
        "instance_date": data.start_time.date(),
    }


def _resolve_target_students(
    db: Session, user: User, target_all: bool, target_ids: list[int],
) -> list[int]:
    """解析目标学生列表（班委权限）"""
    if target_all:
        students = db.query(Student).all()
        return [s.id for s in students]
    # 指定学生：校验 ID 都存在
    if not target_ids:
        return []
    students = db.query(Student).filter(Student.id.in_(target_ids)).all()
    return [s.id for s in students]


def _share_targets(db: Session, student: Student, share_from: Optional[int]) -> list[int]:
    """按已有的某条日程，取「当初发给的那批人」的学生 ID（沿用分组）

    给「编辑全天事件时新增的天数」用：那条日程原本发给谁，新的一天就发给谁，
    不用把学生名单再传一遍。

    只有这条原始日程确实是本人分配出去的才认 —— 不然传一个别人的日程 ID
    就能把日程塞进一堆无关学生的表里。不是自己的就返回空，调用方会退回「仅自己」。
    """
    if not share_from:
        return []
    src = ss.get_template(db, share_from, student.id)
    if not src or not ss.can_share(src, student.id):
        return []
    # 自己那份（src）+ 其他学生的副本。**按学生去重**：同一个学生在分组里可能
    # 不止一行（他自己「本次及以后」拆过就成了两条），不去重的话 create_batch
    # 会在他的表里建出两条一模一样的日程，页面上同一天叠两个
    ids = [src.student_id] + [c.student_id for c in ss._share_copies(db, src)]
    return list(dict.fromkeys(ids))


# ---------- 编辑日程 ----------

def _check_share(tpl: Schedule, student_id: int) -> None:
    """下发的资格校验：只有把这条日程分配出去的人，才能改到别人的表里

    个人日程（没有批次）上带 share 是无副作用的 no-op，直接放行 —— 前端本来
    也不会对它们显示这一档。

    不静默降级成「只改自己那份」：用户勾了「所有人的」却只改了自己的，
    界面上看不出任何异常，比直接报错危险得多。
    """
    if tpl.source_batch_id and not ss.can_share(tpl, student_id):
        raise HTTPException(
            status_code=403, detail="这条日程不是你分配的，改不了其他人的表"
        )


@router.put("/item/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: int,
    data: ScheduleUpdate,
    instance_date: date = Query(..., description="要编辑的实例日期"),
    share: bool = Query(False, description="是否一并改掉其他学生的表（仅限分配者）"),
    student: Student = Depends(get_current_student),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """编辑日程

    scope 参数控制编辑范围：
    - single：仅本次
    - forward：本次及以后
    - all：全部（默认）

    share 为真时，同一条原始日程在其他学生表里的副本一起改（见 schedule_service）。
    放 query 而不是 body：下面 update_data 会把 body 里所有非 scope 字段当业务
    字段写进模型，混一个控制参数进去早晚要出事。
    """
    tpl = ss.get_template(db, schedule_id, student.id)
    if not tpl:
        raise HTTPException(status_code=404, detail="日程不存在")

    scope = _check_scope(data.scope)
    if share:
        _check_share(tpl, student.id)

    # 只能编辑自己创建的批量日程的全部 —— 或者说，批量来的日程不允许学生自己改？
    # 需求里没说不能改学生自己的批量日程。学生可以自己改被分配的日程。
    # 但批量的「全部修改」应该只有班委能做（通过批次管理）。
    # 这里允许学生改自己的那份，包括 scope=all（只改自己的模板）

    update_data = data.model_dump(exclude={"scope"}, exclude_unset=True)

    # 如果改了 repeat_type，校验；改成重复类型还必须带结束日期
    if "repeat_type" in update_data and update_data["repeat_type"] is not None:
        _check_repeat_type(update_data["repeat_type"])
        if update_data["repeat_type"] != REPEAT_NONE and not update_data.get("repeat_end_date"):
            raise HTTPException(status_code=400, detail="重复日程必须设置结束日期")

    if update_data.get("all_day"):
        # 全天事件不给时刻（同新建）。日期取这次传的，没传就用库里那条的 ——
        # 从「普通日程」改成「全天」时前端会连着日期一起传
        day = (update_data.get("start_time") or tpl.start_time).date()
        update_data["start_time"], update_data["end_time"] = _all_day_times(day)
    elif "start_time" in update_data and "end_time" in update_data:
        # 如果改了起止时间，校验
        if update_data["start_time"] and update_data["end_time"]:
            _validate_times(update_data["start_time"], update_data["end_time"])

    # 点中那一行现在的样子，先记下来：scope=single 会把本次拆成一条新记录，
    # 原记录被截断、只剩一次发生时还会被删掉
    clicked = ss._to_instance(tpl, instance_date)

    if share:
        count = ss.update_shared(db, tpl, update_data, scope, instance_date)
    else:
        count = ss.update_schedule(
            db, schedule_id, student.id, update_data, scope, instance_date
        )
    if count == 0:
        raise HTTPException(status_code=404, detail="日程不存在")

    db.commit()
    log_operation(db, user, f"编辑日程：{clicked['title']}（{scope}{'，含他人' if share else ''}）")

    # 响应按 id 报点中的那一行。原来这里是「按标题反查最近更新的那条」，
    # 改名的场景下必然找错（新标题在新记录上，按旧标题找回来的是别的东西），
    # 标题相同的日程多的是，找回来的行可能跟这次编辑毫无关系。前端不看这个响应
    # （保存后自己重新拉列表），但别再回一句假话
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if row is None:
        # 原行已经被拆没了（只剩一次发生的重复日程改成「仅本次」）：本次落在新建
        # 的那条独立日程上，没有现成的行可回，就把提交上来的字段套在点中的实例上
        # 报回去；拆出来的这条按 service 的约定是不重复的，跟着写上
        echo = ss._apply_update_to_dict(clicked, update_data)
        echo["repeat_type"] = REPEAT_NONE
        echo["repeat_end_date"] = None
        return echo
    counts = ss.share_counts(db, [row], student.id)
    return ss._to_instance(row, instance_date, counts.get(row.source_series_id, 1))


# ---------- 删除日程 ----------

@router.delete("/item/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    scope: str = Query(SCOPE_ALL, description="删除范围：single/forward/all"),
    instance_date: date = Query(..., description="实例日期"),
    share: bool = Query(False, description="是否一并从其他学生的表里删掉（仅限分配者）"),
    student: Student = Depends(get_current_student),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除日程

    share 为真时，同一条原始日程在其他学生表里的副本一起删。
    """
    tpl = ss.get_template(db, schedule_id, student.id)
    if not tpl:
        raise HTTPException(status_code=404, detail="日程不存在")

    scope = _check_scope(scope)
    if share:
        _check_share(tpl, student.id)

    title = tpl.title

    if share:
        count = ss.delete_shared(db, tpl, scope, instance_date)
    else:
        count = ss.delete_schedule(db, schedule_id, student.id, scope, instance_date)
    if count == 0:
        raise HTTPException(status_code=404, detail="日程不存在")

    db.commit()
    log_operation(db, user, f"删除日程：{title}（{scope}{'，含他人' if share else ''}）")
    return {"ok": True, "deleted": count}


# ---------- 导入预览（班委） ----------

@router.post("/import/preview", response_model=ScheduleImportPreviewResponse)
async def import_preview(
    file: UploadFile = File(...),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """上传日程 Excel 并预览解析结果（班委及以上）"""
    # 校验扩展名
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_IMPORT_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 {', '.join(sorted(_ALLOWED_IMPORT_EXT))} 格式",
        )

    # 读取文件内容（限制大小）
    content = await file.read()
    if len(content) > _MAX_IMPORT_SIZE:
        raise HTTPException(status_code=400, detail="文件不能超过 20MB")

    items, warnings, week_count = sis.parse_schedule_excel(content)
    token = sis.save_preview(items, warnings, week_count)

    return {
        "token": token,
        "week_count": week_count,
        "schedule_count": sum(1 for it in items if not it.get("all_day")),
        "all_day_count": sum(1 for it in items if it.get("all_day")),
        "items": items,
        "warnings": warnings,
    }


# ---------- 导入确认（班委） ----------

@router.post("/import", response_model=ScheduleImportResultResponse)
def import_confirm(
    data: ScheduleImportConfirm,
    student: Student = Depends(get_current_student),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """确认导入日程（班委及以上）"""
    preview = sis.load_preview(data.token)
    if not preview:
        raise HTTPException(
            status_code=400, detail="预览已过期或不存在，请重新上传",
        )

    items = preview["items"]
    if not items:
        raise HTTPException(status_code=400, detail="没有可导入的日程")

    # 筛选选中的
    if data.selected_indices:
        selected = [items[i] for i in data.selected_indices if 0 <= i < len(items)]
    else:
        selected = list(items)

    if not selected:
        raise HTTPException(status_code=400, detail="请至少选择一条日程")

    # 解析目标学生
    target_ids = _resolve_target_students(db, user, data.target_all, data.target_student_ids)
    if not target_ids:
        raise HTTPException(status_code=400, detail="请选择目标学生")

    # 转换成 create 需要的格式
    schedules_data = []
    for item in selected:
        # 把 start_time / end_time（HH:MM 字符串）+ start_date 组合成 datetime
        start_date = item.get("start_date")
        if not start_date:
            continue
        start_dt = datetime.combine(start_date, _parse_time_str(item["start_time"]))
        end_dt = datetime.combine(start_date, _parse_time_str(item["end_time"]))

        schedules_data.append({
            "title": item["title"],
            "event_type": item.get("event_type", ""),
            "location": item.get("location", ""),
            "description": item.get("description", ""),
            "start_time": start_dt,
            "end_time": end_dt,
            "all_day": item.get("all_day", False),
            "repeat_type": item.get("repeat_type", "none"),
            "repeat_end_date": item.get("repeat_end_date"),
            "notify_enabled": item.get("notify_enabled", False),
            "notify_minutes_before": item.get("notify_minutes_before", 10),
            # 学期第 1 周的周一（由表名折算）。存下来有两个用处：单双周判断
            # 有个真实基准，页面上的「第几周」也不用再自己估
            "week_start": item.get("week_start"),
        })

    if not schedules_data:
        raise HTTPException(status_code=400, detail="没有有效的日程可导入")

    batch = ss.create_batch(
        db,
        operator_id=student.id,
        operator_name=student.name,
        batch_name=data.batch_name or "导入日程",
        schedules_data=schedules_data,
        target_student_ids=target_ids,
    )
    db.commit()

    # 清掉预览缓存
    sis.drop_preview(data.token)

    log_operation(
        db, user,
        f"导入日程「{batch.name}」：{len(schedules_data)} 条 × {len(target_ids)} 人 = {len(schedules_data) * len(target_ids)} 条",
    )

    return {
        "batch_id": batch.id,
        "batch_name": batch.name,
        "target_count": len(target_ids),
        "schedule_per_student": len(schedules_data),
        "total_created": len(schedules_data) * len(target_ids),
        "warnings": preview.get("warnings", []),
    }


def _parse_time_str(s: str) -> datetime.time:
    """把 HH:MM 字符串解析成 time 对象"""
    h, m = map(int, s.split(":"))
    return time(h, m)


# ---------- 批次管理（班委） ----------

@router.get("/batches", response_model=list[ScheduleBatchResponse])
def list_batches(
    student: Student = Depends(get_current_student),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """查看自己创建的导入批次"""
    batches = ss.list_batches(db, student.id)
    return [
        {
            "id": b.id,
            "name": b.name,
            "target_count": b.target_count,
            "schedule_count": b.schedule_count,
            "operator_name": b.operator_name or "",
            "created_at": b.created_at,
        }
        for b in batches
    ]


@router.delete("/batches/{batch_id}")
def delete_batch(
    batch_id: int,
    student: Student = Depends(get_current_student),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """撤销整个导入批次（删除该批次下所有日程）"""
    batch = db.query(ScheduleBatch).filter(ScheduleBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    if batch.operator_id != student.id:
        raise HTTPException(status_code=403, detail="只能撤销自己创建的批次")

    count = ss.delete_batch(db, batch_id, student.id)
    db.commit()
    log_operation(db, user, f"撤销日程批次：{batch.name}（{count} 条）")
    return {"ok": True, "deleted": count}


# ---------- iCal 订阅 ----------

@router.get("/ical/token", response_model=ICalTokenResponse)
def get_ical_token(
    request: Request,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """获取当前学生的 iCal 订阅链接"""
    token, path = ss.get_or_create_ical_token(db, student.id)
    db.commit()  # 确保 token 持久化（iCal 请求是另一个 session）
    url = _build_full_url(request, path)
    token_row = ss.get_student_by_ical_token(db, token)
    last_accessed = token_row[1].last_accessed_at if token_row else None
    return {"token": token, "url": url, "last_accessed_at": last_accessed}


@router.post("/ical/token/reset", response_model=ICalTokenResponse)
def reset_ical_token(
    request: Request,
    student: Student = Depends(get_current_student),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重置 iCal 订阅令牌（旧链接立即失效）"""
    token, path = ss.reset_ical_token(db, student.id)
    db.commit()
    url = _build_full_url(request, path)
    log_operation(db, user, "重置 iCal 订阅令牌")
    return {"token": token, "url": url, "last_accessed_at": None}


# 注意：这个接口不走登录会话，纯 token 鉴权（放在 api_router 里但手动鉴权）
@router.get("/ical/{token}.ics")
def ical_feed(
    token: str,
    db: Session = Depends(get_db),
):
    """iCal 订阅端点（公开接口，通过 URL 中的 token 鉴权）

    返回标准 .ics 文件内容。
    """
    result = ss.get_student_by_ical_token(db, token)
    if not result:
        # token 无效返回 404，不泄露「这个 token 曾经存在」
        raise HTTPException(status_code=404, detail="Not found")

    student_id, token_row = result
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Not found")

    db.commit()  # 提交 last_accessed_at 的更新

    content = sics.generate_ical(db, student.id, student.name)
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="schedule.ics"',
            # 建议客户端 1 小时刷新一次
            "Cache-Control": "max-age=3600",
        },
    )


def _build_full_url(request: Request, path: str) -> str:
    """根据请求构建完整 URL"""
    base = f"{request.url.scheme}://{request.url.netloc}"
    return base + path
