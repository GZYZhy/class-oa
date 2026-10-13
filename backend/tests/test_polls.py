"""投票的回归：出卷名单带得出政治面貌、点名收得下「共青团员」、投票能编辑

    cd backend && python -m pytest tests -q

盯三件事：

1. GET /api/polls/roster 得把每个人的政治面貌带回给出卷弹窗。「仅团员」那枚快捷键
   的判据在前端（utils/roster.js 的 isLeagueMember），后端只要少回一个字段、
   或者字段名改成别的，前端就会静默筛出零个人 —— 点下去「已选 0 人」，不报错。

2. POST /api/attendance 的 scope 收得下「共青团员」。这一列是 String(10)、schema 上
   还有 max_length=10，四个汉字眼下放得下 —— 但那是恰好，不是设计。哪天有人顺手给它
   加个枚举白名单，点名选团员就会当场 400，而这类改动看起来完全无害。

3. PATCH /api/polls/{id} 编辑投票的边界。最容易写错、也最不该写错的是**题目只在
   没开始时能换**：作答存的是选项下标，已经开始之后再动题目，历史作答会整体错位，
   而库里的数据看不出任何异常。
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
