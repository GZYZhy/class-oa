"""域外账号的手写签字图：管理员在系统管理里传，也只有管理员能取

    cd backend && python -m pytest tests -q

域外账号（老师等协助人员，users 表里 is_external=1，**没有 Student 行**）也可能是
办件的审批者，落款要用到签字，所以它也得能有一张。与学生那份不同的是取图口径：
学生的签字是「班委申请 → 管理员批准 → 只有申请人在一小时内能看」，域外账号这份
**只有管理员能取** —— 本人、学生、班委一律 403。

最容易写漏的一环是「本人也不能看」：签字是审批落款用的，不是给签字人自己看的。
文件与学生照片共用 data/photos（conftest 已把 PHOTO_DIR 指到 tmp），所以可以直接
数盘上有什么 —— 「换图之后旧文件删了没有」「删账号时清干净没有」只有看盘才作数。
"""
from types import SimpleNamespace

import httpx
import pytest

from conftest import png_bytes

PW = "initpass123"
EXT_PW = "extpass123"   # 域外账号的密码由管理员当场指定，不走身份证后 6 位那套

ADMIN = "2024000001"
CM = "2024000002"       # 班委：签字这功能跟他没关系，取图必须 403
STUDENT = "2024000003"  # 普通学生：同上
ROSTER = [
    (ADMIN, "甲", "010001"),
    (CM, "乙", "010002"),
    (STUDENT, "丙", "010003"),
]
TAILS = dict((n, t) for n, _, t in ROSTER)

# 域外账号：登录名允许带下划线（老师可能想用姓名拼），展示名就是姓名
LOGIN = "teacher_li"
NAME = "李俊刚"

PNG = png_bytes()
# 另一张真 PNG（字节不同，用来断言「换图之后拿到的确实是新图」）
PNG2 = PNG[:-20] + bytes([PNG[-20] ^ 0xFF]) + PNG[-19:]


# ---------- 小工具 ----------

def as_student(b, no) -> httpx.Client:
    """另开一个客户端以某个学生身份登录 —— 会话是按 client 存的"""
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": TAILS[no]})
    assert r.status_code == 200, r.text
    return c


def as_ext(b, login=LOGIN) -> httpx.Client:
    """以域外账号本人登录 —— 用来证明他连自己那张签字图都取不到"""
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": login, "password": EXT_PW})
    assert r.status_code == 200, r.text
    return c


def create_ext(b, sign=None, *, login=LOGIN, name=NAME, role="student", filename="sign.png"):
    """建域外账号；sign 给了就同时把签字图带上（新建时就能传，与头像对称）"""
    data = {"login_name": login, "display_name": name, "password": EXT_PW, "role": role}
    files = {"sign_photo": (filename, sign, "image/png")} if sign else None
    return b.client.post("/api/admin/external-users", data=data, files=files)


def update_ext(b, sign=None, *, login=LOGIN, name=NAME, role="student",
               remove_sign=False, filename="sign.png"):
    """改域外账号。remove_sign=True 表示「清掉现有签字图」——
    不传图又不置这个标志，后端就当成「没动签字」"""
    data = {
        "display_name": name,
        "role": role,
        "remove_sign_photo": "true" if remove_sign else "false",
    }
    files = {"sign_photo": (filename, sign, "image/png")} if sign else None
    return b.client.put(f"/api/admin/external-users/{login}", data=data, files=files)


def fetch_sign(b, client=None, login=LOGIN):
    """取域外账号的签字图。默认用管理员那个 client，具体身份由调用方指定"""
    return (client or b.client).get(f"/api/admin/external-users/{login}/sign-photo")


def db_sign(b, login=LOGIN):
    """库里那一列。直连库：要断言的就是「库里到底存了什么」"""
    return b.rows("SELECT sign_photo FROM users WHERE student_no = ?", login)[0][0]


def user_row(b, login=LOGIN):
    """账号列表里这一行 —— 前端弹窗的「已有签字图」状态就吃这个字段"""
    rows = b.client.get("/api/admin/users").json()
    return next(r for r in rows if r["student_no"] == login)


def files_in(photos) -> list[str]:
    return sorted(p.name for p in photos.glob("*"))


def last_log(b):
    """最近一条操作日志（action, target, detail）"""
    return b.rows("SELECT action, target, detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0]


@pytest.fixture
def ex(backend, tmp_path):
    """初始化完毕：一个管理员、一个班委、一个普通学生

    tmp_path 与 conftest 里指给后端的是同一个（同一个测试函数内 fixture 只实例化一次），
    所以 ex.photos 就是后端真正在写的那个目录。
    """
    b = backend(db="external_sign.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200      # 初始化临时账号

    for no, name, tail in ROSTER:
        r = b.client.post("/api/students", json={
            "student_no": no, "name": name, "id_card": f"11010120000101{tail}",
        })
        assert r.status_code < 300, r.text

    # 指认管理员：这一步之后临时账号当场废止，得用他本人重新登录
    # （/api/admin/* 被初始化闸门挡着，临时账号进不去）
    r = b.client.post("/api/setup/finish", json={"admin_student_no": ADMIN})
    assert r.status_code == 200, r.text
    b.logout()
    assert b.login(student_no=ADMIN, password=TAILS[ADMIN]).status_code == 200

    r = b.client.put(f"/api/admin/users/{CM}/role", json={"role": "committee"})
    assert r.status_code == 200, r.text

    return SimpleNamespace(
        b=b,
        photos=tmp_path / "photos",
        cm=as_student(b, CM),
        student=as_student(b, STUDENT),
    )


# ---------- 上传 / 存储 ----------

def test_create_external_with_sign_lands_on_disk(ex):
    """新建时就能带签字图：图落盘、库里存裸文件名、列表里标志位亮起来"""
    r = create_ext(ex.b, PNG)
    assert r.status_code == 200, r.text

    name = db_sign(ex.b)
    assert name and "/" not in name and "\\" not in name, f"库里该只存裸文件名，实际是 {name!r}"
    assert (ex.photos / name).exists()
    assert files_in(ex.photos) == [name], "目录里该只有这一张签字图"
    assert user_row(ex.b)["has_sign_photo"] is True


def test_replace_then_remove(ex):
    """换图：旧文件删掉、库指向新的；清除：字段清空、盘上不留东西"""
    assert create_ext(ex.b, PNG).status_code == 200
    old = db_sign(ex.b)

    assert update_ext(ex.b, PNG2).status_code == 200
    new = db_sign(ex.b)
    assert new != old, "换了图之后库里该指向新文件名"
    assert not (ex.photos / old).exists(), "旧文件该在提交成功之后被删掉"
    assert files_in(ex.photos) == [new]

    assert update_ext(ex.b, remove_sign=True).status_code == 200
    assert db_sign(ex.b) is None
    assert files_in(ex.photos) == [], "清了签字之后盘上不该留下孤儿"
    assert user_row(ex.b)["has_sign_photo"] is False


def test_rename_only_keeps_sign(ex):
    """只改展示名：签字图和它的文件都不能被动到（库里那一列还指着它）"""
    assert create_ext(ex.b, PNG).status_code == 200
    name = db_sign(ex.b)

    assert update_ext(ex.b, name="李老师").status_code == 200
    assert db_sign(ex.b) == name
    assert (ex.photos / name).exists()


def test_bad_type_is_400_with_sign_wording(ex):
    """坏类型报 400，且文案说的是「签字图片」而不是「照片」

    （底下复用的是照片那套 save_photo，文案不换的话用户会看到「照片」字样）
    """
    r = create_ext(ex.b, b"not an image", filename="sign.txt")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "签字图片" in detail
    assert "照片" not in detail


def test_student_account_cannot_be_touched(ex):
    """学生的学号只能落在学生账号上，域外账号这套接口一律不认"""
    r = update_ext(ex.b, login=STUDENT)
    assert r.status_code == 400, r.text
    assert "学生账号" in r.json()["detail"]

    # 登录名撞上已有学号也不行：撞上了那个学生就登不进自己的账号
    assert create_ext(ex.b, login=STUDENT).status_code == 400


# ---------- 取图：只有管理员 ----------

def test_only_admin_can_fetch(ex):
    """本人、班委、学生全 403，只有管理员 200 —— 这条是整个功能的立身之本"""
    assert create_ext(ex.b, PNG).status_code == 200

    assert fetch_sign(ex.b, as_ext(ex.b)).status_code == 403      # 本人也不行
    assert fetch_sign(ex.b, ex.cm).status_code == 403
    assert fetch_sign(ex.b, ex.student).status_code == 403
    assert fetch_sign(ex.b).status_code == 200


def test_admin_fetch_returns_exact_bytes(ex):
    """拿到的必须是传上去的那张图，逐字节一致"""
    assert create_ext(ex.b, PNG).status_code == 200
    r = fetch_sign(ex.b)
    assert r.status_code == 200
    assert r.content == PNG


def test_fetch_without_sign_is_404(ex):
    """没传过签字的账号：取图 404，而不是空图或者 500"""
    assert create_ext(ex.b).status_code == 200
    r = fetch_sign(ex.b)
    assert r.status_code == 404
    assert "签字" in r.json()["detail"]


# ---------- 日志 ----------

def test_log_actions_are_searchable(ex):
    """动作名与学生签字图那套同名 —— 日志页搜「签字」两条链路都该搜得到"""
    assert create_ext(ex.b, PNG).status_code == 200
    action, target, _ = last_log(ex.b)
    assert action == "上传签字图片"
    assert target == f"{LOGIN} {NAME}"

    assert update_ext(ex.b, sign=PNG2).status_code == 200
    assert last_log(ex.b)[0] == "上传签字图片"

    assert update_ext(ex.b, remove_sign=True).status_code == 200
    assert last_log(ex.b)[0] == "删除签字图片"


def test_rename_logs_no_sign_action(ex):
    """只改名字那次不能冒出签字动作的日志（否则日志页会多出一堆噪音）"""
    assert create_ext(ex.b, PNG).status_code == 200
    assert update_ext(ex.b, name="李老师").status_code == 200
    assert last_log(ex.b)[0] == "修改域外账号"


# ---------- 删账号 ----------

def test_delete_account_cleans_sign_file(ex):
    """账号删掉，它的签字图在盘上也不能留着"""
    assert create_ext(ex.b, PNG).status_code == 200
    name = db_sign(ex.b)

    assert ex.b.client.delete(f"/api/admin/external-users/{LOGIN}").status_code == 200
    assert not (ex.photos / name).exists()
    assert files_in(ex.photos) == []
    assert ex.b.rows("SELECT student_no FROM users WHERE student_no = ?", LOGIN) == []


# ---------- 给办件留的入口 ----------

def test_user_sign_photo_path_helper():
    """办件将来靠这个入口取域外账号的签字图（python-docx 的 add_picture 吃路径）

    用鸭子类型的假对象就够：这个函数只读 sign_photo 那一列，不碰库。
    带上「塞了路径也只取文件名」这一条 —— 它复用的 photo_path 是防路径穿越的那道闸。
    """
    from app.services.student_photo_service import user_sign_photo_path

    assert user_sign_photo_path(SimpleNamespace(sign_photo=None)) is None
    assert user_sign_photo_path(SimpleNamespace(sign_photo="abc.png")).name == "abc.png"
    assert user_sign_photo_path(SimpleNamespace(sign_photo="../../etc/passwd")).name == "passwd"
