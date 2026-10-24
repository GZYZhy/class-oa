"""「关于班级」页的配置：简介卡片、任职表开关和显示顺序

    cd backend && python -m pytest tests/test_about.py -q

盯三件事：

1. **默认值不能把原有页面改没**：升级上来的站点第一次打开时，任职表应该照旧显示，
   简介卡片默认关闭（没写内容时不该多一张空卡片）。
2. **顺序只影响展示**：管理员排的是「关于班级」页的次序，不改 students 表；
   没排到的新成员要接在最后，不能因为数组里没有他就消失。
3. **坏数据不炸页面**：roster_order 是手工可改的 TEXT，解析失败必须退回学号顺序，
   不能让关于页 500。
"""
import pytest

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"

# 学号、姓名、职务。最后一个职务是「无」：判定里它和空串一样不算班委
PEOPLE = [
    ("2024000002", "乙", "班长"),
    ("2024000003", "丙", "团支书"),
    ("2024000004", "丁", "无"),
]


def _world(backend, db_name="about.db"):
    b = backend(db=db_name, BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200

    r = b.client.post("/api/students", json={
        "student_no": ADMIN, "name": "甲", "id_card": "110101200501010001",
    })
    assert r.status_code < 300, r.text

    for no, name, position in PEOPLE:
        r = b.client.post("/api/students", json={
            "student_no": no,
            "name": name,
            "id_card": f"11010120050101{no[-4:]}",
            "class_position": position,
        })
        assert r.status_code < 300, r.text

    assert b.client.post(
        "/api/setup/finish", json={"admin_student_no": ADMIN}
    ).status_code == 200
    b.logout()
    assert b.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200
    return b


@pytest.fixture
def ab(backend):
    return _world(backend)


# ---------- 默认值与读取 ----------

def test_first_boot_creates_the_single_row_and_keeps_old_behaviour(ab):
    """启动时补出单行设置；默认「任职表显示、简介关闭」，和升级前一致"""
    assert ab.rows("SELECT COUNT(*) FROM about_settings")[0][0] == 1

    data = ab.client.get("/api/about").json()
    assert data["roster_enabled"] is True, "升级后任职表不能凭空消失"
    assert data["intro"]["enabled"] is False, "没写内容时默认不显示简介卡片"
    assert data["intro"]["markdown"] == ""
    # 「无」不算班委，顺序默认按学号
    assert [m["student_no"] for m in ab.client.get("/api/admin/about").json()["members"]] == [
        "2024000002", "2024000003",
    ]


# ---------- 保存 ----------

def test_save_intro_roster_and_order(ab):
    r = ab.client.put("/api/admin/about", json={
        "intro_enabled": True,
        "intro_markdown": "## 欢迎\n\n这是 **示例班**。",
        "roster_enabled": False,
        "order": ["2024000003", "2024000002"],
    })
    assert r.status_code == 200, r.text

    admin = ab.client.get("/api/admin/about").json()
    assert admin["intro_enabled"] is True
    assert admin["intro_markdown"].startswith("## 欢迎")
    assert admin["roster_enabled"] is False
    assert [m["student_no"] for m in admin["members"]] == ["2024000003", "2024000002"]

    # 用户端同一份数据：简介按原文下发，渲染交给前端；任职表开关同步
    data = ab.client.get("/api/about").json()
    assert data["intro"]["enabled"] is True
    assert data["intro"]["markdown"].startswith("## 欢迎")
    assert data["roster_enabled"] is False
    assert [m["name"] for m in data["committee"]] == ["丙", "乙"]


def test_members_missing_from_the_order_are_appended(ab):
    """只排了一个人：另一个不能被丢掉，接在最后并按学号"""
    assert ab.client.put("/api/admin/about", json={
        "intro_enabled": False,
        "intro_markdown": "",
        "roster_enabled": True,
        "order": ["2024000003"],
    }).status_code == 200

    data = ab.client.get("/api/about").json()
    assert [m["name"] for m in data["committee"]] == ["丙", "乙"]


def test_broken_order_falls_back_instead_of_500(ab):
    """手工改库写坏了 roster_order：关于页照常开，顺序退回学号"""
    ab.run("UPDATE about_settings SET roster_order = ? WHERE id = 1", "不是 JSON")
    r = ab.client.get("/api/about")
    assert r.status_code == 200, r.text
    assert [m["name"] for m in r.json()["committee"]] == ["乙", "丙"]


# ---------- 权限 ----------

def test_about_settings_are_admin_only(ab):
    """配置接口只给管理员；关于页本身普通学生仍能看"""
    ab.logout()
    assert ab.login(student_no="2024000002", password="010002").status_code == 200

    assert ab.client.get("/api/about").status_code == 200
    assert ab.client.get("/api/admin/about").status_code == 403
    assert ab.client.put("/api/admin/about", json={
        "intro_enabled": True,
        "intro_markdown": "x",
        "roster_enabled": False,
        "order": [],
    }).status_code == 403
