"""空库引导（初始化默认账号）的回归测试

    cd backend && python -m pytest tests -q

只钉「要命」的几条：默认关闭、闸门不许漏、完成即废止、重启不复活、
口令以 env 为唯一事实源、叫 admin 的域外账号不被误伤。
"""

PW = "initpass123"


def test_off_by_default(backend):
    """没配 BOOTSTRAP_PASSWORD：整个功能关闭，一个账号都不建"""
    b = backend(db="off.db")

    assert b.login(password=PW).status_code != 200
    assert b.rows("SELECT count(*) FROM users WHERE is_bootstrap = 1")[0][0] == 0
    # 空库本来就该一个账号都没有 —— 「关闭」得是字面意义上的关闭
    assert b.rows("SELECT count(*) FROM users")[0][0] == 0


def test_empty_library_can_bootstrap(backend):
    """空库 + 配了口令：临时账号能登录，且身份是 is_bootstrap"""
    b = backend(db="empty.db", BOOTSTRAP_PASSWORD=PW)

    r = b.login(password=PW)
    assert r.status_code == 200
    assert r.json()["is_bootstrap"] is True
    # 前端就是靠这个字段决定要不要整屏换成初始化浮层
    assert b.client.get("/api/auth/me").json()["is_bootstrap"] is True


def test_gate_blocks_everything_else(backend):
    """闸门：白名单之外一律 403，且不能靠前缀匹配漏掉删库那条"""
    b = backend(db="gate.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200

    blocked = [
        ("get", "/api/students"),  # 学生名单（白名单里只放行了 POST "" 这一条）
        ("delete", "/api/students/1"),  # 前缀匹配会漏掉它，等于把删库权限给了临时账号
        ("delete", "/api/admin/external-users/whoever"),  # 域外账号那一片全不给
    ]
    for method, path in blocked:
        r = getattr(b.client, method)(path)
        assert r.status_code == 403, f"{method.upper()} {path} 应当被闸门挡住，实际 {r.status_code}"
        assert r.headers.get("x-bootstrap-required"), f"{method.upper()} {path} 少了 X-Bootstrap-Required 头"

    # 白名单里的要放行
    assert b.client.get("/api/setup/state").status_code == 200


def test_finish_then_dead_and_no_revive(backend):
    """完成初始化：临时账号当场废止；重启也不会复活"""
    b = backend(db="flow.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200

    r = b.client.post("/api/students", json={"student_no": "26990000001", "name": "张三"})
    assert r.status_code < 300, r.text
    r = b.client.post("/api/setup/finish", json={"admin_student_no": "26990000001"})
    assert r.status_code == 200 and r.json()["completed"] is True

    # 行没了、会话也失效了
    assert b.rows("SELECT count(*) FROM users WHERE is_bootstrap = 1")[0][0] == 0
    assert b.client.get("/api/setup/state").status_code == 401
    # 临时口令再也进不来；真实管理员已经在库里
    assert b.login(password=PW).status_code != 200
    assert b.rows("SELECT count(*) FROM users WHERE role = 'admin'")[0][0] == 1

    # 重启：不该再建一个临时账号出来
    b2 = backend(db="flow.db", BOOTSTRAP_PASSWORD=PW)
    assert b2.rows("SELECT count(*) FROM users WHERE is_bootstrap = 1")[0][0] == 0
    assert b2.login(password=PW).status_code != 200


def test_password_follows_env(backend):
    """口令以 env 为唯一事实源：改了 env 重启，旧口令立刻作废"""
    b = backend(db="pw.db", BOOTSTRAP_PASSWORD="firstpass1")
    assert b.login(password="firstpass1").status_code == 200
    b.logout()

    b2 = backend(db="pw.db", BOOTSTRAP_PASSWORD="secondpass9")
    assert b2.login(password="firstpass1").status_code != 200
    assert b2.login(password="secondpass9").status_code == 200


def test_external_account_named_admin_is_not_polluted(backend):
    """叫 admin 的域外账号不能被当成初始化账号（判定只认 is_bootstrap 列）"""
    b = backend(db="ext.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200
    # 把临时账号就地改成一个普通的、叫 admin 的班委账号：库里从此没有管理员
    b.run("UPDATE users SET is_bootstrap = 0, role = 'committee' WHERE student_no = 'admin'")
    b.logout()

    # 重启时想建临时账号会发现名字被占用 —— 只能跳过，绝不能把这人改造成临时账号
    b2 = backend(db="ext.db", BOOTSTRAP_PASSWORD=PW)
    r = b2.login(password=PW)
    assert r.status_code == 200
    assert r.json()["is_bootstrap"] is False
    assert b2.rows("SELECT count(*) FROM users WHERE is_bootstrap = 1")[0][0] == 0
    # 他被当成普通班委：闸门不管他
    assert b2.client.get("/api/students").status_code == 200
