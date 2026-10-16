"""证明开具：提交、受理、审批、成品上传与下载

    cd backend && python -m pytest tests/test_certificate_api.py -q

三个办件里只有这份是从零补的接口测试（请假和通行证各有一份，证明此前一个用例都没有）。
受理环节的**通用语义**（幂等、撤回、补正、待办口径）在 test_review_flow.py 里对着
三个办件一起跑，这里只写证明自己的东西：

1. 附件是**选填**的（`File(default=[])`）—— 一条不带附件的申请没有「打开材料」这个
   动作，只靠「打开即受理」会永久卡死。所以受理必须有一个显式的按钮能按，
   这条在这里钉住（这正是 POST /{id}/accept 存在的理由）。
2. approve / reject 原先那两个漏洞：只挡「已通过」的 approve、一句检查都没有的 reject。
   现在两者共用 require_accepted，回归断言在这里（通用语义那侧也有）。
3. 成品 PDF 的下载口子：学生本人、且**已通过**才能下；班委能看申请附件、但下不了成品
   （成品走 admin_required，班委不是 admin）。
"""
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import httpx
import pytest

from conftest import png_bytes

PW = "initpass123"
ADMIN = "2024000001"
CM = "2024000002"         # 班委：能看列表和申请附件，审批与成品都轮不到他
APPLICANT = "2024000003"
CLASSMATE = "2024000004"  # 同班同学：别人的证明附件绝不该看得到
ROSTER = [
    (ADMIN, "甲", "010001"),
    (CM, "乙", "010002"),
    (APPLICANT, "丙", "010003"),
    (CLASSMATE, "丁", "010004"),
]
TAILS = {no: tail for no, _name, tail in ROSTER}

PNG = png_bytes()
# 后端只看后缀、不解析内容，成品那份要逐字节比对，所以内容随便造但要固定
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"

FORM = {
    "title": "在读证明",
    "recipient": "某某公司人力资源部",
    "content": "兹证明该同学系我校在读学生",
    "extra_request": "需要两份",
    "confirmed": "true",
}


# ---------- 装置与小工具 ----------

def as_student(b, no) -> httpx.Client:
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": TAILS[no]})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def cp(backend):
    """初始化完毕：管理员（登录态）、班委、申请人（登录态）、同班同学（登录态）"""
    b = backend(db="cert.db", BOOTSTRAP_PASSWORD=PW)
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

    return SimpleNamespace(
        b=b,
        applicant=as_student(b, APPLICANT),
        classmate=as_student(b, CLASSMATE),
        cm=as_student(b, CM),
        attach_dir=b.db.parent / "cert_attachments",
        result_dir=b.db.parent / "cert_results",
    )


def submit(cp, files=(("basis.png", PNG, "image/png"),), **overrides) -> int:
    """交一份申请。files 是若干个 (文件名, 字节, 类型)，传 None 就是不带附件"""
    parts = [("attachments", f) for f in files] if files else None
    r = cp.applicant.post("/api/certificates", data={**FORM, **overrides}, files=parts)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def accept(cp, rid):
    return cp.b.client.post(f"/api/certificates/{rid}/accept")


def approve(cp, rid):
    assert accept(cp, rid).status_code == 200
    r = cp.b.client.post(f"/api/certificates/{rid}/approve")
    assert r.status_code == 200, r.text
    return r


def upload_result(cp, rid, name="证明.pdf", data=PDF):
    return cp.b.client.post(f"/api/certificates/{rid}/result",
                            files={"file": (name, data, "application/pdf")})


def status_of(cp, rid) -> str:
    return cp.b.rows("SELECT status FROM certificate_requests WHERE id = ?", rid)[0][0]


def inbox_total(b) -> int:
    """全库的站内信条数。比「某人收件箱没变」结实：提交时那条待办提醒已经写在管理员
    名下，受理若发通知，这里一定会多出来"""
    return b.rows("SELECT COUNT(*) FROM inbox_messages")[0][0]


def attachments_of(cp, rid) -> list[dict]:
    import json
    raw = cp.b.rows("SELECT attachments FROM certificate_requests WHERE id = ?", rid)[0][0]
    return json.loads(raw)


# ---------- 提交 ----------

def test_submit_needs_the_confirmation_but_not_the_attachments(cp):
    r = cp.applicant.post("/api/certificates", data={**FORM, "confirmed": "false"})
    assert r.status_code == 400 and "确认" in r.json()["detail"]

    r = cp.applicant.post("/api/certificates", data={k: v for k, v in FORM.items() if k != "title"})
    assert r.status_code == 422, "标题是必填的"

    # 附件选填：不带任何附件也要能交上（受理靠显式按钮，见下面那条用例）
    rid = submit(cp, files=None)
    assert status_of(cp, rid) == "pending"
    assert attachments_of(cp, rid) == []
    assert cp.applicant.get("/api/certificates/my").json()[0]["id"] == rid


def test_attachments_are_capped_and_type_checked(cp):
    four = [("f1.png", PNG, "image/png"), ("f2.png", PNG, "image/png"),
            ("f3.png", PNG, "image/png"), ("f4.png", PNG, "image/png")]
    r = cp.applicant.post("/api/certificates", data=FORM, files=[("attachments", f) for f in four])
    assert r.status_code == 400 and "最多" in r.json()["detail"]

    r = cp.applicant.post("/api/certificates", data=FORM,
                          files={"attachments": ("木马.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400 and "不支持" in r.json()["detail"]

    # 校验没过的那一趟不能留下孤儿文件：盘上还是空的
    assert list(cp.attach_dir.iterdir()) == []

    # 三个以内、后缀合法就收，响应里带回原始文件名与字节数
    rid = submit(cp, files=[("a.png", PNG, "image/png"), ("b.pdf", PDF, "application/pdf")])
    items = attachments_of(cp, rid)
    assert [item["name"] for item in items] == ["a.png", "b.pdf"]
    assert items[0]["size"] == len(PNG)
    assert len(list(cp.attach_dir.iterdir())) == 2


# ---------- 谁能看附件 ----------

def test_attachment_access_is_by_owner_and_by_committee(cp):
    rid = submit(cp)
    assert cp.applicant.get(f"/api/certificates/{rid}/attachment/0").status_code == 200
    assert cp.applicant.get(f"/api/certificates/{rid}/attachment/9").status_code == 404

    assert cp.classmate.get(f"/api/certificates/{rid}/attachment/0").status_code == 403
    assert cp.classmate.get(f"/api/certificates/{rid}/attachment/0/admin").status_code == 403
    assert cp.classmate.get("/api/certificates").status_code == 403, "普通学生看不到列表"

    assert cp.cm.get(f"/api/certificates/{rid}/attachment/0/admin").status_code == 200
    assert cp.cm.get("/api/certificates").json()[0]["id"] == rid


# ---------- 受理到成品 ----------

def test_the_whole_flow_from_submit_to_download(cp):
    rid = submit(cp)

    # 未受理时审批点不动（证明原先那两个漏洞的回归）
    r = cp.b.client.post(f"/api/certificates/{rid}/approve")
    assert r.status_code == 400 and "受理" in r.json()["detail"]
    r = cp.b.client.post(f"/api/certificates/{rid}/reject", json={"reason": "材料不对"})
    assert r.status_code == 400 and "受理" in r.json()["detail"]
    assert status_of(cp, rid) == "pending"

    # 班委能看，但审批轮不到他
    assert cp.cm.post(f"/api/certificates/{rid}/approve").status_code == 403
    assert cp.cm.post(f"/api/certificates/{rid}/accept").status_code == 403

    assert accept(cp, rid).status_code == 200
    assert cp.b.client.post(f"/api/certificates/{rid}/approve").status_code == 200
    assert status_of(cp, rid) == "approved"

    # 通过之后：说明学生那侧也看得到审核人
    assert cp.applicant.get("/api/certificates/my").json()[0]["reviewer_name"]

    r = upload_result(cp, rid)
    assert r.status_code == 200, r.text

    r = cp.applicant.get(f"/api/certificates/{rid}/result")
    assert r.status_code == 200, r.text
    assert r.content == PDF, "下载到的就是上传的那份"
    # 文件名按 RFC 5987 编码（中文名要 percent-encode），解回来再比
    assert "证明.pdf" in unquote(r.headers["content-disposition"])

    assert cp.b.client.get(f"/api/certificates/{rid}/result/admin").status_code == 200
    assert cp.classmate.get(f"/api/certificates/{rid}/result").status_code == 403
    assert cp.cm.get(f"/api/certificates/{rid}/result/admin").status_code == 403, "成品只有管理员能下"


def test_the_result_can_only_be_uploaded_after_approval(cp):
    rid = submit(cp)
    r = upload_result(cp, rid)
    assert r.status_code == 400 and "未通过" in r.json()["detail"]

    accept(cp, rid)
    assert upload_result(cp, rid).status_code == 400, "受理了也还没通过"

    assert cp.b.client.post(f"/api/certificates/{rid}/approve").status_code == 200
    r = upload_result(cp, rid, name="证明.docx", data=b"PK\x03\x04")
    assert r.status_code == 400 and "PDF" in r.json()["detail"]

    assert cp.b.client.get(f"/api/certificates/{rid}/result/admin").status_code == 404, "还没传"
    assert cp.applicant.get(f"/api/certificates/{rid}/result").status_code == 404


def test_uploading_a_new_result_replaces_the_old_one(cp):
    rid = submit(cp)
    approve(cp, rid)
    assert upload_result(cp, rid, name="旧.pdf").status_code == 200
    old = cp.b.rows("SELECT result_file FROM certificate_requests WHERE id = ?", rid)[0][0]

    second = b"%PDF-1.4\nsecond\n%%EOF\n"
    assert upload_result(cp, rid, name="新.pdf", data=second).status_code == 200
    assert cp.applicant.get(f"/api/certificates/{rid}/result").content == second
    assert not (cp.result_dir / old).exists(), "换成品之后旧文件不该留在盘上"


def test_an_empty_attachment_application_can_still_be_accepted(cp):
    """附件选填，所以必须有一个不依赖「打开材料」的受理入口 —— 否则这种单子永久卡死"""
    rid = submit(cp, files=None)
    assert attachments_of(cp, rid) == []

    before = inbox_total(cp.b)
    r = accept(cp, rid)
    assert r.status_code == 200, r.text
    assert status_of(cp, rid) == "accepted"
    assert inbox_total(cp.b) == before, "受理不发通知"

    # 受理也不记审核人/审核时间：记上去的话，这条还没批的申请会提前出现在「我审批的」里
    assert cp.b.rows(
        "SELECT reviewer_no, reviewed_at FROM certificate_requests WHERE id = ?", rid,
    )[0] == (None, None)

    assert cp.b.client.post(f"/api/certificates/{rid}/approve").status_code == 200


# ---------- 迁移后老库里的这一列 ----------

def test_a_legacy_row_has_an_empty_correction_reason(cp):
    """补列补出来的是空串（= 没被打回过），不是 NULL —— 前端拿它判真假值"""
    rid = submit(cp)
    assert cp.b.rows(
        "SELECT correction_reason FROM certificate_requests WHERE id = ?", rid)[0][0] == ""
    assert Path(cp.attach_dir).exists()


# ---------- 列表筛选的四档 ----------

def _at(cp, status) -> int:
    """提交一条，再把库里的状态直接改成目标值（理由见 test_leave_sign_api.py 同名帮手）"""
    rid = submit(cp)
    cp.b.run("UPDATE certificate_requests SET status = ? WHERE id = ?", status, rid)
    return rid


def test_the_status_filter_has_a_closed_bucket(cp):
    """筛选器就四档：待处理 / 待补正 / 已办结 / 全部（默认「全部」）

    「已办结」要把通过和驳回都收进来，漏一个就永远筛不全 —— 三个办件的列表接口
    各写了一遍这个分支，所以三个文件里各有一条同样的用例
    """
    made = {s: _at(cp, s) for s in
            ("pending", "accepted", "correcting", "approved", "rejected")}

    def ids(status):
        url = f"/api/certificates?status={status}" if status else "/api/certificates"
        r = cp.b.client.get(url)
        assert r.status_code == 200, r.text
        return {row["id"] for row in r.json()}

    assert ids("open") == {made["pending"], made["accepted"]}, "待处理 = 待受理 + 已受理"
    assert ids("correcting") == {made["correcting"]}
    assert ids("closed") == {made["approved"], made["rejected"]}, "已办结 = 已通过 + 已驳回"
    assert ids("") == set(made.values()), "不传 status 就是全部"
