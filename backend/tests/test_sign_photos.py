"""签字图的回归：申请-审批链、只给申请人看、一小时过期、文件与档案同步

    cd backend && python -m pytest tests -q

签字是全班最敏感的一份东西 —— 手写签字能被拿去伪造请假条、证明材料。所以它跟
另外三张照片（高考照、实地采集、自备证件照）走的不是同一条权限链：照片是「班委
看得见这个学生就能看」，签字是「班委申请 → 管理员批准 → 只有申请人在一小时内能看」。

这个文件盯的就是那条链上每一环都真的拦得住。最容易写漏的一环是第 6 条用例：
判权限时只查了「有没有批准的申请」，忘了申请人必须是**当前这个人** ——
那样任何一个班委被批过一次，就等于给全班班委发了通行证。

照片目录被隔离了（conftest 给后端指了 tmp_path/photos），所以可以直接数盘上有
什么 —— 「有没有留下孤儿」「删学生时清干净没有」只有看盘才作数。
"""
import io
import zipfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from conftest import png_bytes

PW = "initpass123"

# (学号, 姓名, 身份证后 6 位 —— 也就是这个学生的默认密码)
ADMIN = "2024000001"
CM1 = "2024000002"      # 提出申请的那个班委
CM2 = "2024000003"      # 另一个班委：绝不该因为 CM1 被批了就能看
TARGET = "2024000004"   # 被看签字的学生
STUDENT = "2024000005"  # 普通学生：签字这功能对他完全不存在
ROSTER = [
    (ADMIN, "甲", "010001"),
    (CM1, "乙", "010002"),
    (CM2, "丙", "010003"),
    (TARGET, "丁", "010004"),
    (STUDENT, "戊", "010005"),
]
TARGET_NAME = "丁"
PNG = png_bytes()
# 另一张真 PNG（字节不同，用来断言「换图之后拿到的确实是新图」）
PNG2 = PNG[:-20] + bytes([PNG[-20] ^ 0xFF]) + PNG[-19:]


# ---------- 小工具 ----------

def as_student(b, no) -> httpx.Client:
    """另开一个客户端以某个学生身份登录 —— 会话是按 client 存的"""
    tail = dict((n, t) for n, _, t in ROSTER)[no]
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": tail})
    assert r.status_code == 200, r.text
    return c


def sid_of(b, no) -> int:
    return b.rows("SELECT id FROM students WHERE student_no = ?", no)[0][0]


def db_sign(b, no=TARGET):
    """档案里的签字文件名。直连库：要断言的就是「库里到底存了什么」"""
    return b.rows("SELECT sign_photo FROM students WHERE student_no = ?", no)[0][0]


def files_in(photos) -> list[str]:
    return sorted(p.name for p in photos.glob("*"))


def upload_sign(sp, data=PNG, filename="sign.png", sid=None):
    return sp.b.client.post(
        f"/api/sign-photos/image/{sid or sp.target}",
        files={"file": (filename, data, "image/png")},
    )


def fetch_sign(sp, client=None, sid=None):
    """取签字图。默认用管理员那个 client —— 具体身份由调用方指定"""
    c = client or sp.b.client
    return c.get(f"/api/sign-photos/image/{sid or sp.target}")


def request_view(sp, client, sid=None):
    return client.post("/api/sign-photos/requests", json={"student_id": sid or sp.target})


def status_of(sp, client, sid=None):
    return client.get(f"/api/sign-photos/status/{sid or sp.target}")


def last_log(b):
    """最近一条操作日志（action, target, detail）"""
    return b.rows("SELECT action, target, detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0]


def approve(sp, request_id):
    """管理员批准，返回请求 id"""
    r = sp.b.client.post(f"/api/sign-photos/requests/{request_id}/approve")
    assert r.status_code == 200, r.text
    return r.json()


def apply_for(sp, client) -> dict:
    """班委提申请并让管理员批下来，返回那条申请"""
    r = request_view(sp, client)
    assert r.status_code == 200, r.text
    return approve(sp, r.json()["id"])


@pytest.fixture
def sp(backend, tmp_path):
    """初始化完毕：管理员、两个班委、一个待看的学生、一个普通学生

    tmp_path 与 conftest 里指给后端的是同一个（同一个测试函数内 fixture 只实例化一次），
    所以 sp.photos 就是后端真正在写的那个目录。
    """
    b = backend(db="sign.db", BOOTSTRAP_PASSWORD=PW)
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
    assert b.login(student_no=ADMIN, password=dict((n, t) for n, _, t in ROSTER)[ADMIN]).status_code == 200

    # 提两个人当班委：申请查看签字这条链路只对班委及以上开放
    for no in (CM1, CM2):
        r = b.client.put(f"/api/admin/users/{no}/role", json={"role": "committee"})
        assert r.status_code == 200, r.text

    return SimpleNamespace(
        b=b,
        photos=tmp_path / "photos",
        target=sid_of(b, TARGET),
        cm1=as_student(b, CM1),
        cm2=as_student(b, CM2),
        student=as_student(b, STUDENT),
    )


# ---------- 上传 / 替换 / 删除 ----------

def test_admin_upload_lands_on_disk_and_in_the_archive(sp):
    """上传之后：文件真的在盘上、档案里指向它、日志记了一条"""
    assert files_in(sp.photos) == []

    r = upload_sign(sp)
    assert r.status_code == 200, r.text

    name = db_sign(sp.b)
    assert name and (sp.photos / name).exists(), "文件名写进档案了，盘上也该有这张图"
    assert files_in(sp.photos) == [name]
    assert last_log(sp.b)[0] == "上传签字图片"
    assert last_log(sp.b)[1] == f"{TARGET} {TARGET_NAME}"


def test_admin_replace_removes_the_old_file(sp):
    """换一张：新图在、旧图被删，盘上不留孤儿"""
    upload_sign(sp)
    old = db_sign(sp.b)
    assert (sp.photos / old).exists()

    assert upload_sign(sp, data=PNG2).status_code == 200
    new = db_sign(sp.b)

    assert new != old, "换图就该换一个文件名，否则浏览器/反向代理会拿缓存的旧图"
    assert (sp.photos / new).exists()
    assert not (sp.photos / old).exists(), "旧图提交成功之后就没人引用了，得删掉"
    assert files_in(sp.photos) == [new]

    # 取回来的字节确实是新的那一张
    assert fetch_sign(sp).content == PNG2
    assert last_log(sp.b)[2] == "替换了原有签字"


def test_admin_delete_clears_both_sides(sp):
    """删除：字段清空、文件没了、日志有"""
    upload_sign(sp)
    name = db_sign(sp.b)

    r = sp.b.client.delete(f"/api/sign-photos/image/{sp.target}")
    assert r.status_code == 200, r.text

    assert db_sign(sp.b) is None
    assert not (sp.photos / name).exists()
    assert last_log(sp.b)[0] == "删除签字图片"


def test_delete_when_there_is_nothing_is_not_an_error(sp):
    """本来就没有签字，删一次不该报错 —— 前端那个按钮可能被连点"""
    r = sp.b.client.delete(f"/api/sign-photos/image/{sp.target}")
    assert r.status_code == 200
    assert "本来就没有" in r.json()["message"]


def test_bad_file_type_is_refused(sp):
    """后缀白名单照旧：400 的文案要把「照片」说成「签字图片」"""
    r = upload_sign(sp, filename="sign.txt")
    assert r.status_code == 400
    assert "签字图片" in r.json()["detail"]
    assert files_in(sp.photos) == [], "被拒的那次不该在盘上留下东西"


def test_committee_cannot_upload_for_others(sp):
    """班委不能替别人传：「能看名单」不等于「能替人签字」"""
    r = sp.cm1.post(
        f"/api/sign-photos/image/{sp.target}",
        files={"file": ("sign.png", PNG, "image/png")},
    )
    assert r.status_code == 403
    assert "自己的" in r.json()["detail"]


# ---------- 学生本人上传（只能传，不能看 / 删 / 下载） ----------

def test_student_can_upload_own_sign(sp):
    """学生本人可以传自己的签字图，落盘、写库、日志标明是本人上传"""
    own = sid_of(sp.b, STUDENT)
    r = sp.student.post(
        f"/api/sign-photos/image/{own}",
        files={"file": ("sign.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text

    name = db_sign(sp.b, STUDENT)
    assert name and (sp.photos / name).exists()
    action, target, detail = last_log(sp.b)
    assert action == "上传签字图片"
    assert target == f"{STUDENT} 戊"
    assert "本人上传" in detail


def test_student_can_replace_own_sign(sp):
    """重新上传就是换一张：旧文件不留在盘上，新图字节确实换掉了"""
    own = sid_of(sp.b, STUDENT)

    def upload(data):
        return sp.student.post(
            f"/api/sign-photos/image/{own}",
            files={"file": ("sign.png", data, "image/png")},
        )

    assert upload(PNG).status_code == 200
    old = db_sign(sp.b, STUDENT)
    assert upload(PNG2).status_code == 200
    new = db_sign(sp.b, STUDENT)

    assert new != old
    assert (sp.photos / new).read_bytes() == PNG2
    assert not (sp.photos / old).exists()
    assert "替换了原有签字" in last_log(sp.b)[2]


def test_admin_is_reminded_after_student_changes_own_sign(sp):
    """学生本人换图后，管理员收到一条站内信提醒确认；图本身当场生效，不进审批"""
    own = sid_of(sp.b, STUDENT)
    r = sp.student.post(
        f"/api/sign-photos/image/{own}",
        files={"file": ("sign.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert db_sign(sp.b, STUDENT), "学生传完就该写进档案，不然就成了待审"

    inbox = sp.b.client.get("/api/inbox").json()["items"]
    hits = [m for m in inbox if m["title"] == "学生更换了签字图"]
    assert len(hits) == 1
    assert STUDENT in hits[0]["body"] and "戊" in hits[0]["body"]
    # 点进去直接打开这个学生的详情，管理员在那里看图并决定要不要处理
    assert hits[0]["page"] == f"/students?open={own}"


def test_admin_upload_does_not_remind_itself(sp):
    """管理员代传、批量签字都是管理员自己的操作，不该给自己发提醒"""
    assert upload_sign(sp).status_code == 200
    inbox = sp.b.client.get("/api/inbox").json()["items"]
    assert not [m for m in inbox if m["title"] == "学生更换了签字图"]


def test_student_cannot_upload_someone_else(sp):
    """普通学生传别人的同样 403 —— 放行的是「本人」，不是「学生」这个角色"""
    r = sp.student.post(
        f"/api/sign-photos/image/{sp.target}",
        files={"file": ("sign.png", PNG, "image/png")},
    )
    assert r.status_code == 403
    assert db_sign(sp.b) is None


def test_student_cannot_delete_own_sign(sp):
    """允许上传，但不给删除权：删自己的也 403，库和文件都不动"""
    own = sid_of(sp.b, STUDENT)
    assert sp.student.post(
        f"/api/sign-photos/image/{own}",
        files={"file": ("sign.png", PNG, "image/png")},
    ).status_code == 200
    name = db_sign(sp.b, STUDENT)

    r = sp.student.delete(f"/api/sign-photos/image/{own}")
    assert r.status_code == 403
    assert db_sign(sp.b, STUDENT) == name
    assert (sp.photos / name).exists()


def test_student_cannot_view_own_sign(sp):
    """传完也看不到自己的图：取图那条路的门槛是「班委 + 管理员批准」"""
    own = sid_of(sp.b, STUDENT)
    assert sp.student.post(
        f"/api/sign-photos/image/{own}",
        files={"file": ("sign.png", PNG, "image/png")},
    ).status_code == 200

    r = sp.student.get(f"/api/sign-photos/image/{own}")
    assert r.status_code == 403


def test_student_own_status_is_only_a_boolean(sp):
    """状态接口只回 uploaded，连文件名都不给 —— 学生拿不到任何取图线索"""
    r = sp.student.get("/api/sign-photos/my-status")
    assert r.status_code == 200
    assert r.json() == {"uploaded": False}

    own = sid_of(sp.b, STUDENT)
    assert sp.student.post(
        f"/api/sign-photos/image/{own}",
        files={"file": ("sign.png", PNG, "image/png")},
    ).status_code == 200

    r = sp.student.get("/api/sign-photos/my-status")
    assert r.status_code == 200
    assert r.json() == {"uploaded": True}
    assert "sign" not in str(r.json()), "文件名 / 路径一个字段都不该出现"


def test_student_own_upload_checks_format(sp):
    """学生这条路同样过后缀白名单，报错文案说「签字图片」"""
    own = sid_of(sp.b, STUDENT)
    r = sp.student.post(
        f"/api/sign-photos/image/{own}",
        files={"file": ("sign.txt", PNG, "text/plain")},
    )
    assert r.status_code == 400
    assert "签字图片" in r.json()["detail"]


# ---------- 「不向学生展示」 ----------

def test_student_role_is_shut_out_of_viewing(sp):
    """普通学生：取图、申请查看、查别人的状态三条路全 403

    学生现在可以上传自己的签字（见下面的「学生本人上传」一组），但查看这条链
    仍然只对班委开放。403 而不是 404 —— 得让学生看不出能不能看别人那张。
    """
    upload_sign(sp)

    assert fetch_sign(sp, client=sp.student).status_code == 403
    assert request_view(sp, sp.student).status_code == 403
    assert status_of(sp, sp.student).status_code == 403


def test_student_detail_never_carries_any_sign_key(sp):
    """学生详情响应里**没有**任何签字相关的键（原始字段和派生字段都没有）

    靠的是给 StudentResponse 显式列字段 —— 不加进去就永远不返回。这里的断言是
    在钉住这个实现方式：将来谁把 sign_photo 顺手加进 StudentResponse（或者加一个
    好心的 has_sign_photo），这条会红。
    """
    upload_sign(sp)   # 有图也没用，字段压根不在出参模型里
    r = sp.b.client.get(f"/api/students/{sp.target}")
    assert r.status_code == 200

    body = r.json()
    leaked = [k for k in body if "sign" in k.lower()]
    assert not leaked, f"学生详情里出现了签字相关的键：{leaked}"
    assert "sign_photo" not in str(body), "连值都不该出现"


def test_list_reports_whether_a_student_has_a_sign(sp):
    """学生列表多一个 has_sign_photo：批量签字靠它筛人

    刻意放在 StudentListItem 而不是 StudentResponse 里 —— 列表需要知道「有没有」，
    通用详情接口仍然一个签字相关的键都不带（上一条用例盯着）。
    列表里也只有布尔值，文件名不出网。
    """
    upload_sign(sp)
    r = sp.b.client.get("/api/students", params={"page_size": 100})
    assert r.status_code == 200

    items = {i["student_no"]: i for i in r.json()["items"]}
    assert items[TARGET]["has_sign_photo"] is True
    assert items[STUDENT]["has_sign_photo"] is False
    for item in items.values():
        assert "has_sign_photo" in item
        assert "sign_photo" not in item, "列表只给布尔值，不该带文件名"

    # 通用详情接口的边界不变
    detail = sp.b.client.get(f"/api/students/{sp.target}").json()
    assert not [k for k in detail if "sign" in k.lower()]


# ---------- 取图权限 ----------

def test_committee_without_approval_cannot_view(sp):
    """班委没申请就是看不见 —— 这是它和另外三张照片最大的区别"""
    upload_sign(sp)
    r = fetch_sign(sp, client=sp.cm1)
    assert r.status_code == 403
    assert "申请" in r.json()["detail"]


def test_admin_does_not_need_to_apply(sp):
    """管理员不受限：有图就能看，状态直接是 approved"""
    upload_sign(sp)
    r = fetch_sign(sp)
    assert r.status_code == 200
    assert r.content == PNG
    assert status_of(sp, sp.b.client).json()["status"] == "approved"


def test_approved_applicant_gets_the_exact_bytes(sp):
    """申请 → 批准 → 申请人取到的那张图，字节和上传的一模一样"""
    upload_sign(sp)
    apply_for(sp, sp.cm1)

    r = fetch_sign(sp, client=sp.cm1)
    assert r.status_code == 200
    assert r.content == PNG
    # 授权是短时的，绝不能被缓存
    assert "no-store" in r.headers["cache-control"]


def test_approval_is_only_for_the_applicant(sp):
    """**另一个班委**没申请过，照样 403

    这是整条链路最容易写漏的一环：判权限时若只查「这个学生有没有被批准的申请」，
    任一班委被批过一次就等于给全班班委发了通行证。
    """
    upload_sign(sp)
    apply_for(sp, sp.cm1)

    assert fetch_sign(sp, client=sp.cm2).status_code == 403
    assert status_of(sp, sp.cm2).json()["status"] == "none"

    # 而申请过的那个人是能看的
    assert fetch_sign(sp, client=sp.cm1).status_code == 200


def test_approval_expires_after_an_hour(sp):
    """把批准时间改成两小时前 —— 权限就该没了，且状态变成 expired"""
    upload_sign(sp)
    apply_for(sp, sp.cm1)
    assert fetch_sign(sp, client=sp.cm1).status_code == 200

    # 直连库改时间：一小时这个时长写在代码里，改时钟得靠改数据
    expired = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S.%f")
    sp.b.run(
        "UPDATE sign_photo_requests SET reviewed_at = ? WHERE applicant_no = ?",
        expired, CM1,
    )

    r = fetch_sign(sp, client=sp.cm1)
    assert r.status_code == 403
    assert "过期" in r.json()["detail"]
    assert status_of(sp, sp.cm1).json()["status"] == "expired"


def test_expired_approval_can_be_reapplied(sp):
    """过期之后再申请一次是允许的 —— 否则这个人就永久卡死了"""
    upload_sign(sp)
    first = apply_for(sp, sp.cm1)

    sp.b.run(
        "UPDATE sign_photo_requests SET reviewed_at = ? WHERE id = ?",
        (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S.%f"), first["id"],
    )

    r = request_view(sp, sp.cm1)
    assert r.status_code == 200, r.text
    assert r.json()["id"] != first["id"], "过期后重来要新开一条，不能把老记录改回去"


def test_rejected_applicant_stays_out(sp):
    """驳回之后申请人取不到图，状态退回 none（前端于是又是「申请签署」）"""
    upload_sign(sp)
    req_id = request_view(sp, sp.cm1).json()["id"]

    r = sp.b.client.post(
        f"/api/sign-photos/requests/{req_id}/reject", json={"reason": "用途不明"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reason"] == "用途不明"

    assert fetch_sign(sp, client=sp.cm1).status_code == 403
    assert status_of(sp, sp.cm1).json()["status"] == "none"
    assert last_log(sp.b)[0] == "驳回签字查看申请"
    assert CM1 in last_log(sp.b)[2] or "乙" in last_log(sp.b)[2]


# ---------- 申请本身的边界 ----------

def test_cannot_apply_when_there_is_no_sign(sp):
    """学生还没传签字图，申请没有意义 —— 挡在提交这一步，别让管理员白批一遍"""
    r = request_view(sp, sp.cm1)
    assert r.status_code == 400
    assert "还没有签字图片" in r.json()["detail"]


def test_duplicate_pending_application_is_refused(sp):
    """待审期间再申请一次 → 400"""
    upload_sign(sp)
    assert request_view(sp, sp.cm1).status_code == 200

    r = request_view(sp, sp.cm1)
    assert r.status_code == 400
    assert "待审核" in r.json()["detail"]


def test_duplicate_approved_application_is_refused(sp):
    """已经有权限还再申请 → 400

    不挡的话，反复申请就能把有效期一路往后滚，一小时这个限制就没了。
    """
    upload_sign(sp)
    apply_for(sp, sp.cm1)

    r = request_view(sp, sp.cm1)
    assert r.status_code == 400
    assert "有效期至" in r.json()["detail"]


def test_admin_cannot_be_asked_through_the_queue(sp):
    """申请要 404 学生不存在 / 400 已处理：列表接口只给管理员"""
    upload_sign(sp)
    assert sp.cm1.get("/api/sign-photos/requests").status_code == 403
    assert sp.b.client.get("/api/sign-photos/requests").status_code == 200


def test_requests_of_other_students_do_not_interfere(sp):
    """申请是按 (学生, 申请人) 配对的：给甲申请过，不等于给乙也能看"""
    upload_sign(sp)                                     # 丁的签字
    apply_for(sp, sp.cm1)                               # 乙获批看丁

    # 另一个学生（戊）也传一张，乙对他仍然是「没申请过」
    other = sid_of(sp.b, STUDENT)
    assert upload_sign(sp, sid=other).status_code == 200
    assert fetch_sign(sp, client=sp.cm1, sid=other).status_code == 403
    assert status_of(sp, sp.cm1, sid=other).json()["status"] == "none"


# ---------- 状态接口 ----------

def test_status_carries_a_safe_download_name(sp):
    """状态接口给出「姓名_签字.png」这种能直接存盘的名字

    库里存的是内部命名（单张上传是 uuid4 hex），一个字符都不该出网；但后缀必须留着，
    预览组件靠它决定按图片还是 PDF 渲染。没有图时是空串。
    """
    assert status_of(sp, sp.cm1).json()["download_name"] == ""

    upload_sign(sp)
    body = status_of(sp, sp.b.client).json()
    assert body["download_name"] == f"{TARGET_NAME}_签字.png"

    name = db_sign(sp.b)
    assert name not in body["download_name"], "库里的裸文件名不能出现在给前端的数据里"


def test_status_separates_no_photo_from_not_applied(sp):
    """**没图**和**没申请**必须分得开 —— 前端那个按钮靠这个信号决定渲不渲染

    两种情况的状态字符串都是 none。若无图时也把 download_name 填上，学生详情页
    会给一个点开必然 404 的「申请签署」；反过来若没申请时不给 download_name，
    有图的学生也永远等不到那个按钮。所以判据是「有没有 download_name」，
    状态字符串只管按钮长什么样。
    """
    # 没有图：状态 none、下载名为空 → 前端整个不渲染
    body = status_of(sp, sp.cm1).json()
    assert (body["status"], body["download_name"]) == ("none", "")

    upload_sign(sp)
    # 有图但没申请：状态仍是 none，但下载名有了 → 前端渲染「申请签署」
    body = status_of(sp, sp.cm1).json()
    assert body["status"] == "none"
    assert body["download_name"] == f"{TARGET_NAME}_签字.png"
    assert body["expires_at"] is None


def test_pending_status_tells_the_frontend_to_wait(sp):
    """待审时状态是 pending（按钮变「申请待审核」并禁用），且没有到期时间"""
    upload_sign(sp)
    request_view(sp, sp.cm1)

    body = status_of(sp, sp.cm1).json()
    assert body["status"] == "pending"
    assert body["expires_at"] is None


def test_approved_status_has_an_expiry_time(sp):
    """批准之后状态里带上有效期，前端用来提示「有效期至 HH:MM」"""
    upload_sign(sp)
    apply_for(sp, sp.cm1)

    body = status_of(sp, sp.cm1).json()
    assert body["status"] == "approved"
    assert body["expires_at"], "批准了就得给出到期时间"
    assert body["download_name"] == f"{TARGET_NAME}_签字.png"


# ---------- 删除学生 ----------

def test_deleting_a_student_cleans_the_sign_file(sp):
    """删学生时签字文件也要清掉（三张照片之外的第四份文件）"""
    upload_sign(sp)
    name = db_sign(sp.b)
    assert (sp.photos / name).exists()

    r = sp.b.client.delete(f"/api/students/{sp.target}")
    assert r.status_code == 200, r.text
    assert not (sp.photos / name).exists()


def test_pending_application_blocks_deleting_the_student(sp):
    """签字申请挂在半路上时不能删学生

    否则管理员点「通过」会撞上「学生不存在」，那条待办就永远收不了尾。
    """
    upload_sign(sp)
    request_view(sp, sp.cm1)                            # 留一条 pending

    r = sp.b.client.delete(f"/api/students/{sp.target}")
    assert r.status_code == 400
    assert "签字查看申请" in r.json()["detail"]


# ---------- 打包导入（zip）认签字 ----------

def _zip_with(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, data)
    return buf.getvalue()


def test_zip_import_accepts_sign(sp):
    """打包导入的第四个类型：签字图，跟另外三张照片走同一条链路（管理员动作）"""
    z = _zip_with(f"{TARGET}.png", PNG)

    r = sp.b.client.post(
        "/api/students/photos/import/preview",
        params={"photo_type": "sign"},
        files={"file": ("sign.zip", z, "application/zip")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"] == {"ok": 1}, body
    assert body["items"][0]["student_name"] == TARGET_NAME

    r = sp.b.client.post("/api/students/photos/import", json={
        "token": body["token"], "photo_type": "sign", "overwrite": False,
    })
    assert r.status_code == 200, r.text
    assert r.json()["saved"] == 1

    name = db_sign(sp.b)
    assert name and (sp.photos / name).exists()
    # 日志的 target 用的是类型标签，与另外三种照片一致
    assert last_log(sp.b)[1] == "签字图"


def test_zip_import_rejects_an_unknown_type(sp):
    """非法类型照旧 400，而且报错里要列出四个（含签字）"""
    z = _zip_with(f"{TARGET}.png", PNG)
    r = sp.b.client.post(
        "/api/students/photos/import/preview",
        params={"photo_type": "avatar"},
        files={"file": ("sign.zip", z, "application/zip")},
    )
    assert r.status_code == 400
    assert "sign" in r.json()["detail"], "报错要按 IMPORT_PHOTO_FIELDS 现取，别写死三个"


def test_sign_cannot_be_fetched_through_the_generic_photo_api(sp):
    """**签字只从 api/sign_photos.py 出**，通用照片接口认不到它

    这条是上面那条安全边界的运行期版本：就算有人绕过前端直接敲
    /students/{id}/photo?type=sign，也该拿到 400 而不是签字图。
    """
    upload_sign(sp)
    for client in (sp.b.client, sp.cm1):
        r = client.get(f"/api/students/{sp.target}/photo?type=sign")
        assert r.status_code == 400
        assert "照片类型只能是" in r.json()["detail"]
