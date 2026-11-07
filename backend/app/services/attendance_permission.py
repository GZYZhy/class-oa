"""考勤 / 签到的管理权限

口径（与投票、收集对齐）：
- **管理（写）**：只有管理员或这场记录（点名 / 签到）的发起者；
  包含删除、改某人状态、暂停/恢复、延长、提前结束。
- **催促、改标题**：仍然放给所有班委 —— 这两件事不动考勤结果，
  谁看到问题都可以顺手催一句、把标题写清楚。
- **导出与只读明细**：不受影响，沿用 committee_required。

发起者用学号判断（AttendanceRecord.operator_no / Checkin.created_by_no）：
签到结算生成的那条考勤，operator_no 就是签发的 created_by_no，
所以同一套判断在两种记录上都成立。域外账号当发起者时存的是登录名，同样对得上。
"""

from fastapi import HTTPException

from ..models import AttendanceRecord, Checkin, User
from ..utils.roles import ROLE_RANK


def _is_admin(user: User) -> bool:
    return ROLE_RANK.get(user.role or "student", 0) >= ROLE_RANK["admin"]


def can_manage_attendance(record: AttendanceRecord, user: User) -> bool:
    """能不能改 / 删这次点名（管理员，或这场点名的发起者）"""
    if _is_admin(user):
        return True
    return bool(record.operator_no) and record.operator_no == user.student_no


def can_manage_checkin(checkin: Checkin, user: User) -> bool:
    """能不能改 / 删这次签到（管理员，或这场签到的发起者）"""
    if _is_admin(user):
        return True
    return bool(checkin.created_by_no) and checkin.created_by_no == user.student_no


def ensure_manage_attendance(
    record: AttendanceRecord, user: User, action: str = "管理"
) -> None:
    if not can_manage_attendance(record, user):
        raise HTTPException(
            status_code=403,
            detail=f"只有管理员或这场点名的发起人可以{action}",
        )


def ensure_manage_checkin(
    checkin: Checkin, user: User, action: str = "管理"
) -> None:
    if not can_manage_checkin(checkin, user):
        raise HTTPException(
            status_code=403,
            detail=f"只有管理员或这场签到的发起人可以{action}",
        )
