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
# 口径：标题和描述随时能改；**题目只有还没开始时能改**（作答存的是选项下标，
# 已经开始之后再动题目会让历史作答错位）。时间、表决范围、记名与否都不在可编辑
# 之列，所以这里也不测它们 —— 请求体里根本没有这些字段，多传会被 pydantic 忽略。

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

    只能从库里改：编辑接口里压根没有时间字段（改了要动摇已经投出去的票），
    而测试里等真实时间过去不现实。**这正是这一整套要跑的路径** ——
    没开始时改题目 → 到点开始 → 大家按新卷子投。
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
