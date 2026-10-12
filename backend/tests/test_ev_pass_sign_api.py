"""电动车通行证：经办班委签字（批准时定 / 事后补签）、两份 PDF 的权限与水印

    cd backend && python -m pytest tests/test_ev_pass_sign_api.py -q

签字这套机件跟请假的班导师签字共用（services/signer_service.py），所以这个文件不重测
「候选人口径」本身，盯的是电动车**自己**那几处一漏就静默的地方：

- 批准时选的那位，签字图要**复制一份**进 EV_PASS_DIR —— 原图后来换了或删了，
  历史单据不许掉签字（快照语义的全部价值就在这一条）；
- 批准**只允许 pending**、补签**不覆盖已签过的**：这两条一起才守得住快照 ——
  已批准的单子能再点一次「通过」，就会按新选的人**重新快照并覆盖**当初那张；
- 两份 PDF 的水印 source 必须**是两个值**（evpa / evpc）：它们的 file_id 是同一个
  申请 id，光看 id 分不出学生下到的是申请表还是承诺书；
- 两份都**不写 file_access_logs** —— 学生和班委下的是同一份文件，记下来只是噪音。

版式在 tests/test_ev_pass_pdf.py，这里只管接口与落库。
EV_PASS_DIR 与照片目录都被 conftest 隔离到 tmp_path 了（见 conftest 里的注释），
所以这里能直接数盘上有什么 —— 「有没有留下孤儿」只有看盘才作数。
"""
import pymupdf
import httpx
import pytest
from types import SimpleNamespace

from conftest import png_bytes

PW = "initpass123"

# (登录名, 姓名, 身份证后 6 位 —— 也就是这个学生的默认密码)
ADMIN = "2024000001"      # 管理员，在册学生：签字图走 students.sign_photo
NOSIGN = "2024000002"     # 管理员但没上传签字图：不该出现在候选人里
CM = "2024000003"         # 班委：能下载，不能批准
MATE = "2024000004"       # 普通学生：同班同学，403 那一位
APPLICANT = "2024000005"  # 申请人
ROSTER = [
    (ADMIN, "甲", "010001"),
    (NOSIGN, "乙", "010002"),
    (CM, "丙", "010003"),
    (MATE, "丁", "010004"),
    (APPLICANT, "戊", "010005"),
]
TAIL = {no: tail for no, _, tail in ROSTER}
NAME = {no: name for no, name, _ in ROSTER}

# 域外管理员。登录名故意带个 `-`：水印的令牌是 `OA-WM:evpa:1:T-001:175…`，
# 账号那一段要是写死成 \w+，这种登录名就会被当成「没水印」
EXTERNAL = "T-001"
EXTERNAL_PW = "extinit123"
EXTERNAL_NAME = "外域管理员"

PNG = png_bytes()
# 另一张真 PNG（只差一个字节，用来断言「换图之后拿到的是不是原来那张」）
PNG2 = PNG[:-20] + bytes([PNG[-20] ^ 0xFF]) + PNG[-19:]


# ---------- 小工具 ----------

def as_student(b, no) -> httpx.Client:
    """另开一个客户端以某个学生身份登录 —— 会话是按 client 存的"""
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": TAIL[no]})
    assert r.status_code == 200, r.text
    return c


def sid_of(b, no) -> int:
    return b.rows("SELECT id FROM students WHERE student_no = ?", no)[0][0]


def upload_sign(b, sid, data=PNG):
    """给某个学生传签字图（仅管理员）"""
    return b.client.post(f"/api/sign-photos/image/{sid}",
                         files={"file": ("sign.png", data, "image/png")})


def submit(client, brand="雅迪", plate="京A1234567") -> int:
    """以某个学生身份提交一条申请，返回申请 id"""
    r = client.post("/api/ev-passes", data={"brand": brand, "plate_number": plate},
                    files={"license_file": ("license.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def approve(b, req_id, sign_no=None):
    """管理员批准。sign_no=None 就是**整个不 body**（老前端那句 approveEvPass(id)）"""
    url = f"/api/ev-passes/{req_id}/approve"
    return b.client.post(url) if sign_no is None else b.client.post(url, json={"sign_no": sign_no})


def sign(b, req_id, sign_no):
    return b.client.post(f"/api/ev-passes/{req_id}/sign", json={"sign_no": sign_no})


def req_row(b, req_id):
    """库里那一行的三列签字快照"""
    return b.rows(
        "SELECT sign_no, sign_name, sign_file FROM ev_pass_requests WHERE id = ?", req_id
    )[0]


def names_in(ev_dir) -> list[str]:
    """EV_PASS_DIR 里的文件名（行驶证与签字副本同目录）"""
    return sorted(p.name for p in ev_dir.glob("*"))


def pdf_images(pdf: bytes) -> list[bytes]:
    """PDF 里嵌入图的原始字节

    用 get_image_info(xrefs=True) 而不是 get_images()：前者按**绘制次数**算。
    这里要的是「表上到底印了几张图」，同一张图印两次也该算两张
    """
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    return [doc.extract_image(i["xref"])["image"] for i in doc[0].get_image_info(xrefs=True)]


def access_log_rows(b) -> int:
    return b.rows("SELECT COUNT(*) FROM file_access_logs")[0][0]


def last_log(b):
    """最近一条操作日志（action, detail）"""
    return b.rows("SELECT action, detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0]


@pytest.fixture
def ep(backend, tmp_path):
    """一个装好的班：管理员（有图 / 没图各一）+ 域外管理员 + 班委 + 同学 + 申请人

    tmp_path 与 conftest 里指给后端的是同一个（同一个测试函数内 fixture 只实例化一次），
    所以 ep.ev_dir / ep.photos 就是后端真正在写的那个目录。
    """
    b = backend(db="ev.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200      # 初始化临时账号

    for no, name, tail in ROSTER:
        r = b.client.post("/api/students", json={
            "student_no": no, "name": name, "id_card": f"11010120000101{tail}",
        })
        assert r.status_code < 300, r.text

    # 指认管理员：这一步之后临时账号当场废止，得用他本人重新登录
    assert b.client.post("/api/setup/finish",
                         json={"admin_student_no": ADMIN}).status_code == 200
    b.logout()
    assert b.login(student_no=ADMIN, password=TAIL[ADMIN]).status_code == 200

    assert b.client.put(f"/api/admin/users/{CM}/role",
                        json={"role": "committee"}).status_code == 200
    assert b.client.put(f"/api/admin/users/{NOSIGN}/role",
                        json={"role": "admin"}).status_code == 200

    # 签字图：甲（要当经办班委）与戊（申请人的那张，印在承诺书上）
    assert upload_sign(b, sid_of(b, ADMIN)).status_code == 200
    assert upload_sign(b, sid_of(b, APPLICANT)).status_code == 200

    # 域外管理员，创建时就带上签字图
    r = b.client.post("/api/admin/external-users", data={
        "login_name": EXTERNAL, "display_name": EXTERNAL_NAME,
        "password": EXTERNAL_PW, "role": "admin",
    }, files={"sign_photo": ("sign.png", PNG, "image/png")})
    assert r.status_code < 300, r.text
    ext = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    assert ext.post("/api/auth/login",
                    json={"student_no": EXTERNAL, "password": EXTERNAL_PW}).status_code == 200

    return SimpleNamespace(
        b=b,
        ev_dir=tmp_path / "ev_passes",
        photos=tmp_path / "photos",
        applicant_sid=sid_of(b, APPLICANT),
        admin_sid=sid_of(b, ADMIN),
        applicant=as_student(b, APPLICANT),
        cm=as_student(b, CM),
        mate=as_student(b, MATE),
        external=ext,
    )


def client_of(ep, who) -> httpx.Client:
    """按名字取一个已登录的客户端；admin 就是主客户端"""
    return {"admin": ep.b.client, "applicant": ep.applicant,
            "cm": ep.cm, "mate": ep.mate, "external": ep.external}[who]


# ---------- 批准时定签字 ----------

def test_approve_snapshots_the_signature_into_the_ev_pass_dir(ep):
    """选了签字人：三列落库、图复制一份进 EV_PASS_DIR、响应告诉前端「已签」"""
    rid = submit(ep.applicant)
    r = approve(ep.b, rid, sign_no=ADMIN)
    assert r.status_code == 200, r.text

    assert r.json()["has_sign"] is True
    assert r.json()["sign_name"] == NAME[ADMIN]

    sign_no, sign_name, sign_file = req_row(ep.b, rid)
    assert (sign_no, sign_name) == (ADMIN, NAME[ADMIN])
    assert sign_file and f"sign_{rid}" in sign_file, "副本按申请 id 起名"
    # 副本是**逐字节的复制**（不是记个原图名）
    assert (ep.ev_dir / sign_file).read_bytes() == PNG


def test_approve_without_a_body_skips_the_committee_line(ep):
    """不带 body（老前端）就是「暂不签署」：三列全空、盘上不留签字副本"""
    rid = submit(ep.applicant)
    assert approve(ep.b, rid).status_code == 200

    assert req_row(ep.b, rid) == ("", "", "")
    before = names_in(ep.ev_dir)
    assert not [n for n in before if n.startswith("sign_")], f"凭空多出签字副本：{before}"


def test_empty_sign_no_is_the_same_as_not_signing(ep):
    """前端下拉首项「暂不签署」发的是空串，和「不带 body」得是一回事"""
    rid = submit(ep.applicant)
    r = approve(ep.b, rid, sign_no="   ")

    assert r.status_code == 200, r.text
    assert r.json()["has_sign"] is False and r.json()["sign_name"] == ""
    assert req_row(ep.b, rid) == ("", "", "")


def test_a_signer_without_a_photo_on_disk_is_refused(ep):
    """选了没有签字图的账号 → 400（库里留着文件名、图却没了的那种）"""
    rid = submit(ep.applicant)
    r = approve(ep.b, rid, sign_no=NOSIGN)

    assert r.status_code == 400 and "签字图" in r.json()["detail"]
    # 校验失败要挡在改状态**之前**，否则会留下一条「已通过、没签字」的单子
    assert ep.b.rows("SELECT status FROM ev_pass_requests WHERE id = ?", rid)[0][0] == "pending"


def test_an_unknown_signer_is_refused(ep):
    rid = submit(ep.applicant)
    assert approve(ep.b, rid, sign_no="查无此人").status_code == 400


def test_approving_twice_is_refused(ep):
    """已批准的单子不许再批 —— 那会按新选的人重新快照，把当初那张覆盖掉"""
    rid = submit(ep.applicant)
    approve(ep.b, rid, sign_no=ADMIN)
    snapshot = req_row(ep.b, rid)

    r = approve(ep.b, rid, sign_no=NOSIGN)      # 换个人重批
    assert r.status_code == 400 and "已处理" in r.json()["detail"]
    assert req_row(ep.b, rid) == snapshot, "当初那张快照被改写了"


def test_rejecting_an_approved_request_is_refused(ep):
    """撤销/重驳会把 reject_reason 覆盖掉、状态跟着翻（和请假对齐的那条守卫）"""
    rid = submit(ep.applicant)
    approve(ep.b, rid)
    r = ep.b.client.post(f"/api/ev-passes/{rid}/reject", json={"reason": "改主意了"})

    assert r.status_code == 400 and "已处理" in r.json()["detail"]
    assert ep.b.rows("SELECT status FROM ev_pass_requests WHERE id = ?", rid)[0][0] == "approved"


# ---------- 候选人 ----------

def test_signers_lists_admins_with_a_photo_and_nobody_else(ep):
    """候选人 = 管理员 + 签字图真在盘上；域外与在册同等对待

    没图的乙、以及班委丙都不该在里头 —— 丙不在是因为**权限**（班委不能签），
    乙不在是因为点了他也插不进表
    """
    r = ep.b.client.get("/api/ev-passes/signers")
    assert r.status_code == 200, r.text

    rows = {row["student_no"]: row for row in r.json()}
    assert set(rows) == {ADMIN, EXTERNAL}, f"候选人口径不对：{sorted(rows)}"
    assert rows[ADMIN]["name"] == NAME[ADMIN]
    assert rows[EXTERNAL] == {"student_no": EXTERNAL, "name": EXTERNAL_NAME,
                              "is_external": True}, "域外账号要标出来，前端好区分"


def test_signers_is_admin_only(ep):
    """学生与班委都取不到候选人名单（那是账号清单）"""
    for who in ("applicant", "mate", "cm"):
        assert client_of(ep, who).get("/api/ev-passes/signers").status_code == 403


def test_an_external_admin_can_be_the_signer(ep):
    """域外管理员选的图也照落 —— 顺带把「登录名带 - 能不能写进水印」验了"""
    from app.services import extract_watermark, parse_watermark_token

    rid = submit(ep.applicant)
    assert approve(ep.b, rid, sign_no=EXTERNAL).status_code == 200
    assert req_row(ep.b, rid)[1] == EXTERNAL_NAME

    pdf = ep.external.get(f"/api/ev-passes/{rid}/pass-pdf").content
    parsed = parse_watermark_token(extract_watermark(pdf))
    assert parsed and parsed["user_no"] == EXTERNAL, "带 - 的登录名被水印吃掉了"


# ---------- 事后补签字 ----------

def test_sign_after_approval_adds_the_signature(ep):
    """批准时没签，事后补上：签字落库、图落盘，但**审批信息一律不动**"""
    rid = submit(ep.applicant)
    approve(ep.b, rid)
    reviewed_before = ep.b.rows("SELECT reviewed_at, reviewer_no FROM ev_pass_requests WHERE id = ?",
                                rid)[0]

    r = sign(ep.b, rid, ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["has_sign"] is True and r.json()["sign_name"] == NAME[ADMIN]

    sign_no, _, sign_file = req_row(ep.b, rid)
    assert sign_no == ADMIN and (ep.ev_dir / sign_file).read_bytes() == PNG
    assert ep.b.rows("SELECT reviewed_at, reviewer_no FROM ev_pass_requests WHERE id = ?",
                     rid)[0] == reviewed_before, "补的是签字，不是重新审一遍"


def test_signing_twice_is_refused(ep):
    """已经签过的一律拒 —— 快照语义下静默改写等于篡改已经发出去的那张表"""
    rid = submit(ep.applicant)
    approve(ep.b, rid, sign_no=ADMIN)

    r = sign(ep.b, rid, NOSIGN)
    assert r.status_code == 400 and "已有" in r.json()["detail"]
    assert req_row(ep.b, rid)[0] == ADMIN


def test_signing_a_pending_request_is_refused(ep):
    rid = submit(ep.applicant)
    r = sign(ep.b, rid, ADMIN)

    assert r.status_code == 400 and "审核通过" in r.json()["detail"]
    assert req_row(ep.b, rid) == ("", "", "")


def test_sign_without_a_signer_is_refused(ep):
    """补签是明确动作，空签字人不能当「暂不签署」糊过去（那属于批准那一步）"""
    rid = submit(ep.applicant)
    approve(ep.b, rid)

    r = sign(ep.b, rid, "  ")
    assert r.status_code == 400 and "请选择签字人" in r.json()["detail"]
    assert req_row(ep.b, rid) == ("", "", "")


def test_sign_and_approve_are_admin_only(ep):
    rid = submit(ep.applicant)
    approve(ep.b, rid)
    assert ep.cm.post(f"/api/ev-passes/{rid}/sign", json={"sign_no": ADMIN}).status_code == 403

    rid2 = submit(ep.applicant)
    assert ep.cm.post(f"/api/ev-passes/{rid2}/approve").status_code == 403


# ---------- 两份 PDF 的下载权限 ----------

@pytest.mark.parametrize("who, expected", [
    ("applicant", 200),     # 本人：拿去打印签字
    ("cm", 200),            # 班委：留档、报学院盖章
    ("external", 200),      # 域外管理员权限同在册的**管理员**，不是「域外」就另算一档
    ("mate", 403),          # 同班同学不行 —— 表上全是本人的个人信息
])
def test_pass_pdf_download_permissions(ep, who, expected):
    rid = submit(ep.applicant)
    approve(ep.b, rid)
    assert client_of(ep, who).get(f"/api/ev-passes/{rid}/pass-pdf").status_code == expected


def test_admin_can_download_both_pdfs(ep):
    rid = submit(ep.applicant)
    approve(ep.b, rid)

    for kind in ("pass", "promise"):
        r = ep.b.client.get(f"/api/ev-passes/{rid}/{kind}-pdf")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.headers["cache-control"] == "no-store", "表里是个人信息，不许中间层缓存"
        assert r.content.startswith(b"%PDF")


def test_download_name_carries_the_application_day(ep):
    """文件名里的日期取**申请当天**（和前端拼的是同一个日子，跨天不会两边对不上）"""
    from datetime import datetime
    from urllib.parse import quote

    rid = submit(ep.applicant)
    approve(ep.b, rid)
    day = ep.b.rows("SELECT created_at FROM ev_pass_requests WHERE id = ?", rid)[0][0]

    r = ep.b.client.get(f"/api/ev-passes/{rid}/pass-pdf")
    want = quote(f"{NAME[APPLICANT]}_电动车通行证申请表_{datetime.fromisoformat(day):%Y%m%d}.pdf")
    assert want in r.headers["content-disposition"], r.headers["content-disposition"]


def test_download_before_approval_is_refused(ep):
    """还没批就没表可下（批了才有落款和经办班委那一行）"""
    rid = submit(ep.applicant)
    for kind in ("pass", "promise"):
        r = ep.applicant.get(f"/api/ev-passes/{rid}/{kind}-pdf")
        assert r.status_code == 400 and "未通过" in r.json()["detail"]


def test_download_of_a_missing_request_is_404(ep):
    assert ep.b.client.get("/api/ev-passes/9999/pass-pdf").status_code == 404


# ---------- 两份 PDF 上的签字 ----------

def test_the_pass_pdf_carries_the_committee_signature(ep):
    rid = submit(ep.applicant)
    approve(ep.b, rid, sign_no=ADMIN)
    assert len(pdf_images(ep.applicant.get(f"/api/ev-passes/{rid}/pass-pdf").content)) == 1

    rid2 = submit(ep.applicant)
    approve(ep.b, rid2)                       # 暂不签署
    assert pdf_images(ep.applicant.get(f"/api/ev-passes/{rid2}/pass-pdf").content) == []


def test_the_promise_pdf_carries_the_applicants_own_signature(ep):
    """承诺书落的是**学生本人**那张（和申请表那位管理员是两个人）"""
    rid = submit(ep.applicant)
    approve(ep.b, rid, sign_no=ADMIN)
    pdf = ep.applicant.get(f"/api/ev-passes/{rid}/promise-pdf").content

    assert pdf_images(pdf), "申请人传过签字图，承诺书上该有"


def test_a_snapshot_survives_replacing_or_deleting_the_original(ep):
    """原图换了、删了，历史单据上还是批准当时那张 —— 存副本的全部意义

    比对的是**两次下载里嵌的图字节完全相同**，而不是「有没有图」：后者在原图被换掉时
    照样会过，只是悄悄换成了新签字
    """
    rid = submit(ep.applicant)
    approve(ep.b, rid, sign_no=ADMIN)
    before = pdf_images(ep.b.client.get(f"/api/ev-passes/{rid}/pass-pdf").content)
    # 没有这句，下面两条「两次字节相同」在两边都是空的时候也会过（接口要是压根没把
    # 签字带上，这条用例就白测了）；顺便把「删了原图图就没了」这个真回归钉死
    assert len(before) == 1, "前提：批准并签字之后，申请表上该正好有一张签字图"

    # 换一张，再把原图整个删掉
    assert upload_sign(ep.b, ep.admin_sid, data=PNG2).status_code == 200
    after_replace = pdf_images(ep.b.client.get(f"/api/ev-passes/{rid}/pass-pdf").content)
    assert after_replace == before, "换了原图，历史单据跟着变了"

    assert ep.b.client.delete(f"/api/sign-photos/image/{ep.admin_sid}").status_code == 200
    after_delete = pdf_images(ep.b.client.get(f"/api/ev-passes/{rid}/pass-pdf").content)
    assert after_delete == before, "原图删了，历史单据上的签字跟着没了"


def test_deleting_the_student_takes_the_signature_copy_too(ep):
    """删学生要把签字副本一并收走（student_files）

    申请记录会被级联删掉，sig_<id>.png 就成了没人引用的孤儿 —— 只收行驶证不收副本，
    data/ev_passes/ 里会一年年堆下去
    """
    rid = submit(ep.applicant)
    approve(ep.b, rid, sign_no=ADMIN)
    copy_name = req_row(ep.b, rid)[2]
    assert (ep.ev_dir / copy_name).exists()

    assert ep.b.client.delete(f"/api/students/{ep.applicant_sid}").status_code == 200
    assert not (ep.ev_dir / copy_name).exists(), "删了学生，签字副本还留在盘上"
    assert names_in(ep.ev_dir) == [], f"这个学生名下的文件没清干净：{names_in(ep.ev_dir)}"


# ---------- 水印与访问日志 ----------

def test_each_pdf_carries_its_own_watermark_source(ep):
    """申请表 evpa、承诺书 evpc —— 两份的 file_id 是同一个数，只靠 source 分得出是哪份"""
    from app.services import extract_watermark, parse_watermark_token

    rid = submit(ep.applicant)
    approve(ep.b, rid)

    for kind, source in (("pass", "evpa"), ("promise", "evpc")):
        pdf = ep.applicant.get(f"/api/ev-passes/{rid}/{kind}-pdf").content
        parsed = parse_watermark_token(extract_watermark(pdf))
        assert parsed, f"{kind}-pdf 里没有水印"
        assert parsed["source"] == source, f"{kind}-pdf 的来源码不对"
        assert parsed["file_id"] == rid
        assert parsed["user_no"] == APPLICANT, "水印要认得出是谁下的"


def test_downloading_writes_no_access_log(ep):
    """下载**不写** file_access_logs：学生和班委下到的是同一份文件，记下来只是噪音

    这也是「凭水印就够了」的前提 —— 水印那两条断言得跟这条一起看
    """
    rid = submit(ep.applicant)
    approve(ep.b, rid)

    before = access_log_rows(ep.b)
    for client in (ep.applicant, ep.b.client, ep.cm):
        for kind in ("pass", "promise"):
            assert client.get(f"/api/ev-passes/{rid}/{kind}-pdf").status_code == 200
    assert access_log_rows(ep.b) == before, "访问日志里多出了电动车两份的记录"


def test_the_watermark_points_at_this_application_not_a_same_numbered_notice(ep):
    """电动车 1 号申请不许溯到公告 1 号 —— 每张表的 id 各自从 1 编号，必然撞号

    两份的 file_id 又是**同一个数**，所以这条把两份都喂进去：只加 source 常量、
    忘了并进 TOKEN_PATTERN 那条枚举式正则，或者漏掉 admin.py 里任何一处 guard，
    都会指着一份八竿子打不着的公告说「是它」
    """
    assert ep.b.client.post("/api/announcements", data={
        "title": "一号公告", "publish_date": "2026-10-01",
    }, files={"file": ("notice.pdf", b"%PDF-1.4\n", "application/pdf")}).status_code == 200

    rid = submit(ep.applicant)
    approve(ep.b, rid, sign_no=ADMIN)
    assert rid == ep.b.rows("SELECT id FROM announcements")[0][0] == 1, "没撞号，这条在空转"

    for kind, what in (("pass", "电动车通行证申请表"), ("promise", "电动车使用承诺书")):
        pdf = ep.applicant.get(f"/api/ev-passes/{rid}/{kind}-pdf").content
        r = ep.b.client.post("/api/admin/file-access-logs/extract",
                             files={"file": ("x.pdf", pdf, "application/pdf")})
        assert r.status_code == 200, r.text
        data = r.json()

        assert data["found"] is True
        assert data["source_type"] == "evpass"
        assert data["file_id"] == rid
        assert data["user_no"] == APPLICANT, "水印要认得出是谁下的"
        # 两份共用一个 source_type，下的是哪一份全靠后端写好的标题
        assert NAME[APPLICANT] in data["file_title"] and what in data["file_title"], \
            f"标题分不出是哪一份：{data['file_title']}"
        assert data["log_matched"] is False
        assert "访问日志" in data["message"], "得说清「不写日志是按设计的」，别让人当成日志丢了"


# ---------- 操作日志 ----------

def test_approve_and_sign_leave_a_trace(ep):
    """审批日志里要能看出签字是「谁签的」还是「暂不签署」"""
    rid = submit(ep.applicant)
    approve(ep.b, rid, sign_no=ADMIN)
    action, detail = last_log(ep.b)
    assert action == "通过电动车通行证" and f"经办班委签字：{NAME[ADMIN]}" in detail

    rid2 = submit(ep.applicant)
    approve(ep.b, rid2)
    assert "经办班委签字：暂不签署" in last_log(ep.b)[1]

    sign(ep.b, rid2, EXTERNAL)
    action, detail = last_log(ep.b)
    assert action == "补签经办班委签字" and EXTERNAL_NAME in detail
