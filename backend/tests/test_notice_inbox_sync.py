"""公告与站内信的已读必须双向同步

    cd backend && python -m pytest tests/test_notice_inbox_sync.py -q

背景：同一条公告有两个入口——公告页和「我的消息」。用户在任意一边点开，
另一边都该跟着消失，不能出现「站内信已读、公告页还挂着红点」。

实现上靠站内信的 topic（notice:<id>）把两边对上；本文件把两个方向都跑一遍。
"""
from types import SimpleNamespace

import httpx
import pytest

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"
STUDENT = "2024000002"
STUDENT_PW = "010002"


@pytest.fixture
def ns(backend):
    b = backend(db="notice_inbox_sync.db", BOOTSTRAP_PASSWORD=PW)
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

    student = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    assert student.post(
        "/api/auth/login", json={"student_no": STUDENT, "password": STUDENT_PW}
    ).status_code == 200
    return SimpleNamespace(b=b, student=student)


def _publish(b, title: str) -> int:
    r = b.client.post("/api/notices", data={
        "title": title, "publish_date": "2026-11-08", "content": "正文",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _message(b, student_no: str, title: str) -> tuple[int, str, str]:
    rows = b.rows(
        "SELECT id, topic, page FROM inbox_messages WHERE student_no = ? AND title = ?",
        student_no, title,
    )
    assert rows, f"没找到站内信：{title}"
    return rows[0]


def _is_read(student, notice_id: int) -> bool:
    items = student.get("/api/notices").json()
    return next(item for item in items if item["id"] == notice_id)["is_read"]


def test_notice_creates_linked_inbox_message(ns):
    nid = _publish(ns.b, "关于期中考试的通知")
    _, topic, page = _message(ns.b, STUDENT, "新通知：关于期中考试的通知")

    assert topic == f"notice:{nid}"
    assert page == f"/notices?id={nid}", "站内信要能直接落到那一篇"
    assert _is_read(ns.student, nid) is False


def test_reading_the_inbox_marks_the_notice_read(ns):
    nid = _publish(ns.b, "关于期中考试的通知")
    mid, _, _ = _message(ns.b, STUDENT, "新通知：关于期中考试的通知")
    assert _is_read(ns.student, nid) is False

    assert ns.student.post(f"/api/inbox/{mid}/read").status_code == 200

    assert _is_read(ns.student, nid) is True
    assert ns.b.rows(
        "SELECT read_at FROM notice_reads WHERE notice_id = ? AND student_no = ?",
        nid, STUDENT,
    )[0][0] is not None


def test_reading_the_notice_marks_the_inbox_message_read(ns):
    nid = _publish(ns.b, "关于期中考试的通知")
    mid, _, _ = _message(ns.b, STUDENT, "新通知：关于期中考试的通知")
    assert ns.b.rows(
        "SELECT read_at FROM inbox_messages WHERE id = ?", mid
    )[0][0] is None

    assert ns.student.post(f"/api/notices/{nid}/read").status_code == 200

    assert ns.b.rows(
        "SELECT read_at FROM inbox_messages WHERE id = ?", mid
    )[0][0] is not None
    assert _is_read(ns.student, nid) is True


def test_read_all_in_inbox_marks_all_linked_notices(ns):
    first = _publish(ns.b, "第一条通知")
    second = _publish(ns.b, "第二条通知")
    assert _is_read(ns.student, first) is False
    assert _is_read(ns.student, second) is False

    assert ns.student.post("/api/inbox/read-all").status_code == 200

    assert _is_read(ns.student, first) is True
    assert _is_read(ns.student, second) is True
    assert ns.student.get("/api/inbox").json()["unread"] == 0


def test_sync_is_scoped_to_the_same_person(ns):
    """只清本人：学生把公告读掉，不该替管理员补一条公告已读"""
    nid = _publish(ns.b, "关于期中考试的通知")
    student_mid, _, _ = _message(ns.b, STUDENT, "新通知：关于期中考试的通知")

    assert ns.student.post(f"/api/inbox/{student_mid}/read").status_code == 200

    assert not ns.b.rows(
        "SELECT read_at FROM notice_reads WHERE notice_id = ? AND student_no = ?",
        nid, ADMIN,
    ), "管理员（发布人）不在这条公告的收件人里，不该凭空多一条已读"
    assert _is_read(ns.student, nid) is True
