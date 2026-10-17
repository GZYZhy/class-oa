"""签到：状态、距离与结算

状态、能不能签、最后算到还是请假，**全在这里定义**（同 poll_service 的口径），
接口只负责搬运，前端只认字段不重算 —— 否则迟早出现「页面说进行中、结算说已结束」。
"""

from datetime import datetime
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import AttendanceItem, AttendanceRecord, Checkin, CheckinTarget, LeaveRequest

CHECKIN_ONGOING = "ongoing"
CHECKIN_ENDED = "ended"

# 地球平均半径（米）。距离只用来判「在不在允许范围」，这个精度足够了
EARTH_RADIUS_M = 6371000


def checkin_status(checkin: Checkin, now: datetime | None = None) -> str:
    """进行中 / 已结束

    `finalized_at` 优先于时间判断：提前结束的签到 closed_at 已经落了，
    再怎么等也不会重新变成进行中。
    """
    if checkin.finalized_at is not None:
        return CHECKIN_ENDED
    now = now or datetime.now()
    return CHECKIN_ENDED if now >= checkin.end_at else CHECKIN_ONGOING


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点间的大圆距离（米）

    两个点都是 GCJ-02（高德坐标系）。**不要**拿浏览器原始定位（WGS-84）直接比：
    在内地两者差几十到几百米，100 米半径会整片误判。转换在前端做，见
    frontend/src/utils/geolocation.js。
    """
    p1, p2 = radians(lat1), radians(lat2)
    dp = p2 - p1
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    # 球面中心角 = 2·asin(√a)。班级场景里两点不会正好是地球两端，a 远小于 1，
    # 直接 asin 没有精度问题
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def approved_leave_nos(db: Session, student_nos: list[str], moment: datetime) -> set[str]:
    """在 `moment` 这一刻持有已批准请假的学生

    用 `<=` / `>=` 两端都算在内：请假到 10:00、签到截止也是 10:00，这个人
    应当按「请假」算，不能因为差一秒被推成无应答。
    """
    if not student_nos:
        return set()
    rows = (
        db.query(LeaveRequest.student_no)
        .filter(
            LeaveRequest.status == "approved",
            LeaveRequest.student_no.in_(student_nos),
            LeaveRequest.start_at <= moment,
            LeaveRequest.end_at >= moment,
        )
        .all()
    )
    return {no for (no,) in rows}


def finalize_due(db: Session, now: datetime | None = None) -> None:
    """把到点或已提前结束、但还没结算的签到逐个结算

    懒结算：不另起定时任务。考勤列表、签到列表、公开信息页都会先调它，
    所以班委就算不打开签到页，到点后的考勤记录也会出现在「考勤记录」里。
    """
    now = now or datetime.now()
    rows = (
        db.query(Checkin)
        .filter(
            Checkin.finalized_at.is_(None),
            or_(Checkin.closed_at.isnot(None), Checkin.end_at <= now),
        )
        .all()
    )
    for checkin in rows:
        finalize_checkin(db, checkin)


def finalize_checkin(db: Session, checkin: Checkin) -> bool:
    """结算一次签到，生成一条普通考勤记录

    规则的唯一出处（用户口径）：
      - 签到了 → present（**持有有效请假的人签了也算到**）
      - 没签、且截止时刻在已批准请假区间内 → leave
      - 其余 → absent（页面上的「无应答」）

    返回是否由本次调用完成结算。并发调用时靠条件 UPDATE 抢：
    两个请求同时进来，只有第一个能把 finalized_at 从 NULL 改掉，
    第二个 rowcount=0 直接退出，不会生成两条考勤记录。
    """
    reference = checkin.closed_at or checkin.end_at
    claimed = (
        db.query(Checkin)
        .filter(Checkin.id == checkin.id, Checkin.finalized_at.is_(None))
        .update({Checkin.finalized_at: reference}, synchronize_session=False)
    )
    if not claimed:
        # 别人已经结算过了。结束本次事务，让后面读到的是最新状态
        db.rollback()
        return False

    targets = (
        db.query(CheckinTarget)
        .filter(CheckinTarget.checkin_id == checkin.id)
        .order_by(CheckinTarget.student_no)
        .all()
    )
    leave_nos = approved_leave_nos(db, [t.student_no for t in targets], reference)

    scope = f"签到·{len(targets)}人"
    remark = f"签到：{checkin.title}"
    if checkin.remark:
        remark += f"；{checkin.remark}"
    record = AttendanceRecord(
        call_date=reference.date(),
        scope=scope,
        called_at=reference,
        operator_no=checkin.created_by_no,
        operator_name=checkin.created_by_name,
        remark=remark[:200],
    )
    db.add(record)
    db.flush()   # 拿到自增 id，明细要用

    db.add_all(
        [
            AttendanceItem(
                record_id=record.id,
                student_no=t.student_no,
                student_name=t.student_name,
                status=(
                    "present"
                    if t.signed_at is not None
                    else ("leave" if t.student_no in leave_nos else "absent")
                ),
            )
            for t in targets
        ]
    )
    # attendance_record_id 是普通字段赋值，会和上面的 UPDATE 在同一个事务里提交
    checkin.attendance_record_id = record.id
    db.commit()
    return True
