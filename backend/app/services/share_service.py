"""外链分享的公共拼装：统一路径与 head 片段

外链地址统一为 `/share/{kind}/{token}`（例如 `/share/vote/12.abcd`）。
nginx 对 `/share/` 返回 SPA 的 index.html 并开启 SSI，把这里渲染的 head 片段
在**同一次响应**里注入页面，所以微信爬虫不执行 JS 也能读到这一场的标题和摘要。

新增一种外链类型只需要两步：
1. 在 api/share_meta.py 的 _RESOLVERS 里注册一个 resolver；
2. 在前端 views/share/SharePage.vue 的组件映射里加一项。
nginx、index.html 都不用动 —— 它们只认 `/share/{kind}/{token}` 这个形状。
"""

from dataclasses import dataclass
from html import escape

from ..config import settings
from ..utils.links import full_url


@dataclass(frozen=True)
class ShareMeta:
    """一张分享卡片需要的全部信息

    kind/token 决定真实路径；valid=False 的卡片走统一的失效文案。
    """

    kind: str
    token: str
    title: str
    description: str
    valid: bool = True

    @property
    def path(self) -> str:
        return share_path(self.kind, self.token)


def share_path(kind: str, token: str) -> str:
    """外链（也是应用内路由）的统一路径

    前端的路由是 `/share/:kind/:token`，这里拼的是同名真实路径；
    两处共用这一个形状，前端 utils/share.js 里有一份对应的拼法。
    """
    return f"/share/{kind}/{token}"


def _one_line(value: str) -> str:
    """压成一行：换行、制表符和连续空格都折叠掉

    meta 的 content 属性里出现换行虽然合法，但会让卡片摘要断得莫名其妙；
    标题里更不该带换行。
    """
    return " ".join(str(value or "").split())


def _esc(value: str) -> str:
    """HTML 属性转义。所有动态值都必须过这里"""
    return escape(_one_line(value), quote=True)


def render_meta_html(request, meta: ShareMeta | None) -> str:
    """把 meta 渲染成一段可以直接插进 <head> 的 HTML

    **永远不要抛异常**：nginx 的 SSI include 会把非 200 响应（或错误页正文）
    原样插进 <head>。meta 为 None 或已失效时返回统一的失效卡片。
    """
    site_name = settings.site_name or settings.app_name
    logo_url = full_url(request, "/icons/icon-512.png")

    if meta is None or not meta.valid:
        title = f"链接已失效 - {site_name}" if site_name else "链接已失效"
        description = "分享链接无效或已失效，请向发布人重新要一次"
        url = full_url(request, "/")
        robots = "noindex, nofollow"
    else:
        title = _one_line(meta.title) or site_name
        description = _one_line(meta.description) or site_name
        url = full_url(request, meta.path)
        robots = "index,follow"

    title_attr = _esc(title)
    description_attr = _esc(description)
    url_attr = _esc(url)
    site_attr = _esc(site_name)
    logo_attr = _esc(logo_url)

    return (
        f"<title>{title_attr}</title>"
        f'<meta name="description" content="{description_attr}">'
        f'<meta name="robots" content="{robots}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{title_attr}">'
        f'<meta property="og:description" content="{description_attr}">'
        f'<meta property="og:url" content="{url_attr}">'
        f'<meta property="og:site_name" content="{site_attr}">'
        f'<meta property="og:image" content="{logo_attr}">'
        f'<meta property="og:image:width" content="512">'
        f'<meta property="og:image:height" content="512">'
        f'<meta property="og:locale" content="zh_CN">'
        f'<meta name="twitter:card" content="summary">'
        f'<meta name="twitter:title" content="{title_attr}">'
        f'<meta name="twitter:description" content="{description_attr}">'
        f'<meta name="twitter:image" content="{logo_attr}">'
    )
