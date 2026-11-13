"""关联内容的权限、批量分配、重复日程拆分与失效引用回归。"""

from datetime import datetime, timedelta

from test_schedules import b as schedule_backend, as_student, _make_schedule, ROSTER

b = schedule_backend


def seed_content(b):
    b.run(
        "INSERT INTO notices (title,publisher,publish_date,content) VALUES (?,?,?,?)",
        "班会通知",
        "甲",
        "2026-11-13",
        "请按时参加",
    )
    notice_id = b.rows("SELECT id FROM notices WHERE title='班会通知'")[0][0]
    now = datetime.now()
    common = {
        "title": "班会议题",
        "start_at": (now - timedelta(hours=1)).isoformat(),
        "end_at": (now + timedelta(hours=2)).isoformat(),
        "targets": [ROSTER[1][0]],
        "notify_on_start": False,
    }
    poll = b.client.post(
        "/api/polls",
        json={
            **common,
            "questions": [
                {
                    "title": "议题",
                    "multiple": False,
                    "max_choices": 1,
                    "options": ["甲", "乙"],
                }
            ],
        },
    )
    assert poll.status_code == 200, poll.text
    return [
        {"kind": "notice", "id": notice_id},
        {"kind": "vote", "id": poll.json()["id"]},
    ]


def test_related_permissions_status_and_deleted_content(b):
    refs = seed_content(b)
    response = b.client.post(
        "/api/schedules", json=_make_schedule(target_all=True, related_items=refs)
    )
    assert response.status_code == 200, response.text
    schedule = response.json()
    assert schedule["related_items"] == refs
    endpoint = f"/api/schedules/item/{schedule['id']}/related"
    data = b.client.get(endpoint).json()
    assert data[0]["hint"] == "未读"
    assert data[1]["progress"] == "0/1 人已投票"
    assert data[1]["manage_url"]
    for idx in (1, 2):
        client = as_student(b, idx)
        try:
            # 不能通过引用端点读取其他学生的日程。
            assert client.get(endpoint).status_code == 404
            own = client.get(
                "/api/schedules",
                params={"start_date": "2026-10-12", "end_date": "2026-10-12"},
            ).json()[0]
            items = client.get(f"/api/schedules/item/{own['id']}/related").json()
            if idx == 1:
                assert items[1]["hint"] == "待投票"
                assert items[1]["progress"] == ""
                assert not items[1]["manage_url"]
            else:
                assert items[1]["unavailable"]
                assert "url" not in items[1]
                assert items[1]["title"] != "班会议题"
                options = client.get(
                    "/api/schedules/related/options", params={"kind": "vote"}
                ).json()
                assert options["items"] == []
                bad = client.post(
                    "/api/schedules", json=_make_schedule(related_items=[refs[1]])
                )
                assert bad.status_code == 400
        finally:
            client.close()
    b.run("DELETE FROM notices WHERE id=?", refs[0]["id"])
    assert b.client.get(endpoint).json()[0]["unavailable"]
    # 失效引用可以移除，也允许编辑其他字段时原样保留。
    result = b.client.put(
        f"/api/schedules/item/{schedule['id']}",
        params={"instance_date": "2026-10-12", "share": True},
        json={"title": "新标题", "related_items": refs},
    )
    assert result.status_code == 200, result.text
    b.client.delete(
        f"/api/schedules/item/{schedule['id']}", params={"instance_date": "2026-10-12"}
    )
    assert b.client.get(f"/api/polls/{refs[1]['id']}").status_code == 200


def test_related_repeat_split_clear_and_validation(b):
    refs = seed_content(b)
    result = b.client.post(
        "/api/schedules",
        json=_make_schedule(
            related_items=refs, repeat_type="weekly", repeat_end_date="2026-11-02"
        ),
    )
    assert result.status_code == 200, result.text
    schedule_id = result.json()["id"]
    result = b.client.put(
        f"/api/schedules/item/{schedule_id}",
        params={"instance_date": "2026-10-19"},
        json={"scope": "single", "title": "单次班会"},
    )
    assert result.status_code == 200, result.text
    rows = b.client.get(
        "/api/schedules", params={"start_date": "2026-10-12", "end_date": "2026-11-02"}
    ).json()
    assert len(rows) == 4
    assert all(row["related_items"] == refs for row in rows)
    single = next(row for row in rows if row["title"] == "单次班会")
    response = b.client.put(
        f"/api/schedules/item/{single['id']}",
        params={"instance_date": single["instance_date"]},
        json={"related_items": []},
    )
    assert response.status_code == 200, response.text
    assert response.json()["related_items"] == []
    assert b.client.get(f"/api/schedules/item/{single['id']}/related").json() == []
    assert (
        b.client.post(
            "/api/schedules", json=_make_schedule(related_items=[refs[0], refs[0]])
        ).status_code
        == 400
    )
    assert (
        b.client.post(
            "/api/schedules",
            json=_make_schedule(related_items=[{"kind": "notice", "id": 999999}]),
        ).status_code
        == 400
    )
    assert (
        b.client.get(
            "/api/schedules/related/options", params={"kind": "unknown"}
        ).status_code
        == 400
    )


def test_related_collection_checkin_resource_and_personal_progress(b):
    now = datetime.now()
    collection = b.client.post(
        "/api/collections",
        json={
            "title": "会后反馈",
            "start_at": (now - timedelta(hours=1)).isoformat(),
            "end_at": (now + timedelta(hours=2)).isoformat(),
            "targets": [ROSTER[1][0]],
            "submit_quota": 2,
            "notify_on_start": False,
            "questions": [{"title": "意见", "qtype": "short_text", "required": True}],
        },
    )
    assert collection.status_code == 200, collection.text
    checkin = b.client.post(
        "/api/checkins",
        json={
            "title": "班会签到",
            "end_at": (now + timedelta(hours=1)).isoformat(),
            "targets": [ROSTER[1][0]],
            "notify_on_start": False,
        },
    )
    assert checkin.status_code == 200, checkin.text
    b.run(
        "INSERT INTO resources (name,file_name,category,sort_order) VALUES (?,?,?,?)",
        "会议纪要",
        "missing.pdf",
        "班会",
        0,
    )
    resource_id = b.rows("SELECT id FROM resources WHERE name='会议纪要'")[0][0]
    refs = [
        {"kind": "collect", "id": collection.json()["id"]},
        {"kind": "checkin", "id": checkin.json()["id"]},
        {"kind": "resource", "id": resource_id},
    ]
    response = b.client.post(
        "/api/schedules", json=_make_schedule(target_all=True, related_items=refs)
    )
    assert response.status_code == 200, response.text
    items = b.client.get(f"/api/schedules/item/{response.json()['id']}/related").json()
    assert items[0]["progress"] == "0/1 人已填满"
    assert items[0]["scope_warning"]
    assert items[1]["progress"] == "0/1 人已签到"
    assert items[2]["hint"] == "文件暂不可用"
    assert items[2]["url"] is None
    client = as_student(b, 1)
    try:
        own = client.get(
            "/api/schedules",
            params={"start_date": "2026-10-12", "end_date": "2026-10-12"},
        ).json()[0]
        items = client.get(f"/api/schedules/item/{own['id']}/related").json()
        assert items[0]["hint"] == "已提交 0/2 份"
        assert items[0]["progress"] == ""
        assert items[1]["hint"] == "待签到"
        assert items[1]["checkin_id"] is None
        b.run(
            "UPDATE checkin_targets SET signed_at=? WHERE checkin_id=?",
            now.isoformat(),
            refs[1]["id"],
        )
        assert (
            client.get(f"/api/schedules/item/{own['id']}/related").json()[1]["hint"]
            == "已签到"
        )
    finally:
        client.close()


def test_related_existing_sqlite_upgrade(b, backend):
    import sqlite3

    row = b.client.post(
        "/api/schedules", json=_make_schedule(title="升级前日程")
    ).json()
    old_db = b.db.parent / "old-schedules.db"
    with sqlite3.connect(b.db) as source, sqlite3.connect(old_db) as target:
        source.backup(target)
        target.execute("ALTER TABLE schedules DROP COLUMN related_items")
    upgraded = backend(db=old_db.name)
    assert "related_items" in {
        column[1] for column in upgraded.rows("PRAGMA table_info(schedules)")
    }
    assert upgraded.login(ROSTER[0][0], ROSTER[0][2]).status_code == 200
    result = upgraded.client.get(
        f"/api/schedules/item/{row['id']}", params={"instance_date": "2026-10-12"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["title"] == "升级前日程"
    assert result.json()["related_items"] == []


def test_related_external_account_scope(b):
    import httpx

    refs = seed_content(b)
    response = b.client.post(
        "/api/admin/external-users",
        data={
            "login_name": "activity_teacher",
            "display_name": "测试老师",
            "password": "teacher-test-password1",
            "role": "committee",
        },
    )
    assert response.status_code == 200, response.text
    private = b.client.post(
        "/api/schedules", json=_make_schedule(related_items=refs)
    ).json()
    public = b.client.post(
        "/api/schedules", json=_make_schedule(related_items=refs, target_all=True)
    ).json()
    with httpx.Client(base_url=str(b.client.base_url), timeout=10) as client:
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "student_no": "activity_teacher",
                    "password": "teacher-test-password1",
                },
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/schedules/item/{private['id']}/related").status_code
            == 404
        )
        items = client.get(f"/api/schedules/item/{public['id']}/related").json()
        assert items[0]["title"] == "班会通知"
        assert items[1]["unavailable"]
        response = client.post(
            "/api/schedules/external",
            json=_make_schedule(
                related_items=[refs[0]],
                target_student_ids=[
                    b.rows("SELECT id FROM students WHERE student_no=?", ROSTER[1][0])[
                        0
                    ][0]
                ],
            ),
        )
        assert response.status_code == 200, response.text
        assert (
            client.get(f"/api/schedules/item/{response.json()['id']}/related").json()[
                0
            ]["title"]
            == "班会通知"
        )
