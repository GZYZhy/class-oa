"""请假审批表的班导师意见与签字：谁能签、签完能改吗、谁能下载

    cd backend && python -m pytest tests/test_leave_sign_api.py -q

这条链上每一步都有一个「就差一点」的写法会静默出错：

1. 批准时选了谁的签字，就**复制一份**进 LEAVE_DIR、库里存副本名 —— 只存原图名的话，
   管理员换图或删图（两个接口都有）之后，历史单据会静默掉签字，而库里还写着「已签字」。
2. 已批准的记录不许再批一次：能再点一次就会重新快照、把当初那张覆盖掉。
3. 下载口子从「仅管理员」放开到「申请人本人或管理员」—— 放开时最容易顺手写成
   「任何登录用户」，那样全班的请假条互相都能下。
4. 下载**不写访问日志**是按设计的（学生和管理员下到同一份文件），所以溯源只能靠水印。

请假文件的目录被隔离了（conftest 给后端指了 tmp_path/leaves），所以可以直接数盘上
有什么 —— 「副本落没落盘」「提交失败留没留孤儿」只有看盘才作数。
"""
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pymupdf import open as open_pdf

from conftest import png_bytes

PW = "initpass123"
TAILS = {}
EXT_PW = "extpass123"

ADMIN = "2024000001"     # 管理员，也是签字人
CM = "2024000002"        # 班委：能看列表，但审批和下载都轮不到他
APPLICANT = "2024000003"  # 申请人
CLASSMATE = "2024000004"  # 同班同学：绝不该因为「都是学生」就能下载别人的请假表
ROSTER = [
    (ADMIN, "甲", "010001"),
    (CM, "乙", "010002"),
    (APPLICANT, "丙", "010003"),
    (CLASSMATE, "丁", "010004"),
]
for _no, _name, _tail in ROSTER:
    TAILS[_no] = _tail

EXT_LOGIN = "teacher_li"   # 域外账号：同等权限，也能当签字人
EXT_NAME = "李俊刚"

PNG = png_bytes()

FORM = {
    "leave_type": "事假",
    "start_at": "2026-10-15 08:00",
    "end_at": "2026-10-17 18:00",
    "reason": "家里有事需要回去一趟",
    "travel_mode": "高铁",
    "travel_detail": "G123 次",
    "destination": "山东省济南市历下区解放路1号",
    "destination_phone": "13700137000",
}


# ---------- 小工具 ----------

def as_student(b, no) -> httpx.Client:
    """另开一个客户端以某个学生身份登录 —— 会话是按 client 存的"""
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": TAILS[no]})
    assert r.status_code == 200, r.text
    return c


def sid_of(b, no) -> int:
    return b.rows("SELECT id FROM students WHERE student_no = ?", no)[0][0]


def create_ext(b, login=EXT_LOGIN, name=EXT_NAME, role="admin"):
    """建一个域外账号（默认就是管理员 —— 这次要的是「域外同等权限」那个口径）"""
    return b.client.post("/api/admin/external-users", data={
        "login_name": login, "display_name": name, "password": EXT_PW, "role": role,
    }, files={"sign_photo": ("sign.png", PNG, "image/png")})


def upload_sign(b, sid, data=PNG):
    r = b.client.post(f"/api/sign-photos/image/{sid}",
                      files={"file": ("sign.png", data, "image/png")})
    assert r.status_code == 200, r.text


def photo_file_of(b, no) -> Path:
    """某个学生签字图在盘上叫什么（后端只存文件名，路径是 PHOTO_DIR / 文件名）"""
    name = b.rows("SELECT sign_photo FROM students WHERE student_no = ?", no)[0][0]
    return b.db.parent / "photos" / name


def submit(client) -> int:
    r = client.post("/api/leaves", data=FORM,
                    files={"proof": ("proof.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def approve(b, lid, **body):
    """带 body 就传，不带就一个字节都不发 —— 老前端那句 approveLeave(id) 正是后者"""
    if body:
        return b.client.post(f"/api/leaves/{lid}/approve", json=body)
    return b.client.post(f"/api/leaves/{lid}/approve")


def advisor_sign(b, lid, **body):
    return b.client.post(f"/api/leaves/{lid}/advisor-sign", json=body)


def row_of(b, lid):
    """(status, opinion, sign_no, sign_name, sign_file)"""
    return b.rows(
        "SELECT status, advisor_opinion, advisor_sign_no, advisor_sign_name, advisor_sign_file"
        " FROM leave_requests WHERE id = ?", lid,
    )[0]


def images_in(pdf_bytes) -> int:
    """PDF 里画了几张图 —— 请假表上除了签字图没有别的图，数它就是数签字

    用 get_image_info（**逐次绘制**）而不是 get_images：同一张图在两处画出来
    在 PDF 里只有一个 XObject，get_images 只报一次，两处签字会数成一处。
    """
    return sum(len(page.get_image_info()) for page in open_pdf(stream=pdf_bytes, filetype="pdf"))


def last_log(b):
    return b.rows("SELECT action, detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0]


def log_count(b) -> int:
    return b.rows("SELECT COUNT(*) FROM file_access_logs")[0][0]


@pytest.fixture
def sp(backend, tmp_path):
    """初始化完毕：管理员（有签字）、域外管理员（有签字）、班委、申请人、同班同学"""
    b = backend(db="leave.db", BOOTSTRAP_PASSWORD=PW)
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
    assert b.login(student_no=ADMIN, password=TAILS[ADMIN]).status_code == 200

    r = b.client.put(f"/api/admin/users/{CM}/role", json={"role": "committee"})
    assert r.status_code == 200, r.text

    upload_sign(b, sid_of(b, ADMIN))          # 管理员自己的签字图
    upload_sign(b, sid_of(b, APPLICANT))      # 申请人的签字图（两处都要印）
    assert create_ext(b).status_code == 200, "域外管理员建不出来"

    return SimpleNamespace(
        b=b,
        leaves=tmp_path / "leaves",
        applicant_client=as_student(b, APPLICANT),
        classmate_client=as_student(b, CLASSMATE),
        cm_client=as_student(b, CM),
    )


# ---------- 批准时的意见与签字 ----------

def test_approve_without_body_still_works(sp):
    """不带 body 的批准照旧能用 —— 老前端那句 approveLeave(id) 就是这个调用"""
    lid = submit(sp.applicant_client)
    r = approve(sp.b, lid)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    # 三个签字字段全空 = 暂不签字
    assert row_of(sp.b, lid)[2:] == ("", "", "")
    assert r.json()["has_advisor_sign"] is False


def test_approve_records_opinion_and_signature(sp):
    """带意见和签字人：库里三列写对、签字图副本真的落到盘上"""
    lid = submit(sp.applicant_client)
    r = approve(sp.b, lid, advisor_opinion="同意，注意安全", advisor_sign_no=ADMIN)
    assert r.status_code == 200, r.text

    _, opinion, sign_no, sign_name, sign_file = row_of(sp.b, lid)
    assert opinion == "同意，注意安全"
    assert (sign_no, sign_name) == (ADMIN, "甲")
    assert sign_file, "签字图副本名该写上（这一列非空就是「已签」）"
    assert (sp.leaves / sign_file).exists(), "副本没落盘"
    assert r.json()["has_advisor_sign"] is True
    assert r.json()["advisor_sign_name"] == "甲"


def test_an_external_admin_can_be_the_signer(sp):
    """域外账号与在册学生同权 —— 他也能当班导师签字人"""
    lid = submit(sp.applicant_client)
    r = approve(sp.b, lid, advisor_sign_no=EXT_LOGIN)

    assert r.status_code == 200, r.text
    _, _, sign_no, sign_name, sign_file = row_of(sp.b, lid)
    assert sign_no == EXT_LOGIN and sign_name == EXT_NAME
    assert (sp.leaves / sign_file).exists()


def test_opinion_alone_is_fine(sp):
    """只填意见、暂不签字 —— 两个字段本来就都是选填"""
    lid = submit(sp.applicant_client)
    assert approve(sp.b, lid, advisor_opinion="知道了").status_code == 200
    assert row_of(sp.b, lid)[1] == "知道了"
    assert row_of(sp.b, lid)[4] == ""


def test_opinion_is_capped_at_200(sp):
    """意见卡 200 字 —— 上限是排版算出来的（超了那张表要翻页）"""
    lid = submit(sp.applicant_client)
    assert approve(sp.b, lid, advisor_opinion="好" * 201).status_code == 422


# ---------- 谁不能当签字人 ----------

def test_a_committee_member_cannot_be_the_signer(sp):
    """班委不是管理员，不能当签字人"""
    lid = submit(sp.applicant_client)
    r = approve(sp.b, lid, advisor_sign_no=CM)
    assert r.status_code == 400
    assert "签字图" in r.json()["detail"]


def test_an_admin_without_a_signature_cannot_be_the_signer(sp):
    """管理员，但没传过签字图：也不行（选了也插不进表）"""
    # 把管理员那张删掉，他就成了「有权限、没图」的人
    assert sp.b.client.delete(
        f"/api/sign-photos/image/{sid_of(sp.b, ADMIN)}").status_code == 200

    lid = submit(sp.applicant_client)
    assert approve(sp.b, lid, advisor_sign_no=ADMIN).status_code == 400


def test_a_deleted_file_is_treated_as_no_signature(sp):
    """库里还指着签字图、文件却被从盘上拿掉了：当没有这个人

    换图 / 删图接口只改库和目录，中间隔了一层；盘上的文件才是唯一算数的。
    """
    photo_file_of(sp.b, ADMIN).unlink()   # 只动文件，库里那列还指着它

    lid = submit(sp.applicant_client)
    assert approve(sp.b, lid, advisor_sign_no=ADMIN).status_code == 400


def test_a_failed_approve_leaves_no_orphan(sp):
    """当签字人不行时，批准整个失败，别在 leaves 目录里留个没人引用的副本

    数目录要在**提交之后**：辅助证明也落在这个目录里，提交那一下本来就多一个文件。
    """
    lid = submit(sp.applicant_client)
    before = sorted(p.name for p in sp.leaves.glob("*"))
    assert approve(sp.b, lid, advisor_sign_no=CM).status_code == 400

    assert sorted(p.name for p in sp.leaves.glob("*")) == before
    assert row_of(sp.b, lid)[0] == "pending", "签字没落成，状态也不该改"


# ---------- 批准 / 补签字的边界 ----------

def test_approving_twice_is_rejected(sp):
    """已批准的不能再批一次 —— 再批会重新快照、把当初那张签字覆盖掉"""
    lid = submit(sp.applicant_client)
    assert approve(sp.b, lid, advisor_sign_no=ADMIN).status_code == 200
    first = row_of(sp.b, lid)[4]

    r = approve(sp.b, lid, advisor_sign_no=EXT_LOGIN)
    assert r.status_code == 400
    assert row_of(sp.b, lid)[4] == first, "那份快照不该被换掉"


def test_sign_afterwards_when_it_was_deferred(sp):
    """批准时选了「暂不签字」，之后补签得上"""
    lid = submit(sp.applicant_client)
    assert approve(sp.b, lid, advisor_opinion="同意").status_code == 200

    r = advisor_sign(sp.b, lid, advisor_sign_no=ADMIN)
    assert r.status_code == 200, r.text
    assert row_of(sp.b, lid)[3] == "甲"
    assert (sp.leaves / row_of(sp.b, lid)[4]).exists()

    # 补签字不碰审核信息：状态、审核人还是批准那一步留下的
    status, opinion, _, _, _ = row_of(sp.b, lid)
    assert status == "approved" and opinion == "同意"


def test_sign_afterwards_keeps_the_original_opinion(sp):
    """补签字时意见不填，当初那段意见要留着（不是被清空）"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid, advisor_opinion="同意")
    advisor_sign(sp.b, lid, advisor_sign_no=ADMIN)
    assert row_of(sp.b, lid)[1] == "同意"


def test_signing_twice_is_rejected(sp):
    """签过的不能再签一次 —— 静默改写等于篡改已经发出去的那张表"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid, advisor_sign_no=ADMIN)
    r = advisor_sign(sp.b, lid, advisor_sign_no=EXT_LOGIN)

    assert r.status_code == 400
    assert "已有班导师签字" in r.json()["detail"]
    assert row_of(sp.b, lid)[2] == ADMIN, "签字人还是当初那个"


def test_signing_a_pending_leave_is_rejected(sp):
    """还没批准的单子谈不上补签字"""
    lid = submit(sp.applicant_client)
    assert advisor_sign(sp.b, lid, advisor_sign_no=ADMIN).status_code == 400


def test_sign_afterwards_needs_a_signer(sp):
    """补签字必须指个人 —— 不指的话这个接口就没意义了"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid)
    assert advisor_sign(sp.b, lid, advisor_sign_no="").status_code == 400


# ---------- 候选人列表 ----------

def test_signers_lists_only_admins_with_a_signature(sp):
    """候选人 = 管理员 + 签字图在盘上；域外管理员和学生管理员都要在"""
    r = sp.b.client.get("/api/leaves/advisor-signers")
    assert r.status_code == 200, r.text

    got = {item["student_no"]: item for item in r.json()}
    assert set(got) == {ADMIN, EXT_LOGIN}, f"漏人或多了人：{sorted(got)}"
    assert got[EXT_LOGIN]["is_external"] is True
    assert got[ADMIN]["is_external"] is False
    assert got[EXT_LOGIN]["name"] == EXT_NAME
    assert CM not in got, "班委不是管理员"


def test_signers_drops_an_admin_whose_file_is_gone(sp):
    """图没了就不该再出现在下拉里（选了也插不进表）"""
    photo_file_of(sp.b, ADMIN).unlink()

    got = [item["student_no"] for item in sp.b.client.get("/api/leaves/advisor-signers").json()]
    assert ADMIN not in got


def test_signers_needs_admin(sp):
    """班委看不了候选人列表 —— 这条链路本来就只给管理员"""
    assert sp.cm_client.get("/api/leaves/advisor-signers").status_code == 403


# ---------- 下载 ----------

def test_applicant_can_download_their_own_table(sp):
    """申请人本人能下 —— 这条接口以前是 admin_required，学生点下去必定 403"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid, advisor_sign_no=ADMIN)

    r = sp.applicant_client.get(f"/api/leaves/{lid}/pdf")
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"


def test_a_classmate_cannot_download_it(sp):
    """同班同学不行 —— 放开给「申请人本人」不等于放开给所有学生"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid)

    assert sp.classmate_client.get(f"/api/leaves/{lid}/pdf").status_code == 403
    assert sp.cm_client.get(f"/api/leaves/{lid}/pdf").status_code == 403


def test_admin_can_download_anyone_s(sp):
    """管理员不受限"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid)
    assert sp.b.client.get(f"/api/leaves/{lid}/pdf").status_code == 200


def test_a_pending_leave_has_no_table(sp):
    """没批准的不出表 —— 未通过的人拿了也没用"""
    lid = submit(sp.applicant_client)
    assert sp.applicant_client.get(f"/api/leaves/{lid}/pdf").status_code == 400


def test_downloaded_table_carries_both_signatures(sp):
    """下到的表上：申请人两处签字 + 班导师一处，一共三张图"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid, advisor_sign_no=ADMIN)

    assert images_in(sp.applicant_client.get(f"/api/leaves/{lid}/pdf").content) == 3


def test_student_and_admin_get_exactly_the_same_file(sp):
    """学生和管理员下到的没有区别（用户口径）—— 图数、页数、水印格式都一样"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid, advisor_sign_no=ADMIN)

    mine = sp.applicant_client.get(f"/api/leaves/{lid}/pdf").content
    theirs = sp.b.client.get(f"/api/leaves/{lid}/pdf").content

    assert images_in(mine) == images_in(theirs) == 3
    assert len(open_pdf(stream=mine, filetype="pdf")) == len(open_pdf(stream=theirs, filetype="pdf"))


def test_the_signature_survives_touching_the_original(sp):
    """把签字人的原图连换带删，已经签过的那张表照样带签字 —— 快照的核心承诺

    换图接口换的是**磁盘上另一个文件**（uuid 命名，旧的当场删掉），所以「原图」
    这条路径在换完那一刻就不存在了。存副本的意义正在这里：历史单据上的签字
    连着的是那个副本，与原图此后怎么折腾无关。
    """
    lid = submit(sp.applicant_client)
    approve(sp.b, lid, advisor_sign_no=ADMIN)
    assert images_in(sp.b.client.get(f"/api/leaves/{lid}/pdf").content) == 3

    sid = sid_of(sp.b, ADMIN)
    upload_sign(sp.b, sid)                                    # 换一张（旧文件被删）
    assert sp.b.client.delete(f"/api/sign-photos/image/{sid}").status_code == 200  # 再删掉

    assert images_in(sp.b.client.get(f"/api/leaves/{lid}/pdf").content) == 3, \
        "原图没了，历史单据上的签字跟着消失（存副本的意义就在这儿）"


def test_download_is_not_written_to_the_access_log(sp):
    """下载**不写** file_access_logs（用户口径：学生和管理员下到的是同一份文件）"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid)

    before = log_count(sp.b)
    assert sp.applicant_client.get(f"/api/leaves/{lid}/pdf").status_code == 200
    assert sp.b.client.get(f"/api/leaves/{lid}/pdf").status_code == 200
    assert log_count(sp.b) == before, "访问日志里多出了请假表的记录"


# ---------- 水印与溯源 ----------

def test_the_download_carries_a_leave_watermark(sp):
    """水印里带着「谁、何时、哪张表」，来源码是 lea"""
    from app.services import extract_watermark, parse_watermark_token

    lid = submit(sp.applicant_client)
    approve(sp.b, lid)
    pdf = sp.applicant_client.get(f"/api/leaves/{lid}/pdf").content

    parsed = parse_watermark_token(extract_watermark(pdf))
    assert parsed, "下到的 PDF 里没有水印"
    assert parsed["source"] == "lea"
    assert parsed["file_id"] == lid
    assert parsed["user_no"] == APPLICANT, "水印要认得出是谁下的"


def test_the_watermark_points_at_this_table_not_a_same_numbered_notice(sp):
    """请假表 1 号不许溯到公告 1 号 —— 三张表的 id 各自从 1 编号，必然撞号

    所以先专门造一份 1 号公告：少的那个「把 lea 从公告兜底里排除」的判断一旦被
    写回去，这条就会指着一份八竿子打不着的公告说「是它」。
    """
    assert sp.b.client.post("/api/announcements", data={
        "title": "一号公告", "publish_date": "2026-10-01",
    }, files={"file": ("notice.pdf", b"%PDF-1.4\n", "application/pdf")}).status_code == 200

    lid = submit(sp.applicant_client)
    approve(sp.b, lid)
    # 先确认真的撞号了，不然这条用例在空转
    assert lid == sp.b.rows("SELECT id FROM announcements")[0][0] == 1
    pdf = sp.applicant_client.get(f"/api/leaves/{lid}/pdf").content

    r = sp.b.client.post(
        "/api/admin/file-access-logs/extract",
        files={"file": ("x.pdf", pdf, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["found"] is True
    assert data["source_type"] == "leave"
    assert data["file_id"] == lid
    assert data["user_no"] == APPLICANT
    assert "丙" in data["file_title"], "标题里该有申请人姓名"
    assert data["log_matched"] is False
    assert "访问日志" in data["message"], "得说清「不写日志是按设计的」，别让人当成日志丢了"


# ---------- 操作日志 ----------

def test_approve_and_sign_leave_a_trace(sp):
    """审批日志里要能看出签字是「谁签的」还是「暂不签字」"""
    lid = submit(sp.applicant_client)
    approve(sp.b, lid, advisor_sign_no=ADMIN)
    assert last_log(sp.b)[0] == "通过请假申请"
    assert "班导师签字：甲" in last_log(sp.b)[1]

    lid2 = submit(sp.applicant_client)
    approve(sp.b, lid2)
    assert "班导师签字：暂不签字" in last_log(sp.b)[1]

    advisor_sign(sp.b, lid2, advisor_sign_no=EXT_LOGIN)
    assert last_log(sp.b)[0] == "补签班导师签字"
    assert EXT_NAME in last_log(sp.b)[1]
