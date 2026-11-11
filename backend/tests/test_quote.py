"""首页一言：关闭、成功缓存、失败降级"""
from app.config import settings
from app.services import quote_service


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_disabled_does_not_call(monkeypatch):
    monkeypatch.setattr(settings, "hitokoto_enabled", False)
    called = []
    monkeypatch.setattr(quote_service.requests, "get", lambda *a, **k: called.append(1))
    assert quote_service.get_quote()["enabled"] is False
    assert called == []


def test_success_is_cached(monkeypatch):
    monkeypatch.setattr(settings, "hitokoto_enabled", True)
    monkeypatch.setattr(settings, "hitokoto_categories", "d,i")
    quote_service._cache.clear()
    calls = []

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append(params)
        return _Resp({"hitokoto": "人间烟火气，最抚凡人心。", "from": "出处", "from_who": "某人"})

    monkeypatch.setattr(quote_service.requests, "get", fake_get)
    first = quote_service.get_quote()
    second = quote_service.get_quote()

    assert first["text"] == "人间烟火气，最抚凡人心。"
    assert first["from_who"] == "某人"
    assert second == first
    assert len(calls) == 1, "同一分类十分钟内只请求一次"
    assert calls[0]["c"] == ["d", "i"], "多分类必须重复传参，不能拼成 d,i"


def test_failure_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(settings, "hitokoto_enabled", True)
    monkeypatch.setattr(settings, "hitokoto_categories", "")
    quote_service._cache.clear()
    monkeypatch.setattr(
        quote_service.requests, "get",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    quote = quote_service.get_quote()
    assert quote == {"enabled": True, "text": "", "from": "", "from_who": ""}
