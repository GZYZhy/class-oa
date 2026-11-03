"""完整档案授权的判定

申请流程本身在 api/archive_views.py，这里只放「谁现在能看完整档案」这一条规则，
因为两个地方都要用：
- GET /api/students/{id} 决定要不要裁剪字段
- GET /api/students/{id}/photo 决定要不要放行实地采集照片

有效期和签字图一致，都是 1 小时；判定用 reviewed_at 现算，不存 expires_at
（理由同 api/sign_photos.py）。
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import ArchiveViewRequest, Student, User
from ..utils.roles import ROLE_RANK

ARCHIVE_VIEW_TTL = timedelta(hours=1)

# 给前端按钮用的状态（与签字申请的状态字符串保持一致）
ST_NONE = "none"          # 没申请过，或被驳回了
ST_PENDING = "pending"    # 等管理员批
ST_APPROVED = "approved"  # 能看
ST_EXPIRED = "expired"    # 批过但过期了，要重新申请


def archive_state(
    db: Session, student_id: int, applicant_no: str
) -> tuple[str, ArchiveViewRequest | None]:
    """某人对某学生**最近一条**档案申请的状态，以及可用的那条记录"""
    req = (
        db.query(ArchiveViewRequest)
        .filter(
            ArchiveViewRequest.student_id == student_id,
            ArchiveViewRequest.applicant_no == applicant_no,
        )
        .order_by(ArchiveViewRequest.id.desc())
        .first()
    )
    if not req:
        return ST_NONE, None
    if req.status == "pending":
        return ST_PENDING, None
    if req.status != "approved":
        return ST_NONE, None
    # approved 但没写 reviewed_at 是不可能的；真出现了就当过期，宁可拒绝
    if not req.reviewed_at or datetime.now() - req.reviewed_at > ARCHIVE_VIEW_TTL:
        return ST_EXPIRED, None
    return ST_APPROVED, req


def archive_expires_at(req: ArchiveViewRequest) -> datetime:
    return req.reviewed_at + ARCHIVE_VIEW_TTL


def is_own_record(user: User, student: Student) -> bool:
    """当前账号是不是这个学生本人

    域外账号的 student_no 是管理员指定的登录名，理论上可能和某个学号撞上，
    所以本人判定必须排除域外账号（同签字上传接口的写法）。
    """
    return not user.is_external and user.student_no == student.student_no


def has_full_archive_access(db: Session, user: User, student: Student) -> bool:
    """这个账号现在能不能看该学生的完整档案

    管理员和本人永远可以；班委需要一条未过期的、本人提出的批准记录。
    普通学生看不了别人（调用方已拦），这里返回 False。
    """
    rank = ROLE_RANK.get(user.role or "student", 0)
    if rank >= ROLE_RANK["admin"]:
        return True
    if rank < ROLE_RANK["committee"]:
        return False
    if is_own_record(user, student):
        return True
    state, _ = archive_state(db, student.id, user.student_no)
    return state == ST_APPROVED
