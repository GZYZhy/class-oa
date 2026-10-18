"""信息修改申请的回归：宿舍号、自备证件照（落盘 / 越权 / 审核 / 清理）

    cd backend && python -m pytest tests -q

装置沿用 conftest 的 backend fixture（真 uvicorn 进程 + 真临时库 + httpx），
引导流程和 test_grades.py 一样。**照片目录也被隔离了**（conftest 给后端指了
tmp_path/photos），所以这里可以直接数盘上有几个文件 —— 判断「有没有留下孤儿」
只有看盘才作数。

这组用例盯的是几件在别处看不出来的事：
- 学生碰不到文件名。照片的值由服务端落盘之后注入，学生从 JSON 塞进来的会被 422 拒掉
- 落盘和建申请在同一个请求里，但**检查排在落盘前面** —— 被 400 拒掉的那次不留文件
- 通过才写档案并删旧图；驳回、落库失败都把新图删掉
"""
from types import SimpleNamespace

import httpx
import pytest

from conftest import png_bytes

PW = "initpass123"

# (学号, 姓名, 身份证后 6 位 —— 也就是这个学生的默认密码)
ROSTER = [
    ("2024000001", "甲", "010001"),
    ("2024000002", "乙", "010002"),
]
ADMIN = ROSTER[0][0]
STUDENT = ROSTER[1][0]
STUDENT_PW = ROSTER[1][2]


PNG = png_bytes()


# ---------- 小工具 ----------

def as_student(b, idx) -> httpx.Client:
    """另开一个客户端以学生身份登录 —— 会话是按 client 存的，换身份就得换 client"""
    no, _, tail = ROSTER[idx]
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": tail})
    assert r.status_code == 200, r.text
    return c


def sid_of(b, no) -> int:
    return b.rows("SELECT id FROM students WHERE student_no = ?", no)[0][0]


def db_photo(b, no):
    """档案里的自备证件照文件名。绕开接口直连库：要断言的就是「库里到底存了什么」"""
    return b.rows("SELECT id_photo FROM students WHERE student_no = ?", no)[0][0]


def files_in(photos) -> list[str]:
    return sorted(p.name for p in photos.glob("*"))


def submit_json(cr, data):
    return cr.student.post("/api/change-requests", json=data)


def submit_photo(cr, data, photo=PNG, filename="id.png"):
    """带照片的申请走 multipart（浏览器发文件只能这么发）"""
    return cr.student.post(
        "/api/change-requests",
        data=data,
        files={"photo": (filename, photo, "image/png")},
    )


def give_photo(cr, no=STUDENT) -> str:
    """由管理员给某个学生传一张，用来铺「换之前已经有照片」的状态"""
    r = cr.b.client.post(
        f"/api/students/{sid_of(cr.b, no)}/photo?type=id",
        files={"file": ("old.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["photo"]


@pytest.fixture
def cr(backend, tmp_path):
    """初始化完毕、管理员（甲）已登录、学生乙也登录好了

    tmp_path 与 conftest 里指给后端的是同一个（同一个测试函数内 fixture 只实例化一次），
    所以 cr.photos 就是后端真正在写的那个目录。
    """
    b = backend(db="change.db", BOOTSTRAP_PASSWORD=PW)
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

    return SimpleNamespace(b=b, photos=tmp_path / "photos", student=as_student(b, 1))


# ---------- 换证件照 ----------

def test_photo_approved_replaces_and_cleans_old(cr):
    """提交时落盘、档案先不动；通过后才写档案并把旧图删掉"""
    old = give_photo(cr)
    assert (cr.photos / old).exists()

    r = submit_photo(cr, {"phone": "13800138000"})
    assert r.status_code == 200, r.text
    new = r.json()["changes"]["id_photo"]
    assert new and new != old, "学生拿到的是服务端生成的文件名，不是他传上来的那个"

    # 待审期间：新图已经在盘上等着，档案里还是旧的
    assert (cr.photos / new).exists()
    assert db_photo(cr.b, STUDENT) == old, "没通过之前绝不能写进档案"

    assert cr.b.client.post(f"/api/change-requests/{r.json()['id']}/approve").status_code == 200
    assert db_photo(cr.b, STUDENT) == new
    assert (cr.photos / new).exists()
    assert not (cr.photos / old).exists(), "旧图在提交成功之后就该删掉"


def test_photo_without_any_text_field(cr):
    """只换照片、一个字都不改，也是一次有效申请"""
    r = submit_photo(cr, {})
    assert r.status_code == 200, r.text
    assert list(r.json()["changes"]) == ["id_photo"]


def test_photo_rejected_cleans_up(cr):
    """驳回后那张图再没人会引用，不能留在盘上"""
    old = give_photo(cr)
    r = submit_photo(cr, {})
    rid, new = r.json()["id"], r.json()["changes"]["id_photo"]

    resp = cr.b.client.post(f"/api/change-requests/{rid}/reject", json={"reason": "照片不清晰"})
    assert resp.status_code == 200, resp.text
    assert db_photo(cr.b, STUDENT) == old, "驳回不动档案"
    assert not (cr.photos / new).exists(), "驳回后新图成了永久孤儿"


def test_approve_blocked_when_photo_file_gone(cr):
    """待审的照片文件没了就别写档案 —— 否则档案指向一张打不开的图"""
    r = submit_photo(cr, {})
    rid, new = r.json()["id"], r.json()["changes"]["id_photo"]
    (cr.photos / new).unlink()

    resp = cr.b.client.post(f"/api/change-requests/{rid}/approve")
    assert resp.status_code == 400 and "丢失" in resp.json()["detail"]
    assert db_photo(cr.b, STUDENT) is None


# ---------- 越权与闸门 ----------

def test_student_cannot_smuggle_a_file_name(cr):
    """学生从 JSON 直接塞文件名要当场拒掉

    批量导入存下来的文件名是 `{学号}_{类型}.png`，可预测；放行的话，学生传一个
    别人的文件名、班委一点通过，档案就指向别人的证件照，之后换图/删学生还会顺手
    删掉别人的文件。
    """
    r = submit_json(cr, {"id_photo": "2024000001_id.png", "phone": "139"})
    assert r.status_code == 422, "照片字段不接受直接传值"
    assert db_photo(cr.b, STUDENT) is None
    assert not files_in(cr.photos), "整条申请都没落库，更不该有文件"


def test_review_photo_needs_committee(cr):
    """对照图是给班委看的：学生连自己那条也取不到（走的是另一个接口）"""
    rid = submit_photo(cr, {}).json()["id"]
    assert cr.student.get(f"/api/change-requests/{rid}/photo?side=new").status_code == 403
    assert cr.b.client.get(f"/api/change-requests/{rid}/photo?side=new").status_code == 200


def test_review_photo_sides(cr):
    """old 取学生当前那张、new 取申请里那张；学生本来没照片时 old 是正常的 404"""
    rid = submit_photo(cr, {}).json()["id"]
    # 乙还没照片：old 那边没有可对照的
    assert cr.b.client.get(f"/api/change-requests/{rid}/photo?side=old").status_code == 404
    assert cr.b.client.get(f"/api/change-requests/{rid}/photo?side=new").content == PNG

    assert cr.b.client.get(f"/api/change-requests/{rid}/photo?side=xyz").status_code == 400
    assert cr.b.client.get("/api/change-requests/999999/photo").status_code == 404


def test_photo_gates(cr):
    """后缀和大小不合规都是 400，且被拒之后盘上不留东西"""
    r = submit_photo(cr, {}, photo=b"x" * 32, filename="id.txt")
    assert r.status_code == 400 and "格式" in r.json()["detail"]

    r = submit_photo(cr, {}, photo=b"x" * (10 * 1024 * 1024 + 1))
    assert r.status_code == 400 and "10MB" in r.json()["detail"]
    assert not files_in(cr.photos)


def test_pending_checked_before_saving(cr):
    """已有待审申请时再传一次照片：这次 400 不能把图留在盘上"""
    assert submit_photo(cr, {}).status_code == 200
    before = files_in(cr.photos)
    assert len(before) == 1

    r = submit_photo(cr, {})
    assert r.status_code == 400 and "待审核" in r.json()["detail"]
    assert files_in(cr.photos) == before, "「先检查后落盘」的顺序守不住就会多出一张孤儿"


def test_photo_name_not_leaked_into_log(cr):
    """日志里写真名，不写 uuid 文件名 —— 那对学生和班委都不构成信息"""
    r = submit_photo(cr, {"phone": "13800138000"})
    new = r.json()["changes"]["id_photo"]
    detail = cr.b.rows("SELECT detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0][0]
    assert "自备证件照" in detail and "换" in detail
    assert new not in detail, "uuid 文件名不该出现在日志里"


# ---------- 宿舍号 ----------

def test_dormitory_change(cr):
    """宿舍号进了白名单：出参带旧值供对照，通过后写进档案"""
    r = submit_json(cr, {"dormitory": "3 号楼 502", "bed": "1 号床"})
    assert r.status_code == 200, r.text
    assert r.json()["current"]["dormitory"] is None, "原先没有宿舍，出参要如实给 null"

    rid = r.json()["id"]
    assert cr.b.client.post(f"/api/change-requests/{rid}/approve").status_code == 200
    row = cr.b.rows("SELECT dormitory, bed FROM students WHERE student_no = ?", STUDENT)[0]
    assert row == ("3 号楼 502", "1 号床")


def test_dormitory_length_capped(cr):
    """长度上限跟 students.dormitory 的 String(50) 对齐"""
    assert submit_json(cr, {"dormitory": "x" * 51}).status_code == 422
    assert submit_json(cr, {"dormitory": "x" * 50}).status_code == 200


# ---------- 身份证号：只补不改 ----------

NO_ID = "2024000003"
NO_ID_PW = "000003"   # 没有身份证号时默认密码退化成学号后 6 位
ID_CARD = "11010120000101001x"


def make_no_id_client(cr) -> httpx.Client:
    """新建一个没有身份证号的学生并登录 —— 只有这种档案才允许申请补充"""
    r = cr.b.client.post("/api/students", json={"student_no": NO_ID, "name": "丙"})
    assert r.status_code < 300, r.text
    c = httpx.Client(base_url=str(cr.b.client.base_url), timeout=10)
    assert c.post("/api/auth/login", json={
        "student_no": NO_ID, "password": NO_ID_PW,
    }).status_code == 200
    return c


def db_id_card(b, no=NO_ID):
    return b.rows("SELECT id_card FROM students WHERE student_no = ?", no)[0][0]


def test_id_card_can_be_supplemented(cr):
    """档案里没有身份证号时允许申请补充，通过后写进档案；末位 x 统一成大写"""
    c = make_no_id_client(cr)
    r = c.post("/api/change-requests", json={"id_card": ID_CARD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changes"]["id_card"] == ID_CARD.upper()
    assert body["current"]["id_card"] is None, "原先没有，出参如实给 null"
    assert db_id_card(cr.b) is None, "没通过之前不能写进档案"

    assert cr.b.client.post(f"/api/change-requests/{body['id']}/approve").status_code == 200
    assert db_id_card(cr.b) == ID_CARD.upper()

    # 日志里只说「补了身份证号」，不落完整号码
    detail = cr.b.rows("SELECT detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0][0]
    assert "补充了身份证号" in detail
    assert ID_CARD.upper() not in detail


def test_id_card_cannot_change_once_present(cr):
    """档案里已有身份证号的，提交这一项直接 400 —— 前端藏输入框不算数"""
    r = submit_json(cr, {"id_card": "110101200001010099"})
    assert r.status_code == 400 and "已有身份证号" in r.json()["detail"]

    # 班委审批前管理员补录了身份证号：这条申请也不能再通过，免得覆盖管理员的值
    c = make_no_id_client(cr)
    rid = c.post("/api/change-requests", json={"id_card": ID_CARD}).json()["id"]
    cr.b.run("UPDATE students SET id_card = ? WHERE student_no = ?",
             "11010120000202002X", NO_ID)

    resp = cr.b.client.post(f"/api/change-requests/{rid}/approve")
    assert resp.status_code == 400 and "已有值" in resp.json()["detail"]
    assert db_id_card(cr.b) == "11010120000202002X", "管理员刚录的值不能被申请覆盖"


def test_id_card_format_checked(cr):
    """位数不对的号码在提交阶段就被挡掉，不留给班委去猜"""
    c = make_no_id_client(cr)
    assert c.post("/api/change-requests", json={"id_card": "123"}).status_code == 422
    assert c.post("/api/change-requests", json={"id_card": ""}).status_code == 422
    assert db_id_card(cr.b) is None
