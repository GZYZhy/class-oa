"""考勤明细弹窗里的「导出明细」：一次点名 / 一次签到各导一张表

    cd backend && python -m pytest tests/test_detail_export.py -q

和列表页的 `/attendance/export` 区分开：那个一次导一批、两个页签；
这里导的是当前打开的那一场，抬头带摘要（日期、范围、应到实到），
下面逐人明细，打开就能直接发出去。

断言三件事：
1. 内容确实落在「点名明细 / 签到明细」这张单页签里；
2. 抬头和逐人数据都在（签到还要有距离、出勤状态）；
3. 普通学生拿不到（班委及以上才可导）。
"""
from datetime import datetime, timedelta
from io import BytesIO

import httpx
import pytest
from openpyxl import load_workbook

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"
STUDENT = "2024000002"
STUDENT_PW = "010002"


@pytest.fixture
def dx(backend):
    b = backend(db="detail_export.db", BOOTSTRAP_PASSWORD=PW)
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
    return b


def _as_student(b) -> httpx.Client:
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": STUDENT, "password": STUDENT_PW})
    assert r.status_code == 200, r.text
    return c


def _sheet_rows(content: bytes, sheet: str) -> tuple[object, list[list]]:
    wb = load_workbook(BytesIO(content))
    assert sheet in wb.sheetnames, wb.sheetnames
    ws = wb[sheet]
    return ws, [[cell.value for cell in row] for row in ws.iter_rows()]


def test_attendance_detail_export_has_header_and_people(dx):
    r = dx.client.post("/api/attendance", json={
        "scope": "全班",
        "records": [
            {"student_no": ADMIN, "name": "甲", "status": "present"},
            {"student_no": STUDENT, "name": "乙", "status": "absent"},
        ],
    })
    assert r.status_code == 200, r.text
    record_id = r.json()["id"]

    r = dx.client.get(f"/api/attendance/{record_id}/export")
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]

    ws, rows = _sheet_rows(r.content, "点名明细")
    assert "点名明细" in str(ws["A1"].value)
    # 抬头摘要里要有应到/实到和无应答人数
    meta = " ".join(str(cell) for row in rows[:4] for cell in row if cell)
    assert "应到 2 人" in meta and "无应答 1 人" in meta

    header = next(row for row in rows if row[0] == "学号")
    assert header[:3] == ["学号", "姓名", "状态"]
    assert any(
        row[0] == STUDENT and row[2] == "无应答" for row in rows if row[0]
    ), rows


def test_checkin_detail_export_has_distance_and_status(dx):
    r = dx.client.post("/api/checkins", json={
        "title": "晚点名",
        "remark": "",
        "targets": [STUDENT],
        "start_at": (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S"),
        "end_at": (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
        "notify_on_start": False,
        "require_photo": False,
    })
    assert r.status_code == 200, r.text
    checkin = r.json()
    cid, code = checkin["id"], checkin["code"]

    student = _as_student(dx)
    try:
        assert student.post(
            f"/api/checkins/public/{code}/sign", data={"source": "test"}
        ).status_code == 200
    finally:
        student.close()

    r = dx.client.get(f"/api/attendance/checkin/{cid}/export")
    assert r.status_code == 200, r.text
    ws, rows = _sheet_rows(r.content, "签到明细")
    assert "签到明细" in str(ws["A1"].value)

    header = next(row for row in rows if row[0] == "学号")
    assert header[:7] == [
        "学号", "姓名", "签到状态", "签到时间", "距离(米)", "出勤状态", "照片",
    ]
    line = next(row for row in rows if row[0] == STUDENT)
    assert line[2] == "已签到"
    assert line[3], "签到时间要写进表里"


def test_students_cannot_export_details(dx):
    r = dx.client.post("/api/attendance", json={
        "scope": "全班",
        "records": [{"student_no": STUDENT, "name": "乙", "status": "present"}],
    })
    record_id = r.json()["id"]

    c = dx.client.post("/api/checkins", json={
        "title": "点名",
        "targets": [STUDENT],
        "end_at": (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
        "notify_on_start": False,
    })
    checkin_id = c.json()["id"]

    student = _as_student(dx)
    try:
        assert student.get(f"/api/attendance/{record_id}/export").status_code == 403
        assert student.get(
            f"/api/attendance/checkin/{checkin_id}/export"
        ).status_code == 403
    finally:
        student.close()
