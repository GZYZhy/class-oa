"""检查有没有新版本

只做一件事：问一次 GitHub 的 **Git tag**，把「当前版本 / 最新版本」摆给管理员看。
**不下载、不重启、不推送** —— 升级动作仍然是人手动执行
`docker compose pull && docker compose up -d`（见 docs/serve.md「升级与回滚」）。

几条刻意为之的取舍：
  * 只有管理员点「检查更新」才会外呼，普通页面永远不会碰它；
  * **成功结果不缓存**：点一次就真查一次。补丁版本只打 tag、不发 Release，
    以前查 `/releases/latest` 会漏掉它们，还会被 6 小时缓存挡住；
  * 失败缓存 10 分钟，避免管理员连点几次就打出几次超时；
  * Release 只是补充信息：最新 tag 没有对应 Release（补丁版本）时，
    `release_url` / `published_at` 留空，页面显示「小版本无 Release 说明」；
  * 外呼失败**静默**：返回 `error=unreachable`，页面说一句「暂时查不到」，不弹错误、
    不影响任何其它功能（GitHub 在部分校园网下确实连不上）；
  * 版本号解析不出来（本地 dev 构建、或 tag 不是 x.y.z）时 `current_parsed=False`，
    页面显示「开发版」并不做新旧判断 —— 拿字符串硬比会得出「2.10 < 2.9」这种结论。
"""

import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from ..config import settings

# 仓库地址可在 .env 里换（fork 之后仍能用这个功能）
REPO = os.environ.get("UPDATE_CHECK_REPO", "gzyzhy/class-oa").strip() or "gzyzhy/class-oa"
# 测试用：整条 URL 换成指向本地假服务；平时留空走 GitHub API
_CUSTOM_URL = os.environ.get("UPDATE_CHECK_URL", "").strip()
# 查 tag 而不是 releases/latest：补丁版本只打 tag、不发 Release
TAGS_URL = _CUSTOM_URL or f"https://api.github.com/repos/{REPO}/git/matching-refs/tags/v"
RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/tags/{{tag}}"

TIMEOUT = 5
# 成功结果不缓存；失败仍缓存 10 分钟，避免连点几次打几次超时
FAIL_TTL = 10 * 60

# 语义化版本：v2.3.0 / 2.3.0 / 2.3.0-beta.1 都认；2.3 这种缺一段的不认
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "payload": None}


def _ssl_context() -> ssl.SSLContext:
    """HTTPS 用的证书信任链，优先取 certifi 自带的 CA bundle

    为什么需要这一步：macOS 用 python.org 的安装包、Windows 某些发行版、以及没装
    ca-certificates 的精简镜像里，urllib 默认找不到根证书，任何 https 请求都会报
    `CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`。
    requests 会自动用 certifi，urllib 不会 —— 而本项目的外呼（Bark、Turnstile、
    这里）都走 urllib，所以显式指定。

    certifi 由 requests 带进依赖（天气/推送那条线用的），拿不到就退回系统默认；
    Dockerfile 里也显式装了 ca-certificates，两条路都通。

    显式指定 cafile 会盖掉 Python 默认读的 SSL_CERT_FILE，所以这里先看它：
    本机走了抓包代理（Clash 之类）的部署，可以把代理根证书拼进一个 PEM
    并用 SSL_CERT_FILE 指过来，不必去改 certifi 包里的文件。
    """
    custom = os.environ.get("SSL_CERT_FILE", "").strip()
    if custom and os.path.exists(custom):
        return ssl.create_default_context(cafile=custom)
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 - 缺 certifi 就用系统证书，不该因此起不来
        return ssl.create_default_context()


_SSL_CONTEXT = _ssl_context()


def parse_version(text: str) -> tuple[int, int, int] | None:
    """'v2.3.0' → (2, 3, 0)；解析不出来 → None"""
    match = _VERSION_RE.match((text or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新。任一边解析不出来都返回 False（不做判断）"""
    latest_tuple = parse_version(latest)
    current_tuple = parse_version(current)
    if latest_tuple is None or current_tuple is None:
        return False
    return latest_tuple > current_tuple


def _fail(reason: str) -> dict:
    return {
        "current_version": settings.app_version,
        "current_parsed": parse_version(settings.app_version) is not None,
        "latest_version": "",
        "latest_tag": "",
        "published_at": "",
        "release_url": "",
        "update_available": False,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "cached": False,
        "error": reason,
    }


def _get_json(url: str) -> object:
    """GitHub API 要求带 User-Agent，不带直接 403；Accept 固定住 v3 的响应形状"""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"class-oa/{settings.app_version}",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=_SSL_CONTEXT) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _release_of(tag: str) -> dict:
    """这个 tag 对应的 Release，没有就返回空 dict

    补丁版本按约定不发 Release，404 是正常情况，不该当成「查不到新版本」。
    其它错误也不影响 tag 本身的结果，只在日志里留一句。
    """
    try:
        body = _get_json(RELEASE_URL.format(tag=tag))
        return body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            detail = exc.read().decode("utf-8", errors="replace")[:120]
            print(f"[更新检查] Release 查询 HTTP {exc.code}：{detail}", flush=True)
    except Exception as exc:  # noqa: BLE001 - Release 只是补充信息
        print(f"[更新检查] Release 查询失败：{exc!r}", flush=True)
    return {}


def _latest_tag(body: object) -> str:
    """从 GitHub tag 列表里挑最新的语义化版本 tag

    兼容测试用自定义 URL 返回的旧 Release 形状：那样直接取 tag_name。
    """
    if isinstance(body, dict):
        return str(body.get("tag_name") or "").strip()

    tags = []
    for item in body if isinstance(body, list) else []:
        ref = str(item.get("ref") or "")
        tag = ref.rsplit("/", 1)[-1]
        if parse_version(tag):
            tags.append(tag)
    if not tags:
        return ""
    return max(tags, key=lambda tag: parse_version(tag) or (0, 0, 0))


def _fetch() -> dict:
    try:
        body = _get_json(TAGS_URL)
    except urllib.error.HTTPError as exc:
        # 私有仓库/被限流（403）与「网络不通」在看页面上是两回事，但都不该报错弹窗
        detail = exc.read().decode("utf-8", errors="replace")[:120]
        print(f"[更新检查] GitHub 返回 HTTP {exc.code}：{detail}", flush=True)
        return _fail("unreachable")
    except Exception as exc:  # noqa: BLE001 - 网络层任何异常都算「查不到」
        print(f"[更新检查] 请求失败：{exc!r}", flush=True)
        return _fail("unreachable")

    tag = _latest_tag(body)
    if not tag:
        return _fail("unreachable")
    # 自定义 URL 是测试替身：它若直接返回 Release 形状，就用它自己；
    # 真实 GitHub 的 tag 列表则再查一次 Release（可能 404 = 补丁版本）
    release = body if isinstance(body, dict) else (
        {} if _CUSTOM_URL else _release_of(tag)
    )
    latest = tag[1:] if tag.startswith("v") else tag
    current = settings.app_version
    return {
        "current_version": current,
        "current_parsed": parse_version(current) is not None,
        "latest_version": latest,
        "latest_tag": tag,
        "published_at": str(release.get("published_at") or ""),
        "release_url": str(release.get("html_url") or ""),
        "update_available": is_newer(latest, current),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "cached": False,
        "error": "",
    }


def check(force: bool = False) -> dict:
    """返回检查结果；force=True 时忽略缓存

    成功结果**不缓存**：每次点都真查 tag。只有失败结果缓存 10 分钟。
    """
    now = time.time()
    with _lock:
        payload = _cache["payload"]
        if payload is not None and not force and payload.get("error"):
            if now - _cache["at"] < FAIL_TTL:
                return {**payload, "cached": True}

    result = _fetch()
    with _lock:
        _cache["at"] = time.time()
        _cache["payload"] = result
        # 让本次响应里的 cached 保持 False：这是刚查回来的
        return dict(result)


def reset_cache() -> None:
    """测试用：清掉缓存"""
    with _lock:
        _cache["at"] = 0.0
        _cache["payload"] = None
