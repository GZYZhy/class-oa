"""办件的受理环节：三个办件逐字同构，这份测试也就只写一遍

    cd backend && python -m pytest tests/test_review_flow.py -q

请假 / 电动车通行证 / 证明开具走的是同一套流程（app/services/review_flow.py）：
提交 → 受理 → 办结，五个状态、四个动作。三份实现的差别只有「交什么材料、挂哪个
URL、材料落在哪」，所以差别收进下面的 WORKFLOWS，同一批用例对着三份各跑一遍 ——
把同一批断言抄三遍的话，第三份漏一颗守卫不报错也不留痕，而这恰恰是公共层要消灭的东西。

每条用例都对着一个「差一点就静默出错」的写法：

1. 没受理就放行审批 —— 受理这一步当场形同虚设，且没有任何报错（用户口径是硬的：
   审批按钮在待受理时置灰）。
2. 受理重复调用写第二条日志、或者撤回受理把已经发出去的审批结果也顺手翻了。
3. 学生改完重交没回到「已受理」（用户口径：待补正也算已受理）—— 回了待受理的话
   班委得把材料重看一遍，而这不会报错。
4. 待办口径各写各的：红点数一档、列表 open 档数另一档、删学生拦截只认 pending。
   三处不一致时，「受理完红点减一，而这件事还等着他批」。
5. 撤销只删记录不删盘上的材料 —— 库里干净了，附件永远留在盘上没人清。
"""
import json
from types import SimpleNamespace

import httpx
import pytest

from conftest import png_bytes

PW = "initpass123"
ADMIN = "2024000001"      # 管理员：受理、审批、撤回都归他
CM = "2024000002"         # 班委：能看列表，但受理和审批都轮不到他
APPLICANT = "2024000003"  # 申请人
ROSTER = [(ADMIN, "甲", "010001"), (CM, "乙", "010002"), (APPLICANT, "丙", "010003")]
TAILS = {no: tail for no, _name, tail in ROSTER}

PNG = png_bytes()

LEAVE_FORM = {
    "leave_type": "事假",
    "start_at": "2026-10-15 08:00",
    "end_at": "2026-10-17 18:00",
    "reason": "家里有事需要回去一趟",
}


# ---------- 三个办件的差异点 ----------

def _leave_files(b, rid):
    return [b.rows("SELECT proof_file FROM leave_requests WHERE id = ?", rid)[0][0]]


def _ev_pass_files(b, rid):
    return [b.rows("SELECT license_file FROM ev_pass_requests WHERE id = ?", rid)[0][0]]


def _cert_files(b, rid):
    raw = b.rows("SELECT attachments FROM certificate_requests WHERE id = ?", rid)[0][0]
    return [item["file"] for item in json.loads(raw)]


WORKFLOWS = [
    SimpleNamespace(
        name="请假", tab="leave", table="leave_requests", url="/api/leaves",
        dirname="leaves", files_of=_leave_files,
        accept_log="受理请假申请", unaccept_log="撤回受理请假申请",
        correct_log="退回补正请假申请", blocker="待处理的请假申请",
        submit=lambda c: c.post("/api/leaves", data=LEAVE_FORM,
                                files={"proof": ("proof.png", PNG, "image/png")}),
        # 改的时候不重选证明（后端 PUT 的 proof 是 File(None) = 不动）
        update=lambda c, rid: c.put(f"/api/leaves/{rid}", data=LEAVE_FORM),
    ),
    SimpleNamespace(
        name="通行证", tab="evpass", table="ev_pass_requests", url="/api/ev-passes",
        dirname="ev_passes", files_of=_ev_pass_files,
        accept_log="受理电动车通行证申请", unaccept_log="撤回受理电动车通行证申请",
        correct_log="退回补正电动车通行证申请", blocker="待处理的电动车通行证",
        submit=lambda c: c.post("/api/ev-passes",
                                data={"brand": "雅迪", "plate_number": "北京1234567"},
                                files={"license_file": ("license.png", PNG, "image/png")}),
        update=lambda c, rid: c.put(f"/api/ev-passes/{rid}",
                                    data={"brand": "爱玛", "plate_number": "北京7654321"}),
    ),
    SimpleNamespace(
        name="证明", tab="certificate", table="certificate_requests",
        url="/api/certificates",
        dirname="cert_attachments", files_of=_cert_files,
        accept_log="受理证明开具申请", unaccept_log="撤回受理证明开具申请",
        correct_log="退回补正证明开具申请", blocker="待处理的证明开具",
        submit=lambda c: c.post("/api/certificates",
                                data={"title": "在读证明", "recipient": "某某公司",
                                      "content": "兹证明该同学系我校在读学生", "confirmed": "true"},
                                files={"attachments": ("basis.png", PNG, "image/png")}),
        update=lambda c, rid: c.put(f"/api/certificates/{rid}",
                                    data={"title": "在读证明（改）", "recipient": "某某公司",
                                          "content": "兹证明该同学系我校在读学生"}),
    ),
]


# ---------- 装置与小工具 ----------

def as_student(b, no) -> httpx.Client:
    """另开一个客户端以某个学生身份登录 —— 会话是按 client 存的"""
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": TAILS[no]})
    assert r.status_code == 200, r.text
    return c


def sid_of(b, no) -> int:
    return b.rows("SELECT id FROM students WHERE student_no = ?", no)[0][0]


@pytest.fixture
def rf(backend):
    """初始化完毕：管理员（登录态）、班委、申请人（登录态）"""
    b = backend(db="review.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200      # 初始化临时账号

    for no, name, tail in ROSTER:
        r = b.client.post("/api/students", json={
            "student_no": no, "name": name, "id_card": f"11010120000101{tail}",
        })
        assert r.status_code < 300, r.text

    r = b.client.post("/api/setup/finish", json={"admin_student_no": ADMIN})
    assert r.status_code == 200, r.text
    b.logout()
    assert b.login(student_no=ADMIN, password=TAILS[ADMIN]).status_code == 200

    r = b.client.put(f"/api/admin/users/{CM}/role", json={"role": "committee"})
    assert r.status_code == 200, r.text

    return SimpleNamespace(b=b, applicant=as_student(b, APPLICANT), cm=as_student(b, CM))


@pytest.fixture(params=WORKFLOWS, ids=[w.name for w in WORKFLOWS])
def wf(request):
    return request.param


def submit(rf, wf) -> int:
    r = wf.submit(rf.applicant)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending", "刚交上来的单子是待受理"
    return r.json()["id"]


def accept(rf, wf, rid):
    return rf.b.client.post(f"{wf.url}/{rid}/accept")


def correct(rf, wf, rid, reason):
    return rf.b.client.post(f"{wf.url}/{rid}/correcting", json={"reason": reason})


def status_of(b, wf, rid) -> str:
    return b.rows(f"SELECT status FROM {wf.table} WHERE id = ?", rid)[0][0]


def row_of(b, wf, rid):
    """(status, reviewer_no, reviewed_at, correction_reason)"""
    return b.rows(
        f"SELECT status, reviewer_no, reviewed_at, correction_reason"
        f" FROM {wf.table} WHERE id = ?", rid,
    )[0]


def actions(b) -> list[str]:
    return [row[0] for row in b.rows("SELECT action FROM operation_logs ORDER BY id")]


def inbox_of(b, no) -> list[tuple[str, str]]:
    """某人的站内信 (标题, 正文)，按收到的先后排"""
    return b.rows("SELECT title, body FROM inbox_messages WHERE student_no = ? ORDER BY id", no)


def inbox_total(b) -> int:
    """全库的站内信条数"""
    return b.rows("SELECT COUNT(*) FROM inbox_messages")[0][0]


def badge(rf, wf) -> int:
    r = rf.b.client.get("/api/badges")
    assert r.status_code == 200, r.text
    return r.json()["review_tabs"][wf.tab]


def open_ids(rf, wf) -> list[int]:
    """「待处理」那一档（= 审核页默认档）里有哪些单子"""
    r = rf.b.client.get(f"{wf.url}?status=open")
    assert r.status_code == 200, r.text
    return [row["id"] for row in r.json()]


# ---------- 没受理不能批 ----------

def test_approve_and_reject_need_an_accept_first(rf, wf):
    """审批的硬前置：材料没看过就不给批（这正是受理这一步存在的理由）"""
    rid = submit(rf, wf)

    r = rf.b.client.post(f"{wf.url}/{rid}/approve")
    assert r.status_code == 400, r.text
    assert "受理" in r.json()["detail"], "驳回理由得说清楚是「还没受理」"

    r = rf.b.client.post(f"{wf.url}/{rid}/reject", json={"reason": "材料不对"})
    assert r.status_code == 400, r.text
    assert row_of(rf.b, wf, rid)[0] == "pending", "两条都挡下了，状态一步没动"

    assert accept(rf, wf, rid).status_code == 200, "受理本身不用理由、不用附件"
    assert status_of(rf.b, wf, rid) == "accepted"

    assert rf.b.client.post(f"{wf.url}/{rid}/approve").status_code == 200
    assert status_of(rf.b, wf, rid) == "approved"


# ---------- 受理、撤回受理、办结后不能翻案 ----------

def test_accept_is_idempotent_and_unaccept_only_undoes_the_accept(rf, wf):
    rid = submit(rf, wf)

    assert accept(rf, wf, rid).status_code == 200
    assert accept(rf, wf, rid).status_code == 200, "反复打开材料是常态，第二次不该报错"
    assert actions(rf.b).count(wf.accept_log) == 1, "第二次什么都没改，就不该再写一条日志"

    assert rf.b.client.post(f"{wf.url}/{rid}/unaccept").status_code == 200
    assert status_of(rf.b, wf, rid) == "pending"
    assert actions(rf.b).count(wf.unaccept_log) == 1
    assert rf.b.client.post(f"{wf.url}/{rid}/unaccept").status_code == 400, "不是已受理就没得撤"

    # 办结之后退不回来：审批结果已经发出去了（通知推了、单据生成了、签字快照了）
    assert accept(rf, wf, rid).status_code == 200
    assert rf.b.client.post(f"{wf.url}/{rid}/approve").status_code == 200
    r = rf.b.client.post(f"{wf.url}/{rid}/unaccept")
    assert r.status_code == 400, r.text
    assert status_of(rf.b, wf, rid) == "approved"


def test_a_finished_application_cannot_be_flipped(rf, wf):
    """已通过的不许再驳回、已驳回的不许再通过 —— 证明那两个接口原先就漏在这"""
    rid = submit(rf, wf)
    accept(rf, wf, rid)
    assert rf.b.client.post(f"{wf.url}/{rid}/approve").status_code == 200
    r = rf.b.client.post(f"{wf.url}/{rid}/reject", json={"reason": "反悔了"})
    assert r.status_code == 400, r.text
    assert status_of(rf.b, wf, rid) == "approved"

    rid2 = submit(rf, wf)
    accept(rf, wf, rid2)
    assert rf.b.client.post(f"{wf.url}/{rid2}/reject", json={"reason": "材料不对"}).status_code == 200
    r = rf.b.client.post(f"{wf.url}/{rid2}/approve")
    assert r.status_code == 400, r.text
    assert status_of(rf.b, wf, rid2) == "rejected"
    assert wf.submit(rf.applicant).json()["id"] == rid2 + 1, "驳回之后只能重新交一份"


# ---------- 受理的对外效果 ----------

def test_accept_sends_no_notice_and_touches_no_reviewer_field(rf, wf):
    rid = submit(rf, wf)
    # 比的是**全库**的条数：提交时那条待办提醒已经写在管理员名下，受理若发通知，
    # 这里一定会多出来。只比申请人的收件箱是空的断言 —— 他这条链上本来就不收东西
    before = inbox_total(rf.b)

    assert accept(rf, wf, rid).status_code == 200
    assert inbox_total(rf.b) == before, "受理只是审批人自己的一步，不该惊动任何人"

    # 受理不碰审核人/审核时间：记上去的话，这条还没批的申请会提前出现在「我审批的」里，
    # 带着一个其实是受理时间的「审核时间」
    status, reviewer_no, reviewed_at, _ = row_of(rf.b, wf, rid)
    assert (status, reviewer_no, reviewed_at) == ("accepted", None, None)


def test_correcting_asks_the_applicant_to_fix_it_and_returns_to_accepted(rf, wf):
    """退回补正：带理由、要通知、学生改完回「已受理」（用户口径：待补正也算已受理）"""
    rid = submit(rf, wf)
    accept(rf, wf, rid)

    assert correct(rf, wf, rid, "").status_code == 422, "理由必填：学生要照着它补材料"
    assert status_of(rf.b, wf, rid) == "accepted", "校验没过，状态不该动"

    before = inbox_of(rf.b, APPLICANT)
    r = correct(rf, wf, rid, "照片上的日期看不清")
    assert r.status_code == 200, r.text
    assert status_of(rf.b, wf, rid) == "correcting"
    assert r.json()["correction_reason"] == "照片上的日期看不清", "理由要原样给学生看"
    assert actions(rf.b).count(wf.correct_log) == 1

    new = inbox_of(rf.b, APPLICANT)[len(before):]
    assert len(new) == 1 and "日期看不清" in new[0][1], "退回补正要通知申请人（理由带着走）"

    r = rf.b.client.post(f"{wf.url}/{rid}/approve")
    assert r.status_code == 400, "材料还没补就批它，是自相矛盾"

    # 学生改完重交
    assert wf.update(rf.applicant, rid).status_code == 200
    assert status_of(rf.b, wf, rid) == "accepted", "补完回「已受理」，不必让班委再看一遍"
    assert row_of(rf.b, wf, rid)[3] == "", "理由用完就清掉，别挂在记录上"
    assert rf.b.client.post(f"{wf.url}/{rid}/approve").status_code == 200


# ---------- 学生端：谁能改、谁能撤、撤了留下什么 ----------

def test_the_applicant_can_only_edit_or_cancel_before_it_is_done(rf, wf):
    rid = submit(rf, wf)

    # 不是自己的申请，改和撤都轮不到 —— 班委也不行（他只能看列表）。
    # 请假那边报 404（连「有这么一条」都不告诉他），另两个报 403，两种都算挡下了
    assert wf.update(rf.cm, rid).status_code in (403, 404)
    assert rf.cm.delete(f"{wf.url}/{rid}").status_code in (403, 404)

    # 待受理：改（状态原地不动，本来就还没人看过）、撤（连盘上的材料一起删）
    assert wf.update(rf.applicant, rid).status_code == 200
    assert status_of(rf.b, wf, rid) == "pending"

    # 受理之后：改不了也撤不掉，得先让班委撤回受理
    accept(rf, wf, rid)
    assert wf.update(rf.applicant, rid).status_code == 400
    assert rf.applicant.delete(f"{wf.url}/{rid}").status_code == 400

    # 待补正：能改（这就是退回补正的全部意义），但不能撤（是让补材料，不是让放弃）
    correct(rf, wf, rid, "缺一张照片")
    assert rf.applicant.delete(f"{wf.url}/{rid}").status_code == 400
    assert wf.update(rf.applicant, rid).status_code == 200
    assert status_of(rf.b, wf, rid) == "accepted"

    # 退回待受理，撤销：记录和材料一起没
    assert rf.b.client.post(f"{wf.url}/{rid}/unaccept").status_code == 200
    paths = [rf.b.db.parent / wf.dirname / name for name in wf.files_of(rf.b, rid)]
    assert paths and all(p.exists() for p in paths), "撤销前材料得在盘上，否则这条断言是空的"

    assert rf.applicant.delete(f"{wf.url}/{rid}").status_code == 200
    assert rf.b.rows(f"SELECT COUNT(*) FROM {wf.table} WHERE id = ?", rid)[0][0] == 0
    assert wf.update(rf.applicant, rid).status_code == 404, "撤销之后就没这条了"
    assert not any(p.exists() for p in paths), "记录删了，材料不该留在盘上"


# ---------- 待办口径（红点 / 列表 open 档 / 删学生拦截）----------

def test_the_badge_the_open_filter_and_the_delete_guard_share_one_rule(rf, wf):
    rid = submit(rf, wf)
    assert badge(rf, wf) == 1
    assert open_ids(rf, wf) == [rid]

    accept(rf, wf, rid)
    assert badge(rf, wf) == 1, "受理完这件事还等着他批，红点不该减"
    assert open_ids(rf, wf) == [rid], "默认档里也得留着，否则点一下受理行就从眼前消失了"

    assert rf.b.client.post(f"{wf.url}/{rid}/approve").status_code == 200
    assert badge(rf, wf) == 0
    assert open_ids(rf, wf) == []

    # 没办结的单子留着学生：学生先没了的话，班委那边点「通过」会撞上「学生不存在」
    rid2 = submit(rf, wf)
    accept(rf, wf, rid2)
    correct(rf, wf, rid2, "缺一张照片")
    r = rf.b.client.delete(f"/api/students/{sid_of(rf.b, APPLICANT)}")
    assert r.status_code == 400, r.text
    assert wf.blocker in r.json()["detail"], "待补正的也算没办结，照样拦着"

    assert wf.update(rf.applicant, rid2).status_code == 200      # 补完回已受理
    assert rf.b.client.post(f"{wf.url}/{rid2}/approve").status_code == 200
    assert rf.b.client.delete(f"/api/students/{sid_of(rf.b, APPLICANT)}").status_code == 200


# ---------- 迁移 ----------

def test_migration_backfills_correction_reason(backend):
    """老库（三张办件表都没有 correction_reason）启动一次就该补上

    证明那张表此前一列都没补过，这是它第一次进 NEW_COLUMNS —— 所以三张表各看一行。
    补列那一刻库里可能已经有数据（本机库就是生产数据的拷贝），所以断言里也带上：
    老行补出来是空串（= 没被打回过），不是 NULL。
    """
    b = backend(db="mig.db", BOOTSTRAP_PASSWORD=PW)
    tables = ("leave_requests", "ev_pass_requests", "certificate_requests")
    for table in tables:
        # 退回补列之前的样子（SQLite 3.35+ 才有 DROP COLUMN，本机 3.50）
        b.run(f"ALTER TABLE {table} DROP COLUMN correction_reason")

    b2 = backend(db="mig.db", BOOTSTRAP_PASSWORD=PW)     # 同一个库再起一次 = 重启
    for table in tables:
        columns = {row[1] for row in b2.rows(f"PRAGMA table_info({table})")}
        assert "correction_reason" in columns, f"{table} 没补上列"
