"""成绩模块的回归：单科统计、学生位次、通过制、形态防线、导入、迁移

    cd backend && python -m pytest tests -q

装置沿用 conftest 的 backend fixture（真 uvicorn 进程 + 真临时库 + httpx）。
空库起不来班委，所以走项目自己的引导流程拿第一个管理员：配 BOOTSTRAP_PASSWORD 起库 →
临时账号建名单 → /api/setup/finish 指认管理员 → 用他本人登录。学生的密码是
**身份证后 6 位**（user_service.default_password），造名单时带上身份证就推得出来，
不必去动库里的密码列。

分数分布都挑能手算的，断言里直接写死人数与百分比 —— 数字对不上时一眼看得出是哪条。
"""
from io import BytesIO
from types import SimpleNamespace

import httpx
import openpyxl
import pytest

PW = "initpass123"

# (学号, 姓名, 身份证后 6 位 —— 也就是这个学生的默认密码)
ROSTER = [
    ("2024000001", "甲", "010001"),
    ("2024000002", "乙", "010002"),
    ("2024000003", "丙", "010003"),
    ("2024000004", "丁", "010004"),
    ("2024000005", "戊", "010005"),
    ("2024000006", "己", "010006"),
    ("2024000007", "庚", "010007"),
]
ADMIN = ROSTER[0][0]

# 第一场：数学 150 分制（150/120/90/0 分、戊缺考、己那行空着、庚整行没出现）
#         体育 通过制（通过 3 / 不通过 1 / 戊缺考）
GRADES_HEADERS = ["学号", "姓名", "数学", "体育"]
GRADES_ROWS = [
    [ROSTER[0][0], "甲", 150, "通过"],
    [ROSTER[1][0], "乙", 120, "通过"],
    [ROSTER[2][0], "丙", 90, "不通过"],
    [ROSTER[3][0], "丁", 0, "通过"],
    [ROSTER[4][0], "戊", "缺考", "缺考"],
    [ROSTER[5][0], "己", None, None],
]

# 第二场：头两名并列 100 分，专门用来验「并列取最好名次」
TIED_HEADERS = ["学号", "姓名", "数学"]
TIED_ROWS = [
    [ROSTER[0][0], "甲", 100],
    [ROSTER[1][0], "乙", 100],
    [ROSTER[2][0], "丙", 90],
    [ROSTER[3][0], "丁", 50],
]


# ---------- 小工具 ----------

def xlsx(headers, rows) -> bytes:
    """现造一份 Excel。表头在第 1 行、必须有「学号」列 —— 同 parse_grade_excel 的要求"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(b, headers, rows) -> dict:
    """上传并预览，返回预览结果（token 在里面）"""
    r = b.client.post(
        "/api/grades/import/preview",
        files={"file": ("成绩.xlsx", xlsx(headers, rows),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def confirm(b, preview, name="期中", tested_at="2026-04-01", modes=None,
            full_scores=None, notify=False):
    """确认录入，默认录预览里的所有列；notify 关掉免得真去发通知

    modes 是**确认页上下拉选了什么**：默认取预览的预判（前端打开确认页时就是这么填的），
    传进来的只覆盖要改的那几列。后端本身不认预判，它只看传上来的形态。
    """
    chosen = {c["name"]: ("pass_fail" if c["suggest_pass_fail"] else "score")
              for c in preview["columns"]}
    chosen.update(modes or {})
    return b.client.post("/api/grades/import", json={
        "token": preview["token"],
        "name": name,
        "tested_at": tested_at,
        "subjects": [c["name"] for c in preview["columns"]],
        "subject_modes": chosen,
        "subject_full_scores": full_scores or {},
        "notify": notify,
    })


def subjects_of(b, test_id) -> dict:
    """科目名 → 科目对象。写格子、改形态都要 subject_id"""
    r = b.client.get(f"/api/grades/{test_id}")
    assert r.status_code == 200, r.text
    return {s["name"]: s for s in r.json()["subjects"]}


def stats_of(b, test_id) -> dict:
    """科目名 → 统计条"""
    r = b.client.get(f"/api/grades/{test_id}/stats")
    assert r.status_code == 200, r.text
    return {s["name"]: s for s in r.json()["subjects"]}


def mine_of(client, test_id) -> dict:
    """我的某一场：科目名 → entry（没参加的场次返回空字典）"""
    r = client.get("/api/grades/mine")
    assert r.status_code == 200, r.text
    for item in r.json():
        if item["test_id"] == test_id:
            return {e["subject"]: e for e in item["scores"]}
    return {}


def as_student(b, idx) -> httpx.Client:
    """另开一个客户端以学生身份登录 —— 会话是按 client 存的，换身份就得换 client"""
    no, _, tail = ROSTER[idx]
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": tail})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def g(backend):
    """初始化完毕、录了两场成绩的后端；管理员已登录"""
    b = backend(db="grades.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200      # 初始化临时账号

    for no, name, tail in ROSTER:
        r = b.client.post("/api/students", json={
            "student_no": no, "name": name, "id_card": f"11010120000101{tail}",
        })
        assert r.status_code < 300, r.text

    # 指认管理员：这一步之后临时账号当场废止，得用他本人重新登录
    r = b.client.post("/api/setup/finish", json={"admin_student_no": ADMIN})
    assert r.status_code == 200, r.text
    b.logout()
    assert b.login(student_no=ADMIN, password=ROSTER[0][2]).status_code == 200

    t1 = confirm(b, upload(b, GRADES_HEADERS, GRADES_ROWS), name="高数期中考",
                 tested_at="2026-04-01", modes={"体育": "pass_fail"},
                 full_scores={"数学": 150})
    assert t1.status_code == 200, t1.text
    t2 = confirm(b, upload(b, TIED_HEADERS, TIED_ROWS), name="并列测试",
                 tested_at="2026-04-02")
    assert t2.status_code == 200, t2.text

    return SimpleNamespace(b=b, t1=t1.json()["test_id"], t2=t2.json()["test_id"])


# ---------- 统计 ----------

def test_stats_counts_each_bucket(g):
    """三类格子分开数：有成绩 / 有标记词 / 没录；0 分算成绩、缺考不进平均"""
    r = g.b.client.get(f"/api/grades/{g.t1}/stats").json()
    assert r["roster_count"] == 7, "统计范围是名单上的所有人"
    assert [s["name"] for s in r["subjects"]] == ["数学", "体育"], "科目按 sort 排"

    m = r["subjects"][0]
    assert m["mode"] == "score" and m["full_score"] == 150.0
    assert m["scored_count"] == 4, "150/120/90/0 —— 0 分是成绩，不是没录"
    assert m["marked_count"] == 1, "戊：缺考"
    assert m["blank_count"] == 2, "己那行空着、庚整行没出现"
    assert m["avg"] == 90.0, "(150+120+90+0)/4 —— 缺考不进分母"
    assert (m["max"], m["min"]) == (150.0, 0.0), "最低 0，没被当成没录丢掉"
    assert m["pass_count"] == 3, "及格线 150×0.6 = 90，90 分本人也算及格"
    assert m["pass_rate"] == 75.0
    assert [(x["label"], x["count"]) for x in m["ranges"]] == [
        ("不足 60%", 1), ("60~69%", 1), ("70~79%", 0), ("80~89%", 1), ("90% 以上", 1)]
    assert sum(x["count"] for x in m["ranges"]) == m["scored_count"], "分数段加起来不漏人"


def test_stats_pass_fail_subject(g):
    """通过制：通过率的分母只有真记了通过/不通过的人，缺考不算"""
    p = stats_of(g.b, g.t1)["体育"]
    assert p["mode"] == "pass_fail"
    assert (p["passed_count"], p["failed_count"]) == (3, 1)
    assert p["pass_rate"] == 75.0, "3/(3+1)，戊缺考不进分母"
    assert p["scored_count"] == 4, "通过制这边「有成绩」= 通过 + 不通过"
    assert p["marked_count"] == 1, "缺考是标记词，不是成绩"
    # 计分科目才有的那几项：schema 是共用的，键一直在，通过制下留空
    assert p["avg"] is None and p["max"] is None and p["min"] is None
    assert p["ranges"] == [] and p["pass_count"] == 0


# ---------- 位次 ----------

def test_rank_percent(g):
    """位次 = 名次 ÷ 有成绩人数；并列同分取最好名次"""
    yi = as_student(g.b, 1)                     # 乙：数学 120 分
    e = mine_of(yi, g.t1)["数学"]
    assert e["value"] == "120" and e["mode"] == "score"
    assert e["rank_percent"] == 50.0, "只有甲比他高，(1+1)/4"

    # 第二场甲、乙都 100 分：两人都该是第 1 名，不是「先来后到」的前 25% / 前 50%
    assert mine_of(yi, g.t2)["数学"]["rank_percent"] == 25.0
    jia = as_student(g.b, 0)
    assert mine_of(jia, g.t2)["数学"]["rank_percent"] == 25.0


def test_zero_score_still_ranks(g):
    """0 分是合法成绩，照样参与排名（写成 if score 就会把他当没录）"""
    ding = as_student(g.b, 3)                   # 丁：0 分垫底
    assert mine_of(ding, g.t1)["数学"]["rank_percent"] == 100.0


def test_rank_none_without_score(g):
    """缺考、通过制、空格都没有位次"""
    wu = as_student(g.b, 4)                     # 戊：缺考
    assert mine_of(wu, g.t1)["数学"]["rank_percent"] is None

    yi = as_student(g.b, 1)
    sports = mine_of(yi, g.t1)["体育"]
    assert sports["mode"] == "pass_fail" and sports["value"] == "通过"
    assert sports["rank_percent"] is None, "二元值的百分位没有意义"


def test_mine_hides_denominator(g):
    """学生端只给百分位，不给「一共多少人考了」（分母只是算比例的中间量）"""
    entry = mine_of(as_student(g.b, 1), g.t1)["数学"]
    assert "scored_count" not in entry
    assert sorted(entry) == ["mode", "rank_percent", "subject", "value"]


# ---------- 权限 ----------

def test_student_cannot_see_stats(g):
    """统计是班级层面的，学生一律看不到；自己的位次照常"""
    yi = as_student(g.b, 1)
    sid = subjects_of(g.b, g.t1)["数学"]["id"]
    assert yi.get(f"/api/grades/{g.t1}/stats").status_code == 403
    assert yi.patch(f"/api/grades/{g.t1}/subjects/{sid}",
                    json={"mode": "pass_fail"}).status_code == 403
    assert yi.get("/api/grades/mine").status_code == 200


# ---------- 写一格：按科目形态判 ----------

def test_write_cell_follows_subject_mode(g):
    """同一个值在不同形态的科目里收不收是不一样的"""
    subs = subjects_of(g.b, g.t1)
    geng = ROSTER[6][0]                         # 庚，本来整行没录

    def put(subject, value):
        return g.b.client.put(f"/api/grades/{g.t1}/scores", json={
            "student_no": geng, "subject_id": subs[subject]["id"], "value": value})

    r = put("数学", "通过")
    assert r.status_code == 400 and "0~1000" in r.json()["detail"], "计分科目不收通过制的话"
    r = put("体育", "88")
    assert r.status_code == 400 and "通过制" in r.json()["detail"], "通过制科目不收分数"
    assert put("体育", "良").status_code == 400, "通过制也不认别的词"

    assert put("体育", "通过").status_code == 200
    # 标记词是「没参加考试的原因」，两种形态都得收（通过制科目照样有人缺考）
    assert put("数学", "缺考").status_code == 200
    assert put("体育", "缺考").status_code == 200
    assert put("数学", "").status_code == 200, "空串 = 清空"


# ---------- 改形态的防线 ----------

def test_change_subject_mode_blocked_by_data(g):
    """有分数就不能改成通过制，有通过/不通过就不能改成计分 —— 不静默清空"""
    subs = subjects_of(g.b, g.t1)
    url = f"/api/grades/{g.t1}/subjects/"

    r = g.b.client.patch(url + str(subs["数学"]["id"]), json={"mode": "pass_fail"})
    assert r.status_code == 400
    assert "4 条分数成绩" in r.json()["detail"], "要说清有几条，班委才知道要清多少"

    r = g.b.client.patch(url + str(subs["体育"]["id"]), json={"mode": "score"})
    assert r.status_code == 400
    assert "通过 / 不通过" in r.json()["detail"]

    # 只改满分、不动数据 → 放行
    assert g.b.client.patch(url + str(subs["数学"]["id"]),
                            json={"full_score": 150}).status_code == 200
    assert g.b.client.patch(url + str(subs["数学"]["id"]),
                            json={"mode": "计分"}).status_code == 400, "瞎词要拒"
    # 满分 0 走 pydantic 的 gt=0，是 422 不是 400
    assert g.b.client.patch(url + str(subs["数学"]["id"]),
                            json={"full_score": 0}).status_code == 422


def test_change_subject_mode_allowed_once_empty(g):
    """把那一列的成绩清空之后就该放行"""
    subs = subjects_of(g.b, g.t1)
    for no, _, _ in ROSTER[:4]:                 # 4 个有分数的人
        r = g.b.client.put(f"/api/grades/{g.t1}/scores", json={
            "student_no": no, "subject_id": subs["数学"]["id"], "value": ""})
        assert r.status_code == 200, r.text

    r = g.b.client.patch(f"/api/grades/{g.t1}/subjects/{subs['数学']['id']}",
                         json={"mode": "pass_fail"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "pass_fail"


# ---------- 导入 ----------

def test_import_records_mode_and_full_score(g):
    """整列都是「通过 / 不通过」就预选通过制；确认时选的形态与满分要真写进库"""
    pv = upload(g.b, ["学号", "姓名", "数学", "体育"], [
        [ROSTER[0][0], "甲", 88, "通过"],
        [ROSTER[1][0], "乙", 76, "不通过"],
        [ROSTER[2][0], "丙", 95, "通过"],
    ])
    cols = {c["name"]: c for c in pv["columns"]}
    assert cols["体育"]["suggest_pass_fail"] is True, "整列都是通过/不通过 → 预选通过制"
    assert cols["数学"]["suggest_pass_fail"] is False, "数字列不预选"
    assert pv["problems"] == [], "预判对了就不该有解析不了的格子"

    r = confirm(g.b, pv, name="导入测试", tested_at="2026-05-01",
                modes={"体育": "pass_fail"}, full_scores={"数学": 120})
    assert r.status_code == 200, r.text
    tid = r.json()["test_id"]

    subs = subjects_of(g.b, tid)
    assert subs["体育"]["mode"] == "pass_fail"
    assert subs["数学"]["full_score"] == 120.0

    st = stats_of(g.b, tid)
    assert (st["体育"]["passed_count"], st["体育"]["failed_count"]) == (2, 1)
    assert st["数学"]["avg"] == 86.3, "(88+76+95)/3 = 86.33…"
    assert st["数学"]["pass_rate"] == 100.0, "及格线 120×0.6 = 72，三人都过"


def test_import_rejects_mismatched_mode(g):
    """形态和数据对不上，两个方向都当场拒掉并点名哪一科；拒完令牌还在"""
    rows = [
        [ROSTER[0][0], "甲", 88, "通过"],
        [ROSTER[1][0], "乙", 76, "不通过"],
        [ROSTER[2][0], "丙", 95, "通过"],
    ]
    heads = ["学号", "姓名", "数学", "体育"]
    pv = upload(g.b, heads, rows)

    r = confirm(g.b, pv, name="选反了", modes={"体育": "score"})
    assert r.status_code == 400 and "体育" in r.json()["detail"], "通过/不通过 不能按计分录"

    r = confirm(g.b, pv, name="选反了2", modes={"数学": "pass_fail"})
    assert r.status_code == 400 and "数学" in r.json()["detail"], "分数不能按通过制录"

    # 被 400 挡回来之后令牌**留着**：班委改个下拉再点一次确认就该过，
    # 不该让人重新上传一次 Excel
    r = confirm(g.b, pv, name="改对了", modes={"体育": "pass_fail"})
    assert r.status_code == 200, r.text

    pv2 = upload(g.b, ["学号", "姓名", "数学"], [[ROSTER[0][0], "甲", 88]])
    assert confirm(g.b, pv2, name="瞎形态", modes={"数学": "等级制"}).status_code == 400


def test_pass_fail_column_with_absence(g):
    """通过制列里夹着缺考，照样该预选成通过制

    标记词两种形态都合法，不该把预判带偏。带偏的后果不只是下拉默认值不对：
    预判**同时是解析判据**，被当成计分制的话这一列的「通过 / 不通过」会在解析阶段
    逐格变成非法值，班委事后把形态改回来数据也回不来，只能重传 Excel。
    「多数人通过、个别缺考」恰恰是体育这种科目最常见的形状。
    """
    pv = upload(g.b, ["学号", "姓名", "体育"], [
        [ROSTER[0][0], "甲", "通过"],
        [ROSTER[1][0], "乙", "不通过"],
        [ROSTER[2][0], "丙", "缺考"],
    ])
    assert {c["name"]: c for c in pv["columns"]}["体育"]["suggest_pass_fail"] is True
    assert pv["problems"] == [], "预判对了就不该有非法格子"

    r = confirm(g.b, pv, name="混缺考", tested_at="2026-05-02")   # 不传 modes，走预判
    assert r.status_code == 200, r.text
    st = stats_of(g.b, r.json()["test_id"])["体育"]
    assert (st["passed_count"], st["failed_count"], st["marked_count"]) == (1, 1, 1)


# ---------- 迁移 ----------

def test_migration_backfills_subject_columns(backend):
    """老库（grade_subjects 缺 mode / full_score）启动一次就该补上，老数据按计分 100 分解释"""
    b = backend(db="mig.db", BOOTSTRAP_PASSWORD=PW)
    # 直连 SQLite 时 SQLAlchemy 的 default= 不生效（那是 Python 层的），两列都得显式给
    b.run("INSERT INTO grade_subjects (test_id, name, sort, mode, full_score)"
          " VALUES (1, '语文', 0, 'score', 100)")
    # 退回补列之前的样子：SQLite 3.35+ 才有 DROP COLUMN（本机 3.50）
    b.run("ALTER TABLE grade_subjects DROP COLUMN mode")
    b.run("ALTER TABLE grade_subjects DROP COLUMN full_score")

    b2 = backend(db="mig.db", BOOTSTRAP_PASSWORD=PW)     # 同一个库再起一次 = 重启
    row = b2.rows("SELECT name, mode, full_score FROM grade_subjects")[0]
    assert row == ("语文", "score", 100.0), "补列后老数据要按「计分 / 100 分」解释"
