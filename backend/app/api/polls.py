"""投票（表决）：班委出卷，范围内的人一人一票，发起人实时看结果

四条贯穿全模块的口径，改任何一处都要一起想清楚：

1. **越权一律 404 而不是 403**。范围外的人不该知道「有这场投票」这件事，
   403 等于告诉他存在（同 api/feedback.py 的口径）。只有「看得见但时机不对」
   （未开始 / 已结束 / 已投过 / 不在表决范围内）才用 400 加一句能看懂的中文。
2. **状态、可见性、能不能投全由 services/poll_service.py 一处定义**，
   算好塞进响应（status / is_target / has_voted / results_visible / can_vote），
   前端只认字段不重算 —— 否则迟早出现「列表说能投、详情说不能」。
3. **不记名只做到接口级**（用户口径，不做数据库级）：库里照存 student_no，
   但接口永不返回「谁投了什么」。落地在 GET /{poll_id}/ballots，有断言守着。
4. **不许改票**：投过再提交直接 400，所以 poll_answers 里没有「先删后插」那一套。
"""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Poll, PollAnswer, PollQuestion, PollTarget, Student, User
from ..schemas import (
    PollBallotsResponse,
    PollCloseResponse,
    PollCreate,
    PollDetailResponse,
    PollListResponse,
    PollRemindResponse,
    PollRosterResponse,
    PollUpdate,
    PollVoteIn,
)
from ..services import account_name, log_operation, notify, recipients
from ..services.poll_service import (
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_PENDING,
    ballot_rows,
    can_manage,
    detail,
    filter_visible,
    has_voted,
    is_target,
    list_items,
    poll_status,
    question_options,
    voted_count,
)
from .deps import (
    ROLE_RANK,
    committee_required,
    get_client_ip,
    get_current_user,
    is_admin,
)

router = APIRouter(prefix="/api/polls", tags=["投票"])

# 前端固定传 20（同站内信），这个上限只是防手工构造请求一次拉全表
MAX_PAGE_SIZE = 100

STATUS_VALUES = (STATUS_PENDING, STATUS_OPEN, STATUS_CLOSED)

# 一次投票最多跨多久。纯属防手滑（把 2027 敲成 2072），不是业务规则
MAX_SPAN = timedelta(days=365)


# ---------- 取投票：可见与可管是两件事 ----------

def _get_poll(db: Session, poll_id: int) -> Poll:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="投票不存在")
    return poll


def _load_visible(db: Session, poll_id: int, user: User, admin: bool) -> Poll:
    """取一场「我看得见」的投票

    看得见 = 我在表决范围内，或者我是发起人 / 管理员。**其余一律 404** ——
    范围外的人拿不到「这场投票存在但你没份」这个信息（见模块开头的第 1 条）。
    与 services.poll_service.filter_visible 是同一个判断（那边过滤一批、这边判一条），
    改的时候必须一起改。
    """
    poll = _get_poll(db, poll_id)
    if not can_manage(poll, user.student_no, admin) and not is_target(
        db, poll_id, user.student_no
    ):
        raise HTTPException(status_code=404, detail="投票不存在")
    return poll


def _load_manageable(db: Session, poll_id: int, user: User, admin: bool) -> Poll:
    """取一场「我能管」的投票：只有发起人和管理员，其余 404

    催票 / 结束 / 删除 / 记名明细都走它 —— 同样不告诉别人「有这么一场投票你管不了」。
    """
    poll = _get_poll(db, poll_id)
    if not can_manage(poll, user.student_no, admin):
        raise HTTPException(status_code=404, detail="投票不存在")
    return poll


# ---------- 出卷校验 ----------

def _check_time(start_at: datetime, end_at: datetime) -> None:
    """时间校验。**带时区的输入直接拒，不静默去时区**

    前端 el-date-picker 用 value-format="YYYY-MM-DD HH:mm"，传的是不带时区的串，
    解析出来是 naive datetime，与库里的 datetime.now()（容器 TZ=Asia/Shanghai）
    同源可比。第三方客户端发的 ISO 里带 Z / +08:00 会解析成 aware datetime，
    拿去和 naive 的 now() 比较会抛 TypeError —— 而静默 strip 更糟，会悄悄错 8 小时，
    所以宁可在这里报一句错。
    """
    if start_at.tzinfo is not None or end_at.tzinfo is not None:
        raise HTTPException(
            status_code=400, detail="时间请用不带时区的写法，例如 2026-10-03 18:00"
        )
    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="截止时间必须晚于开始时间")
    if end_at <= datetime.now():
        raise HTTPException(status_code=400, detail="截止时间已经过了")
    if end_at - start_at > MAX_SPAN:
        raise HTTPException(status_code=400, detail="投票跨度不能超过一年")


def _check_questions(questions: list) -> list[dict]:
    """校验题目，归一成落库用的一份

    **单选强制 max_choices = 1，不信客户端**；多选的 max_choices 越界直接 400，
    不静默夹紧 —— 夹紧会把前端的 bug 掩盖成「我明明设了 3 项」。
    """
    normalized = []
    for index, question in enumerate(questions, start=1):
        title = (question.title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail=f"第 {index} 题的题干不能为空")
        options = [option.strip() for option in question.options]
        if any(not option for option in options):
            raise HTTPException(status_code=400, detail=f"第 {index} 题有空白选项")
        if len(set(options)) != len(options):
            raise HTTPException(status_code=400, detail=f"第 {index} 题有重复的选项")

        if question.multiple:
            if not 2 <= question.max_choices <= len(options):
                raise HTTPException(
                    status_code=400,
                    detail=f"第 {index} 题「最多选几项」要在 2 到 {len(options)} 之间",
                )
            max_choices = question.max_choices
        else:
            max_choices = 1
        normalized.append(
            {
                "title": title,
                "multiple": bool(question.multiple),
                "max_choices": max_choices,
                "options": options,
            }
        )
    return normalized


def _check_answers(questions: list[PollQuestion], answers: list) -> list[tuple]:
    """校验整卷作答，返回 [(题目, 下标列表), ...]

    **每题必答**：空选一律 400。要「弃权」就把它做成一个显式的选项 —— 否则
    「已投」的判定（poll_answers 里有没有我的行）会变得含糊：全弃权的人在库里
    一行都没有，看起来就像没投过。
    """
    submitted = {}
    for answer in answers:
        if answer.question_id in submitted:
            raise HTTPException(status_code=400, detail="同一道题提交了两次")
        submitted[answer.question_id] = answer

    # 交上来的题目必须**正好**是这张卷子上的那些。别图省事只比条数：
    # 漏一题、掺一题别场的进来，条数照样相等，下面按 id 取就会 KeyError（500）
    question_ids = {question.id for question in questions}
    if set(submitted) - question_ids:
        raise HTTPException(status_code=400, detail="提交了不属于本场投票的题目")
    if question_ids - set(submitted):
        raise HTTPException(status_code=400, detail="每题都要作答，不能有漏答")

    result = []
    for question in questions:
        choices = submitted[question.id].choices
        options = question_options(question)
        # 显式拦负数：Python 的 [-1] 是最后一个选项，放过去就等于让人投了他没选的那个
        if any(index < 0 or index >= len(options) for index in choices):
            raise HTTPException(status_code=400, detail=f"「{question.title}」的选项不存在")
        if len(set(choices)) != len(choices):
            raise HTTPException(status_code=400, detail=f"「{question.title}」有重复的选项")
        if question.multiple:
            if len(choices) > (question.max_choices or 2):
                raise HTTPException(
                    status_code=400,
                    detail=f"「{question.title}」最多选 {question.max_choices} 项",
                )
        elif len(choices) != 1:
            raise HTTPException(
                status_code=400, detail=f"「{question.title}」是单选题，只能选一项"
            )
        result.append((question, choices))
    return result


def _target_nos(db: Session, poll_id: int) -> list[str]:
    """这场投票的表决范围（学号），发起通知时循环用"""
    return [
        no
        for (no,) in db.query(PollTarget.student_no)
        .filter(PollTarget.poll_id == poll_id)
        .order_by(PollTarget.student_no)
    ]


# ---------- 接口 ----------

@router.get("", response_model=PollListResponse, summary="投票列表")
def list_polls(
    status: str | None = Query(None, description="按状态筛选：pending / open / closed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """只列我该看得见的：管理员和发起人看全部，其他人在表决名单里才看得见

    status 传了别的值就当没传（前端只会传这三个或空）。
    """
    admin = is_admin(user)
    query = filter_visible(db, db.query(Poll), user.student_no, admin)

    # 状态筛选必须落在 SQL 里，否则分页会算错（先取一页再在 Python 里滤，
    # 每页条数就不是 page_size 了）。下面三个条件和 poll_service.poll_status
    # **一一对应**，改那边必须回来改这里
    now = datetime.now()
    if status == STATUS_PENDING:
        query = query.filter(Poll.closed_at.is_(None), Poll.start_at > now)
    elif status == STATUS_OPEN:
        query = query.filter(
            Poll.closed_at.is_(None), Poll.start_at <= now, Poll.end_at >= now
        )
    elif status == STATUS_CLOSED:
        query = query.filter(
            or_(Poll.closed_at.is_not(None), Poll.end_at < now)
        )

    total = query.count()
    polls = (
        query.order_by(Poll.created_at.desc(), Poll.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": list_items(db, polls, user.student_no, admin),
    }


# ---------- 固定路径必须定义在 /{poll_id} 之前（本项目已踩过 422 那个坑） ----------
@router.get("/roster", response_model=PollRosterResponse, summary="出卷可选的学生名单（班委及以上）")
def get_roster(
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """出卷时勾人用：在校状态正常的学生，带「是不是班委」和「政治面貌」给快捷键

    **「是不是班委」必须 join users.role，绝不能读 students.class_position** ——
    那个字段学生自己在「我的信息 → 申请修改」里就能提交改，拿它当权限等于允许自我
    提权（models/user.py 里 role 那一列写得很清楚）。这是最容易踩进去的一个坑。

    政治面貌则是**学生档案里的普通字段**，读它没有问题 —— 「仅团员」筛的是身份、
    不是权限。
    """
    students = (
        db.query(Student)
        .filter(Student.school_status == "正常")
        .order_by(Student.student_no)
        .all()
    )
    roles = dict(db.query(User.student_no, User.role).all())
    return {
        "items": [
            {
                "student_no": student.student_no,
                "name": student.name or student.student_no,
                "committee": ROLE_RANK.get(roles.get(student.student_no) or "student", 0)
                >= ROLE_RANK["committee"],
                "political_status": student.political_status or "",
            }
            for student in students
        ]
    }


@router.post("", response_model=PollDetailResponse, summary="发起投票（班委及以上）")
def create_poll(
    data: PollCreate,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """出卷：题目、参与范围、起止时间、记名不记名，一次定完

    发出去之后标题和描述随时能改（下面的 update_poll），**题目只有还没开始时能改**
    —— 作答存的是选项**下标**，已经开始之后再动题目会让历史作答整体错位。
    """
    _check_time(data.start_at, data.end_at)
    questions = _check_questions(data.questions)

    # 参与范围：勾的学号得真存在且在正常在校状态（与点名同口径）。
    # 有人对不上就当场拒，而不是悄悄少几个人 —— 少掉的可能是发起人特意勾的
    targets = list(dict.fromkeys(data.targets))  # 去重，但保持勾选顺序无关紧要
    students = (
        db.query(Student)
        .filter(Student.student_no.in_(targets), Student.school_status == "正常")
        .all()
    )
    if len(students) != len(targets):
        raise HTTPException(
            status_code=400,
            detail=f"选中的 {len(targets)} 人里有 {len(targets) - len(students)} 人不存在或不在正常在校状态",
        )

    poll = Poll(
        title=data.title.strip(),
        description=(data.description or "").strip(),
        anonymous=bool(data.anonymous),
        start_at=data.start_at,
        end_at=data.end_at,
        creator_no=user.student_no,
        creator_name=account_name(db, user),
        created_at=datetime.now(),
    )
    db.add(poll)
    db.flush()  # 先 flush 拿到自增 id，题目和名单都要用
    db.add_all(
        [
            PollQuestion(
                poll_id=poll.id,
                sort=index,
                title=question["title"],
                multiple=question["multiple"],
                max_choices=question["max_choices"],
                options=json.dumps(question["options"], ensure_ascii=False),
            )
            for index, question in enumerate(questions)
        ]
    )
    db.add_all(
        [
            PollTarget(poll_id=poll.id, student_no=s.student_no, student_name=s.name)
            for s in students
        ]
    )
    # 不传 target_student_nos：范围动辄几十人，传了会给每个被投学生的「被操作记录」
    # 都塞一条，噪音大于价值（点名传它是因为那确实关乎每个被点的人）
    log_operation(
        db,
        user,
        action="发起投票",
        target=poll.title,
        detail=f"范围 {len(students)} 人，{len(questions)} 题，"
        f"{'不记名' if poll.anonymous else '记名'}",
        ip=ip,
    )
    db.commit()

    # 通知放在 commit 之后：notify 里的站内信写入自己会 commit，不能让它替我们
    # 提交「建投票」这笔半截事务（全项目 19 处调用点都是「先改状态、commit、再通知」）
    body = f"共 {len(questions)} 题，{poll.end_at:%m-%d %H:%M} 截止"
    if poll.anonymous:
        body += "（不记名）"
    for student_no in _target_nos(db, poll.id):
        notify(
            db,
            background,
            # 逐个人调 recipients：范围是任意子集，recipients 没有「批量学号」参数，
            # 要加就得同时改 bark / webpush / email / webhook 四个渠道服务。
            # 班级几十人，循环更简单也更不容易改错（同 api/notices.py 的说明）。
            # exclude_no 把自己排除掉 —— 自己发起的投票不用推给自己
            recipients(db, only_no=student_no, exclude_no=user.student_no),
            f"新投票：{poll.title}",
            body,
            level="timeSensitive",
            page=f"/vote?id={poll.id}",
        )
    return detail(db, poll, user.student_no, is_admin(user))


@router.patch("/{poll_id}", response_model=PollDetailResponse, summary="编辑投票（发起人/管理员）")
def update_poll(
    poll_id: int,
    data: PollUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """改标题和描述；还没开始的还能整卷换题目

    **题目只在这张卷子还没开始时能改**：作答存的是选项**下标**（models/poll.py 的
    PollQuestion 写着这件事），已经开始之后删掉一个选项，历史作答的下标就整体错位。
    没开始时库里不可能有这场投票的作答 —— can_vote 要求状态是 open，而 open 是按
    start_at 现算的，没到点谁也提交不上来。所以那时把旧题删掉重建最省事：
    不用按题号去 diff（题干改了、选项多一个少一个都要小心对齐），也不会留下废题。

    时间、表决范围、记名与否都不在这里 —— 见 schemas/poll.py 的 PollUpdate。
    """
    poll = _load_manageable(db, poll_id, user, is_admin(user))

    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    description = (data.description or "").strip()

    # 日志里写清改了哪几样。只记一个标题的话，「改了描述」和「原样提交了一次」
    # 在操作日志上长得一模一样
    changed = []
    if title != poll.title:
        changed.append("标题")
    if description != (poll.description or ""):
        changed.append("描述")

    if data.questions is not None:
        if poll_status(poll) != STATUS_PENDING:
            raise HTTPException(status_code=400, detail="投票已经开始，题目改不了了")
        questions = _check_questions(data.questions)
        # 先删干净再重建。**SQLite 默认不开外键约束**，顺序上只删题目这一张表，
        # 不会留下孤儿行（同上面删除接口那段的注释）
        db.query(PollQuestion).filter(PollQuestion.poll_id == poll.id).delete(
            synchronize_session=False
        )
        db.add_all(
            [
                PollQuestion(
                    poll_id=poll.id,
                    sort=index,
                    title=question["title"],
                    multiple=question["multiple"],
                    max_choices=question["max_choices"],
                    options=json.dumps(question["options"], ensure_ascii=False),
                )
                for index, question in enumerate(questions)
            ]
        )
        changed.append(f"{len(questions)} 道题")

    poll.title = title
    poll.description = description
    log_operation(
        db,
        user,
        action="编辑投票",
        target=title,
        detail="改了" + "、".join(changed) if changed else "内容没变",
        ip=ip,
    )
    db.commit()
    return detail(db, poll, user.student_no, is_admin(user))


@router.get("/{poll_id}", response_model=PollDetailResponse, summary="投票详情")
def get_poll(
    poll_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """题目 + 我的作答 + 结果（看不到结果时 tallies 是 None）+ can_vote

    记名投票**不额外标注**，不记名才标出来（用户口径）：anonymous 字段就够了。
    """
    poll = _load_visible(db, poll_id, user, is_admin(user))
    return detail(db, poll, user.student_no, is_admin(user))


@router.post("/{poll_id}/vote", response_model=PollDetailResponse, summary="投票（整卷一次提交）")
def vote(
    poll_id: int,
    data: PollVoteIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """一人一卷、整卷一次提交，**投过就不能再投**（不许改票）

    下面三个判断合起来就是 poll_service.can_vote，拆开写只是为了让每种情况都回一句
    说得清楚的话（can_vote 那边是个布尔，够 detail 用）。
    """
    admin = is_admin(user)
    poll = _load_visible(db, poll_id, user, admin)
    if poll_status(poll) != STATUS_OPEN:
        raise HTTPException(status_code=400, detail="投票还没开始或已经结束")
    if not is_target(db, poll_id, user.student_no):
        # 看得见（是发起人或管理员）但不在名单里：能看不能投，说清楚原因
        raise HTTPException(status_code=400, detail="你不在本次投票的表决范围内")
    if has_voted(db, poll_id, user.student_no):
        raise HTTPException(status_code=400, detail="你已经投过票了，不能重复投票")

    questions = (
        db.query(PollQuestion)
        .filter(PollQuestion.poll_id == poll_id)
        .order_by(PollQuestion.sort.asc(), PollQuestion.id.asc())
        .all()
    )
    if not questions:
        # 出卷时至少一题，理论上到不了这里；真遇到了也不该 500
        raise HTTPException(status_code=400, detail="这场投票没有题目")
    answers = _check_answers(questions, data.answers)

    db.add_all(
        [
            PollAnswer(
                poll_id=poll_id,
                question_id=question.id,
                student_no=user.student_no,
                choices=json.dumps(choices, ensure_ascii=False),
            )
            for question, choices in answers
        ]
    )
    try:
        db.commit()
    except IntegrityError:
        # 并发双击：两个请求可能都在上面 has_voted 时查不到旧行，但只有一个插得进去，
        # 另一个会撞 uq_poll_answer。撞了就是「已经投过票了」，不该冒成 500
        db.rollback()
        raise HTTPException(status_code=400, detail="你已经投过票了，不能重复投票")

    # 投票本身**不写操作日志**：一次投票一人一条，几十条会把日志淹掉。
    # 「谁投了什么」由 ballots 接口负责（记名时），那里才是该看的地方
    return detail(db, poll, user.student_no, admin)


@router.get(
    "/{poll_id}/ballots",
    response_model=PollBallotsResponse,
    summary="投票名单与记名明细（发起人/管理员）",
)
def get_ballots(
    poll_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """谁投了、谁没投（催票按它算未投人数）；记名投票再带上谁投了什么

    **不记名投票一样给这份名单**，只是每行的 choices 恒为 None ——
    「谁投了什么」在接口层就不返回（用户口径：不做数据库级不记名，接口级够了）。
    """
    poll = _load_manageable(db, poll_id, user, is_admin(user))
    return ballot_rows(db, poll)


@router.post(
    "/{poll_id}/remind",
    response_model=PollRemindResponse,
    summary="催还没投的人（发起人/管理员）",
)
def remind(
    poll_id: int,
    # BackgroundTasks 没有默认值，必须排在那些带默认值的参数前面（见 api/leaves.py 的注释）
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """给「还没投」的人各推一条提醒。四条口径：

    - 分母是**表决名单**（不是全班），只在名单里的人才有票可投
    - **已投的跳过**：催了也没用，人家已经投了
    - **冻结账号跳过**：投票接口会拒他们，推了也白推
    - **操作人自己跳过**：他正对着页面点催票，再给自己推一条纯属噪音

    前三条前端算按钮上的「未投 N 人」时要同样排除，否则按钮说 3 人、
    提示说「已提醒 1 人」，发起人会以为漏推了（api/notices.py 专门写过这条教训）。
    """
    poll = _load_manageable(db, poll_id, user, is_admin(user))
    if poll_status(poll) != STATUS_OPEN:
        # 没开始催了也投不了，结束了更没意义
        raise HTTPException(status_code=400, detail="只有进行中的投票才能催票")

    pending = [
        row
        for row in ballot_rows(db, poll)["rows"]
        if not row["voted"] and not row["frozen"] and row["student_no"] != user.student_no
    ]
    # 没人可催就直接返回：按钮在 0 人时是禁用的，走到这里说明名单是刚变的
    # （比如别人抢先投了）。这时记一条「已提醒 0 人」的日志只会让后来查日志的人困惑
    if not pending:
        return {"reminded": 0}

    for row in pending:
        # recipients 这里必然非空：站内信不看任何开关，有账号就有一份存档
        notify(
            db,
            background,
            recipients(db, only_no=row["student_no"]),
            f"提醒：{poll.title}",
            f"还没投票，{poll.end_at:%m-%d %H:%M} 截止",
            level="timeSensitive",
            page=f"/vote?id={poll.id}",
        )

    log_operation(
        db, user, action="催票", target=poll.title, detail=f"已提醒 {len(pending)} 人", ip=ip
    )
    db.commit()
    return {"reminded": len(pending)}


@router.post(
    "/{poll_id}/close", response_model=PollCloseResponse, summary="立即结束（发起人/管理员）"
)
def close_poll(
    poll_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """手动结束：把 closed_at 记成此刻。**重复调用幂等**

    幂等不只是「不报错」：已经结束就不再改写 closed_at（否则「什么时候结束的」会
    被每次点击往后推），也不再记日志（否则操作日志里会出现一串假记录）。
    写 closed_at 而不是改 end_at —— 改了就再也看不出这场原本打算什么时候截止。
    """
    poll = _load_manageable(db, poll_id, user, is_admin(user))
    votes = voted_count(db, poll.id)
    if poll_status(poll) == STATUS_CLOSED:
        return {"status": STATUS_CLOSED, "voted_count": votes}

    total = db.query(PollTarget).filter(PollTarget.poll_id == poll.id).count()
    poll.closed_at = datetime.now()
    log_operation(
        db,
        user,
        action="结束投票",
        target=poll.title,
        detail=f"已投 {votes}/{total} 人",
        ip=ip,
    )
    db.commit()
    return {"status": STATUS_CLOSED, "voted_count": votes}


@router.delete("/{poll_id}", summary="删除投票（发起人/管理员）")
def remove_poll(
    poll_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """删掉一场投票和它的全部痕迹

    **允许删已经有人投过的**（前端确认框会写明「已有 N 人投票」）：不然一张发错的
    卷子只要有人投过就永远纠正不了，只能一直挂在那里。
    """
    poll = _load_manageable(db, poll_id, user, is_admin(user))
    votes = voted_count(db, poll.id)
    title = poll.title

    # 先删明细再删本体，**SQLite 默认不开外键约束**，全靠这个顺序保证不留孤儿行
    # （同 api/attendance.py 删除那段的注释）。按 poll_id 一把删干净，这正是
    # poll_answers 单独存一份 poll_id 的价值 —— 否则只能靠 question_id IN (...) 绕
    for model in (PollAnswer, PollQuestion, PollTarget):
        db.query(model).filter(model.poll_id == poll.id).delete(synchronize_session=False)
    db.delete(poll)
    log_operation(db, user, action="删除投票", target=title, detail=f"已投 {votes} 人", ip=ip)
    db.commit()
    return {"message": "删除成功"}
