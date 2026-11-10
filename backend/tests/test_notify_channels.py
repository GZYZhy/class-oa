"""通知渠道的细节：Bark 分组名、邮件 HTML 模板

    cd backend && python -m pytest tests/test_notify_channels.py -q
"""
import base64
import json
from urllib.parse import parse_qs, urlparse

from app.config import settings
from app.services import bark_service, email_service, inbox_service
from app.services.email_service import EmailTarget
from app.services.notify_service import _with_read_urls


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"code": 200}'


def test_bark_group_uses_site_name(monkeypatch):
    """Bark 分组用部署站名，不用代码里写死的通用 app_name"""
    monkeypatch.setattr(settings, "site_name", "统1办")
    monkeypatch.setattr(settings, "app_name", "班级信息管理系统")
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr(bark_service.urllib.request, "urlopen", fake_urlopen)
    assert bark_service.push(["device-key"], "标题", "正文") is True
    assert captured["payload"]["group"] == "统1办"
    assert captured["payload"]["icon"] == "https://example.com/logo.png?v=1"


def test_bark_group_falls_back_to_app_name(monkeypatch):
    monkeypatch.setattr(settings, "site_name", "")
    monkeypatch.setattr(settings, "app_name", "班级信息管理系统")
    monkeypatch.setattr(settings, "public_base_url", "")
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr(bark_service.urllib.request, "urlopen", fake_urlopen)
    assert bark_service.push(["device-key"], "标题", "正文") is True
    assert captured["payload"]["group"] == "班级信息管理系统"


def test_email_html_uses_site_theme_and_escapes(monkeypatch):
    monkeypatch.setattr(settings, "site_name", "统1办")
    monkeypatch.setattr(settings, "app_name", "班级信息管理系统")
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")

    html = email_service._body_html(
        "请假已通过", "第一行\n第二行 <script>alert(1)</script>", "/leave"
    )
    assert "统1办" in html
    assert "请假已通过" in html
    assert "第一行<br>第二行 &lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "https://example.com/#/leave" in html
    assert "#5b5bd6" in html
    assert "https://example.com/logo.png?v=1" in html
    assert 'alt="校徽"' in html
    assert "border-radius:50%" in html


def test_email_code_is_highlighted_without_inapp_button(monkeypatch):
    """验证码邮件把 6 位码单独放大，且不显示「在站内查看」按钮"""
    monkeypatch.setattr(settings, "site_name", "统1办")
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    body = "你的登录验证码是 123456，10 分钟内有效。\n\n如果不是你本人操作，请忽略本邮件。"

    html = email_service._body_html("班级信息管理系统登录验证码", body, "/login", code="123456")
    assert "123456" in html
    assert "font-size:30px" in html
    assert "letter-spacing:8px" in html
    assert "10 分钟内有效" in html
    assert "在站内查看" not in html
    assert "https://example.com/logo.png?v=1" in html


def test_email_has_mark_read_button_without_opening_site(monkeypatch):
    """通知邮件多一个「标记为已读」按钮，链接自带令牌、不需要登录"""
    monkeypatch.setattr(settings, "site_name", "统1办")
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    read_url = "https://example.com/api/inbox/read-email?tokens=abc"

    html = email_service._body_html(
        "请假已通过", "你的请假审批通过了。", "/leave", read_url=read_url
    )
    assert "在站内查看" in html
    assert "标记为已读" in html
    assert read_url in html
    assert "不想打开站点" in html

    text = email_service._body_text("正文", "/leave", read_url=read_url)
    assert f"标记为已读：{read_url}" in text


def test_email_logo_uses_unique_open_url(monkeypatch):
    """非重要通知的校徽换成唯一令牌地址，并保持正圆"""
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    open_url = "https://example.com/api/inbox/email-open?tokens=abc"
    html = email_service._body_html(
        "通知", "正文", "/dashboard", open_url=open_url
    )
    assert f'src="{open_url}"' in html
    assert "https://example.com/logo.png?v=1" not in html
    assert "border-radius:50%" in html


def test_verification_code_email_has_no_mark_read_button(monkeypatch):
    """验证码邮件正在登录页用，不该出现站点/已读这类按钮"""
    monkeypatch.setattr(settings, "site_name", "统1办")
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    html = email_service._body_html(
        "登录验证码", "你的登录验证码是 123456，10 分钟内有效。", "/login",
        code="123456", read_url="https://example.com/api/inbox/read-email?tokens=x",
    )
    assert "标记为已读" not in html
    assert "在站内查看" not in html


def test_read_token_round_trip_and_rejects_tampering(monkeypatch):
    monkeypatch.setattr(settings, "session_secret_key", "unit-test-secret")

    token = inbox_service.read_token(42, "2024000001")
    assert inbox_service.parse_read_token(token) == (42, "2024000001")
    assert inbox_service.parse_read_token("not-a-token") is None

    # 改签名里的一个字符。不要用「token 后面接个字符」来测篡改：
    # base64 在不同 Python 版本下对尾部杂字符的宽容度不一样（3.12 会直接忽略），
    # 这种用例会在本机过、CI 红
    raw = base64.urlsafe_b64decode(token).decode()
    payload, sig = raw.rsplit(":", 1)
    bad_sig = ("0" if sig[0] != "0" else "1") + sig[1:]
    tampered = base64.urlsafe_b64encode(f"{payload}:{bad_sig}".encode()).decode()
    assert inbox_service.parse_read_token(tampered) is None


def test_shared_mailbox_gets_all_students_tokens(monkeypatch):
    """一个邮箱被多人共用时，一封邮件要能同时标记所有人的消息"""
    monkeypatch.setattr(settings, "session_secret_key", "unit-test-secret")
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")

    targets = [EmailTarget("family@example.com", ("2024000001", "2024000002"))]
    result = _with_read_urls(targets, {"2024000001": 7, "2024000002": 8})
    assert len(result) == 1

    query = parse_qs(urlparse(result[0].read_url).query)
    tokens = query["tokens"][0].split(",")
    assert {
        inbox_service.parse_read_token(token) for token in tokens
    } == {(7, "2024000001"), (8, "2024000002")}


def test_clean_targets_merges_same_address(monkeypatch):
    """同一地址大小写不同也算同一个人，合并学号但只发一封"""
    merged = email_service._clean_targets([
        EmailTarget("family@example.com", ("2024000001",)),
        EmailTarget("Family@Example.com", ("2024000002",)),
    ])
    assert len(merged) == 1
    assert merged[0].student_nos == ("2024000001", "2024000002")


def test_push_puts_read_link_in_both_parts(monkeypatch):
    """整条发送链路要把已读按钮带进 HTML 和纯文本两个版本"""
    monkeypatch.setattr(email_service, "smtp_enabled", lambda: True)
    captured = {}

    class FakeServer:
        def send_message(self, message):
            captured["message"] = message

        def quit(self):
            pass

    monkeypatch.setattr(email_service, "_connect", lambda timeout=0: FakeServer())
    read_url = "https://example.com/api/inbox/read-email?tokens=abc"
    open_url = "https://example.com/api/inbox/email-open?tokens=abc"

    assert email_service.push(
        [EmailTarget("student@example.com", ("2024000001",), read_url, open_url)],
        "请假已通过", "你的请假审批通过了。", "/leave",
    )
    message = captured["message"]
    parts = {part.get_content_type(): part.get_content() for part in message.iter_parts()}
    assert "标记为已读" in parts["text/html"]
    assert read_url in parts["text/html"]
    assert read_url in parts["text/plain"]
    assert open_url in parts["text/html"], "非重要通知的校徽应使用追踪地址"


def test_important_email_keeps_static_logo(monkeypatch):
    """重要通知不用唯一校徽，避免「打开图片就当读」"""
    monkeypatch.setattr(email_service, "smtp_enabled", lambda: True)
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    captured = {}

    class FakeServer:
        def send_message(self, message):
            captured["message"] = message

        def quit(self):
            pass

    monkeypatch.setattr(email_service, "_connect", lambda timeout=0: FakeServer())
    open_url = "https://example.com/api/inbox/email-open?tokens=abc"
    assert email_service.push(
        [EmailTarget("student@example.com", ("2024000001",), None, open_url)],
        "签到提醒", "还有 10 分钟截止。",
        level="timeSensitive", page="/dashboard",
    )
    html = captured["message"].get_body(("html",)).get_content()
    assert open_url not in html
    assert "https://example.com/logo.png?v=1" in html
