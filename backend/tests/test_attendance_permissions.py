"""考勤 / 签到的管理权：管理员或本场发起者

    cd backend && python -m pytest tests/test_attendance_permissions.py -q

口径（与投票、收集对齐）：
- 删除、改某人状态、暂停 / 恢复、延长、提前结束：只给管理员或这场记录发起者；
- 催促、改标题：仍然所有班委都能做（不动考勤结果）；
- 导出与只读明细：不受影响。

测试里让 u1 发起、u2（同为班委但不是发起人）来操作，逐项验 403 / 200。
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"
CREATOR = "2024000002"
CREATOR_PW = "010002"
OTHER = "2024000003"
OTHER_PW = "010003"
PEOPLE = (ADMIN, CREATOR, OTHER)


@pytest.fixture
def ap(backend):
    b = backend(db="attendance_permissions.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200
    for no, name, tail in (
        (ADMIN, "甲", "010001"),
        (CREATOR, "乙", "010002"),
        (OTHER, "丙", "010003"),
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

    # 管理员登录后把两个学生都提成班委
    assert b.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200
    for no in (CREATOR, OTHER):
        r = b.client.put(f"/api/admin/users/{no}/role", json={"role": "committee"})
        assert r.status_code == 200, r.text
    return b


def _as(b, no, password) -> httpx.Client:
    """每个角色一个独立会话：共用一个 client 切登录会把前一个身份的请求带走"""
    client = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = client.post("/api/auth/login", json={"student_no": no, "password": password})
    assert r.status_code == 200, r.text
    return client


def _create_attendance(client) -> dict:
    r = client.post("/api/attendance", json={
        "scope": "全班",
        "records": [
            {"student_no": no, "name": name, "status": "present"}
            for no, name in zip(PEOPLE, ("甲", "乙", "丙"))
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


def _create_checkin(client) -> dict:
    now = datetime.now()
    r = client.post("/api/checkins", json={
        "title": "晚点名",
        "targets": [OTHER],
        "start_at": (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "end_at": (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
        "notify_on_start": False,
        "require_photo": False,
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_non_creator_cannot_write_attendance_but_can_rename_and_export(ap):
    creator = _as(ap, CREATOR, CREATOR_PW)
    record = _create_attendance(creator)

    other = _as(ap, OTHER, OTHER_PW)
    assert other.delete(f"/api/attendance/{record['id']}").status_code == 403
    assert other.patch(
        f"/api/attendance/{record['id']}/items/{PEOPLE[0]}",
        json={"status": "absent"},
    ).status_code == 403

    # 改标题、看明细、导出：不受影响
    assert other.patch(
        f"/api/attendance/{record['id']}", json={"remark": "临时集合"}
    ).status_code == 200
    assert other.get(f"/api/attendance/{record['id']}").status_code == 200
    assert other.get(f"/api/attendance/{record['id']}/export").status_code == 200

    # 发起者本人可以改状态、可以删
    assert creator.patch(
        f"/api/attendance/{record['id']}/items/{PEOPLE[0]}",
        json={"status": "absent"},
    ).status_code == 200
    assert creator.delete(f"/api/attendance/{record['id']}").status_code == 200


def test_non_creator_cannot_manage_checkin_but_can_remind_rename_export(ap):
    creator = _as(ap, CREATOR, CREATOR_PW)
    checkin = _create_checkin(creator)

    other = _as(ap, OTHER, OTHER_PW)
    for action in ("pause", "resume", "extend", "close"):
        r = other.post(f"/api/checkins/{checkin['id']}/{action}")
        assert r.status_code == 403, f"{action}: {r.text}"
    assert other.delete(f"/api/checkins/{checkin['id']}").status_code == 403

    # 催一催、改标题、看详情、导明细：照旧
    assert other.post(f"/api/checkins/{checkin['id']}/remind").status_code == 200
    assert other.patch(
        f"/api/checkins/{checkin['id']}", json={"title": "晚点名（改）"}
    ).status_code == 200
    assert other.get(f"/api/checkins/{checkin['id']}").status_code == 200
    assert other.get(f"/api/attendance/checkin/{checkin['id']}/export").status_code == 200


def test_creator_and_admin_can_still_manage_checkin(ap):
    creator = _as(ap, CREATOR, CREATOR_PW)
    checkin = _create_checkin(creator)

    # 发起者：暂停 → 恢复 → 延长 → 结束
    assert creator.post(f"/api/checkins/{checkin['id']}/pause").status_code == 200
    assert creator.post(f"/api/checkins/{checkin['id']}/resume").status_code == 200
    assert creator.post(f"/api/checkins/{checkin['id']}/extend").status_code == 200
    assert creator.post(f"/api/checkins/{checkin['id']}/close").status_code == 200

    # 管理员：别人发起的也能删
    admin = _as(ap, ADMIN, ADMIN_PW)
    assert admin.delete(f"/api/checkins/{checkin['id']}").status_code == 200


def test_batch_delete_is_all_or_nothing(ap):
    creator = _as(ap, CREATOR, CREATOR_PW)
    first = _create_attendance(creator)["id"]
    second = _create_attendance(creator)["id"]

    other = _as(ap, OTHER, OTHER_PW)
    r = other.post("/api/attendance/batch-delete", json={
        "record_ids": [first, second], "checkin_ids": [],
    })
    assert r.status_code == 403
    # 一条没删：不能「删一半留一半」
    assert ap.rows(
        "SELECT COUNT(*) FROM attendance_records WHERE id IN (?, ?)", first, second
    )[0][0] == 2

    assert creator.post("/api/attendance/batch-delete", json={
        "record_ids": [first, second], "checkin_ids": [],
    }).status_code == 200
    assert ap.rows(
        "SELECT COUNT(*) FROM attendance_records WHERE id IN (?, ?)", first, second
    )[0][0] == 0


def test_checkin_generated_attendance_follows_checkin_creator(ap):
    """结算出来的考勤，发起人仍是签发人：别人删不了，发起人可以"""
    creator = _as(ap, CREATOR, CREATOR_PW)
    checkin = _create_checkin(creator)
    assert creator.post(f"/api/checkins/{checkin['id']}/close").status_code == 200
    record_id = ap.rows(
        "SELECT attendance_record_id FROM checkins WHERE id = ?", checkin["id"]
    )[0][0]
    assert record_id

    other = _as(ap, OTHER, OTHER_PW)
    assert other.delete(f"/api/attendance/{record_id}").status_code == 403

    creator = _as(ap, CREATOR, CREATOR_PW)
    assert creator.delete(f"/api/attendance/{record_id}").status_code == 200
