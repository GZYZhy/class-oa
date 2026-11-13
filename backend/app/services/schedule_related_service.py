"""日程关联内容。只保存引用，展示和操作继续遵守原模块的权限。"""

from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import (
    Checkin,
    CheckinTarget,
    Collection,
    CollectionTarget,
    Notice,
    NoticeRead,
    Poll,
    PollTarget,
    Resource,
    User,
)
from ..utils.roles import ROLE_RANK
from . import collection_service, poll_service
from .checkin_service import checkin_status
from .list_filters import keyword_like
from .resource_service import RESOURCE_DIR, download_name

MODELS = {
    "notice": Notice,
    "vote": Poll,
    "collect": Collection,
    "checkin": Checkin,
    "resource": Resource,
}
LABELS = {
    "notice": "通知",
    "vote": "投票",
    "collect": "收集",
    "checkin": "签到",
    "resource": "资料",
}
STATUS_LABELS = {
    "pending": "未开始",
    "open": "进行中",
    "ongoing": "进行中",
    "locked": "已暂停",
    "paused": "已暂停",
    "closed": "已结束",
    "ended": "已结束",
}


def visible_query(db: Session, kind: str, user: User):
    model = MODELS[kind]
    query = db.query(model)
    admin = user.role == "admin"
    if kind == "vote":
        return poll_service.filter_visible(db, query, user.student_no, admin)
    if kind == "collect":
        return collection_service.filter_visible(db, query, user.student_no, admin)
    if kind == "checkin" and ROLE_RANK.get(user.role, 0) < ROLE_RANK["committee"]:
        query = query.filter(
            or_(
                Checkin.created_by_no == user.student_no,
                Checkin.id.in_(
                    db.query(CheckinTarget.checkin_id).filter(
                        CheckinTarget.student_no == user.student_no
                    )
                ),
            )
        )
    return query


def resolve_items(db: Session, refs: list[dict], user: User) -> list[dict]:
    """按保存的顺序返回个人状态，隐藏失效或越权记录的标题与链接。"""
    payloads = {}
    admin = user.role == "admin"
    committee = ROLE_RANK.get(user.role, 0) >= ROLE_RANK["committee"]
    for kind in MODELS:
        ids = [ref["id"] for ref in refs if ref["kind"] == kind]
        if not ids:
            continue
        rows = visible_query(db, kind, user).filter(MODELS[kind].id.in_(ids)).all()
        if kind in ("vote", "collect"):
            service = poll_service if kind == "vote" else collection_service
            for item in service.list_items(db, rows, user.student_no, admin):
                hint = STATUS_LABELS.get(item["status"], item["status"])
                if kind == "vote":
                    if item["has_voted"]:
                        hint = "已投票"
                    elif item["can_vote"]:
                        hint = "待投票"
                    progress = f"{item['voted_count']}/{item['target_count']} 人已投票"
                else:
                    if item["is_target"]:
                        hint = f"已提交 {item['my_submitted_count']}/{item['submit_quota']} 份"
                    progress = (
                        f"{item['completed_count']}/{item['target_count']} 人已填满"
                    )
                payloads[(kind, item["id"])] = {
                    "title": item["title"],
                    "hint": hint,
                    "scope_label": item["scope_label"],
                    "end_at": item["end_at"],
                    "progress": progress if item["can_manage"] else "",
                    "url": f"/share/{kind}/{item['share_token']}",
                    "manage_url": f"/#/vote?tab={kind}&manage={item['id']}"
                    if item["can_manage"]
                    else None,
                }
        else:
            for row in rows:
                data = {
                    "title": getattr(row, "title", None) or getattr(row, "name", ""),
                    "hint": "",
                    "progress": "",
                    "scope_label": "",
                }
                if kind == "notice":
                    read = (
                        db.query(NoticeRead.id)
                        .filter(
                            NoticeRead.notice_id == row.id,
                            NoticeRead.student_no == user.student_no,
                        )
                        .first()
                    )
                    data.update(
                        hint="已读" if read else "未读", url=f"/#/notices?id={row.id}"
                    )
                elif kind == "resource":
                    exists = (RESOURCE_DIR / row.file_name).is_file()
                    data.update(
                        hint="可下载" if exists else "文件暂不可用",
                        url=f"/api/resources/file/{quote(row.file_name, safe='')}"
                        if exists
                        else None,
                        download_name=download_name(row),
                    )
                else:
                    target = (
                        db.query(CheckinTarget)
                        .filter(
                            CheckinTarget.checkin_id == row.id,
                            CheckinTarget.student_no == user.student_no,
                        )
                        .first()
                    )
                    hint = STATUS_LABELS[checkin_status(row)]
                    if target and target.signed_at:
                        hint = "已签到"
                    elif target and checkin_status(row) == "ongoing":
                        hint = "待签到"
                    counts = (
                        db.query(
                            func.count(CheckinTarget.id),
                            func.count(CheckinTarget.signed_at),
                        )
                        .filter(CheckinTarget.checkin_id == row.id)
                        .one()
                    )
                    data.update(
                        hint=hint,
                        url=f"/share/checkin/{row.code}",
                        end_at=row.end_at,
                        scope_label=f"定向 {counts[0]} 人",
                        progress=f"{counts[1]}/{counts[0]} 人已签到"
                        if committee
                        else "",
                        checkin_id=row.id if committee else None,
                    )
                payloads[(kind, row.id)] = data
    return [
        dict(
            ref,
            kind_label=LABELS[ref["kind"]],
            **payloads.get(
                (ref["kind"], ref["id"]),
                {"title": "内容已删除或无权查看", "unavailable": True},
            ),
        )
        for ref in refs
    ]


def validate_items(
    db: Session, refs: list[dict] | None, user: User, existing=None
) -> None:
    if refs is None:
        return
    keys = [(ref["kind"], ref["id"]) for ref in refs]
    if len(set(keys)) != len(keys):
        raise HTTPException(400, "关联内容不能重复")
    retained = {(ref["kind"], ref["id"]) for ref in existing or []}
    for kind, item_id in keys:
        if (kind, item_id) in retained:
            continue
        if not visible_query(db, kind, user).filter(MODELS[kind].id == item_id).first():
            raise HTTPException(400, "关联内容不存在或无权查看，请重新选择")


def search_items(db: Session, kind: str, keyword: str, user: User) -> dict:
    if kind not in MODELS:
        raise HTTPException(400, "不支持的关联类型")
    model = MODELS[kind]
    query = visible_query(db, kind, user)
    match = keyword_like(keyword, model.name if kind == "resource" else model.title)
    if match is not None:
        query = query.filter(match)
    rows = query.order_by(model.id.desc()).limit(21).all()
    refs = [{"kind": kind, "id": row.id} for row in rows[:20]]
    return {"items": resolve_items(db, refs, user), "has_more": len(rows) > 20}


def mark_scope_differences(
    db: Session, items: list[dict], schedule_nos: set[str]
) -> None:
    """提示当前日程分组与事项的参与范围差异，只处理有权查看的事项。"""
    targets = {
        "vote": (PollTarget, PollTarget.poll_id),
        "collect": (CollectionTarget, CollectionTarget.collection_id),
        "checkin": (CheckinTarget, CheckinTarget.checkin_id),
    }
    for kind, (model, parent_id) in targets.items():
        ids = [
            item["id"]
            for item in items
            if item["kind"] == kind and not item.get("unavailable")
        ]
        if not ids:
            continue
        by_id = {item_id: set() for item_id in ids}
        for item_id, student_no in db.query(parent_id, model.student_no).filter(
            parent_id.in_(ids)
        ):
            by_id[item_id].add(student_no)
        for item in items:
            if item["kind"] == kind and item["id"] in by_id:
                item["scope_warning"] = by_id[item["id"]] != schedule_nos
