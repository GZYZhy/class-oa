"""首页一言：后端代理并缓存 hitokoto，前台不直连外部接口"""

import threading
import time

import requests

from ..config import settings

API_URL = "https://v1.hitokoto.cn/"
TIMEOUT = 3
CACHE_SECONDS = 600

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _empty(enabled: bool = True) -> dict:
    return {"enabled": enabled, "text": "", "from": "", "from_who": ""}


def _categories() -> str:
    return ",".join(
        part.strip() for part in (settings.hitokoto_categories or "").split(",")
        if part.strip()
    )


def _fetch(categories: str) -> dict:
    try:
        params = {"encode": "json", "charset": "utf-8"}
        if categories:
            params["c"] = categories
        resp = requests.get(
            API_URL, params=params, timeout=TIMEOUT,
            headers={"User-Agent": "class-oa/quote"},
        )
        resp.raise_for_status()
        data = resp.json()
        text = str(data.get("hitokoto") or "").strip()
        if not text:
            return _empty()
        return {
            "enabled": True,
            "text": text[:160],
            "from": str(data.get("from") or "")[:60],
            "from_who": str(data.get("from_who") or "")[:40],
        }
    except Exception as exc:
        print(f"[一言] 获取失败：{type(exc).__name__}", flush=True)
        return _empty()


def get_quote() -> dict:
    if not settings.hitokoto_enabled:
        return _empty(False)

    key = _categories() or "*"
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

    quote = _fetch(key if key != "*" else "")
    with _lock:
        _cache[key] = (now + CACHE_SECONDS, quote)
    return quote
