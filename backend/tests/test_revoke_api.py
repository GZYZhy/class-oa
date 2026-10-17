"""管理员撤销已通过的单子：三个办件同一套语义

    cd backend && python -m pytest tests/test_revoke_api.py -q

撤销是**终态**，撤了就不能恢复。这条约束靠的不是撤销接口自己，而是其他每个入口
都按状态把路堵死 —— 批不了、补不了签字、下不了 PDF、改不了。少堵一处，
被撤掉的单子就还能接着用，所以这里逐条钉住：

1. 只有 approved 能撤；pending / accepted / 已撤过的都是 400。
2. 撤完进「已办结」：closed 筛选里要能看见它（用户口径：已撤销仍在已办结中展示）。
3. 撤销要发通知、写操作日志 —— 申请人可能已经打印出来了，不喊一声不知道作废了。
4. 班委不是管理员，点不动这个按钮。
"""
from types import SimpleNamespace

import httpx
import pytest

from conftest import png_bytes

PW = "initpass123"
ADMIN = "2024000001"
CM = "2024000002"
APPLICANT = "2024000003"
ROSTER = [
    (ADMIN, "甲", "010001"),
    (CM, "乙", "010002"),
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
    "travel_mode": "高铁",
    "travel_detail": "G123 次",
    "destination": "山东省济南市历下区解放路1号",
    "destination_phone": "13700137000",
}
CERT_FORM = {
    "title": "在读证明",
    "recipient": "某某公司人力资源部",
    "content": "兹证明该同学系我校在读学生",
    "extra_request": "需要两份",
    "confirmed": "true",
}


# ---------- 小工具 ----------

def as_student(b, no) -> httpx.Client:
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": TAILS[no]})
    assert r.status_code == 200, r.text
    return c


def db_row(b, table, rid):
    return b.rows(f"SELECT status FROM {table} WHERE id = ?", rid)[0][0]


def approved_leave(rv) -> int:
    r = rv.applicant.post("/api/leaves", data=LEAVE_FORM,
                          files={"proof": ("proof.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert rv.b.client.post(f"/api/leaves/{rid}/accept").status_code == 200
    assert rv.b.client.post(f"/api/leaves/{rid}/approve").status_code == 200
    return rid


def approved_ev_pass(rv) -> int:
    r = rv.applicant.post("/api/ev-passes",
                          data={"brand": "雅迪", "plate_number": "京A1234567"},
                          files={"license_file": ("license.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert rv.b.client.post(f"/api/ev-passes/{rid}/accept").status_code == 200
    assert rv.b.client.post(f"/api/ev-passes/{rid}/approve").status_code == 200
    return rid


def approved_certificate(rv) -> int:
    r = rv.applicant.post("/api/certificates", data=CERT_FORM,
                          files=[("attachments", ("basis.png", PNG, "image/png"))])
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert rv.b.client.post(f"/api/certificates/{rid}/accept").status_code == 200
    assert rv.b.client.post(f"/api/certificates/{rid}/approve").status_code == 200
    return rid


def revoke_targets(rv):
    """三个办件各造一条已通过的，返回 [(撤销接口路径, 表名, id)]"""
    lid, eid, cid = approved_leave(rv), approved_ev_pass(rv), approved_certificate(rv)
    return [
        (f"/api/leaves/{lid}/revoke", "leave_requests", lid),
        (f"/api/ev-passes/{eid}/revoke", "ev_pass_requests", eid),
        (f"/api/certificates/{cid}/revoke", "certificate_requests", cid),
    ]


def last_log(b):
    return b.rows("SELECT action, detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0]


@pytest.fixture
def rv(backend):
    b = backend(db="revoke.db", BOOTSTRAP_PASSWORD=PW)
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
    assert b.client.put(f"/api/admin/users/{CM}/role",
                        json={"role": "committee"}).status_code == 200

    return SimpleNamespace(
        b=b,
        applicant=as_student(b, APPLICANT),
        cm=as_student(b, CM),
    )


# ---------- 能撤 / 只能撤已通过的 ----------

def test_revoke_turns_three_workflows_into_revoked(rv):
    """三个办件都能撤，撤完库里就是 revoked"""
    for path, table, rid in revoke_targets(rv):
        r = rv.b.client.post(path)
        assert r.status_code == 200, (path, r.text)
        assert db_row(rv.b, table, rid) == "revoked", path


def test_only_approved_can_be_revoked(rv):
    """待受理、已受理、已撤过的都点不动"""
    # 待受理：还没受理
    rid = rv.applicant.post("/api/leaves", data=LEAVE_FORM,
                            files={"proof": ("proof.png", PNG, "image/png")}).json()["id"]
    assert rv.b.client.post(f"/api/leaves/{rid}/revoke").status_code == 400
    # 已受理：审批之前也不能撤
    assert rv.b.client.post(f"/api/leaves/{rid}/accept").status_code == 200
    assert rv.b.client.post(f"/api/leaves/{rid}/revoke").status_code == 400

    # 撤过一次之后，再撤一次也是 400 —— 撤销不能撤销，也不能重复撤销
    rid = approved_leave(rv)
    assert rv.b.client.post(f"/api/leaves/{rid}/revoke").status_code == 200
    again = rv.b.client.post(f"/api/leaves/{rid}/revoke")
    assert again.status_code == 400
    assert "只有已通过" in again.json()["detail"]


def test_a_committee_member_and_a_guest_cannot_revoke(rv):
    """班委只读；没登录的直接 401"""
    paths = [p for p, _, _ in revoke_targets(rv)]
    for path in paths:
        assert rv.cm.post(path).status_code == 403, path

    guest = httpx.Client(base_url=str(rv.b.client.base_url), timeout=10)
    for path in paths:
        assert guest.post(path).status_code == 401, path


# ---------- 撤销之后：别的入口全堵死 ----------

def test_revoked_cannot_be_approved_signed_or_downloaded(rv):
    """撤销是终态：批、补签字、下载都按状态被拦，且下载要给「已撤销」的明确文案"""
    lid = approved_leave(rv)
    eid = approved_ev_pass(rv)
    cid = approved_certificate(rv)
    for path in (f"/api/leaves/{lid}/revoke", f"/api/ev-passes/{eid}/revoke",
                 f"/api/certificates/{cid}/revoke"):
        assert rv.b.client.post(path).status_code == 200, path

    # 再批一次
    assert rv.b.client.post(f"/api/leaves/{lid}/approve").status_code == 400
    assert rv.b.client.post(f"/api/ev-passes/{eid}/approve").status_code == 400
    assert rv.b.client.post(f"/api/certificates/{cid}/approve").status_code == 400

    # 补签字
    assert rv.b.client.post(f"/api/leaves/{lid}/advisor-sign",
                            json={"advisor_sign_no": ADMIN}).status_code == 400
    assert rv.b.client.post(f"/api/ev-passes/{eid}/sign",
                            json={"sign_no": ADMIN}).status_code == 400

    # 下载：学生和管理员都拿不到，且文案点明「已撤销」而不是笼统的「未通过」
    for client in (rv.applicant, rv.b.client):
        r = client.get(f"/api/leaves/{lid}/pdf")
        assert r.status_code == 400 and "已撤销" in r.json()["detail"]
    for suffix in ("pass-pdf", "promise-pdf"):
        r = rv.applicant.get(f"/api/ev-passes/{eid}/{suffix}")
        assert r.status_code == 400 and "已撤销" in r.json()["detail"]
    r = rv.applicant.get(f"/api/certificates/{cid}/result")
    assert r.status_code == 400 and "已撤销" in r.json()["detail"]
    r = rv.b.client.get(f"/api/certificates/{cid}/result/admin")
    assert r.status_code == 400 and "已撤销" in r.json()["detail"]

    # 成品也不能再传（上传要求已通过）
    r = rv.b.client.post(f"/api/certificates/{cid}/result",
                         files={"file": ("result.pdf", PDF, "application/pdf")})
    assert r.status_code == 400


def test_revoked_still_shows_in_the_closed_bucket(rv):
    """「已办结」= 已通过 + 已驳回 + 已撤销（用户口径：已撤销仍在已办结中展示）"""
    made = {
        "leave": approved_leave(rv),
        "ev": approved_ev_pass(rv),
        "cert": approved_certificate(rv),
    }
    for path in (f"/api/leaves/{made['leave']}/revoke", f"/api/ev-passes/{made['ev']}/revoke",
                 f"/api/certificates/{made['cert']}/revoke"):
        assert rv.b.client.post(path).status_code == 200

    for url, key in (("/api/leaves", "leave"), ("/api/ev-passes", "ev"),
                     ("/api/certificates", "cert")):
        closed = rv.b.client.get(f"{url}?status=closed")
        assert closed.status_code == 200, closed.text
        ids = {row["id"] for row in closed.json()}
        assert made[key] in ids, f"{url} 的已办结里漏了已撤销的单子"

        only = rv.b.client.get(f"{url}?status=revoked")
        assert only.status_code == 200, only.text
        assert {row["id"] for row in only.json()} == {made[key]}, url


# ---------- 通知与日志 ----------

def test_revoke_notifies_the_applicant_and_writes_a_log(rv):
    """申请人要收到通知（可能已经打印出来了），操作日志里要有撤销这条"""
    actions = []
    for path, _, _ in revoke_targets(rv):
        assert rv.b.client.post(path).status_code == 200
        actions.append(last_log(rv.b)[0])

    assert actions == [
        "撤销已通过的请假申请",
        "撤销已通过的电动车通行证申请",
        "撤销已通过的证明开具",
    ]

    titles = [r[0] for r in rv.b.rows(
        "SELECT title FROM inbox_messages WHERE student_no = ? ORDER BY id", APPLICANT)]
    for expected in ("请假申请已撤销", "电动车通行证申请已撤销", "证明开具申请已撤销"):
        assert expected in titles, titles
