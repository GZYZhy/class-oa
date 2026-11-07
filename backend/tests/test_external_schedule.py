"""域外账号的日程：只读共享日程；班委/管理员可分配

    cd backend && python -m pytest tests/test_external_schedule.py -q

口径（用户拍板）：
- 域外账号没有自己的日程表，只能看到「分配给所有人」的批次 + 自己创建的批次；
- 等效学生（role=student）不能建/改/删，连格子都点不出表单；
- 班委/管理员可以分配新日程，下发对象固定为全体学生，建完自己也看得见。

测试里直接走接口建批次、切账号登录，最后用域外入口读结果。
"""
from types import SimpleNamespace

import httpx
import pytest

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
    r = client.get(
        "/api/schedules/external",
        params={"start_date": DAY, "end_date": DAY},
    )
    assert r.status_code == 200, r.text
    return r.json()


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


def test_external_endpoint_rejects_student_accounts(es):
    student = _login_as(es, STUDENT, STUDENT_PW)
    r = student.get(
        "/api/schedules/external",
        params={"start_date": DAY, "end_date": DAY},
    )
    assert r.status_code == 403
