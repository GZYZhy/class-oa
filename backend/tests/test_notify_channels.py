"""通知渠道的细节：Bark 分组名、邮件 HTML 模板

    cd backend && python -m pytest tests/test_notify_channels.py -q
"""
import json

from app.config import settings
from app.services import bark_service, email_service


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
