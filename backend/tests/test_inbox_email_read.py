"""邮件里的「标记为已读」链接：不登录也能清掉对应的站内未读

    cd backend && python -m pytest tests/test_inbox_email_read.py -q

链接里的令牌由 inbox_service 用站点密钥签名，绑定了消息 id 和学号；
接口本身不要求登录，所以这里全程不调 /api/auth/login。
"""
from app.services import inbox_service

_INSERT = (
    "INSERT INTO inbox_messages (student_no, title, body, level, created_at, read_at) "
    "VALUES (?, ?, '正文', 'active', '2026-11-07 08:00:00', NULL)"
)


def add_message(b, student_no: str, title: str) -> int:
    b.run(_INSERT, student_no, title)
    return b.rows(
        "SELECT id FROM inbox_messages WHERE student_no = ? AND title = ?"
        " ORDER BY id DESC LIMIT 1", student_no, title
    )[0][0]


def read_at(b, message_id: int):
    return b.rows(
        "SELECT read_at FROM inbox_messages WHERE id = ?", message_id
    )[0][0]


def test_email_link_marks_message_read_without_login(backend):
    b = backend(db="email_read.db")
    message_id = add_message(b, "2024000001", "邮件里的通知")
    token = inbox_service.read_token(message_id, "2024000001")

    r = b.client.get("/api/inbox/read-email", params={"tokens": token})
    assert r.status_code == 200, r.text
    assert "已标记为已读" in r.text
    assert read_at(b, message_id) is not None

    # 再点一次也没关系：已经读过的不改时间，页面照样说已读
    again = b.client.get("/api/inbox/read-email", params={"tokens": token})
    assert again.status_code == 200


def test_one_link_can_clear_a_shared_mailbox(backend):
    """共用邮箱：一封邮件里带多个人的令牌，逐个标记"""
    b = backend(db="email_read_shared.db")
    first = add_message(b, "2024000001", "共用邮箱的通知")
    second = add_message(b, "2024000002", "共用邮箱的通知")
    tokens = ",".join([
        inbox_service.read_token(first, "2024000001"),
        inbox_service.read_token(second, "2024000002"),
    ])

    r = b.client.get("/api/inbox/read-email", params={"tokens": tokens})
    assert r.status_code == 200, r.text
    assert "共 2 条" in r.text
    assert read_at(b, first) is not None
    assert read_at(b, second) is not None


def test_invalid_link_marks_nothing(backend):
    b = backend(db="email_read_bad.db")
    message_id = add_message(b, "2024000001", "不该被标记的通知")
    good = inbox_service.read_token(message_id, "2024000001")

    for bad in ("not-a-token", good + "x", ""):
        r = b.client.get("/api/inbox/read-email", params={"tokens": bad})
        assert r.status_code == 400, r.text
        assert read_at(b, message_id) is None


def test_logo_load_marks_message_read(backend):
    """非重要通知的校徽地址被加载：返回图片并标记已读，不需要登录"""
    b = backend(db="email_open.db")
    message_id = add_message(b, "2024000001", "邮件校徽通知")
    token = inbox_service.read_token(message_id, "2024000001")

    r = b.client.get("/api/inbox/email-open", params={"tokens": token})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/gif")
    assert read_at(b, message_id) is not None


def test_logo_load_redirects_to_static_logo_when_configured(backend):
    b = backend(db="email_open_redirect.db", PUBLIC_BASE_URL="https://example.com")
    message_id = add_message(b, "2024000001", "邮件校徽通知")
    token = inbox_service.read_token(message_id, "2024000001")

    r = b.client.get(
        "/api/inbox/email-open", params={"tokens": token}, follow_redirects=False
    )
    assert r.status_code == 302, r.text
    assert r.headers["location"] == "https://example.com/logo.png?v=1"
    assert read_at(b, message_id) is not None


def test_logo_load_can_be_disabled_in_ops(backend):
    """后台关掉后，旧邮件里的校徽地址再被加载也不标记"""
    b = backend(db="email_open_off.db", EMAIL_OPEN_AUTO_READ="0")
    message_id = add_message(b, "2024000001", "不该自动已读")
    token = inbox_service.read_token(message_id, "2024000001")

    r = b.client.get("/api/inbox/email-open", params={"tokens": token})
    assert r.status_code == 200, r.text
    assert read_at(b, message_id) is None


def test_invalid_logo_token_still_returns_image(backend):
    """坏令牌不能让邮箱里出现破图，也不能标记任何消息"""
    b = backend(db="email_open_bad.db")
    message_id = add_message(b, "2024000001", "不该被标记")
    good = inbox_service.read_token(message_id, "2024000001")

    for bad in ("bad", good + "x", ""):
        r = b.client.get("/api/inbox/email-open", params={"tokens": bad})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/gif")
        assert read_at(b, message_id) is None
