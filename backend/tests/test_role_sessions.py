"""修改角色后，该账号所有已登录设备立即下线

    cd backend && python -m pytest tests/test_role_sessions.py -q

权限变了还让旧会话带着旧角色继续用，是最容易漏的一处：页面上改了角色，
本人那台手机可能还停在旧页面里，直到下次刷新才失效。
"""

import httpx

PW = "initpass123"
ADMIN = "2024000001"
STUDENT = "2024000002"


def test_role_change_revokes_existing_sessions(backend):
    b = backend(db="role-sessions.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200
    for no, name, tail in ((ADMIN, "管理员", "0001"), (STUDENT, "学生", "0002")):
        r = b.client.post("/api/students", json={
            "student_no": no, "name": name,
            "id_card": f"11010120060101{tail}",
        })
        assert r.status_code == 200, r.text
    assert b.client.post(
        "/api/setup/finish", json={"admin_student_no": ADMIN}
    ).status_code == 200

    # 目标同学先在自己设备上登录
    student = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = student.post(
        "/api/auth/login", json={"student_no": STUDENT, "password": "010002"}
    )
    assert r.status_code == 200, r.text
    assert student.get("/api/auth/me").status_code == 200

    # 管理员改角色：旧设备下一次请求就该 401
    b.logout()
    assert b.login(student_no=ADMIN, password="010001").status_code == 200
    r = b.client.put(f"/api/admin/users/{STUDENT}/role", json={"role": "committee"})
    assert r.status_code == 200, r.text
    assert "已下线" in r.json()["message"]
    assert student.get("/api/auth/me").status_code == 401

    # 重新登录后拿到的是新角色
    r = student.post(
        "/api/auth/login", json={"student_no": STUDENT, "password": "010002"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "committee"
    student.close()


def test_freeze_revokes_sessions_even_after_unfreeze(backend):
    """冻结立即下线所有设备；解冻后旧 cookie 也不能复活"""
    b = backend(db="freeze-sessions.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200
    for no, name, tail in ((ADMIN, "管理员", "0001"), (STUDENT, "学生", "0002")):
        assert b.client.post("/api/students", json={
            "student_no": no, "name": name,
            "id_card": f"11010120060101{tail}",
        }).status_code == 200
    assert b.client.post(
        "/api/setup/finish", json={"admin_student_no": ADMIN}
    ).status_code == 200

    student = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    assert student.post(
        "/api/auth/login", json={"student_no": STUDENT, "password": "010002"}
    ).status_code == 200
    assert student.get("/api/auth/me").status_code == 200

    b.logout()
    assert b.login(student_no=ADMIN, password="010001").status_code == 200
    r = b.client.post(f"/api/admin/users/{STUDENT}/freeze")
    assert r.status_code == 200, r.text
    assert "已下线" in r.json()["message"]
    assert student.get("/api/auth/me").status_code == 401

    # 解冻只恢复登录能力，不会让冻结前那张 cookie 复活
    assert b.client.post(f"/api/admin/users/{STUDENT}/unfreeze").status_code == 200
    assert student.get("/api/auth/me").status_code == 401

    r = student.post(
        "/api/auth/login", json={"student_no": STUDENT, "password": "010002"}
    )
    assert r.status_code == 200, r.text
    student.close()
