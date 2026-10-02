"""办件空间：我申请的 / 我审批的

把 6 类办件（信息修改 / 请假 / 电动车通行证 / 证明开具 / 导出申请 / 意见反馈）
聚合成统一列表，前端「我的信息」页的办件空间 tab 使用。

每类办件各查一次，在 Python 层按时间合并排序，结构统一：
    {id, type, type_name, title, applicant_name, applicant_no,
     status, status_label, status_type,
     created_at, updated_at, reviewer_name, reason, detail_url}
"""

import json
from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    CertificateRequest,
    ChangeRequest,
    EvPassRequest,
    ExportRequest,
    Feedback,
    LeaveRequest,
    Student,
    User,
)
from .deps import get_current_user, is_committee, ROLE_RANK

router = APIRouter(prefix="/api/workspace", tags=["办件空间"])


# 办件类型元信息：中文名 + 各状态对应的标签文案 / 标签颜色
_TYPE_META = {
    "change": {
        "name": "信息修改申请",
        "status_labels": {
            "pending": ("待审核", "warning"),
            "approved": ("已通过", "success"),
            "rejected": ("已驳回", "danger"),
        },
    },
    "leave": {
        "name": "请假申请",
        "status_labels": {
            "pending": ("待审核", "warning"),
            "approved": ("已通过", "success"),
            "rejected": ("已驳回", "danger"),
        },
    },
    "evpass": {
        "name": "电动车通行证",
        "status_labels": {
            "pending": ("待审核", "warning"),
            "approved": ("已通过", "success"),
            "rejected": ("已驳回", "danger"),
        },
    },
    "certificate": {
        "name": "证明开具",
        "status_labels": {
            "pending": ("待审核", "warning"),
            "approved": ("已通过", "success"),
            "rejected": ("已驳回", "danger"),
        },
    },
    "export": {
        "name": "导出申请",
        "status_labels": {
            "pending": ("待审核", "warning"),
            "approved": ("已批准，生成中", "info"),
            "generated": ("已生成", "success"),
            "rejected": ("已驳回", "danger"),
            "failed": ("生成失败", "danger"),
        },
    },
    "feedback": {
        "name": "意见反馈",
        "status_labels": {
            "unread": ("未读", "warning"),
            "read": ("已读", "info"),
            "replied": ("已回复", "success"),
        },
    },
}


def _status_info(type_key: str, status: str):
    """返回 (label, tag_type)，未知状态兜底返回原值 + info"""
    labels = _TYPE_META.get(type_key, {}).get("status_labels", {})
    return labels.get(status, (status, "info"))


def _type_name(type_key: str) -> str:
    return _TYPE_META.get(type_key, {}).get("name", type_key)


def _fmt(dt) -> str | None:
    """datetime → ISO 字符串；None 返回 None"""
    if not dt:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _loads_json(val) -> dict:
    """统一把 str / dict / None 解析成 dict"""
    if not val:
        return {}
    if isinstance(val, dict):
        return val
    try:
        return json.loads(val)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 我申请的
# ---------------------------------------------------------------------------

@router.get("/submitted", summary="我申请的办件")
def get_submitted(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """当前用户提交过的所有办件，按提交时间倒序。"""
    items: List[Dict[str, Any]] = []
    sno = user.student_no

    # ---- 1. 信息修改申请 ----
    for row in (
        db.query(ChangeRequest)
        .filter(ChangeRequest.student_no == sno)
        .order_by(ChangeRequest.created_at.desc())
        .all()
    ):
        label, tag = _status_info("change", row.status)
        changes = _loads_json(row.changes)
        items.append({
            "id": row.id,
            "type": "change",
            "type_name": _type_name("change"),
            "title": f"修改 {len(changes)} 项信息",
            "applicant_name": row.student_name,
            "applicant_no": row.student_no,
            "status": row.status,
            "status_label": label,
            "status_type": tag,
            "created_at": _fmt(row.created_at),
            "updated_at": _fmt(row.reviewed_at),
            "reviewer_name": row.reviewer_name,
            "reason": row.reason,
            "detail_url": "/my-info?tab=info",
        })

    # ---- 2. 请假申请 ----
    for row in (
        db.query(LeaveRequest)
        .filter(LeaveRequest.student_no == sno)
        .order_by(LeaveRequest.created_at.desc())
        .all()
    ):
        label, tag = _status_info("leave", row.status)
        title = row.leave_type or "请假"
        if row.reason:
            title += f"：{row.reason}"
        items.append({
            "id": row.id,
            "type": "leave",
            "type_name": _type_name("leave"),
            "title": title,
            "applicant_name": row.student_name,
            "applicant_no": row.student_no,
            "status": row.status,
            "status_label": label,
            "status_type": tag,
            "created_at": _fmt(row.created_at),
            "updated_at": _fmt(row.reviewed_at),
            "reviewer_name": row.reviewer_name,
            "reason": row.reject_reason,
            "detail_url": "/leave",
        })

    # ---- 3. 电动车通行证 ----
    # 通行证表存 student_id，关联 Student 表查学号
    for row in (
        db.query(EvPassRequest)
        .join(Student, EvPassRequest.student_id == Student.id)
        .filter(Student.student_no == sno)
        .order_by(EvPassRequest.created_at.desc())
        .all()
    ):
        label, tag = _status_info("evpass", row.status)
        brand = row.brand or ""
        plate = row.plate_number or ""
        title = f"{brand} {plate}".strip() or "电动车通行证补办"
        items.append({
            "id": row.id,
            "type": "evpass",
            "type_name": _type_name("evpass"),
            "title": title,
            "applicant_name": row.student.name if row.student else "",
            "applicant_no": row.student.student_no if row.student else "",
            "status": row.status,
            "status_label": label,
            "status_type": tag,
            "created_at": _fmt(row.created_at),
            "updated_at": _fmt(row.reviewed_at),
            "reviewer_name": row.reviewer_name,
            "reason": row.reject_reason,
            "detail_url": "/ev-pass",
        })

    # ---- 4. 证明开具 ----
    for row in (
        db.query(CertificateRequest)
        .join(Student, CertificateRequest.student_id == Student.id)
        .filter(Student.student_no == sno)
        .order_by(CertificateRequest.created_at.desc())
        .all()
    ):
        label, tag = _status_info("certificate", row.status)
        items.append({
            "id": row.id,
            "type": "certificate",
            "type_name": _type_name("certificate"),
            "title": row.title or "证明开具",
            "applicant_name": row.student.name if row.student else "",
            "applicant_no": row.student.student_no if row.student else "",
            "status": row.status,
            "status_label": label,
            "status_type": tag,
            "created_at": _fmt(row.created_at),
            "updated_at": _fmt(row.reviewed_at),
            "reviewer_name": row.reviewer_name,
            "reason": row.reject_reason,
            "detail_url": "/certificate",
        })

    # ---- 5. 导出申请（班委及以上才能提交）----
    if is_committee(user):
        for row in (
            db.query(ExportRequest)
            .filter(ExportRequest.student_no == sno)
            .order_by(ExportRequest.created_at.desc())
            .all()
        ):
            label, tag = _status_info("export", row.status)
            type_label = "Excel 名单" if row.export_type == "excel_list" else "个人信息表 PDF"
            items.append({
                "id": row.id,
                "type": "export",
                "type_name": _type_name("export"),
                "title": f"导出 {type_label}",
                "applicant_name": row.student_name,
                "applicant_no": row.student_no,
                "status": row.status,
                "status_label": label,
                "status_type": tag,
                "created_at": _fmt(row.created_at),
                "updated_at": _fmt(row.reviewed_at),
                "reviewer_name": row.reviewer_name,
                "reason": row.reject_reason,
                "detail_url": "/students",
            })

    # ---- 6. 意见反馈 ----
    for row in (
        db.query(Feedback)
        .filter(Feedback.student_no == sno)
        .order_by(Feedback.created_at.desc())
        .all()
    ):
        label, tag = _status_info("feedback", row.status)
        items.append({
            "id": row.id,
            "type": "feedback",
            "type_name": _type_name("feedback"),
            "title": row.title or "意见反馈",
            "applicant_name": row.student_name,
            "applicant_no": row.student_no,
            "status": row.status,
            "status_label": label,
            "status_type": tag,
            "created_at": _fmt(row.created_at),
            "updated_at": _fmt(row.reply_at),
            "reviewer_name": row.reply_name,
            "reason": None,
            "detail_url": "/feedback",
        })

    # 按提交时间倒序
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return items


# ---------------------------------------------------------------------------
# 我审批 / 处理过的
# ---------------------------------------------------------------------------

@router.get("/involved", summary="我参与处理的办件")
def get_involved(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """我已经有过初步应对的办件（不含纯待办）。

    判定口径：
    - 有 reviewer_no == 我的（我审核过的修改/请假/通行证/证明/导出）
    - 有 reply_no == 我的（我回复过的反馈）
    - 反馈的「已读」状态不记录操作人，因此只展示我**回复**过的反馈
    """
    items: List[Dict[str, Any]] = []

    # 班委及以上才有审批权限
    if not is_committee(user):
        return items

    sno = user.student_no
    is_admin = ROLE_RANK.get(user.role or "student", 0) >= ROLE_RANK["admin"]

    # ---- 1. 信息修改申请（班委可批）----
    for row in (
        db.query(ChangeRequest)
        .filter(ChangeRequest.reviewer_no == sno)
        .order_by(ChangeRequest.reviewed_at.desc())
        .all()
    ):
        label, tag = _status_info("change", row.status)
        changes = _loads_json(row.changes)
        items.append({
            "id": row.id,
            "type": "change",
            "type_name": _type_name("change"),
            "title": f"{row.student_name} 申请修改 {len(changes)} 项信息",
            "applicant_name": row.student_name,
            "applicant_no": row.student_no,
            "status": row.status,
            "status_label": label,
            "status_type": tag,
            "created_at": _fmt(row.created_at),
            "updated_at": _fmt(row.reviewed_at),
            "reviewer_name": row.reviewer_name,
            "reason": row.reason,
            "detail_url": "/review?tab=change",
        })

    # ---- 2. 请假申请（仅管理员）----
    if is_admin:
        for row in (
            db.query(LeaveRequest)
            .filter(LeaveRequest.reviewer_no == sno)
            .order_by(LeaveRequest.reviewed_at.desc())
            .all()
        ):
            label, tag = _status_info("leave", row.status)
            title = f"{row.student_name} 的{row.leave_type or ''}请假申请"
            items.append({
                "id": row.id,
                "type": "leave",
                "type_name": _type_name("leave"),
                "title": title,
                "applicant_name": row.student_name,
                "applicant_no": row.student_no,
                "status": row.status,
                "status_label": label,
                "status_type": tag,
                "created_at": _fmt(row.created_at),
                "updated_at": _fmt(row.reviewed_at),
                "reviewer_name": row.reviewer_name,
                "reason": row.reject_reason,
                "detail_url": "/review?tab=leave",
            })

    # ---- 3. 电动车通行证（管理员）----
    if is_admin:
        for row in (
            db.query(EvPassRequest)
            .filter(EvPassRequest.reviewer_no == sno)
            .order_by(EvPassRequest.reviewed_at.desc())
            .all()
        ):
            label, tag = _status_info("evpass", row.status)
            name = row.student.name if row.student else ""
            items.append({
                "id": row.id,
                "type": "evpass",
                "type_name": _type_name("evpass"),
                "title": f"{name} 的电动车通行证申请",
                "applicant_name": name,
                "applicant_no": row.student.student_no if row.student else "",
                "status": row.status,
                "status_label": label,
                "status_type": tag,
                "created_at": _fmt(row.created_at),
                "updated_at": _fmt(row.reviewed_at),
                "reviewer_name": row.reviewer_name,
                "reason": row.reject_reason,
                "detail_url": "/review?tab=evpass",
            })

    # ---- 4. 证明开具（管理员）----
    if is_admin:
        for row in (
            db.query(CertificateRequest)
            .filter(CertificateRequest.reviewer_no == sno)
            .order_by(CertificateRequest.reviewed_at.desc())
            .all()
        ):
            label, tag = _status_info("certificate", row.status)
            name = row.student.name if row.student else ""
            items.append({
                "id": row.id,
                "type": "certificate",
                "type_name": _type_name("certificate"),
                "title": f"{name}：{row.title or '证明开具'}",
                "applicant_name": name,
                "applicant_no": row.student.student_no if row.student else "",
                "status": row.status,
                "status_label": label,
                "status_type": tag,
                "created_at": _fmt(row.created_at),
                "updated_at": _fmt(row.reviewed_at),
                "reviewer_name": row.reviewer_name,
                "reason": row.reject_reason,
                "detail_url": "/review?tab=certificate",
            })

    # ---- 5. 导出申请（管理员审批）----
    if is_admin:
        for row in (
            db.query(ExportRequest)
            .filter(ExportRequest.reviewer_no == sno)
            .order_by(ExportRequest.reviewed_at.desc())
            .all()
        ):
            label, tag = _status_info("export", row.status)
            type_label = "Excel 名单" if row.export_type == "excel_list" else "个人信息表 PDF"
            items.append({
                "id": row.id,
                "type": "export",
                "type_name": _type_name("export"),
                "title": f"{row.student_name} 申请导出 {type_label}",
                "applicant_name": row.student_name,
                "applicant_no": row.student_no,
                "status": row.status,
                "status_label": label,
                "status_type": tag,
                "created_at": _fmt(row.created_at),
                "updated_at": _fmt(row.reviewed_at),
                "reviewer_name": row.reviewer_name,
                "reason": row.reject_reason,
                "detail_url": "/review?tab=export",
            })

    # ---- 6. 意见反馈（班委及以上可回复；只展示我回复过的）----
    for row in (
        db.query(Feedback)
        .filter(Feedback.reply_no == sno)
        .order_by(Feedback.reply_at.desc())
        .all()
    ):
        label, tag = _status_info("feedback", row.status)
        items.append({
            "id": row.id,
            "type": "feedback",
            "type_name": _type_name("feedback"),
            "title": f"{row.student_name}：{row.title or '意见反馈'}",
            "applicant_name": row.student_name,
            "applicant_no": row.student_no,
            "status": row.status,
            "status_label": label,
            "status_type": tag,
            "created_at": _fmt(row.created_at),
            "updated_at": _fmt(row.reply_at),
            "reviewer_name": row.reply_name,
            "reason": None,
            "detail_url": "/review?tab=feedback",
        })

    # 按处理时间倒序（更新时间最新的在前）
    items.sort(key=lambda x: x["updated_at"] or x["created_at"] or "", reverse=True)
    return items
