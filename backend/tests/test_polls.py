"""投票的回归：出卷名单带得出政治面貌、点名收得下「共青团员」、投票能编辑、能暂停

    cd backend && python -m pytest tests -q

盯四件事：

1. GET /api/polls/roster 得把每个人的政治面貌带回给出卷弹窗。「仅团员」那枚快捷键
   的判据在前端（utils/roster.js 的 isLeagueMember），后端只要少回一个字段、
   或者字段名改成别的，前端就会静默筛出零个人 —— 点下去「已选 0 人」，不报错。

2. POST /api/attendance 的 scope 收得下「共青团员」。这一列是 String(10)、schema 上
   还有 max_length=10，四个汉字眼下放得下 —— 但那是恰好，不是设计。哪天有人顺手给它
   加个枚举白名单，点名选团员就会当场 400，而这类改动看起来完全无害。

3. PATCH /api/polls/{id} 编辑投票的边界。最容易写错、也最不该写错的是**题目只在
   没开始时能换**：作答存的是选项下标，已经开始之后再动题目，历史作答会整体错位，
   而库里的数据看不出任何异常。

4. POST /api/polls/{id}/lock 暂停收票。**暂停不是结束** —— 解开之后照样能投，
   锁着到截止时间则照常自动结束。最容易写丢的是后半句：它的落地方式仅仅是
   poll_service.poll_status 里判断截止时间那条排在暂停之前，谁把这两条调个个儿，
   被暂停过的投票就会永远挂在「已暂停」上，再没人能收尾。
"""
from datetime import datetime, timedelta

import pytest

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"

# 学号 → 政治面貌。**刻意放进「中共预备党员」和空值**：判据要是写成
# `includes('团员')` 之类的子串匹配，预备党员就会被算成团员 —— 那是这个功能里
# 唯一一处真正会出错的地方
PEOPLE = [
    ("2024000002", "共青团员"),
    ("2024000003", "群众"),
    ("2024000004", "共青团员"),
    ("2024000005", "中共预备党员"),
    ("2024000006", ""),
]
LEAGUE_NOS = ["2024000002", "2024000004"]


def _world(backend, db_name):
    """初始化完毕、库里 1 个管理员 + 5 个不同政治面貌的学生，**管理员已登录**

    学号决定初始密码（身份证后 6 位），所以 PEOPLE 里那几个人的密码是
    010002…010006 这一串，见 services/user_service.default_password。
    """
    b = backend(db=db_name, BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200

    r = b.client.post("/api/students", json={
        "student_no": ADMIN, "name": "甲", "id_card": "110101200501010001",
    })
    assert r.status_code < 300, r.text

    for no, ps in PEOPLE:
        r = b.client.post("/api/students", json={
            "student_no": no,
            "name": f"学生{no[-2:]}",
            "id_card": f"11010120050101{no[-4:]}",
            "political_status": ps,
        })
        assert r.status_code < 300, r.text

    assert b.client.post("/api/setup/finish", json={"admin_student_no": ADMIN}).status_code == 200
    b.logout()
    assert b.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200
    return b


@pytest.fixture
def pb(backend):
    return _world(backend, "polls.db")


# ---------- 出卷名单 ----------

def test_roster_carries_political_status(pb):
    """每项都带 political_status，取值和库里一致"""
    r = pb.client.get("/api/polls/roster")
    assert r.status_code == 200, r.text
    items = {s["student_no"]: s for s in r.json()["items"]}

    assert len(items) == len(PEOPLE) + 1, "在校状态正常的都该在名单里"
    for no, ps in PEOPLE:
        assert items[no]["political_status"] == ps, f"{no} 的政治面貌对不上"
    # 没填过政治面貌的回**空串**而不是 None：前端判据比的是字符串，null 会当场漏掉
    assert items[ADMIN]["political_status"] == ""


def test_league_filter_yields_exactly_the_league_members(pb):
    """拿前端那条判据（political_status == '共青团员'）筛，筛出来的人得正好对

    这条断的是「后端回什么」和「前端怎么筛」之间的接缝。预备党员和空值都不能混进来。
    """
    items = pb.client.get("/api/polls/roster").json()["items"]
    league = [s["student_no"] for s in items if s["political_status"] == "共青团员"]
    assert sorted(league) == LEAGUE_NOS


def test_roster_needs_committee_and_up(pb):
    """普通学生拉不到这份名单 —— 接口权限没被这次改动松开"""
    pb.logout()
    assert pb.login(student_no="2024000002", password="010002").status_code == 200
    assert pb.client.get("/api/polls/roster").status_code == 403


# ---------- 点名范围 ----------

def test_roll_call_accepts_league_scope(pb):
    """scope 收得下「共青团员」，而且原样落库不截断"""
    r = pb.client.post("/api/attendance", json={
        "scope": "共青团员",
        "records": [
            {"student_no": LEAGUE_NOS[0], "name": "学生02", "status": "present"},
            {"student_no": LEAGUE_NOS[1], "name": "学生04", "status": "absent"},
        ],
    })
    assert r.status_code < 300, r.text

    rows = pb.rows("SELECT scope FROM attendance_records ORDER BY id DESC LIMIT 1")
    assert rows and rows[0][0] == "共青团员", "范围名要原样存下来，不能截断"


def test_roll_call_rejects_an_overlong_scope(pb):
    """反过来：超过 10 个字的范围名仍然要被拒

    上面那条只是说「共青团员」放得下，不是把长度上限拆了 —— 上限还在，两件事一起
    看才说明白。
    """
    r = pb.client.post("/api/attendance", json={
        "scope": "这是一个特别长的范围名字",
        "records": [{"student_no": LEAGUE_NOS[0], "name": "学生02", "status": "present"}],
    })
    assert r.status_code == 422, r.text


# ---------- 编辑投票（PATCH /api/polls/{id}）----------
#
# 口径：标题和描述随时能改；**题目和记名与否只有还没开始时能改**（题目换了作答
# 的下标就错位，记名换了等于把投出去的票重新定义一遍）。**表决范围任何状态都不
# 在可编辑之列** —— 它改了会动摇已经投出去的票。**时间是另一节**（见下面「改时间」）
# 按状态分档，**记名是再下面那一节**。

CREATOR = "2024000002"  # 提成班委用来出卷
CREATOR_PW = "010002"
VOTER = "2024000003"  # 在表决范围内、但不是发起人
VOTER_PW = "010003"


def _stamp(hours):
    """相对现在的一个时刻，形状与 el-date-picker 的 value-format 一致（不带时区）"""
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")


def _body(start=2, end=3, *, title="要不要聚餐", targets=None, options=None):
    """发起投票的请求体：默认 1 道单选、2 个选项、只让 VOTER 投票"""
    return {
        "title": title,
        "description": "",
        "anonymous": False,
        "start_at": _stamp(start),
        "end_at": _stamp(end),
        "targets": targets or [VOTER],
        "questions": [{
            "title": "你赞成哪个方案？",
            "multiple": False,
            "max_choices": 1,
            "options": options or ["方案一", "方案二"],
        }],
    }


def _create(b, **kw):
    """以当前登录人的身份发一场投票，返回它的 ID"""
    r = b.client.post("/api/polls", json=_body(**kw))
    assert r.status_code < 300, r.text
    return r.json()["id"]


def _edit(b, poll_id, **payload):
    return b.client.patch(f"/api/polls/{poll_id}", json=payload)


def _start_now(b, poll_id):
    """把 start_at 拨到一小时前 = 让这场投票真的开始

    直接改库、不走编辑接口：**开始时间一旦过去就改不了了**（update_poll 只让还没开始
    的投票改 start_at），而测试里等真实时间过去不现实。**这正是这一整套要跑的路径**
    —— 没开始时改题目 → 到点开始 → 大家按新卷子投。
    """
    b.run(
        "UPDATE polls SET start_at = ? WHERE id = ?",
        (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
        poll_id,
    )


@pytest.fixture
def pe(backend):
    """和 pb 同一套人，但**发起人和管理员是两个不同的人**：2024000002 提成班委出卷

    两者不能是同一个人 —— 那样「管理员能编辑别人的投票」这条根本测不到，
    _load_manageable 里的权限判据写成 `creator_no == me` 也照样过。回来时是
    2024000002 登录着（发起人视角）。
    """
    b = _world(backend, "polls_edit.db")
    r = b.client.put(f"/api/admin/users/{CREATOR}/role", json={"role": "committee"})
    assert r.status_code < 300, r.text
    b.logout()
    assert b.login(student_no=CREATOR, password=CREATOR_PW).status_code == 200
    return b


def test_creator_edits_title_and_description(pe):
    """改标题描述当场生效；**不传题目就一根手指头都不碰题目**"""
    pid = _create(pe)
    before = pe.client.get(f"/api/polls/{pid}").json()["questions"]

    r = _edit(pe, pid, title="改过的标题", description="补一句背景")
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "改过的标题"
    assert r.json()["description"] == "补一句背景"

    # 题目要原样：**题目 ID 一模一样**。顺手整卷重建一遍最省事，但 ID 会变，
    # 正在填作答的人提交上来就会被判成「提交了不属于本场投票的题目」
    after = pe.client.get(f"/api/polls/{pid}").json()["questions"]
    assert [q["id"] for q in after] == [q["id"] for q in before]
    assert [q["options"] for q in after] == [q["options"] for q in before]

    # 列表页读的也是改过的标题（前端保存后只拉列表，不拉详情）
    assert pe.client.get("/api/polls").json()["items"][0]["title"] == "改过的标题"

    # 标题不能改成空白：详情接口的 title 是必填的，留白了列表会显示成一片空白
    assert _edit(pe, pid, title="   ", description="").status_code == 400


def test_admin_edits_someone_elses_poll(pe):
    """管理员能改别人发起的投票 —— 这条和上面那条是两个判据，得分开钉"""
    pid = _create(pe)
    pe.logout()
    assert pe.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200

    r = _edit(pe, pid, title="管理员改的", description="")
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "管理员改的"
    assert r.json()["creator_no"] == CREATOR, "改的是内容，发起人不会跟着变成管理员"


def test_questions_can_be_replaced_before_start(pe):
    """没开始时整卷能换，**换完还得真能投**"""
    pid = _create(pe)
    old = pe.client.get(f"/api/polls/{pid}").json()["questions"]

    r = _edit(pe, pid, title="要不要聚餐", description="", questions=[{
        "title": "改过的题干", "multiple": False, "max_choices": 1,
        "options": ["甲", "乙", "丙"],
    }])
    assert r.status_code == 200, r.text
    questions = r.json()["questions"]
    assert len(questions) == 1
    assert questions[0]["title"] == "改过的题干"
    assert questions[0]["options"] == ["甲", "乙", "丙"]
    assert len(old) == 1, "起手就该只有一题，下面那条行数断言才有意义"

    # 旧题必须**真从库里删掉**。SQLite 默认不开外键约束，孤儿行不会自己消失，
    # 只会变成详情里凭空多出来的一题（同 api/polls.py 删除接口那段的注释）。
    #
    # 这里**不查「题目 ID 变了没有」**：SQLite 的 rowid 取 max(rowid)+1，把表删空之后
    # 新插入的行会重新拿到 1 —— 那种断言看着挺合理，其实一直在骗人
    assert pe.rows("SELECT COUNT(*) FROM poll_questions WHERE poll_id = ?", pid)[0][0] == 1

    # **这一条才是整件事的落点**：换过的卷子拿新题目的 ID 投，必须投得进去。
    # 旧题没删干净、或者详情回的 ID 和库里对不上，这里就会回
    # 「提交了不属于本场投票的题目」
    _start_now(pe, pid)
    pe.logout()
    assert pe.login(student_no=VOTER, password=VOTER_PW).status_code == 200
    r = pe.client.post(f"/api/polls/{pid}/vote", json={
        "answers": [{"question_id": questions[0]["id"], "choices": [2]}],
    })
    assert r.status_code < 300, r.text


def test_questions_are_frozen_once_started(pe):
    """已经开始就不能换题目了 —— 中文原因，不是 422 的数组"""
    pid = _create(pe, start=-1, end=1)  # start_at 在过去 = 进行中

    r = _edit(pe, pid, title="要不要聚餐", description="", questions=[{
        "title": "偷偷换一题", "multiple": False, "max_choices": 1,
        "options": ["甲", "乙"],
    }])
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, str) and "开始" in detail, detail

    # 题目没被动过
    after = pe.client.get(f"/api/polls/{pid}").json()["questions"]
    assert [q["title"] for q in after] == ["你赞成哪个方案？"]

    # 但标题描述照样能改：封的是题目，不是整场投票
    assert _edit(pe, pid, title="进行中也能改标题", description="").status_code == 200


def test_edit_is_404_for_anyone_else(pe):
    """范围里的人也不行，一律 404（本模块开头第 1 条：不泄露「存在但你管不了」）"""
    pid = _create(pe)
    pe.logout()
    assert pe.login(student_no=VOTER, password=VOTER_PW).status_code == 200

    assert _edit(pe, pid, title="我说了算", description="").status_code == 404

    # 真没改动：换回发起人看，标题还是原来那个
    pe.logout()
    assert pe.login(student_no=CREATOR, password=CREATOR_PW).status_code == 200
    assert pe.client.get(f"/api/polls/{pid}").json()["title"] == "要不要聚餐"


# ---------- 暂停 / 恢复（POST /api/polls/{id}/lock | /unlock）----------
#
# 口径：**暂停不是结束**。暂停只是临时不收票，解锁后照样能投；锁着到点没解开则
# 照常自动结束。所以这一节盯的不是「状态翻没翻」，而是**解除之后真投得进去**，
# 以及**锁着到点了会不会自己停** —— 后者靠 poll_status 里判断截止时间那条排在
# 暂停之前，一旦有人把它们调换，这场投票就会永远挂在「已暂停」上没人能收尾。


def _lock(b, poll_id):
    return b.client.post(f"/api/polls/{poll_id}/lock")


def _unlock(b, poll_id):
    return b.client.post(f"/api/polls/{poll_id}/unlock")


def _set_end(b, poll_id, hours):
    """把截止时间拨到相对现在 hours 小时之后（负数 = 已经过点）

    同 _start_now：编辑接口里没有时间字段，测「到点自动结束」只能直接改库。
    """
    b.run(
        "UPDATE polls SET end_at = ? WHERE id = ?",
        (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S.%f"),
        poll_id,
    )


def _vote_as(b, student_no, password, poll_id, choices=(0,)):
    """换个人登录去把这场投了（_body 里只有一题）。返回响应对象"""
    b.logout()
    assert b.login(student_no=student_no, password=password).status_code == 200
    question_id = b.client.get(f"/api/polls/{poll_id}").json()["questions"][0]["id"]
    return b.client.post(f"/api/polls/{poll_id}/vote", json={
        "answers": [{"question_id": question_id, "choices": list(choices)}],
    })


def _as_creator(b):
    """切回发起人视角（_vote_as 会把登录切成别人）"""
    b.logout()
    assert b.login(student_no=CREATOR, password=CREATOR_PW).status_code == 200


def test_lock_then_unlock_then_vote(pe):
    """**暂停不是结束**：锁着投不进、解开就投得进 —— 这一条是整件事的落点"""
    pid = _create(pe, start=-1, end=2)  # start_at 在过去 = 进行中

    r = _lock(pe, pid)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "locked"
    assert r.json()["can_vote"] is False, "锁着的时候谁都不该还能投"

    blocked = _vote_as(pe, VOTER, VOTER_PW, pid)
    assert blocked.status_code == 400, blocked.text
    # **必须是「暂停」那句**：回「还没开始或已经结束」会让人以为这场票黄了，
    # 而它其实只是歇一会儿
    assert "暂停" in blocked.json()["detail"], blocked.json()
    assert pe.rows("SELECT COUNT(*) FROM poll_answers WHERE poll_id = ?", pid)[0][0] == 0

    _as_creator(pe)
    assert _unlock(pe, pid).json()["status"] == "open"

    r = _vote_as(pe, VOTER, VOTER_PW, pid)
    assert r.status_code < 300, r.text
    assert pe.rows("SELECT COUNT(*) FROM poll_answers WHERE poll_id = ?", pid)[0][0] == 1


def test_locked_poll_still_shows_results_and_ballots(pe):
    """锁定期结果和名单照常看得到（用户口径：可见性规则一行都不改）"""
    pid = _create(pe, start=-1, end=2)
    assert _vote_as(pe, VOTER, VOTER_PW, pid).status_code < 300
    _as_creator(pe)
    assert _lock(pe, pid).status_code == 200

    detail = pe.client.get(f"/api/polls/{pid}").json()
    assert detail["results_visible"] is True
    assert detail["questions"][0]["tallies"] == [1, 0], "发起人锁定期照样看得到票数"
    assert detail["voted_count"] == 1
    assert pe.client.get(f"/api/polls/{pid}/ballots").json()["voted_count"] == 1


def test_locked_poll_closes_at_its_deadline(pe):
    """锁着到点了就照常结束 —— 不用谁去解锁，也不会永远挂着"""
    pid = _create(pe, start=-2, end=1)
    assert _lock(pe, pid).json()["status"] == "locked"

    _set_end(pe, pid, -1)  # 截止时间过了，locked_at 还原样挂着

    detail = pe.client.get(f"/api/polls/{pid}").json()
    assert detail["status"] == "closed", "判断截止时间那条要排在暂停之前"
    assert detail["can_vote"] is False

    # 解锁**不判当前状态**：这种「票已经结束了、暂停的标记还留着」的局面点一下
    # 就能清掉，不该回一句「只有已暂停的投票才能恢复」——用户看到的只是「标记还在」
    r = _unlock(pe, pid)
    assert r.status_code == 200, r.text
    assert pe.rows("SELECT locked_at FROM polls WHERE id = ?", pid)[0][0] is None


def test_locked_poll_can_still_be_closed(pe):
    """暂停期间照样能「立即结束」：想收口的人不该先被迫解锁一次"""
    pid = _create(pe, start=-1, end=2)
    assert _lock(pe, pid).status_code == 200

    r = pe.client.post(f"/api/polls/{pid}/close")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed"


def test_lock_needs_creator_or_admin(pe):
    """表决范围里的普通成员也锁不动 —— 一律 404（不泄露「存在但你管不了」）"""
    pid = _create(pe, start=-1, end=2)

    pe.logout()
    assert pe.login(student_no=VOTER, password=VOTER_PW).status_code == 200
    assert _lock(pe, pid).status_code == 404
    assert _unlock(pe, pid).status_code == 404
    assert pe.rows("SELECT locked_at FROM polls WHERE id = ?", pid)[0][0] is None

    # 管理员能锁别人发起的投票（和发起人是两个判据，分开钉）
    pe.logout()
    assert pe.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200
    assert _lock(pe, pid).status_code == 200


def test_lock_only_works_on_a_running_poll(pe):
    """没开始的本来就没在收票，已结束的更谈不上暂停 —— 都回一句中文原因"""
    pending = _create(pe, start=1, end=2)
    r = _lock(pe, pending)
    assert r.status_code == 400, r.text
    assert "进行中" in r.json()["detail"], r.json()
    assert pe.rows("SELECT locked_at FROM polls WHERE id = ?", pending)[0][0] is None

    closed = _create(pe, start=-1, end=2)
    assert pe.client.post(f"/api/polls/{closed}/close").status_code == 200
    assert _lock(pe, closed).status_code == 400


def test_lock_and_unlock_are_idempotent(pe):
    """连点两次：状态不变、**locked_at 不被这次点击改写**、操作日志也不多记"""
    pid = _create(pe, start=-1, end=2)
    assert _lock(pe, pid).status_code == 200
    first = pe.rows("SELECT locked_at FROM polls WHERE id = ?", pid)[0][0]

    assert _lock(pe, pid).json()["status"] == "locked", "第二次点击照样是 200"
    assert pe.rows("SELECT locked_at FROM polls WHERE id = ?", pid)[0][0] == first, \
        "再点一次不该把「什么时候暂停的」往后推"
    logs = "SELECT COUNT(*) FROM operation_logs WHERE action = '暂停投票'"
    assert pe.rows(logs)[0][0] == 1, "幂等的那次不该再记一条假日志"

    assert _unlock(pe, pid).json()["status"] == "open"
    assert _unlock(pe, pid).status_code == 200, "本来就没暂停，点一下也不该报错"
    assert pe.rows("SELECT locked_at FROM polls WHERE id = ?", pid)[0][0] is None
    logs = "SELECT COUNT(*) FROM operation_logs WHERE action = '恢复投票'"
    assert pe.rows(logs)[0][0] == 1


def test_locked_poll_keeps_questions_frozen(pe):
    """暂停不等于回到未开始：题目照样锁着（作答存的是选项下标，换了整卷就错位）"""
    pid = _create(pe, start=-1, end=2)
    assert _lock(pe, pid).status_code == 200

    r = _edit(pe, pid, title="暂停期间改标题", description="", questions=[{
        "title": "偷偷换一题", "multiple": False, "max_choices": 1,
        "options": ["甲", "乙"],
    }])
    assert r.status_code == 400, r.text
    assert "开始" in r.json()["detail"], r.json()

    # 但标题描述照样能改：封的是题目，不是整场投票（和进行中同款）
    assert _edit(pe, pid, title="暂停期间改标题", description="").status_code == 200


# ---------- 改时间（PATCH 里的 start_at / end_at）----------
#
# 口径（用户 2026-10-14 拍板）：**未开始的两个时间都能改；已经开始的只能改截止
# 时间；已结束的一个都不给改**。要改时间的动机就两种 —— 推迟开场、延长或缩短收票，
# 都不该逼人「删了重发」（删了重发意味着已经投出去的票全没了）。
#
# 校验整段复用出卷那套 _check_time：先后、跨度、截止时间必须还在未来。所以「想提前
# 收口」不该走这儿 —— 拨到现在之前会被拒，正经入口是「立即结束」，那条会写 closed_at。


def test_a_pending_poll_can_change_both_times(pe):
    """还没开始：开始和截止都能改（推迟开场），状态自然也还是未开始"""
    _as_creator(pe)
    pid = _create(pe, start=2, end=3)
    new_start, new_end = _stamp(5), _stamp(9)

    r = _edit(pe, pid, title="要不要聚餐", description="",
              start_at=new_start, end_at=new_end)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "pending"
    assert data["start_at"][:16] == new_start.replace(" ", "T")
    assert data["end_at"][:16] == new_end.replace(" ", "T")


def test_a_pending_poll_starts_early_when_the_start_moves_into_the_past(pe):
    """出卷那栏写着「选过去的时间 = 立刻开始」，编辑时同样成立"""
    _as_creator(pe)
    pid = _create(pe, start=2, end=3)

    r = _edit(pe, pid, title="要不要聚餐", description="", start_at=_stamp(-1))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "open"


def test_a_running_poll_can_extend_its_deadline(pe):
    """进行中延长截止时间 —— 最要紧的一条：延长之后票真的还能接着投"""
    _as_creator(pe)
    pid = _create(pe, start=-1, end=2)
    new_end = _stamp(6)

    r = _edit(pe, pid, title="要不要聚餐", description="", end_at=new_end)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "open"
    assert r.json()["end_at"][:16] == new_end.replace(" ", "T")

    # 不是只把字段改了：换个人来，票投得进去
    assert _vote_as(pe, VOTER, VOTER_PW, pid).status_code == 200


def test_a_running_poll_cannot_change_its_start(pe):
    """已经开始的改不了开始时间：它已经过去了，改它没有意义"""
    _as_creator(pe)
    pid = _create(pe, start=-1, end=3)

    r = _edit(pe, pid, title="要不要聚餐", description="",
              start_at=_stamp(2), end_at=_stamp(5))
    assert r.status_code == 400, r.text
    assert "开始时间" in r.json()["detail"]


def test_a_finished_poll_takes_no_time_change(pe):
    """已结束的一个都不给改 —— 改完也不生效（closed_at 优先于时间判断），允许就是骗人"""
    _as_creator(pe)
    pid = _create(pe, start=-2, end=2)
    _set_end(pe, pid, -1)  # 截止时间已经过去 = 这场结束了

    r = _edit(pe, pid, title="要不要聚餐", description="", end_at=_stamp(5))
    assert r.status_code == 400, r.text
    assert "结束" in r.json()["detail"]


def test_a_paused_poll_can_still_change_its_deadline(pe):
    """暂停只是临时不收票，调截止时间仍是正常的管理动作（暂停期间到点照常结束）"""
    _as_creator(pe)
    pid = _create(pe, start=-1, end=2)
    assert _lock(pe, pid).status_code == 200
    new_end = _stamp(6)

    r = _edit(pe, pid, title="要不要聚餐", description="", end_at=new_end)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "locked"
    assert r.json()["end_at"][:16] == new_end.replace(" ", "T")


def test_the_deadline_cannot_be_moved_into_the_past(pe):
    """进行中的，截止时间改不到现在或更早（用户 2026-10-14 指的边界）

    想提前收口就走「立即结束」，别把截止时间拨到过去 —— 那条路留不下任何痕迹：
    谁提前掐的、什么时候掐的，操作日志和详情里都看不出来。
    """
    _as_creator(pe)
    pid = _create(pe, start=-1, end=3)
    before = pe.client.get(f"/api/polls/{pid}").json()

    # 用 -0.5 而不是 -1：这场是 start=-1 开的，同一分钟会被「必须晚于开始时间」
    # 先拦下，测不到想测的那条。0 是「正好拨到现在」—— 同样得拒，一到点就算结束
    for bad in (_stamp(-0.5), _stamp(0)):
        r = _edit(pe, pid, title="要不要聚餐", description="", end_at=bad)
        assert r.status_code == 400, r.text
        assert "截止时间已经过了" in r.json()["detail"]

    # 拒了就是拒了，一个字都不该落库：状态还得是进行中、截止时间照旧
    now = pe.client.get(f"/api/polls/{pid}").json()
    assert now["status"] == "open"
    assert now["end_at"] == before["end_at"]

    # 正经入口在这儿，而且它会写上 closed_at
    assert pe.client.post(f"/api/polls/{pid}/close").status_code == 200


def test_the_deadline_must_stay_after_the_start(pe):
    """时间和出卷同一套校验：开始推到晚上、截止还留在下午，就得拒"""
    _as_creator(pe)
    pid = _create(pe, start=2, end=3)

    r = _edit(pe, pid, title="要不要聚餐", description="",
              start_at=_stamp(6), end_at=_stamp(3))
    assert r.status_code == 400, r.text
    assert "晚于开始时间" in r.json()["detail"]


def test_editing_without_times_leaves_them_alone(pe):
    """不传时间 = 一个字都不动。前端把原值原样回传，也不该留下「改了截止时间」的日志"""
    _as_creator(pe)
    pid = _create(pe, start=-1, end=3)
    before = pe.client.get(f"/api/polls/{pid}").json()

    r = _edit(pe, pid, title="换个标题", description="")
    assert r.status_code == 200, r.text
    assert r.json()["start_at"] == before["start_at"]
    assert r.json()["end_at"] == before["end_at"]


def test_times_and_questions_can_change_in_one_request(pe):
    """一次 PATCH 同时改开场时间和题目：按**改时间之前**的状态判，两样都算数

    判定用的状态要在动手改之前取 —— 否则「把开场提早到现在」会先把这场变成进行中，
    同一份表单里刚填好的题目就莫名改不了了。
    """
    _as_creator(pe)
    pid = _create(pe, start=2, end=3)

    r = _edit(pe, pid, title="要不要聚餐", description="",
              start_at=_stamp(-1), end_at=_stamp(5),
              questions=[{"title": "改过的题", "multiple": False,
                          "max_choices": 1, "options": ["甲", "乙"]}])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "open"  # 开场时间真的提前了
    assert data["questions"][0]["title"] == "改过的题"


def test_questions_freeze_once_the_start_moves_into_the_past(pe):
    """改时间会连带改变「题目还改不改得了」—— 状态本来就是现算的"""
    _as_creator(pe)
    pid = _create(pe, start=2, end=3)
    assert _edit(pe, pid, title="要不要聚餐", description="",
                 start_at=_stamp(-1)).status_code == 200

    r = _edit(pe, pid, title="要不要聚餐", description="",
              questions=[{"title": "偷偷换一题", "multiple": False,
                          "max_choices": 1, "options": ["甲", "乙"]}])
    assert r.status_code == 400, r.text
    assert "题目改不了" in r.json()["detail"]


# ---------- 改记名（PATCH 里的 anonymous）----------
#
# 口径（用户 2026-10-14 拍板）：**开始前允许改记名情况，开始了不许**。和题目同一条
# 理由 —— 改了等于「换一张票」：记名方式一换，已经投出去的那些票就被重新定义了一遍
# （不记名的票突然有了主）。没开始时库里不可能有这场投票的作答（can_vote 要求状态
# 是 open），所以那时怎么改都安全。暂停不等于回到未开始，锁着一样不给改。
#
# **字段语义别搞反**：`anonymous=True` 是**不记名**，名册上就不返回谁选了什么。


def test_anonymous_can_be_turned_on_before_start(pe):
    """还没开始时能改成不记名，而且**真生效**：开场、投票，名册上就看不到谁选了什么"""
    _as_creator(pe)
    pid = _create(pe, start=2, end=3)  # _body 默认 anonymous=False = 记名
    assert pe.client.get(f"/api/polls/{pid}").json()["anonymous"] is False

    r = _edit(pe, pid, title="要不要聚餐", description="", anonymous=True)
    assert r.status_code == 200, r.text
    assert r.json()["anonymous"] is True

    _start_now(pe, pid)
    assert _vote_as(pe, VOTER, VOTER_PW, pid).status_code == 200
    _as_creator(pe)
    rows = pe.client.get(f"/api/polls/{pid}/ballots").json()["rows"]
    row = next(r for r in rows if r["student_no"] == VOTER)
    assert row["voted"] is True, "名单照给 —— 催票要按它算未投人数"
    assert row["choices"] is None, "改成不记名了，谁选了什么就不该再露出来"


def test_anonymous_can_be_turned_off_before_start(pe):
    """反过来也一样：还没开始时能从「不记名」改回记名"""
    _as_creator(pe)
    pid = _create(pe, start=2, end=3)
    assert _edit(pe, pid, title="要不要聚餐", description="",
                 anonymous=True).json()["anonymous"] is True

    r = _edit(pe, pid, title="要不要聚餐", description="", anonymous=False)
    assert r.status_code == 200, r.text
    assert r.json()["anonymous"] is False


def test_anonymous_is_frozen_once_started(pe):
    """已经开投了就不许再改 —— 记名的票不能突然变成没主"""
    _as_creator(pe)
    pid = _create(pe, start=-1, end=3)  # start_at 在过去 = 进行中
    assert _vote_as(pe, VOTER, VOTER_PW, pid).status_code == 200
    _as_creator(pe)

    r = _edit(pe, pid, title="要不要聚餐", description="", anonymous=True)
    assert r.status_code == 400, r.text
    assert "记名方式" in r.json()["detail"]
    # 拒了就不许落库
    assert pe.client.get(f"/api/polls/{pid}").json()["anonymous"] is False


def test_a_paused_poll_still_freezes_anonymous(pe):
    """暂停不等于回到未开始：锁着一样不给改记名，那会儿的票还挂在那儿"""
    _as_creator(pe)
    pid = _create(pe, start=-1, end=3)
    assert _lock(pe, pid).status_code == 200

    r = _edit(pe, pid, title="要不要聚餐", description="", anonymous=True)
    assert r.status_code == 400, r.text
    assert "记名方式" in r.json()["detail"]


def test_editing_without_anonymous_leaves_it_alone(pe):
    """不传 = 一个字都不动：改成记名之后只动标题，记名得留着"""
    _as_creator(pe)
    pid = _create(pe, start=2, end=3)
    assert _edit(pe, pid, title="要不要聚餐", description="",
                 anonymous=True).status_code == 200

    r = _edit(pe, pid, title="换个标题", description="")
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "换个标题"
    assert r.json()["anonymous"] is True


def test_times_and_anonymous_can_change_in_one_request(pe):
    """一次 PATCH 同时提前开场和改记名：状态按**改时间之前**取，两样都算数

    判定用的状态必须在动手改之前取 —— 否则「把开场提早到现在」会先把这场变成
    进行中，同一份表单里刚打开的记名开关就莫名改不了了。
    """
    _as_creator(pe)
    pid = _create(pe, start=2, end=3)

    r = _edit(pe, pid, title="要不要聚餐", description="",
              start_at=_stamp(-1), anonymous=True)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "open"  # 开场时间真的提前了
    assert r.json()["anonymous"] is True


# ---------- 分享页 ----------

def test_share_link_redirects_and_meta_is_server_rendered(pe):
    """旧地址 302 到真实路径；新 meta 由服务端渲染，爬虫不登录也能读

    外链是 `/share/vote/{token}` 这样的真实路径，nginx 会在同一次响应里把这一场
    的 head 写进 index.html。旧的 `/api/polls/share/{token}` 只为老链接保留。
    """
    pid = _create(pe, title="入党推优第三轮选举")
    row = pe.client.get("/api/polls").json()["items"][0]
    token = row["share_token"]
    assert token.startswith(f"{pid}."), "分享串要带上投票 id，签名用来防枚举"
    # 同一场投票的签名串必须稳定，否则每次刷新列表都会换一个新链接
    assert pe.client.get("/api/polls").json()["items"][0]["share_token"] == token
    assert pe.client.get(f"/api/polls/{pid}").json()["share_token"] == token

    pe.logout()  # 模拟微信爬虫：没有登录态
    r = pe.client.get(f"/api/polls/share/{token}")
    assert r.status_code == 302
    assert r.headers["location"].endswith(f"/share/vote/{token}")

    r = pe.client.get(f"/api/share-meta/share/vote/{token}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    assert "<title>投票：入党推优第三轮选举</title>" in html
    assert '<meta property="og:title" content="投票：入党推优第三轮选举">' in html
    assert 'name="robots" content="index,follow"' in html
    assert "应投 1 人" in html and "1 道题" in html and "记名" in html
    assert "定向 1 人" in html, "公开范围要写进卡片"
    assert "截止" in html
    assert "icons/share-512.jpg" in html, "卡片图用优化过的 512 JPEG"
    assert f"/share/vote/{token}" in html, "卡片地址是新的真实路径"


def test_share_info_public_fields_and_scope_label(pe):
    """公开接口只给标题、完整描述、范围、状态和人数；题目不下发"""
    pid = _create(pe, title="入党推优第三轮选举")
    _edit(pe, pid, title="入党推优第三轮选举", description="请如实填写")
    token = pe.client.get(f"/api/polls/{pid}").json()["share_token"]

    pe.logout()
    r = pe.client.get(f"/api/polls/share/{token}/info")
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["title"] == "入党推优第三轮选举"
    assert info["description"] == "请如实填写", "描述要完整公开，不是截前 60 字"
    assert info["scope_label"] == "定向 1 人"
    assert info["target_count"] == 1 and info["question_count"] == 1
    assert info["is_login"] is False and info["in_scope"] is False
    assert info["questions"] == []
    assert info["can_vote"] is False and info["results_visible"] is False
    assert "creator_no" not in info, "分享页不该带发起人学号"

    # 伪造签名 / 不存在的投票：404，不泄露「有这一场」
    assert pe.client.get("/api/polls/share/999.0123456789abcdef/info").status_code == 404


def test_share_scope_label_reflects_targets(pe):
    """范围反推：全班 / 班委 / 团员 / 定向 N 人，四种都要对"""
    all_targets = [ADMIN] + [no for no, _ in PEOPLE]
    cases = [
        (all_targets, "全班"),
        ([CREATOR, ADMIN], "班委"),
        ([CREATOR, "2024000004"], "团员"),
        ([VOTER], "定向 1 人"),
    ]
    for targets, label in cases:
        pid = _create(pe, targets=targets)
        token = pe.client.get(f"/api/polls/{pid}").json()["share_token"]
        info = pe.client.get(f"/api/polls/share/{token}/info").json()
        assert info["scope_label"] == label, (targets, info["scope_label"])


def test_share_info_reveals_questions_only_in_scope(pe):
    """范围内的人拿得到题目和 can_vote；范围外的人只有公开字段"""
    pid = _create(pe)
    _start_now(pe, pid)
    token = pe.client.get(f"/api/polls/{pid}").json()["share_token"]

    pe.logout()
    pe.login(student_no=VOTER, password=VOTER_PW)
    info = pe.client.get(f"/api/polls/share/{token}/info").json()
    assert info["is_login"] is True and info["in_scope"] is True
    assert info["is_target"] is True and info["can_vote"] is True
    assert len(info["questions"]) == 1
    assert info["questions"][0]["options"] == ["方案一", "方案二"]

    # 范围外的登录用户：题目仍然不下发
    pe.logout()
    pe.login(student_no="2024000005", password="010005")
    info = pe.client.get(f"/api/polls/share/{token}/info").json()
    assert info["is_login"] is True and info["in_scope"] is False
    assert info["questions"] == []
    assert info["can_vote"] is False


def test_share_meta_is_always_200_and_escaped(pe):
    """SSI 子请求必须永远 200；标题里的 HTML 要被转义，失效时给统一兜底"""
    pid = _create(pe, title='<script>"&')
    token = pe.client.get(f"/api/polls/{pid}").json()["share_token"]
    pe.logout()

    r = pe.client.get(f"/api/share-meta/share/vote/{token}")
    assert r.status_code == 200
    assert "<script>" not in r.text and "&lt;script&gt;" in r.text

    for path in (
        "/api/share-meta/share/vote/999.0123456789abcdef",
        "/api/share-meta/share/vote/abc",
        "/api/share-meta/share/unknown/x",
        "/api/share-meta/nonsense",
    ):
        r = pe.client.get(path)
        assert r.status_code == 200, path
        assert 'name="robots" content="noindex, nofollow"' in r.text, path
        assert "分享链接无效或已失效" in r.text, path


def test_old_share_endpoint_rejects_forged_tokens(pe):
    """换成别的数字 / 乱写签名都 404，不能靠遍历 id 把全班投票标题看一遍"""
    pid = _create(pe)
    assert pe.client.get(f"/api/polls/share/{pid}").status_code == 404
    assert pe.client.get("/api/polls/share/999.0123456789abcdef").status_code == 404
    assert pe.client.get("/api/polls/share/abc").status_code == 404


# ---------- 迁移 ----------

def test_migration_adds_locked_at(backend):
    """老库（polls 缺 locked_at）启动一次就该补上，老行一律「从没暂停过」"""
    b = _world(backend, "polls_mig.db")
    r = b.client.put(f"/api/admin/users/{CREATOR}/role", json={"role": "committee"})
    assert r.status_code < 300, r.text
    pid = _create(b, start=-1, end=2)

    # 退回补列之前的样子：SQLite 3.35+ 才有 DROP COLUMN（本机 3.50）
    b.run("ALTER TABLE polls DROP COLUMN locked_at")
    assert "locked_at" not in {row[1] for row in b.rows("PRAGMA table_info(polls)")}, \
        "得先确认旧结构真造出来了，否则下面那条是假通过"

    b2 = backend(db="polls_mig.db", BOOTSTRAP_PASSWORD=PW)  # 同一个库再起一次 = 重启
    assert "locked_at" in {row[1] for row in b2.rows("PRAGMA table_info(polls)")}
    assert b2.rows("SELECT locked_at FROM polls WHERE id = ?", pid)[0][0] is None

    # 补上来的列得**真能用**：老投票照常读得出、也照常暂停得了 —— 这才是接口层的落点
    # （b2 是另一个进程、另一份 cookie，先登录）
    assert b2.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200
    detail = b2.client.get(f"/api/polls/{pid}").json()
    assert detail["status"] == "open", "补列前就在进行的投票，不该凭空变成已暂停"
    assert b2.client.post(f"/api/polls/{pid}/lock").json()["status"] == "locked"
