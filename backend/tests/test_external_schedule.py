"""域外账号的日程：只读共享日程；班委/管理员可分配

    cd backend && python -m pytest tests/test_external_schedule.py -q

口径（用户拍板）：
- 域外账号没有自己的日程表，只能看到「分配给所有人」的批次 + 自己创建的批次；
- 等效学生（role=student）不能建/改/删，连格子都点不出表单；
- 班委/管理员可以分配新日程、导入课表，下发对象可选全体或指定学生；
  指定学生的批次只有操作者自己能看到。

测试里直接走接口建批次、切账号登录，最后用域外入口读结果。
"""
from io import BytesIO
from types import SimpleNamespace

import httpx
import openpyxl
import pytest
from sqlalchemy import create_engine, text

from app.database_migrate import _apply_schedule_batch_all_fix

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"
STUDENT = "2024000002"
STUDENT_PW = "010002"

TEACHER = "teacher01"
TEACHER_PW = "teacherpass1"
MANAGER = "teacher02"
MANAGER_PW = "teacherpass2"

DAY = "2026-11-10"


@pytest.fixture
def es(backend):
    b = backend(db="external_schedule.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200
    for no, name, tail in (
        (ADMIN, "甲", "010001"),
        (STUDENT, "乙", "010002"),
    ):
        r = b.client.post("/api/students", json={
            "student_no": no, "name": name,
            "id_card": f"11010120050101{tail}",
        })
        assert r.status_code < 300, r.text
    assert b.client.post(
        "/api/setup/finish", json={"admin_student_no": ADMIN}
    ).status_code == 200
    b.logout()
    assert b.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200

    # 域外账号：等效学生 / 班委各一个
    for login, name, password, role in (
        (TEACHER, "示例老师甲", TEACHER_PW, "student"),
        (MANAGER, "示例老师乙", MANAGER_PW, "committee"),
    ):
        r = b.client.post("/api/admin/external-users", data={
            "login_name": login, "display_name": name,
            "password": password, "role": role,
        })
        assert r.status_code == 200, r.text
    return b


def _login_as(b, no, password) -> httpx.Client:
    b.logout()
    assert b.login(student_no=no, password=password).status_code == 200
    return b.client


def _as(b, no, password) -> httpx.Client:
    """独立会话：同一用例里要同时用域外/学生多个身份，不能共用一个 client"""
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": password})
    assert r.status_code == 200, r.text
    return c


def _student_id(b, no) -> int:
    return b.rows("SELECT id FROM students WHERE student_no = ?", no)[0][0]


def _admin(b):
    b.logout()
    assert b.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200
    return b.client


def _schedule(title: str, start: str = "10:00", end: str = "11:00") -> dict:
    return {
        "title": title,
        "start_time": f"{DAY}T{start}:00",
        "end_time": f"{DAY}T{end}:00",
        "all_day": False,
        "repeat_type": "none",
        "notify_enabled": False,
    }


def _list(client) -> list[dict]:
    return _list_range(client, DAY, DAY)


def _list_range(client, start: str, end: str) -> list[dict]:
    r = client.get(
        "/api/schedules/external",
        params={"start_date": start, "end_date": end},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _import_xlsx() -> bytes:
    """最小可导入课表：第 1 周周一 10/12，一节高数"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "第1周"
    ws.cell(row=1, column=2, value="10/12 周一")
    for row in range(90):
        hour = 7 + row // 6
        minute = (row % 6) * 10
        ws.cell(row=row + 2, column=1, value=f"{hour:02d}:{minute:02d}")
    ws.merge_cells(start_row=2, start_column=2, end_row=7, end_column=2)
    ws.cell(row=2, column=2, value="高等数学\n课程\n教学楼C101")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_external_sees_only_all_student_batches(es):
    # 管理员建一条「全体学生」的，再建一条只给自己的
    r = _admin(es).post("/api/schedules", json={
        **_schedule("全班大会"), "target_all": True,
    })
    assert r.status_code == 200, r.text
    r = _admin(es).post("/api/schedules", json=_schedule("个人备课"))
    assert r.status_code == 200, r.text

    teacher = _login_as(es, TEACHER, TEACHER_PW)
    items = _list(teacher)
    assert [item["title"] for item in items] == ["全班大会"], items
    assert all(item["source_type"] == "batch" for item in items)


def test_external_student_equivalent_is_read_only(es):
    _admin(es).post("/api/schedules", json={
        **_schedule("全班大会"), "target_all": True,
    })
    teacher = _login_as(es, TEACHER, TEACHER_PW)

    # 建：拒
    r = teacher.post("/api/schedules/external", json=_schedule("临时会议"))
    assert r.status_code == 403
    assert "只能查看" in r.json()["detail"]

    # 普通学生入口也进不去（没有 Student 行）
    assert teacher.get("/api/schedules", params={
        "start_date": DAY, "end_date": DAY,
    }).status_code == 403
    assert _list(teacher), "只读仍然看得到共享日程"


def test_external_manager_can_allocate_and_sees_own(es):
    _admin(es).post("/api/schedules", json={
        **_schedule("全班大会"), "target_all": True,
    })

    manager = _login_as(es, MANAGER, MANAGER_PW)
    r = manager.post("/api/schedules/external", json=_schedule("教师例会"))
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "教师例会"

    items = _list(manager)
    assert {item["title"] for item in items} == {"全班大会", "教师例会"}, items

    # 批次里记下了「谁建的 / 是否全体」，否则下次重启就认不出来了
    batch = es.rows(
        "SELECT target_all, operator_user_id FROM schedule_batches "
        "ORDER BY id DESC LIMIT 1"
    )[0]
    assert batch[0] == 1 and batch[1] is not None

    # 分给的是全体学生：两个学生各一条副本
    assert es.rows(
        "SELECT COUNT(*) FROM schedules WHERE source_batch_id = "
        "(SELECT MAX(id) FROM schedule_batches)"
    )[0][0] == 2


def test_external_manager_can_allocate_to_selected_students(es):
    """指定学生：操作者自己能看到，别的域外账号看不到，被点到的学生能看到"""
    manager = _as(es, MANAGER, MANAGER_PW)
    student_id = _student_id(es, STUDENT)
    r = manager.post("/api/schedules/external", json={
        **_schedule("只给一人"),
        "target_all": False,
        "target_student_ids": [student_id],
    })
    assert r.status_code == 200, r.text

    assert [item["title"] for item in _list(manager)] == ["只给一人"]
    teacher = _as(es, TEACHER, TEACHER_PW)
    assert _list(teacher) == [], "没有发给全体，另一个域外账号不该看到"

    student = _as(es, STUDENT, STUDENT_PW)
    r = student.get("/api/schedules", params={
        "start_date": DAY, "end_date": DAY,
    })
    assert r.status_code == 200, r.text
    assert [item["title"] for item in r.json()] == ["只给一人"]

    batch = es.rows(
        "SELECT target_all FROM schedule_batches ORDER BY id DESC LIMIT 1"
    )[0]
    assert batch[0] == 0


def test_external_manager_can_import_and_assign_selected(es):
    """导入同样可用；指定学生时只有操作者和目标学生看得到"""
    manager = _as(es, MANAGER, MANAGER_PW)
    student_id = _student_id(es, STUDENT)
    preview = manager.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", _import_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert preview.status_code == 200, preview.text

    r = manager.post("/api/schedules/import", json={
        "token": preview.json()["token"],
        "batch_name": "外部导入",
        "target_all": False,
        "target_student_ids": [student_id],
        "selected_indices": [],
    })
    assert r.status_code == 200, r.text
    assert r.json()["target_count"] == 1

    items = _list_range(manager, "2026-10-12", "2026-10-18")
    assert any(item["title"] == "高等数学" for item in items), items
    teacher = _as(es, TEACHER, TEACHER_PW)
    assert _list_range(teacher, "2026-10-12", "2026-10-18") == []

    student = _as(es, STUDENT, STUDENT_PW)
    r = student.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    assert any(item["title"] == "高等数学" for item in r.json()), r.text


def test_backfill_only_marks_schedules_copied_to_everyone():
    """迁移不能只看 target_count，也要容忍个别学生删掉几节课

    批次 1：两条 series，各只有 1 份（典型生日批次，旧逻辑误标成 1）
    批次 2：一条 series，复制给 2 个人（真正发给全体）
    批次 3：只发给 1 个人（指定学生）
    批次 4：发给 4 个人，但每条 series 只剩 3 份（课程发下去后被删掉几份）
    批次 5：只发了 1 份，却挂着 target_count=4（个人日程伪装成全体）
    """
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE students (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE schedule_batches ("
            "id INTEGER PRIMARY KEY, target_count INTEGER, "
            "target_all BOOLEAN NOT NULL DEFAULT 0)"
        ))
        conn.execute(text(
            "CREATE TABLE schedules ("
            "id INTEGER PRIMARY KEY, source_batch_id INTEGER, source_series_id TEXT)"
        ))
        conn.execute(text("INSERT INTO students (id) VALUES (1), (2), (3), (4)"))
        conn.execute(text(
            "INSERT INTO schedule_batches (id, target_count, target_all) "
            "VALUES (1, 4, 1), (2, 4, 0), (3, 1, 0), (4, 4, 0), (5, 4, 0)"
        ))
        conn.execute(text(
            "INSERT INTO schedules (source_batch_id, source_series_id) VALUES "
            "(1, 'birthday-a'), (1, 'birthday-b'), "
            "(2, 'class-a'), (2, 'class-a'), (2, 'class-a'), (2, 'class-a'), "
            "(3, 'one-person'), "
            "(4, 'course-a'), (4, 'course-a'), (4, 'course-a'), "
            "(5, 'personal-a')"
        ))

        _apply_schedule_batch_all_fix(conn)

        flags = dict(conn.execute(text(
            "SELECT id, target_all FROM schedule_batches"
        )).all())

        # 第二次启动不能再重算：模拟新建批次明确写了 target_all=1，
        # 即使数据看着不像「全班」也不该被历史推断覆盖
        conn.execute(text("UPDATE schedule_batches SET target_all = 1 WHERE id = 1"))
        _apply_schedule_batch_all_fix(conn)
        again = dict(conn.execute(text(
            "SELECT id, target_all FROM schedule_batches"
        )).all())

    assert flags == {1: 0, 2: 1, 3: 0, 4: 1, 5: 0}
    assert again[1] == 1, "标记写入后不应再重算，新建批次的显式标记必须保留"


def test_external_endpoint_rejects_student_accounts(es):
    student = _login_as(es, STUDENT, STUDENT_PW)
    r = student.get(
        "/api/schedules/external",
        params={"start_date": DAY, "end_date": DAY},
    )
    assert r.status_code == 403
