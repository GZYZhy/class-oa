"""站内绝对地址的拼接

订阅链接（iCal / RSS）和推送里的跳转都要是**绝对地址**：它们会被存进第三方
（日历 App、RSS 阅读器、手机通知栏），必须在生成的那一刻就点得开，
拿一条 `/api/notices/rss/xxx.xml` 给阅读器是没法用的。

原先这份代码是 api/schedules.py 里的私有函数 `_build_full_url`，只认请求本身；
通知公告要发 RSS 又需要一份，就提到这里共用，顺手把基址修对。
"""

from fastapi import Request

from ..config import settings


def full_url(request: Request, path: str) -> str:
    """把站内路径拼成绝对地址。path 要以 / 开头

    基址按三级回落，先准后用：

    1. `settings.public_base_url` —— 这个配置的语义正是「本站对外的地址」，
       配了就一定是对的（它还得是手机能访问到的公网地址，推送的图标也靠它）。
    2. `X-Forwarded-Proto` / `X-Forwarded-Host` —— 反代给的。**必须看它**：
       nginx 里是 `proxy_set_header Host $host`，而 `$host` 不含端口，
       从 `http://IP:8080` 访问时生成的链接会掉端口，点开就是 404。
       nginx 已经设了 X-Forwarded-Proto，Host 那个头将来加上就自动生效。
    3. `request.url` 本身 —— 直连后端（本地开发、容器内自测）时的正确值。
    """
    base = (settings.public_base_url or "").strip().rstrip("/")
    if not base:
        proto = _first_header(request, "x-forwarded-proto") or request.url.scheme
        # 取不到 X-Forwarded-Host 就用 Host；两个都没有（HTTP/1.0 的裸请求）
        # 才回落到 request.url.netloc
        host = _first_header(request, "x-forwarded-host") or _first_header(request, "host")
        base = f"{proto}://{host or request.url.netloc}"
    return base + path


def _first_header(request: Request, name: str) -> str:
    """取一个头的第一个值

    代链路上同一个头可能被追加成逗号分隔的列表（`https, http`），
    第一个才是客户端真实用的那个。
    """
    return request.headers.get(name, "").split(",")[0].strip()
