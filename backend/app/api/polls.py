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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
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
    PollShareResponse,
    PollUpdate,
    PollVoteIn,
)
from ..services import account_name, log_operation, notify, recipients
from ..services.list_filters import keyword_like
from ..services.poll_service import (
    STATUS_CLOSED,
    STATUS_LOCKED,
    STATUS_OPEN,
    STATUS_PENDING,
    ballot_rows,
    can_manage,
    detail,
    filter_visible,
    has_voted,
    is_target,
    list_items,
    parse_poll_share_token,
    poll_share_token,
    poll_status,
    question_options,
    scope_label,
    voted_count,
)
from ..services.share_service import share_path
from ..utils.links import full_url
from .deps import (
    ROLE_RANK,
    committee_required,
    get_client_ip,
    get_current_user,
    get_optional_user,
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


# ---------- 接口 ----------

@router.get("", response_model=PollListResponse, summary="投票列表")
def list_polls(
    status: str | None = Query(None, description="按状态筛选：pending / open / closed"),
    keyword: str | None = Query(None, description="按标题模糊搜索"),
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

    # 标题搜索也必须落在 SQL 里，理由同下面的状态筛选（分页要先算对 total）
    title_match = keyword_like(keyword, Poll.title)
    if title_match is not None:
        query = query.filter(title_match)

    # 状态筛选必须落在 SQL 里，否则分页会算错（先取一页再在 Python 里滤，
    # 每页条数就不是 page_size 了）。**这三档不等于状态的四种取值**：STATUS_OPEN
    # 那一档同时圈进「进行中」和「已暂停」—— 暂停只是中途歇一下，界面上仍归在
    # 「进行中」里（用户口径），所以 locked 的行没有、也不需要单独一条 SQL。
    # 改 poll_service.poll_status 时回来核一遍这里还等不等价
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


def _share_link(request: Request, poll: Poll) -> str:
    """对外的分享地址：真实路径，服务器能看到是哪一场

    不能用 `/#/vote?id=…`：hash 后面的内容不会发给服务器，微信爬虫拿不到
    这一场的 meta。真实路径由 nginx 返回 index.html 并注入 head 片段，
    浏览器落地后由 share-boot.js 映射到同一个应用内路由。
    """
    return full_url(request, share_path("vote", poll_share_token(poll.id)))


@router.get(
    "/share/{token}/info",
    response_model=PollShareResponse,
    summary="投票分享页公开信息（无需登录）",
)
def share_poll_info(
    token: str,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """外链分享页的数据源

    公开：标题、完整描述、范围、状态、起止时间、应投人数、题数；
    登录且在范围内（或发起人 / 管理员）：额外返回题目、我的作答和票数。
    游客与范围外的人拿不到题目、选项、票数、名单，也不含发起人学号
    （schema 没有继承 PollListItem，就是为了不把 creator_no 带出去）。
    """
    poll_id = parse_poll_share_token(token)
    poll = db.query(Poll).filter(Poll.id == poll_id).first() if poll_id else None
    if not poll:
        raise HTTPException(status_code=404, detail="分享链接无效或投票已删除")

    target_count = (
        db.query(PollTarget).filter(PollTarget.poll_id == poll.id).count()
    )
    question_count = (
        db.query(PollQuestion).filter(PollQuestion.poll_id == poll.id).count()
    )
    student_no = user.student_no if user else ""
    admin = is_admin(user) if user else False
    in_target = bool(user and is_target(db, poll.id, student_no))
    can_manage_this = bool(user and can_manage(poll, student_no, admin))
    in_scope = in_target or can_manage_this

    questions = []
    has_voted_this = False
    results = False
    can_vote_this = False
    voted = 0
    if in_scope:
        data = detail(db, poll, student_no, admin)
        questions = data["questions"]
        has_voted_this = data["has_voted"]
        results = data["results_visible"]
        can_vote_this = data["can_vote"]
        # detail → list_items 在结果不可见时会把两个计数置 0；应投人数是公开的，
        # 这里用真实计数覆盖。已投人数仍然只在结果可见时给真值。
        voted = data["voted_count"]

    return PollShareResponse(
        id=poll.id,
        share_token=token,
        title=poll.title or "",
        description=poll.description or "",
        anonymous=bool(poll.anonymous),
        status=poll_status(poll),
        start_at=poll.start_at,
        end_at=poll.end_at,
        closed_at=poll.closed_at,
        scope_label=scope_label(db, poll.id),
        question_count=question_count,
        target_count=target_count,
        voted_count=voted,
        is_login=user is not None,
        in_scope=in_scope,
        is_target=in_target,
        has_voted=has_voted_this,
        results_visible=results,
        can_manage=can_manage_this,
        can_vote=can_vote_this,
        questions=questions,
    )


@router.get(
    "/share/{token}",
    summary="旧投票分享链接（302 到新地址）",
    include_in_schema=False,
)
def share_poll(token: str, request: Request, db: Session = Depends(get_db)):
    """兼容老聊天里的链接：校验通过就 302 到新的真实路径

    新链接由 _share_link 直接给出 `/share/vote/{token}`，这个接口只为已经
    发出去的旧链接保留。用 302 不用 301：万一以后路径再调，浏览器不会把
    旧地址永久记住。无效签名仍回 404，不泄露「有这一场」。
    """
    poll_id = parse_poll_share_token(token)
    poll = db.query(Poll).filter(Poll.id == poll_id).first() if poll_id else None
    if not poll:
        raise HTTPException(status_code=404, detail="分享链接无效")
    return RedirectResponse(
        full_url(request, share_path("vote", token)),
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )


@router.post("", response_model=PollDetailResponse, summary="发起投票（班委及以上）")
def create_poll(
    data: PollCreate,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """出卷：题目、参与范围、起止时间、记名不记名，一次定完

    发出去之后标题和描述随时能改（下面的 update_poll），**题目只有还没开始时能改**
    —— 作答存的是选项**下标**，已经开始之后再动题目会让历史作答整体错位。

    **不在创建时通知**：出卷人用 notify_on_start 指定要不要在开始时间提醒；
    真正的发送在 services/start_notify_service.py，开始时间改了提醒自然跟着走。
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
        notify_on_start=bool(data.notify_on_start),
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

    # 创建时不发通知：到 start_at 由 start_notify_service 巡检发一次，
    # 出卷人是否要提醒由 notify_on_start 决定。
    return detail(db, poll, user.student_no, is_admin(user))


@router.patch("/{poll_id}", response_model=PollDetailResponse, summary="编辑投票（发起人/管理员）")
def update_poll(
    poll_id: int,
    data: PollUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """改标题、描述、时间和记名方式；还没开始的还能整卷换题目

    **时间按状态分档**，不是「编辑时一概不能改」：还没开始的两个都能改（把开场时间
    往后推 = 推迟开始，总比删了重发强）；**已经开始的只能改截止时间**（start_at 已经
    过去了，改它没有任何意义，还会把「开始时锁题」那条规则的依据弄乱）；**已结束的
    一个都不给改** —— closed_at 优先于时间判断，改了也不会生效，允许就是骗人。

    **题目和记名与否都只在这张卷子还没开始时能改** —— 两样都会「换一张票」：题目换了
    下标就错位（作答存的是选项**下标**，models/poll.py 的 PollQuestion 写着这件事），
    记名方式换了等于把已经投出去的票重新定义一遍（不记名的票突然有了主）。没开始时
    库里不可能有这场投票的作答 —— can_vote 要求状态是 open，而 open 是按 start_at
    现算的，没到点谁也提交不上来。所以那时把旧题删掉重建最省事：不用按题号去 diff
    （题干改了、选项多一个少一个都要小心对齐），也不会留下废题。

    表决范围才是真的一个字都不能动 —— 见 schemas/poll.py 的 PollUpdate。
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

    # 状态取一次，下面几处判据共用。**必须在任何改动落库之前取**：一次请求里的改动是
    # 原子的 —— 同时把开场时间提到现在、又改题目，两样都该算数
    status = poll_status(poll)

    # 时间先只校验、不往 poll 上写（赋值统一放到最后）
    if data.start_at is not None or data.end_at is not None:
        if status == STATUS_CLOSED:
            raise HTTPException(status_code=400, detail="投票已经结束，时间改不了了")
        if data.start_at is not None and status != STATUS_PENDING:
            raise HTTPException(status_code=400, detail="投票已经开始，开始时间改不了了")
        # 和出卷走同一套校验。**想提前收口就用「立即结束」**，别指望把截止时间拨到过去
        # —— 那条会被「截止时间已经过了」挡下，而这样正好：手动结束会写 closed_at，操作
        # 日志和详情里都看得出这场是被谁提前掐掉的，时间悄悄拨过去就什么都没留下
        _check_time(data.start_at or poll.start_at, data.end_at or poll.end_at)

    # 记名与否和题目同款：只有还没开始能改。开始之后再改，等于把已经投出去的那些票
    # 重新定义一遍（不记名的票突然有了主）；没开始时则没有任何作答可动摇
    if data.anonymous is not None:
        if status != STATUS_PENDING:
            raise HTTPException(status_code=400, detail="投票已经开始，记名方式改不了了")
        if data.anonymous != bool(poll.anonymous):
            poll.anonymous = data.anonymous
            changed.append("记名方式")

    # 开始提醒：只能在还没开始、且还没发过的时候改。开始时间改了，巡检自然按新时间走
    if data.notify_on_start is not None:
        if status != STATUS_PENDING or poll.start_notified_at is not None:
            raise HTTPException(status_code=400, detail="开始提醒只能在投票开始前设置")
        if data.notify_on_start != bool(poll.notify_on_start):
            poll.notify_on_start = data.notify_on_start
            changed.append("开始提醒")

    if data.questions is not None:
        if status != STATUS_PENDING:
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

    # 值真的变了才写、才记一笔。「原样回传」和「真改了」在日志上要分得开
    if data.start_at is not None and data.start_at != poll.start_at:
        poll.start_at = data.start_at
        changed.append("开始时间")
    if data.end_at is not None and data.end_at != poll.end_at:
        poll.end_at = data.end_at
        changed.append("截止时间")

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
    status = poll_status(poll)
    if status == STATUS_LOCKED:
        # 单独一条文案：暂停不是「还没开始或已经结束」，回那句会让人以为这场票黄了
        raise HTTPException(status_code=400, detail="投票已暂停，等发起人解锁后才能继续投")
    if status != STATUS_OPEN:
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
            page=share_path("vote", poll_share_token(poll.id)),
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


@router.post(
    "/{poll_id}/extend",
    response_model=PollDetailResponse,
    summary="延长投票截止时间 5 分钟（发起人/管理员）",
)
def extend_poll(
    poll_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """截止前可反复延长，每次 5 分钟（和签到的「延长5分钟」同一交互）

    只改 end_at，不动 start_at。已经手动结束（closed_at 有值）或已经过了 end_at
    就不能再延长 —— 否则等于把一场已经结束的投票重新拉回进行中。
    """
    poll = _load_manageable(db, poll_id, user, is_admin(user))
    if poll.closed_at is not None:
        raise HTTPException(status_code=400, detail="投票已经结束")
    now = datetime.now()
    if now >= poll.end_at:
        raise HTTPException(
            status_code=400, detail="已经过了截止时间，不能再延长"
        )

    before = poll.end_at
    poll.end_at = before + timedelta(minutes=5)
    log_operation(
        db,
        user,
        action="延长投票",
        target=poll.title,
        detail=f"截止 {before:%m-%d %H:%M} → {poll.end_at:%m-%d %H:%M}",
        ip=ip,
    )
    db.commit()
    return detail(db, poll, user.student_no, is_admin(user))


@router.post(
    "/{poll_id}/lock", response_model=PollDetailResponse, summary="暂停投票（发起人/管理员）"
)
def lock_poll(
    poll_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """暂停收票。**暂停不是结束**：解锁后照样能投

    到点还没解开就照常自动结束 —— 这条不用在这儿写任何代码，poll_service.poll_status
    里判断截止时间那一条排在锁定之前，算出来的自然就是「已结束」（见那个函数的说明）。

    只认「进行中」这一种状态：没开始的本来就没在收票，已结束的更谈不上暂停。
    **重复调用幂等**（同 close_poll）：已经暂停就不再改写 locked_at、也不再记日志，
    否则连点几次会把「什么时候暂停的」一直往后推。
    """
    admin = is_admin(user)
    poll = _load_manageable(db, poll_id, user, admin)
    status = poll_status(poll)
    if status == STATUS_LOCKED:
        # 这一条必须排在下面 != OPEN 那句**之前**：已经暂停的正是要幂等返回的那种，
        # 顺序写反了第二次点击就会拿到「只有进行中的投票才能暂停」
        return detail(db, poll, user.student_no, admin)
    if status != STATUS_OPEN:
        raise HTTPException(status_code=400, detail="只有进行中的投票才能暂停")

    poll.locked_at = datetime.now()
    log_operation(db, user, action="暂停投票", target=poll.title, ip=ip)
    db.commit()
    return detail(db, poll, user.student_no, admin)


@router.post(
    "/{poll_id}/unlock", response_model=PollDetailResponse, summary="恢复投票（发起人/管理员）"
)
def unlock_poll(
    poll_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """恢复收票：把 locked_at 清回 NULL。**重复调用幂等**

    **不判当前状态、无条件清空**：暂停期间到了截止时间的那种，状态早就自己变成
    已结束了，locked_at 却还挂在一条已结束的投票上。这时要是按状态判，会回一句
    「只有已暂停的投票才能恢复」—— 用户看到的却只是「票结束了，暂停的标记还留着」。
    清掉没有任何副作用：已结束的投票本来就不再收票。
    """
    admin = is_admin(user)
    poll = _load_manageable(db, poll_id, user, admin)
    was_locked = poll.locked_at is not None
    poll.locked_at = None
    if was_locked:
        # 本来就没暂停就别记一条「恢复投票」的假日志
        log_operation(db, user, action="恢复投票", target=poll.title, ip=ip)
    db.commit()
    return detail(db, poll, user.student_no, admin)


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
