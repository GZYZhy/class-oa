"""列表搜索：投票按标题、成绩按考试名、考勤按备注、审核七类按提交人 / 提交日期

    cd backend && python -m pytest tests -q

这些筛选**必须落在 SQL 里**（分页接口尤其）：先取一页再在 Python 里滤，total 就
跟着错，用户会看见「共 20 条」却只筛出 1 条。

审核那七类里，请假、修改申请、反馈、导出申请自己存了姓名/学号；电动车和证明只有
student_id，得绕到学生表去匹配 —— 两种实现各测一遍。

提交日期按**自然日**算：只传 start=03-10 时，当天 00:00 之后提交的都在，
前后两天的不在。
"""

from datetime import datetime, timedelta

import pytest

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"
S1, S1_NAME = "2024000002", "张小明"
S2, S2_NAME = "2024000003", "李晓红"

EARLY = "2026-03-10 09:00:00.000000"   # 3 月那一笔
LATE = "2026-04-15 09:00:00.000000"    # 4 月那一笔


def _world(backend):
    """初始化完毕、库里 1 个管理员 + 2 个学生，**管理员已登录**"""
    b = backend(db="list_search.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200

    for no, name in [(ADMIN, "管理员"), (S1, S1_NAME), (S2, S2_NAME)]:
        r = b.client.post("/api/students", json={
            "student_no": no,
            "name": name,
            "id_card": f"11010120050101{no[-4:]}",
        })
        assert r.status_code < 300, r.text

    assert b.client.post("/api/setup/finish",
                         json={"admin_student_no": ADMIN}).status_code == 200
    b.logout()
    assert b.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200
    return b


@pytest.fixture
def lb(backend):
    return _world(backend)


def _sid(b, student_no):
    return b.rows("SELECT id FROM students WHERE student_no = ?", student_no)[0][0]


def _ids(data):
    """列表接口有两种形状：直接回数组，或者分页的 {total, items}"""
    items = data["items"] if isinstance(data, dict) else data
    return {item["id"] for item in items}


# ---------- 投票：按标题搜 ----------

def _create_poll(b, title):
    now = datetime.now()
    r = b.client.post("/api/polls", json={
        "title": title,
        "description": "",
        "anonymous": False,
        "start_at": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
        "end_at": (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
        "targets": [S1],
        "questions": [{
            "title": "选哪个？", "multiple": False, "max_choices": 1,
            "options": ["甲", "乙"],
        }],
    })
    assert r.status_code < 300, r.text
    return r.json()["id"]


def test_poll_title_search(lb):
    """标题含关键词的才出来，**total 也跟着筛**（不是先分页再过滤）"""
    dinner = _create_poll(lb, "国庆聚餐投票")
    travel = _create_poll(lb, "寒假出行安排")

    r = lb.client.get("/api/polls", params={"keyword": "聚餐", "page_size": 1})
    assert r.status_code == 200, r.text
    data = r.json()
    assert [p["id"] for p in data["items"]] == [dinner]
    assert data["total"] == 1, "page_size=1 时 total 仍是筛后的条数"

    # 学号不会误命中标题；空白关键词等于没传
    assert lb.client.get("/api/polls", params={"keyword": S1}).json()["total"] == 0
    assert lb.client.get("/api/polls", params={"keyword": "   "}).json()["total"] == 2

    all_items = lb.client.get("/api/polls").json()["items"]
    assert {p["id"] for p in all_items} == {dinner, travel}
    assert travel  # 只为说明两场都在


# ---------- 成绩：按考试名搜 ----------

def test_grade_name_search(lb):
    lb.run("INSERT INTO grade_tests (name, tested_at, remark) VALUES (?, ?, '')",
           "高数期中考", "2026-03-10")
    lb.run("INSERT INTO grade_tests (name, tested_at, remark) VALUES (?, ?, '')",
           "线性代数期末", "2026-06-20")

    r = lb.client.get("/api/grades", params={"keyword": "高数"})
    assert r.status_code == 200, r.text
    assert [t["name"] for t in r.json()["items"]] == ["高数期中考"]
    assert r.json()["total"] == 1

    # 备注不参与搜索：这个接口只认考试名
    lb.run("UPDATE grade_tests SET remark = '补考' WHERE name = '线性代数期末'")
    assert lb.client.get("/api/grades", params={"keyword": "补考"}).json()["total"] == 0
    assert lb.client.get("/api/grades", params={"keyword": "期末"}).json()["total"] == 1
    assert lb.client.get("/api/grades", params={"keyword": " "}).json()["total"] == 2


# ---------- 考勤：按备注搜 ----------

def _call(b, remark, day):
    b.run(
        "INSERT INTO attendance_records "
        "(call_date, scope, called_at, operator_no, operator_name, remark) "
        "VALUES (?, '全班', ?, ?, '管理员', ?)",
        day, f"{day} 08:00:00.000000", ADMIN, remark,
    )


def test_attendance_remark_search(lb):
    _call(lb, "学院临时集合，迟到 5 人", "2026-03-12")
    _call(lb, "", "2026-03-13")

    r = lb.client.get("/api/attendance", params={"keyword": "临时集合"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["remark"] for i in items] == ["学院临时集合，迟到 5 人"]
    assert r.json()["total"] == 1

    # 和日期范围是「并且」的关系
    both = lb.client.get("/api/attendance", params={
        "keyword": "临时集合", "start": "2026-04-01", "end": "2026-04-30",
    }).json()
    assert both["total"] == 0 and both["items"] == []

    # 没写备注的那条不该被空关键词搜出来（空关键词 = 不过滤，两条都在）
    assert lb.client.get("/api/attendance", params={"keyword": "  "}).json()["total"] == 2


# ---------- 审核审批：七类都按提交人 / 提交日期筛 ----------
#
# 每条用例只跑一种申请；直接往库里塞两行（3 月由张小明提交、4 月由李晓红提交），
# 省掉七条提交流程各自要传的附件和前置状态，测的仍然是接口层那条 SQL。

# (说明, 路径, 表名, 插入 SQL, 是否自带姓名/学号列)
CASES = [
    (
        "请假",
        "/api/leaves",
        "leave_requests",
        # 响应模型里那几个 str 字段直接给 NULL 会 500（它们只有 Python 端默认值），
        # 所以直接插库时得把空串一并写上
        "INSERT INTO leave_requests "
        "(student_id, student_no, student_name, leave_type, start_at, end_at, reason, "
        " travel_mode, travel_detail, destination, destination_phone, status, "
        " reject_reason, correction_reason, advisor_opinion, advisor_sign_no, "
        " advisor_sign_name, created_at) "
        "VALUES (?, ?, ?, '事假', '2026-03-10 08:00:00.000000', "
        "'2026-03-10 18:00:00.000000', '家中有事', '', '', '', '', 'pending', "
        "'', '', '', '', '', ?)",
        "person",
    ),
    (
        "电动车通行证",
        "/api/ev-passes",
        "ev_pass_requests",
        "INSERT INTO ev_pass_requests (student_id, status, created_at) "
        "VALUES (?, 'pending', ?)",
        "sid",   # 姓名/学号在学生表
    ),
    (
        "证明开具",
        "/api/certificates",
        "certificate_requests",
        "INSERT INTO certificate_requests (student_id, status, created_at) "
        "VALUES (?, 'pending', ?)",
        "sid",   # 同上
    ),
    (
        "信息修改",
        "/api/change-requests",
        "change_requests",
        "INSERT INTO change_requests "
        "(student_id, student_no, student_name, changes, status, created_at) "
        "VALUES (?, ?, ?, '{\"qq\": \"123456\"}', 'pending', ?)",
        "person",
    ),
    (
        "签字查看",
        "/api/sign-photos/requests",
        "sign_photo_requests",
        # 「提交人」是 applicant_*，不是被查看签字的学生（这里两者碰巧是同一人）
        "INSERT INTO sign_photo_requests "
        "(student_id, student_no, student_name, applicant_no, applicant_name, "
        " status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        "applicant",
    ),
    (
        "导出申请",
        "/api/export-requests",
        "export_requests",
        "INSERT INTO export_requests "
        "(student_id, student_no, student_name, export_type, scope_type, status, created_at) "
        "VALUES (?, ?, ?, 'excel_list', 'all', 'pending', ?)",
        "person",
    ),
    (
        "意见反馈",
        "/api/feedback",
        "feedbacks",
        "INSERT INTO feedbacks "
        "(student_id, student_no, student_name, title, content, status, created_at) "
        "VALUES (?, ?, ?, '一个建议', '正文', 'unread', ?)",
        "person",
    ),
]


@pytest.mark.parametrize("label,path,table,sql,mode", CASES)
def test_review_list_filters_by_person_and_date(lb, label, path, table, sql, mode):
    s1, s2 = _sid(lb, S1), _sid(lb, S2)

    def seed(sid, no, name, created):
        if mode == "person":     # 表里自己存了姓名/学号
            lb.run(sql, sid, no, name, created)
        elif mode == "sid":      # 只有 student_id，姓名/学号在学生表
            lb.run(sql, sid, created)
        else:                    # sign_photo_requests：提交人与被查看人是两列
            lb.run(sql, sid, no, name, no, name, created)

    seed(s1, S1, S1_NAME, EARLY)
    seed(s2, S2, S2_NAME, LATE)

    row_ids = [row[0] for row in lb.rows(f"SELECT id FROM {table} ORDER BY id")]
    assert len(row_ids) == 2, f"{label}：两行都得塞进去，否则下面全是假通过"
    early_id, late_id = row_ids

    def found(**params):
        r = lb.client.get(path, params=params)
        assert r.status_code == 200, f"{label}：{r.text}"
        return _ids(r.json())

    assert found() == {early_id, late_id}, f"{label}：不传条件就是全部"
    assert found(keyword="张小明") == {early_id}, f"{label}：按姓名搜"
    assert found(keyword=S1) == {early_id}, f"{label}：按学号搜"
    assert found(keyword="李晓") == {late_id}, f"{label}：换个人也能搜"
    assert found(keyword="查无此人") == set(), f"{label}：搜不到就是空"

    # 日期是自然日：只给 start 时，当天 00:00 之后都算；只给 end 时，当天 23:59 都算
    assert found(start="2026-04-01") == {late_id}, f"{label}：起始日"
    assert found(end="2026-03-31") == {early_id}, f"{label}：结束日"
    assert found(start="2026-03-10", end="2026-03-10") == {early_id}, \
        f"{label}：首尾两天都含"
    assert found(start="2026-04-01", end="2026-04-30") == {late_id}, f"{label}：整个 4 月"

    # 两个条件是「并且」：张小明在 4 月没提过任何申请
    assert found(keyword="张小明", start="2026-04-01") == set(), \
        f"{label}：姓名和日期一起用时是并且"
