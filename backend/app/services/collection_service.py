"""投票收集的共用逻辑：状态、可见性、份数统计、分享签名、答卷读取

和 poll_service 刻意分开：投票是一人一卷，收集是一人多份、按提交单管理。
两边共用的只有「范围标签」和文件/通知等基础能力。
"""

import hashlib
import hmac
import json
from datetime import datetime
from functools import lru_cache

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import resolve_session_secret
from ..models import (
    Collection,
    CollectionAnswer,
    CollectionQuestion,
    CollectionSubmission,
    CollectionTarget,
    Student,
    User,
)
from .scope_service import target_scope_label, target_scope_labels

# ---------- 状态 ----------

STATUS_PENDING = "pending"
STATUS_OPEN = "open"
STATUS_PAUSED = "paused"
STATUS_CLOSED = "closed"


def collection_status(collection: Collection, now: datetime | None = None) -> str:
    """未开始 / 进行中 / 已暂停 / 已结束

    和投票同一套顺序：closed_at 优先；到点自动结束排在暂停之前 ——
    暂停只是暂时不收，不是把终点推后，锁着到点也照常结束。
    """
    now = now or datetime.now()
    if collection.closed_at is not None:
        return STATUS_CLOSED
    if now < collection.start_at:
        return STATUS_PENDING
    if now > collection.end_at:
        return STATUS_CLOSED
    if collection.paused_at is not None:
        return STATUS_PAUSED
    return STATUS_OPEN


# ---------- 题型 ----------

QTYPE_SINGLE = "single"
QTYPE_MULTIPLE = "multiple"
QTYPE_SHORT_TEXT = "short_text"
QTYPE_LONG_TEXT = "long_text"
QTYPE_IMAGE = "image"
QTYPE_RATING = "rating"

QUESTION_TYPES = (
    QTYPE_SINGLE,
    QTYPE_MULTIPLE,
    QTYPE_SHORT_TEXT,
    QTYPE_LONG_TEXT,
    QTYPE_IMAGE,
    QTYPE_RATING,
)
CHOICE_TYPES = {QTYPE_SINGLE, QTYPE_MULTIPLE}
TEXT_TYPES = {QTYPE_SHORT_TEXT, QTYPE_LONG_TEXT}

# 这些是产品定的常量，不落库：改的时候前后端一起改
TEXT_LIMITS = {QTYPE_SHORT_TEXT: 200, QTYPE_LONG_TEXT: 2000}
RATING_MIN = 1
RATING_MAX = 5
IMAGE_MAX_FILES = 3

# 图片上传的后缀白名单（和签到照片一致）
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


# ---------- 分享签名 ----------

@lru_cache(maxsize=1)
def _share_key() -> bytes:
    return resolve_session_secret().encode("utf-8")


def collection_share_token(collection_id: int) -> str:
    """收集的对外分享签名串，形如 `12.9f3a…`

    和投票用同一个会话密钥，但 HMAC 文本前缀不同：同一个 id 不会和投票的签名串
    撞在一起，也不能拿投票的 token 去猜收集的。
    """
    sig = hmac.new(
        _share_key(),
        f"collection-share:{collection_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"{collection_id}.{sig}"


def parse_collection_share_token(token: str) -> int | None:
    try:
        raw_id, _ = token.split(".", 1)
        collection_id = int(raw_id)
    except (AttributeError, ValueError):
        return None
    if not hmac.compare_digest(collection_share_token(collection_id), token):
        return None
    return collection_id


# ---------- 可见性与权限 ----------

def is_target(db: Session, collection_id: int, student_no: str) -> bool:
    return (
        db.query(CollectionTarget.id)
        .filter(
            CollectionTarget.collection_id == collection_id,
            CollectionTarget.student_no == student_no,
        )
        .first()
        is not None
    )


def can_manage(collection: Collection, student_no: str, admin: bool) -> bool:
    """看详情、提醒、导出、关闭：发起人和管理员"""
    return admin or collection.creator_no == student_no


def filter_visible(db: Session, query, student_no: str, admin: bool):
    """列表收窄：管理员看全部；其他人只看自己发起或自己在范围内的"""
    if admin:
        return query
    return query.filter(
        or_(
            Collection.creator_no == student_no,
            Collection.id.in_(
                db.query(CollectionTarget.collection_id).filter(
                    CollectionTarget.student_no == student_no
                )
            ),
        )
    )


def cap_reached(collection: Collection) -> bool:
    """全局竞争名额是否已满（以原子计数器为准）"""
    return (
        collection.max_responses is not None
        and collection.response_count >= collection.max_responses
    )


def can_submit(
    collection: Collection, in_target: bool, my_submitted_count: int
) -> bool:
    return (
        collection_status(collection) == STATUS_OPEN
        and in_target
        and my_submitted_count < collection.submit_quota
        and not cap_reached(collection)
    )


def has_submissions(db: Session, collection_id: int) -> bool:
    """有没有人交过 —— 编辑时用来锁定题目结构和配额设置"""
    return (
        db.query(CollectionSubmission.id)
        .filter(CollectionSubmission.collection_id == collection_id)
        .first()
        is not None
    )


# ---------- 读取题目 / 答案 ----------

def questions_of(db: Session, collection_id: int) -> list[CollectionQuestion]:
    return (
        db.query(CollectionQuestion)
        .filter(CollectionQuestion.collection_id == collection_id)
        .order_by(CollectionQuestion.sort.asc(), CollectionQuestion.id.asc())
        .all()
    )


def question_options(question: CollectionQuestion) -> list[str]:
    try:
        value = json.loads(question.options or "")
    except (ValueError, TypeError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def read_choices(answer: CollectionAnswer | None) -> list[int]:
    if answer is None:
        return []
    try:
        value = json.loads(answer.choices or "")
    except (ValueError, TypeError):
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]


def read_files(answer: CollectionAnswer | None) -> list[dict]:
    if answer is None:
        return []
    try:
        value = json.loads(answer.files or "")
    except (ValueError, TypeError):
        return []
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, dict) and item.get("name"):
            result.append(
                {
                    "name": str(item.get("name")),
                    "original": str(item.get("original") or item.get("name")),
                    "size": int(item.get("size") or 0),
                }
            )
    return result


def question_payload(question: CollectionQuestion) -> dict:
    """题目的公开/作答定义：前端按 qtype 渲染、后端按同一份校验"""
    qtype = question.qtype or QTYPE_SINGLE
    return {
        "id": question.id,
        "sort": question.sort or 0,
        "title": question.title or "",
        "qtype": qtype,
        "required": bool(question.required),
        "options": question_options(question),
        "max_choices": question.max_choices,
        "text_limit": TEXT_LIMITS.get(qtype),
        "rating_min": RATING_MIN if qtype == QTYPE_RATING else None,
        "rating_max": RATING_MAX if qtype == QTYPE_RATING else None,
        "max_files": IMAGE_MAX_FILES if qtype == QTYPE_IMAGE else None,
    }


def answer_payload(question: CollectionQuestion, answer: CollectionAnswer | None) -> dict:
    qtype = question.qtype or QTYPE_SINGLE
    return {
        "question_id": question.id,
        "qtype": qtype,
        "choices": read_choices(answer),
        "text": (answer.text_value or "") if answer is not None else "",
        "rating": answer.rating if answer is not None else None,
        "files": read_files(answer),
    }


# ---------- 统计 ----------

def _counts_of(db: Session, collections: list[Collection]) -> dict:
    """一次查清一页收集的题目数、范围人数、提交份数、提交人数、完成人数"""
    ids = [collection.id for collection in collections]
    empty = {
        "questions": {},
        "targets": {},
        "submissions": {},
        "submitters": {},
        "completed": {},
    }
    if not ids:
        return empty

    questions = dict(
        db.query(CollectionQuestion.collection_id, func.count(CollectionQuestion.id))
        .filter(CollectionQuestion.collection_id.in_(ids))
        .group_by(CollectionQuestion.collection_id)
        .all()
    )
    targets = dict(
        db.query(CollectionTarget.collection_id, func.count(CollectionTarget.id))
        .filter(CollectionTarget.collection_id.in_(ids))
        .group_by(CollectionTarget.collection_id)
        .all()
    )
    per_student = db.query(
        CollectionSubmission.collection_id,
        CollectionSubmission.student_no,
        func.count(CollectionSubmission.id),
    ).filter(CollectionSubmission.collection_id.in_(ids)).group_by(
        CollectionSubmission.collection_id, CollectionSubmission.student_no
    ).all()

    submissions: dict[int, int] = {}
    submitters: dict[int, int] = {}
    completed: dict[int, int] = {}
    counts_by_collection: dict[int, list[int]] = {}
    for collection_id, _student_no, count in per_student:
        submissions[collection_id] = submissions.get(collection_id, 0) + count
        counts_by_collection.setdefault(collection_id, []).append(count)

    quota_by_id = {collection.id: collection.submit_quota for collection in collections}
    for collection_id, counts in counts_by_collection.items():
        submitters[collection_id] = len(counts)
        completed[collection_id] = sum(
            1 for count in counts if count >= quota_by_id.get(collection_id, 1)
        )

    return {
        "questions": questions,
        "targets": targets,
        "submissions": submissions,
        "submitters": submitters,
        "completed": completed,
    }


def _my_counts(db: Session, collection_ids: list[int], student_no: str) -> dict:
    if not collection_ids or not student_no:
        return {}
    rows = (
        db.query(CollectionSubmission.collection_id, func.count(CollectionSubmission.id))
        .filter(
            CollectionSubmission.collection_id.in_(collection_ids),
            CollectionSubmission.student_no == student_no,
        )
        .group_by(CollectionSubmission.collection_id)
        .all()
    )
    return {collection_id: count for collection_id, count in rows}


def _my_target_ids(db: Session, collection_ids: list[int], student_no: str) -> set[int]:
    if not collection_ids or not student_no:
        return set()
    return {
        collection_id
        for (collection_id,) in db.query(CollectionTarget.collection_id)
        .filter(
            CollectionTarget.collection_id.in_(collection_ids),
            CollectionTarget.student_no == student_no,
        )
        .all()
    }


def _target_sets(db: Session, collection_ids: list[int]) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    if not collection_ids:
        return result
    for collection_id, student_no in (
        db.query(CollectionTarget.collection_id, CollectionTarget.student_no)
        .filter(CollectionTarget.collection_id.in_(collection_ids))
        .all()
    ):
        result.setdefault(collection_id, set()).add(student_no)
    return result


def list_items(
    db: Session, collections: list[Collection], student_no: str, admin: bool
) -> list[dict]:
    """列表项：份数、我的进度、竞争名额、范围标签一次算好"""
    ids = [collection.id for collection in collections]
    counts = _counts_of(db, collections)
    my_counts = _my_counts(db, ids, student_no)
    my_targets = _my_target_ids(db, ids, student_no)
    target_sets = _target_sets(db, ids)
    labels = target_scope_labels(db, target_sets)

    items = []
    for collection in collections:
        status = collection_status(collection)
        my_count = my_counts.get(collection.id, 0)
        in_target = collection.id in my_targets
        max_responses = collection.max_responses
        remaining_slots = (
            max(0, max_responses - collection.response_count)
            if max_responses is not None
            else None
        )
        items.append(
            {
                "id": collection.id,
                "share_token": collection_share_token(collection.id),
                "title": collection.title or "",
                "description": collection.description or "",
                "anonymous": bool(collection.anonymous),
                "allow_withdraw": bool(collection.allow_withdraw),
                "status": status,
                "start_at": collection.start_at,
                "end_at": collection.end_at,
                "closed_at": collection.closed_at,
                "creator_name": collection.creator_name or "",
                "created_at": collection.created_at,
                "notify_on_start": bool(collection.notify_on_start),
                "start_notified_at": collection.start_notified_at,
                "question_count": counts["questions"].get(collection.id, 0),
                "target_count": counts["targets"].get(collection.id, 0),
                "submitted_count": counts["submissions"].get(collection.id, 0),
                "submitted_people": counts["submitters"].get(collection.id, 0),
                "completed_count": counts["completed"].get(collection.id, 0),
                "scope_label": labels.get(collection.id, ""),
                "submit_quota": collection.submit_quota,
                "max_responses": max_responses,
                "response_count": collection.response_count,
                "remaining_slots": remaining_slots,
                "cap_reached": cap_reached(collection),
                "my_submitted_count": my_count,
                "my_remaining": max(0, collection.submit_quota - my_count),
                "quota_reached": my_count >= collection.submit_quota,
                "is_target": in_target,
                "can_manage": bool(
                    student_no and can_manage(collection, student_no, admin)
                ),
                "can_submit": bool(
                    student_no and can_submit(collection, in_target, my_count)
                ),
            }
        )
    return items


def detail(db: Session, collection: Collection, student_no: str, admin: bool) -> dict:
    """详情 = 列表项 + 题目定义（不返回任何人的答卷）"""
    data = list_items(db, [collection], student_no, admin)[0]
    data["questions"] = [
        question_payload(question)
        for question in questions_of(db, collection.id)
    ]
    return data


def scope_label(db: Session, collection_id: int) -> str:
    target_nos = {
        no
        for (no,) in db.query(CollectionTarget.student_no).filter(
            CollectionTarget.collection_id == collection_id
        )
    }
    return target_scope_label(db, target_nos)


def my_submission_count(db: Session, collection_id: int, student_no: str) -> int:
    if not student_no:
        return 0
    return (
        db.query(func.count(CollectionSubmission.id))
        .filter(
            CollectionSubmission.collection_id == collection_id,
            CollectionSubmission.student_no == student_no,
        )
        .scalar()
        or 0
    )


# ---------- 答卷明细 ----------

def responses_page(
    db: Session,
    collection: Collection,
    page: int,
    page_size: int,
    order: str = "asc",
) -> tuple[int, list[dict]]:
    """管理端答卷分页，按提交时间排序（同秒用 id 兜底，翻页才稳定）

    匿名时**不返回学号/姓名**，只保留序号和答案；管理端仍可按 id 删除。
    """
    query = db.query(CollectionSubmission).filter(
        CollectionSubmission.collection_id == collection.id
    )
    total = query.count()
    if order == "desc":
        query = query.order_by(
            CollectionSubmission.submitted_at.desc(), CollectionSubmission.id.desc()
        )
    else:
        query = query.order_by(
            CollectionSubmission.submitted_at.asc(), CollectionSubmission.id.asc()
        )
    rows = (
        query.offset((page - 1) * page_size).limit(page_size).all()
    )
    if not rows:
        return total, []

    questions = questions_of(db, collection.id)
    question_map = {question.id: question for question in questions}
    answers = (
        db.query(CollectionAnswer)
        .filter(CollectionAnswer.submission_id.in_([row.id for row in rows]))
        .all()
    )
    by_submission: dict[int, dict[int, CollectionAnswer]] = {}
    for answer in answers:
        by_submission.setdefault(answer.submission_id, {})[answer.question_id] = answer

    # 姓名优先取学生表现名；删档后退回建活动时抄下的快照
    student_nos = [row.student_no for row in rows]
    live_names = dict(
        db.query(Student.student_no, Student.name)
        .filter(Student.student_no.in_(student_nos))
        .all()
    )
    snapshot_names = dict(
        db.query(CollectionTarget.student_no, CollectionTarget.student_name)
        .filter(
            CollectionTarget.collection_id == collection.id,
            CollectionTarget.student_no.in_(student_nos),
        )
        .all()
    )

    result = []
    for row in rows:
        answers_by_question = by_submission.get(row.id, {})
        payload = {
            "id": row.id,
            "seq_no": row.seq_no,
            "submitted_at": row.submitted_at,
            "duration_seconds": row.duration_seconds,
            "answers": [
                answer_payload(question, answers_by_question.get(question.id))
                for question in question_map.values()
                if question.id in answers_by_question
            ],
        }
        if not collection.anonymous:
            payload["student_no"] = row.student_no
            payload["student_name"] = (
                live_names.get(row.student_no)
                or snapshot_names.get(row.student_no)
                or row.student_no
            )
        result.append(payload)
    return total, result


def submission_payload(
    db: Session, collection: Collection, submission: CollectionSubmission
) -> dict:
    """一份答卷的形状（答题人回显自己的答卷用，不带姓名/学号）

    顺序按题目定义走，和下载图片接口的下标展开顺序一致。
    """
    questions = questions_of(db, collection.id)
    answers = {
        answer.question_id: answer
        for answer in db.query(CollectionAnswer)
        .filter(CollectionAnswer.submission_id == submission.id)
        .all()
    }
    return {
        "id": submission.id,
        "seq_no": submission.seq_no,
        "submitted_at": submission.submitted_at,
        "duration_seconds": submission.duration_seconds,
        "answers": [
            answer_payload(question, answers.get(question.id))
            for question in questions
            if question.id in answers
        ],
    }


def pending_rows(db: Session, collection: Collection) -> list[dict]:
    """还没达到每人配额的人（催填名单）

    匿名模式下调用方只展示「未完成」，不要把 submitted_count 暴露出去 ——
    「谁提交了几份」会削弱接口级匿名。
    """
    targets = (
        db.query(CollectionTarget)
        .filter(CollectionTarget.collection_id == collection.id)
        .order_by(CollectionTarget.student_no)
        .all()
    )
    counts = dict(
        db.query(CollectionSubmission.student_no, func.count(CollectionSubmission.id))
        .filter(CollectionSubmission.collection_id == collection.id)
        .group_by(CollectionSubmission.student_no)
        .all()
    )
    frozen = dict(
        db.query(User.student_no, User.is_frozen)
        .filter(User.student_no.in_([target.student_no for target in targets]))
        .all()
    ) if targets else {}

    rows = []
    for target in targets:
        submitted = counts.get(target.student_no, 0)
        if submitted >= collection.submit_quota:
            continue
        rows.append(
            {
                "student_no": target.student_no,
                "name": target.student_name or target.student_no,
                "submitted_count": submitted,
                "remaining": collection.submit_quota - submitted,
                "frozen": bool(frozen.get(target.student_no)),
            }
        )
    return rows


def duration_stats(db: Session, collection: Collection) -> dict:
    """答卷用时聚合；旧答卷、没带用时的答卷不计入

    只统计升级后新提交的答卷：旧数据没有开始时刻，补不出来。
    """
    values = [
        max(0, min(86400, int(value)))
        for (value,) in db.query(CollectionSubmission.duration_seconds)
        .filter(
            CollectionSubmission.collection_id == collection.id,
            CollectionSubmission.duration_seconds.isnot(None),
        )
        .all()
    ]
    if not values:
        return {
            "count": 0, "average_seconds": 0, "median_seconds": 0,
            "min_seconds": 0, "max_seconds": 0,
        }
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else round((ordered[middle - 1] + ordered[middle]) / 2)
    )
    return {
        "count": len(values),
        "average_seconds": round(sum(values) / len(values)),
        "median_seconds": median,
        "min_seconds": ordered[0],
        "max_seconds": ordered[-1],
    }


def statistics(db: Session, collection: Collection) -> list[dict]:
    """聚合统计：选择题给选项票数，评分给 1–5 分布，文本/图片只给份数"""
    questions = questions_of(db, collection.id)
    answers = (
        db.query(CollectionAnswer)
        .join(CollectionSubmission, CollectionSubmission.id == CollectionAnswer.submission_id)
        .filter(CollectionSubmission.collection_id == collection.id)
        .all()
    )
    by_question: dict[int, list[CollectionAnswer]] = {}
    for answer in answers:
        by_question.setdefault(answer.question_id, []).append(answer)

    result = []
    for question in questions:
        qtype = question.qtype or QTYPE_SINGLE
        items = by_question.get(question.id, [])
        entry = {
            "question_id": question.id,
            "title": question.title or "",
            "qtype": qtype,
            "answered_count": len(items),
        }
        if qtype in CHOICE_TYPES:
            options = question_options(question)
            counts = [0] * len(options)
            for answer in items:
                for index in read_choices(answer):
                    if 0 <= index < len(counts):
                        counts[index] += 1
            entry["options"] = options
            entry["counts"] = counts
        elif qtype == QTYPE_RATING:
            distribution = {str(value): 0 for value in range(RATING_MIN, RATING_MAX + 1)}
            total = 0
            for answer in items:
                if answer.rating is not None and RATING_MIN <= answer.rating <= RATING_MAX:
                    distribution[str(answer.rating)] += 1
                    total += answer.rating
            entry["distribution"] = distribution
            entry["average"] = round(total / len(items), 2) if items else 0
        elif qtype == QTYPE_IMAGE:
            entry["file_count"] = sum(len(read_files(answer)) for answer in items)
        result.append(entry)
    return result
