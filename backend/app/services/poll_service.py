"""投票的共用逻辑：状态、可见性、票数聚合、名单

**状态和可见性各只在这一个文件里定义**，四个接口共用，前端只读后端算好的字段。
分散着写迟早会出现「列表说能投、详情说不能」这种自相矛盾。

本模块只做数据，不做角色判断：角色是 api 层的事（全项目的 services 都不 import api），
所以需要「是不是管理员」的地方一律由调用方传一个 admin 布尔进来。
"""

import hashlib
import hmac
import json
from datetime import datetime
from functools import lru_cache

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import resolve_session_secret
from ..models import Poll, PollAnswer, PollQuestion, PollTarget, Student, User
from .scope_service import target_scope_label

# 四种状态。前端在 views/Vote.vue 和 utils/poll.js 里按这几个值分支，改的时候一起改
STATUS_PENDING = "pending"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
# 已暂停：发起人临时停止收票，**不是结束** —— 解锁后还能继续投
STATUS_LOCKED = "locked"


# ---------- 分享链接 ----------

@lru_cache(maxsize=1)
def _share_key() -> bytes:
    """分享签名的密钥。进程内只读一次，避免列表里每行都去读一次密钥文件"""
    return resolve_session_secret().encode("utf-8")


def poll_share_token(poll_id: int) -> str:
    """对外分享用的签名串，形如 `12.9f3a…`

    分享页要公开给微信爬虫（它不会登录），所以不能直接把自增 id 放在地址里 ——
    换个数字就能把全班的投票标题、截止时间看一遍。这里用会话密钥做 HMAC：
    同一个 id 永远得到同一个串，链接稳定；不知道密钥就伪造不出来。
    """
    sig = hmac.new(
        _share_key(), f"poll-share:{poll_id}".encode("utf-8"), hashlib.sha256
    ).hexdigest()[:16]
    return f"{poll_id}.{sig}"


def parse_poll_share_token(token: str) -> int | None:
    """校验分享串，返回投票 id。格式不对或签名不符一律 None（接口回 404）"""
    try:
        raw_id, _ = token.split(".", 1)
        poll_id = int(raw_id)
    except (AttributeError, ValueError):
        return None
    # compare_digest：别用 == 比签名，免得留下时序侧信道
    if not hmac.compare_digest(poll_share_token(poll_id), token):
        return None
    return poll_id


# ---------- 状态与可见性 ----------

def poll_status(poll: Poll, now: datetime | None = None) -> str:
    """未开始 / 进行中 / 已暂停 / 已结束

    表里**没有 status 列**，全靠 start_at、end_at、closed_at、locked_at 几个时刻现算 ——
    到点自动结束是「算出来」的，不需要有人定时去改状态（本项目没有为投票转的调度线程，
    存了状态列反而要担心它过期）。

    closed_at 优先于时间判断：手动结束之后，即便还没到 end_at 也算结束。

    **locked 那两条必须排在 end_at 那条之后**：暂停期间到了截止时间要照常自动结束
    （暂停只是不收票，不是把终点推后），锁着不放也不会让这场投票永远挂着。
    """
    now = now or datetime.now()
    if poll.closed_at is not None:
        return STATUS_CLOSED
    if now < poll.start_at:
        return STATUS_PENDING
    if now > poll.end_at:
        return STATUS_CLOSED
    if poll.locked_at is not None:
        return STATUS_LOCKED
    return STATUS_OPEN


def is_target(db: Session, poll_id: int, student_no: str) -> bool:
    """我在不在这场投票的表决范围内"""
    return (
        db.query(PollTarget.id)
        .filter(PollTarget.poll_id == poll_id, PollTarget.student_no == student_no)
        .first()
        is not None
    )


def has_voted(db: Session, poll_id: int, student_no: str) -> bool:
    """我投没投。一人一卷投一次、不许改票，所以「有没有我的行」就是答案"""
    return (
        db.query(PollAnswer.id)
        .filter(PollAnswer.poll_id == poll_id, PollAnswer.student_no == student_no)
        .first()
        is not None
    )


def results_visible(poll: Poll, student_no: str, admin: bool) -> bool:
    """我能不能看票数

    **发起人和管理员随时可见**（「实时查看结果」看的就是这个）；
    **其他参与者一律等投票结束**（截止或手动结束）才看得到 —— 中途看得见就给了
    「看一眼风向再投」的空间，何况本项目不许改票，投出去就只能认。
    """
    if admin or poll.creator_no == student_no:
        return True
    return poll_status(poll) == STATUS_CLOSED


def can_manage(poll: Poll, student_no: str, admin: bool) -> bool:
    """我能不能结束 / 催票 / 删除这场投票：只有发起人和管理员"""
    return admin or poll.creator_no == student_no


def can_vote(poll: Poll, in_target: bool, voted: bool, now: datetime | None = None) -> bool:
    """我现在能不能投。三条缺一不可

    「还没投过」这一条就是**不许改票**的落地 —— 投过之后按钮就没了。

    两条旗标由调用方传进来而不是自己查库：list_items 一次要算 20 条，
    那边已经把「我在不在名单里 / 投没投」批量查好了（见 _my_poll_ids），
    这里再各查一次就是 40 次多余查询。判定规则只留这一份。
    """
    return poll_status(poll, now) == STATUS_OPEN and in_target and not voted


def scope_label(db: Session, poll_id: int) -> str:
    """这场投票的公开范围标签（全班 / 班委 / 团员 / 定向 N 人）

    反推逻辑在 services/scope_service.py —— 收集复用同一份，避免两套口径。
    """
    target_nos = {
        no
        for (no,) in db.query(PollTarget.student_no).filter(
            PollTarget.poll_id == poll_id
        )
    }
    return target_scope_label(db, target_nos)


def filter_visible(db: Session, query, student_no: str, admin: bool):
    """把查询收窄到「我该看得见」的投票

    管理员和发起人不受限；其他人在名单里才看得见。范围外的人**压根不该知道有这场
    投票**（用户口径），所以列表里就滤掉，直接访问详情也按 404 处理。

    这段和 is_target 是同一件事的两种写法（一个过滤一批、一个判一条），
    **改的时候必须一起改**。
    """
    if admin:
        return query
    return query.filter(
        or_(
            Poll.creator_no == student_no,
            Poll.id.in_(
                db.query(PollTarget.poll_id).filter(PollTarget.student_no == student_no)
            ),
        )
    )


# ---------- 读 JSON 列 ----------

def question_options(question: PollQuestion) -> list[str]:
    """一道题的选项文案。存的是 JSON 数组，坏了就当空

    坏数据只让这道题少几个选项，不该把整个详情接口打成 500。
    """
    try:
        value = json.loads(question.options or "")
    except (ValueError, TypeError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def read_choices(answer: PollAnswer) -> list[int]:
    """一份作答选中的选项下标。存的是 JSON 数组，坏了就当空

    `isinstance(True, int)` 在 Python 里是 True，所以布尔要单独剔掉 ——
    真混进来会让 True 变成下标 1。
    """
    try:
        value = json.loads(answer.choices or "")
    except (ValueError, TypeError):
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]


# ---------- 计数与聚合 ----------

def _counts_of(db: Session, poll_ids: list[int]) -> dict:
    """一次查清一批投票的三个计数，供列表接口用（逐条查就是 3N 次查询）

    三项都是现算的，表里没有对应的计数列 —— 存了计数就要在每次作答时同步维护，
    两份数据迟早走散（同 models/attendance.py 对「不存计数」的说明）。
    """
    if not poll_ids:
        return {"questions": {}, "targets": {}, "voted": {}}
    return {
        "questions": dict(
            db.query(PollQuestion.poll_id, func.count(PollQuestion.id))
            .filter(PollQuestion.poll_id.in_(poll_ids))
            .group_by(PollQuestion.poll_id)
            .all()
        ),
        "targets": dict(
            db.query(PollTarget.poll_id, func.count(PollTarget.id))
            .filter(PollTarget.poll_id.in_(poll_ids))
            .group_by(PollTarget.poll_id)
            .all()
        ),
        # 一人一卷会投出多行，所以已投人数要数**人头**不是数行
        "voted": dict(
            db.query(PollAnswer.poll_id, func.count(func.distinct(PollAnswer.student_no)))
            .filter(PollAnswer.poll_id.in_(poll_ids))
            .group_by(PollAnswer.poll_id)
            .all()
        ),
    }


def voted_count(db: Session, poll_id: int) -> int:
    """一场投票的已投人数（结束/删除/催票三处都要报这个数）"""
    return _counts_of(db, [poll_id])["voted"].get(poll_id, 0)


def tally(db: Session, questions: list[PollQuestion], poll_id: int) -> dict[int, list[int]]:
    """每题每个选项各得几票，返回 {题目 ID: [票数, ...]}（下标与选项对齐）

    选项存在 JSON 列里，所以没法在 SQL 里按选项 GROUP BY，只能在 Python 侧数
    —— 班级几十人，这个量级无所谓（同 models/poll.py 的说明）。

    单选题的票数之和就是作答人数；多选题会大于它，前端要标出来。
    没有一个人选过的选项票数是 0（不是缺字段），前端照样要画出来。
    """
    result = {q.id: [0] * len(question_options(q)) for q in questions}
    if not result:
        return result
    answers = db.query(PollAnswer).filter(PollAnswer.poll_id == poll_id).all()
    for answer in answers:
        counts = result.get(answer.question_id)
        if counts is None:
            continue
        for index in read_choices(answer):
            # 越界的下标当不存在：正常情况下存不进去（接口会挡），
            # 万一有人手改了库，宁少算一票也不要 IndexError 把详情打成 500
            if 0 <= index < len(counts):
                counts[index] += 1
    return result


# ---------- 组装响应 ----------

def _questions_of(db: Session, poll_id: int) -> list[PollQuestion]:
    """一张卷子上的题，按题号排

    排序带上 id 兜底：sort 撞上时（手改库、或将来允许重排）顺序不会在
    两次请求之间跳来跳去。
    """
    return (
        db.query(PollQuestion)
        .filter(PollQuestion.poll_id == poll_id)
        .order_by(PollQuestion.sort.asc(), PollQuestion.id.asc())
        .all()
    )


def _my_poll_ids(db: Session, model, poll_ids: list[int], student_no: str) -> set[int]:
    """我在哪些投票里留过行（model 传 PollTarget 或 PollAnswer，两者都有 poll_id + student_no）"""
    if not poll_ids:
        return set()
    return {
        row[0]
        for row in db.query(model.poll_id)
        .filter(model.poll_id.in_(poll_ids), model.student_no == student_no)
        .all()
    }


def list_items(db: Session, polls: list[Poll], student_no: str, admin: bool) -> list[dict]:
    """把一批投票组装成响应字段

    列表接口一次 20 条，逐条去数题目/名单/作答就是 60 次查询，所以在外面批量查好。
    """
    poll_ids = [poll.id for poll in polls]
    counts = _counts_of(db, poll_ids)
    my_targets = _my_poll_ids(db, PollTarget, poll_ids, student_no)
    my_votes = _my_poll_ids(db, PollAnswer, poll_ids, student_no)

    items = []
    for poll in polls:
        # 看不到结果的人也不该看到投票率（参与者要等投票结束），所以两个计数给 0
        visible = results_visible(poll, student_no, admin)
        status = poll_status(poll)
        in_target = poll.id in my_targets
        voted = poll.id in my_votes
        items.append(
            {
                "id": poll.id,
                # 分享页地址里的签名串：前端用它拼微信卡片链接
                "share_token": poll_share_token(poll.id),
                "title": poll.title,
                "description": poll.description or "",
                "anonymous": bool(poll.anonymous),
                "status": status,
                "start_at": poll.start_at,
                "end_at": poll.end_at,
                "closed_at": poll.closed_at,
                "creator_no": poll.creator_no or "",
                "creator_name": poll.creator_name or "",
                "created_at": poll.created_at,
                "notify_on_start": bool(poll.notify_on_start),
                "start_notified_at": poll.start_notified_at,
                "question_count": counts["questions"].get(poll.id, 0),
                "target_count": counts["targets"].get(poll.id, 0) if visible else 0,
                "voted_count": counts["voted"].get(poll.id, 0) if visible else 0,
                "is_target": in_target,
                "has_voted": voted,
                "results_visible": visible,
                "can_manage": can_manage(poll, student_no, admin),
                # **列表里也得给 can_vote**：列表页「操作」列那唯一一个按钮的文案和
                # 去向全看它（utils/poll.js 的 actionText + Vote.vue 的 openDetail）。
                # 只在详情里给过一次的后果是：状态列写着「待投票」，操作列却永远写
                # 「查看结果」，点开是个没有作答控件的结果弹窗 —— 从列表根本投不了票，
                # 只有从站内信的深链（读详情）进得来。
                "can_vote": can_vote(poll, in_target, voted),
            }
        )
    return items


def detail(db: Session, poll: Poll, student_no: str, admin: bool) -> dict:
    """详情 = 列表项那份字段 + 题目（含我的作答、票数）"""
    data = list_items(db, [poll], student_no, admin)[0]

    questions = _questions_of(db, poll.id)
    # 看不到结果时索性不算票数，下游拿到的就是 None（省一次查询）
    tallies = tally(db, questions, poll.id) if data["results_visible"] else {}
    mine = {
        answer.question_id: read_choices(answer)
        for answer in db.query(PollAnswer).filter(
            PollAnswer.poll_id == poll.id, PollAnswer.student_no == student_no
        )
    }

    data["questions"] = [
        {
            "id": question.id,
            "sort": question.sort or 0,
            "title": question.title or "",
            "multiple": bool(question.multiple),
            "max_choices": question.max_choices or (2 if question.multiple else 1),
            "options": question_options(question),
            "my_choices": mine.get(question.id, []),
            # tallies 为空（不可见）时这里自然拿到 None
            "tallies": tallies.get(question.id),
        }
        for question in questions
    ]
    # can_vote 不用在这儿再算一遍：上面的 list_items 已经给过了（同一份规则）
    return data


def ballot_rows(db: Session, poll: Poll) -> dict:
    """谁投了、谁没投；记名投票再带上谁投了什么

    分母取 poll_targets，**不是** users 表：只有名单里的人才有表决权。
    被冻结的人不排除 —— 照样列在名单里、标记出来（他投不了票，催票也会跳过），
    否则「应投 30 人已投 12 人」对不上。

    不记名投票**照给这份名单**（催票要按它算未投人数），但每行的 choices 恒为 None：
    「谁投了什么」在接口层就不返回（用户口径：不做数据库级匿名，接口级够）。

    未投的排在前面 —— 打开这个名单就是为了找还没投的人。
    """
    targets = (
        db.query(PollTarget)
        .filter(PollTarget.poll_id == poll.id)
        .order_by(PollTarget.student_no)
        .all()
    )
    if not targets:
        return {"total": 0, "voted_count": 0, "rows": []}

    student_nos = [target.student_no for target in targets]
    # 名字优先取学生表里的现名（学生改了名，名单跟着变）；学生已删档就退回
    # 建投票时抄下来的快照 —— 这正是 poll_targets.student_name 那列存在的理由
    live_names = dict(
        db.query(Student.student_no, Student.name)
        .filter(Student.student_no.in_(student_nos))
        .all()
    )
    # 冻结与否只有 users 表知道（这个名单里不会有域外账号）
    frozen = dict(
        db.query(User.student_no, User.is_frozen)
        .filter(User.student_no.in_(student_nos))
        .all()
    )

    by_student: dict[str, list[PollAnswer]] = {}
    for answer in db.query(PollAnswer).filter(PollAnswer.poll_id == poll.id):
        by_student.setdefault(answer.student_no, []).append(answer)

    rows = []
    for target in targets:
        mine = by_student.get(target.student_no, [])
        rows.append(
            {
                "student_no": target.student_no,
                "name": live_names.get(target.student_no) or target.student_name or target.student_no,
                "voted": bool(mine),
                "voted_at": min(
                    (a.answered_at for a in mine if a.answered_at), default=None
                ),
                "frozen": bool(frozen.get(target.student_no)),
                # 不记名时恒为 None：接口层不返回「谁投了什么」
                "choices": None
                if poll.anonymous
                else {str(a.question_id): read_choices(a) for a in mine},
            }
        )

    rows.sort(key=lambda row: (row["voted"], row["student_no"]))
    return {
        "total": len(rows),
        "voted_count": sum(1 for row in rows if row["voted"]),
        "rows": rows,
    }
