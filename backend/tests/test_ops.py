"""运维页：运行时配置 + 检查更新

    cd backend && python -m pytest tests/test_ops.py -q

运行时配置是「存数据库、改了立刻生效」的那一层：管理员在
「系统管理 → 运维」里改 SMTP / Turnstile / 封禁阈值 / 办件文档信息，
不用再登服务器改 .env 重启。机密与安全边界仍然只认环境变量（见 ENV_ONLY）。
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

PW = "initpass123"
ADMIN_NO = "2024000001"
STUDENT_NO = "2024000002"


@pytest.fixture
def b(backend):
    """初始化完毕、管理员已登录，且 SMTP / Turnstile 都是「没配」的后端

    显式置空是为了隔离：仓库根目录的 .env 里可能配着真实发信账号，
    不置空的话「保存后 source 变成 database」这类断言会被环境变量干扰。
    """
    inst = backend(
        db="ops.db",
        BOOTSTRAP_PASSWORD=PW,
        SMTP_HOST="", SMTP_PORT="0", SMTP_SECURITY="ssl",
        SMTP_USER="", SMTP_PASSWORD="", SMTP_FROM="",
        TURNSTILE_SITE_KEY="", TURNSTILE_SECRET_KEY="",
        LOGIN_BAN_THRESHOLD="20", LOGIN_FAIL_WINDOW_MINUTES="10", LOGIN_BAN_MINUTES="60",
    )
    assert inst.login(password=PW).status_code == 200
    r = inst.client.post("/api/students", json={
        "student_no": ADMIN_NO, "name": "管理员",
        "id_card": "110101200601010001",
    })
    assert r.status_code == 200, r.text
    r = inst.client.post("/api/setup/finish", json={"admin_student_no": ADMIN_NO})
    assert r.status_code == 200, r.text
    inst.logout()
    assert inst.login(ADMIN_NO, "010001").status_code == 200
    return inst


def _config(b):
    r = b.client.get("/api/admin/ops/config")
    assert r.status_code == 200, r.text
    return r.json()


def _save(b, values):
    return b.client.put("/api/admin/ops/config", json={"values": values})


def _field(b, key):
    return next(item for item in _config(b)["fields"] if item["key"] == key)


def test_snapshot_lists_every_field_and_env_only_items(b):
    data = _config(b)

    assert data["groups"][0] == "站点与链接"
    keys = {field["key"] for field in data["fields"]}
    assert {"smtp_host", "smtp_password", "turnstile_site_key", "login_ban_threshold",
            "ev_pass_grade"} <= keys
    assert all(field["source"] in ("database", "environment", "default")
               for field in data["fields"])
    assert data["env_only"], "机密与安全边界项要以只读清单展示"
    assert data["version"]["app_version"]


def test_saving_takes_effect_without_restart(b):
    """保存 SMTP 与 Turnstile 之后，登录页 / 我的信息立刻反映出来"""
    before = b.client.get("/api/auth/captcha-required").json()
    assert before["mode"] == "math"

    r = _save(b, {
        "smtp_host": "smtp.example.com",
        "smtp_port": "465",
        "smtp_security": "ssl",
        "smtp_user": "oa@example.com",
        "smtp_password": "auth-code",
        "smtp_from": "oa@example.com",
        "turnstile_site_key": "site-key-1",
        "turnstile_secret_key": "secret-key-1",
    })
    assert r.status_code == 200, r.text
    assert set(r.json()["changed"]) >= {"smtp_host", "smtp_port", "smtp_password"}

    # 密文项在接口里打码，其它项原样回显，来源标记为 database
    assert _field(b, "smtp_password")["value"] == "********"
    assert _field(b, "smtp_host")["value"] == "smtp.example.com"
    assert _field(b, "smtp_host")["source"] == "database"

    # 生效：SMTP 配齐了 → /api/auth/me 的 smtp_enabled 变 true
    me = b.client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["smtp_enabled"] is True

    # 生效：Turnstile 两个 key 都配了 → 登录页改用 Turnstile
    after = b.client.get("/api/auth/captcha-required").json()
    assert after["mode"] == "turnstile"
    assert after["site_key"] == "site-key-1"


def test_bad_values_are_rejected_and_nothing_is_saved(b):
    assert _save(b, {"smtp_port": "abc"}).status_code == 400
    assert _save(b, {"smtp_security": "plain"}).status_code == 400
    assert _save(b, {"login_ban_threshold": "-1"}).status_code == 400
    assert _save(b, {"bark_server": "api.day.app"}).status_code == 400
    assert _save(b, {"not_a_setting": "x"}).status_code == 400

    assert _field(b, "smtp_port")["source"] == "environment", "校验失败时一项都不该落库"
    assert b.rows("SELECT COUNT(*) FROM runtime_settings")[0][0] == 0


def test_secret_mask_means_no_change(b):
    assert _save(b, {"smtp_password": "first-code"}).status_code == 200
    # 页面把打码值原样提交回来：代表「不改」，不能把密码改成 ********
    assert _save(b, {"smtp_password": "********"}).status_code == 200
    rows = b.rows("SELECT value FROM runtime_settings WHERE key = 'smtp_password'")
    assert rows[0][0] == "first-code"


def test_clearing_falls_back_to_env(b):
    assert _save(b, {"login_ban_threshold": "5"}).status_code == 200
    assert _field(b, "login_ban_threshold")["value"] == "5"

    assert _save(b, {"login_ban_threshold": ""}).status_code == 200
    assert _field(b, "login_ban_threshold")["source"] == "environment"
    assert _field(b, "login_ban_threshold")["value"] == "20", "回落到 .env / 代码默认值"
    assert b.rows("SELECT COUNT(*) FROM runtime_settings WHERE key = 'login_ban_threshold'")[0][0] == 0


def test_saving_is_logged(b):
    assert _save(b, {"ev_pass_grade": "示例专业2027级"}).status_code == 200
    action, detail = b.rows(
        "SELECT action, detail FROM operation_logs ORDER BY id DESC LIMIT 1"
    )[0]
    assert action == "修改运维配置"
    assert "专业年级" in detail


def test_student_cannot_read_or_save(b):
    r = b.client.post("/api/students", json={
        "student_no": STUDENT_NO, "name": "张三",
        "id_card": "110101200602020002",
    })
    assert r.status_code == 200, r.text
    b.logout()
    assert b.login(STUDENT_NO, "020002").status_code == 200

    assert b.client.get("/api/admin/ops/config").status_code == 403
    assert _save(b, {"smtp_host": "x.example.com"}).status_code == 403
    assert b.client.get("/api/admin/update-check").status_code == 403


# ---------------- 检查更新 ----------------


class _ReleaseHandler(BaseHTTPRequestHandler):
    """一个假的 GitHub Releases 接口"""

    hits = 0
    tag = "v9.9.9"

    def do_GET(self):  # noqa: N802 - http.server 的约定
        type(self).hits += 1
        body = json.dumps({
            "tag_name": type(self).tag,
            "published_at": "2026-10-20T08:00:00Z",
            "html_url": "https://example.com/releases/tag/v9.9.9",
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def release_url():
    _ReleaseHandler.hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ReleaseHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/releases/latest"
    finally:
        server.shutdown()


def _admin(backend, db, **env):
    inst = backend(db=db, BOOTSTRAP_PASSWORD=PW, **env)
    assert inst.login(password=PW).status_code == 200
    r = inst.client.post("/api/students", json={
        "student_no": ADMIN_NO, "name": "管理员",
        "id_card": "110101200601010001",
    })
    assert r.status_code == 200, r.text
    assert inst.client.post(
        "/api/setup/finish", json={"admin_student_no": ADMIN_NO}
    ).status_code == 200
    inst.logout()
    assert inst.login(ADMIN_NO, "010001").status_code == 200
    return inst


def test_update_check_reports_newer_release_and_caches(backend, release_url):
    b = _admin(backend, "ops-update.db", UPDATE_CHECK_URL=release_url)

    first = b.client.get("/api/admin/update-check")
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["error"] == ""
    assert data["latest_version"] == "9.9.9"
    assert data["latest_tag"] == "v9.9.9"
    assert data["update_available"] is True
    assert data["release_url"].startswith("https://example.com/")
    assert data["published_at"]
    assert data["cached"] is False

    # 再点一次：吃缓存，不再打外部接口
    second = b.client.get("/api/admin/update-check").json()
    assert second["cached"] is True
    assert _ReleaseHandler.hits == 1


def test_update_check_is_silent_when_unreachable(backend):
    """连不上 GitHub 时给 200 + error，不弹错误、不影响页面其它部分"""
    b = _admin(backend, "ops-update-down.db", UPDATE_CHECK_URL="http://127.0.0.1:1/latest")

    r = b.client.get("/api/admin/update-check")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["error"] == "unreachable"
    assert data["update_available"] is False
    assert data["current_version"]


def test_version_comparison_is_semantic():
    from app.services.update_service import is_newer, parse_version

    assert parse_version("v2.3.0") == (2, 3, 0)
    assert parse_version("2.3.0") == (2, 3, 0)
    assert parse_version("2.3.0-beta.1") == (2, 3, 0)
    assert parse_version("2.3") is None
    assert parse_version("dev") is None

    # 字符串比较会得出 2.10 < 2.9，这里必须按数字比
    assert is_newer("2.10.0", "2.9.0") is True
    assert is_newer("2.9.0", "2.10.0") is False
    assert is_newer("2.3.0", "2.3.0") is False
    assert is_newer("2.3.0", "dev") is False, "解析不出来时不做判断"
