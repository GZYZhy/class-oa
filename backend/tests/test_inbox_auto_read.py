"""站内信的自动已读：办件推进了，对应的消息就该算已读

    cd backend && python -m pytest tests/test_inbox_auto_read.py -q

判定规则（见 inbox_service.settle_topic）：

1. **待办类**（提交时推给审批人的那条）：批准 / 驳回 / 退回补正 / 撤销、
   申请人撤回 —— 任何让这单离开审批队列的动作，都对这单的所有收件人生效。
   审核中心页看得到结果，红点不必再提醒没看过的人。
2. **交代类**（退回补正推给学生的那条）：学生补齐重交后自动已读。
3. **交付类**（「已通过可下载」「已开好」）：对应文件被下载者本人下走后自动已读。
   管理员代下不算 —— 那不代表学生看过。

只走真接口推进办件，再用直连库的 read_at 断言结果；每条用例里都埋一条
无 topic 的普通消息，证明 settle 只清同一单的，不误伤别的。
"""
from types import SimpleNamespace

import httpx
import pytest

from conftest import png_bytes

PW = "initpass123"

ADMIN = "2024000001"      # 管理员（审批人）
APPLICANT = "2024000002"  # 申请人
ROSTER = [
    (ADMIN, "甲", "010001"),
    (APPLICANT, "丙", "010003"),
]
TAILS = {no: tail for no, _name, tail in ROSTER}

PNG = png_bytes()
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"

LEAVE_FORM = {
    "leave_type": "事假",
    "start_at": "2026-10-15 08:00",
    "end_at": "2026-10-17 18:00",
    "reason": "家里有事需要回去一趟",
}

CERT_FORM = {
    "title": "在读证明",
    "recipient": "某某公司人力资源部",
    "content": "兹证明该同学系我校在读学生",
    "extra_request": "",
    "confirmed": "true",
}

# 直接写一条「普通消息」（无 topic）当对照组：settle 不该碰它
_INSERT = (
    "INSERT INTO inbox_messages (student_no, title, body, level, created_at, read_at) "
    "VALUES (?, ?, ?, 'active', '2026-10-01 08:00:00', NULL)"
)


# ---------- 装置与小工具 ----------

def as_student(b, no) -> httpx.Client:
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": TAILS[no]})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def sp(backend):
    """初始化完毕：管理员（登录态在 b.client）、申请人（独立登录态）"""
    b = backend(db="auto_read.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200

    for no, name, tail in ROSTER:
        r = b.client.post("/api/students", json={
            "student_no": no, "name": name, "id_card": f"11010120000101{tail}",
        })
        assert r.status_code < 300, r.text

    r = b.client.post("/api/setup/finish", json={"admin_student_no": ADMIN})
    assert r.status_code == 200, r.text
    b.logout()
    assert b.login(student_no=ADMIN, password=TAILS[ADMIN]).status_code == 200

    # 对照组消息：埋在管理员和申请人各一条
    b.run(_INSERT, ADMIN, "普通消息", "正文")
    b.run(_INSERT, APPLICANT, "普通消息", "正文")
    return SimpleNamespace(b=b, applicant=as_student(b, APPLICANT))


def submit_leave(sp) -> int:
    r = sp.applicant.post("/api/leaves", data=LEAVE_FORM,
                          files={"proof": ("proof.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def unread_titles(b, no) -> list[str]:
    """未读标题，**不含对照组那条「普通消息」** —— 它永远未读，不参与业务断言"""
    return [row[0] for row in b.rows(
        "SELECT title FROM inbox_messages WHERE student_no = ? AND read_at IS NULL"
        " AND title != '普通消息'", no
    )]


def read_at_of(b, no, title):
    """某人某标题消息的 read_at；没有这条消息时返回 None 并让断言自己说话"""
    rows = b.rows(
        "SELECT read_at FROM inbox_messages WHERE student_no = ? AND title = ?", no, title
    )
    return rows[0][0] if rows else None


# ---------- 待办类：审批动作了结所有人的那条 ----------

def test_approving_reads_the_todo_and_keeps_the_result_unread(sp):
    """批准后：待办自动已读（含没看过的人），学生收到的「已通过」保持未读"""
    lid = submit_leave(sp)
    todo = f"leave:{lid}"

    assert read_at_of(sp.b, ADMIN, "有新的请假申请待审核") is None
    assert sp.b.rows(
        "SELECT topic FROM inbox_messages WHERE student_no = ? AND title = ?",
        ADMIN, "有新的请假申请待审核",
    )[0][0] == todo

    # 先受理再批准（审批的硬前置）
    assert sp.b.client.post(f"/api/leaves/{lid}/accept").status_code == 200
    assert sp.b.client.post(f"/api/leaves/{lid}/approve").status_code == 200

    assert read_at_of(sp.b, ADMIN, "有新的请假申请待审核") is not None, "待办该自动已读"
    assert read_at_of(sp.b, ADMIN, "普通消息") is None, "无 topic 的消息不该被牵连"
    assert unread_titles(sp.b, APPLICANT) == ["请假申请已通过"], "刚发的结果消息得保持未读"
    assert sp.b.rows(
        "SELECT topic FROM inbox_messages WHERE student_no = ? AND title = ?",
        APPLICANT, "请假申请已通过",
    )[0][0] == todo


def test_rejecting_reads_the_todo(sp):
    """驳回同样了结待办；学生那条「被驳回」保持未读"""
    lid = submit_leave(sp)
    assert sp.b.client.post(f"/api/leaves/{lid}/accept").status_code == 200
    assert sp.b.client.post(
        f"/api/leaves/{lid}/reject", json={"reason": "材料不全"}
    ).status_code == 200

    assert read_at_of(sp.b, ADMIN, "有新的请假申请待审核") is not None
    assert unread_titles(sp.b, APPLICANT) == ["请假申请被驳回"]


def test_withdrawing_reads_the_todo(sp):
    """学生撤回待受理的申请：单子没了，待办跟着作废"""
    lid = submit_leave(sp)
    assert sp.applicant.delete(f"/api/leaves/{lid}").status_code == 200

    assert read_at_of(sp.b, ADMIN, "有新的请假申请待审核") is not None


def test_correcting_reads_the_todo_and_resubmit_reads_the_notice(sp):
    """退回补正：管理员侧待办了结、学生侧来了条未读；学生重交后那条也自动已读"""
    lid = submit_leave(sp)
    assert sp.b.client.post(f"/api/leaves/{lid}/accept").status_code == 200
    assert sp.b.client.post(
        f"/api/leaves/{lid}/correcting", json={"reason": "证明材料不清晰"}
    ).status_code == 200

    assert read_at_of(sp.b, ADMIN, "有新的请假申请待审核") is not None
    assert unread_titles(sp.b, APPLICANT) == ["请假申请需要补交材料"]

    # 学生补齐重交（整套覆盖的 PUT），单子回到已受理，那条交代随之了结
    r = sp.applicant.put(f"/api/leaves/{lid}", data=LEAVE_FORM,
                         files={"proof": ("proof2.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    assert read_at_of(sp.b, APPLICANT, "请假申请需要补交材料") is not None
    assert unread_titles(sp.b, APPLICANT) == []


def test_editing_a_pending_leave_does_not_read_anything(sp):
    """还在待受理的单子被学生改了改：不算推进，谁的未读都不动"""
    lid = submit_leave(sp)
    r = sp.applicant.put(f"/api/leaves/{lid}", data=LEAVE_FORM,
                         files={"proof": ("proof2.png", PNG, "image/png")})
    assert r.status_code == 200, r.text

    assert read_at_of(sp.b, ADMIN, "有新的请假申请待审核") is None


# ---------- 交付类：文件下到手了才算完 ----------

def test_downloading_the_leave_table_reads_the_approval(sp):
    """「已通过」那条在学生把表下走后自动已读"""
    lid = submit_leave(sp)
    assert sp.b.client.post(f"/api/leaves/{lid}/accept").status_code == 200
    assert sp.b.client.post(f"/api/leaves/{lid}/approve").status_code == 200
    assert unread_titles(sp.b, APPLICANT) == ["请假申请已通过"]

    r = sp.applicant.get(f"/api/leaves/{lid}/pdf")
    assert r.status_code == 200, r.text
    assert read_at_of(sp.b, APPLICANT, "请假申请已通过") is not None


def test_admin_downloading_does_not_read_the_students_notice(sp):
    """管理员代下不算学生看过：申请人那条「已通过」还得挂着"""
    lid = submit_leave(sp)
    assert sp.b.client.post(f"/api/leaves/{lid}/accept").status_code == 200
    assert sp.b.client.post(f"/api/leaves/{lid}/approve").status_code == 200

    assert sp.b.client.get(f"/api/leaves/{lid}/pdf").status_code == 200
    assert unread_titles(sp.b, APPLICANT) == ["请假申请已通过"]


def test_certificate_flow_reads_in_order(sp):
    """证明这条链：批了 →「已通过待下载」；成品传了 → 上一条自动已读、
    「已开好」未读；学生下载 → 也自动已读"""
    r = sp.applicant.post("/api/certificates", data=CERT_FORM, files=None)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    assert sp.b.client.post(f"/api/certificates/{rid}/accept").status_code == 200
    assert sp.b.client.post(f"/api/certificates/{rid}/approve").status_code == 200
    assert unread_titles(sp.b, APPLICANT) == ["证明开具申请已通过"]

    assert sp.b.client.post(
        f"/api/certificates/{rid}/result",
        files={"file": ("result.pdf", PDF, "application/pdf")},
    ).status_code == 200
    # 成品一传，前一条就过时了；「已开好」顶上来
    assert read_at_of(sp.b, APPLICANT, "证明开具申请已通过") is not None
    assert unread_titles(sp.b, APPLICANT) == ["证明已开好"]

    r = sp.applicant.get(f"/api/certificates/{rid}/result")
    assert r.status_code == 200, r.text
    assert read_at_of(sp.b, APPLICANT, "证明已开好") is not None
    assert read_at_of(sp.b, APPLICANT, "普通消息") is None


# ---------- 签字查看申请 ----------

def test_sign_photo_review_reads_the_todo(sp):
    """签字查看也是审批类：批准后「有新的签字查看申请」自动已读，
    「已通过」那条保持未读"""
    sid = sp.b.rows(
        "SELECT id FROM students WHERE student_no = ?", APPLICANT
    )[0][0]
    r = sp.b.client.post(
        f"/api/sign-photos/image/{sid}",
        files={"file": ("sign.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text

    r = sp.b.client.post("/api/sign-photos/requests", json={"student_id": sid})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    assert read_at_of(sp.b, ADMIN, "有新的签字查看申请") is None
    assert sp.b.client.post(
        f"/api/sign-photos/requests/{rid}/approve"
    ).status_code == 200

    assert read_at_of(sp.b, ADMIN, "有新的签字查看申请") is not None
    assert unread_titles(sp.b, ADMIN) == ["签字查看申请已通过"]


def test_withdrawing_a_certificate_reads_the_todo(sp):
    """证明申请撤回后，管理员那条待办同样作废（记录删了 topic 还对得上）"""
    r = sp.applicant.post("/api/certificates", data=CERT_FORM)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    assert read_at_of(sp.b, ADMIN, "有新的证明开具申请") is None
    assert sp.applicant.delete(f"/api/certificates/{rid}").status_code == 200
    assert read_at_of(sp.b, ADMIN, "有新的证明开具申请") is not None


# ---------- 信息修改申请 ----------

def test_change_request_review_reads_the_todo(sp):
    """修改申请：班委审完（无论通过驳回），那条待办自动已读"""
    r = sp.applicant.post("/api/change-requests", json={"qq": "12345678"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    assert read_at_of(sp.b, ADMIN, "有新的信息修改申请待审核") is None
    assert sp.b.rows(
        "SELECT topic FROM inbox_messages WHERE student_no = ? AND title = ?",
        ADMIN, "有新的信息修改申请待审核",
    )[0][0] == f"change:{rid}"

    assert sp.b.client.post(f"/api/change-requests/{rid}/approve").status_code == 200
    assert read_at_of(sp.b, ADMIN, "有新的信息修改申请待审核") is not None
    assert unread_titles(sp.b, APPLICANT) == ["信息修改申请已通过"]
