"""通知公告 RSS 2.0 订阅生成

比 iCal 那套简单：没有重复规则、没有时区换算、没有折行要求。RSS 是 XML，
转义和格式都有标准库可用，这里只管把字段填对。

纯函数风格（同 schedule_ical_service）：通知由调用方查好传进来，这里不碰数据库。
"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape, quoteattr

from ..utils.notify_text import clip, markdown_to_text
from ..models import Notice

# 一次最多出多少条。班级规模的通知总量不大，但断断续续发几年也会攒到几百条，
# 全塞进一个 feed 会让阅读器每次拉几百 KB。超出的是最旧的那些，直接不出。
MAX_ITEMS = 50

# 条目摘要的长度上限
SUMMARY_LIMIT = 200

# 固定 +0800。publish_date 是用户在页面上填的「发布时间」，本来就是北京时间
# （库里存的是本地墙上时间，容器 TZ=Asia/Shanghai）。写成 UTC 的话阅读器
# 会把 00:00 显示成前一天 16:00。
CST = timezone(timedelta(hours=8))

# XML 1.0 里非法的字符：除了 \t \n \r 之外的全部 C0 控制字符，外加 DEL。
# 从 Word / 微信里粘一段带 \x0b（软换行）的正文太常见了，而 xml.sax.saxutils.escape
# 对它们**完全不起作用** —— 一个这样的字符就能让**整份** feed 解析失败
# （不是那一条坏掉，是整个文档不是 well-formed）。
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def generate_rss(
    notices: list[Notice],
    site_url: str,
    feed_url: str,
    site_name: str,
) -> str:
    """生成 RSS 2.0 文档

    site_url：站点根地址，允许带尾斜杠
    feed_url：这个 feed 自己的绝对地址（atom:link rel="self"）
    site_name：频道名里用的站点名
    """
    site_url = _xml_clean(site_url).rstrip("/")
    feed_url = _xml_clean(feed_url)
    name = _xml_clean(site_name) or "通知公告"

    lines = ['<?xml version="1.0" encoding="utf-8"?>']
    # xmlns:atom 必须在这里声明：下面用了 atom: 前缀，不声明的话前缀没有绑定，
    # 整份 XML 连 well-formed 都不是（阅读器直接判为坏源）
    lines.append('<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">')
    lines.append("<channel>")
    lines.append(f"<title>{escape('通知公告 - ' + name)}</title>")
    # channel 的 title / link / description **三个都是 RSS 2.0 的必填项**，少了
    # description 严格校验的阅读器会整源拒收。
    # 注意链接是 hash 路由（前端用 createWebHashHistory），拼成 /notices?id=1
    # 会被后端 try_files 兜到 index.html、再被 hash 路由当成根路径跳去 /dashboard。
    lines.append(f"<link>{escape(site_url + '/#/notices')}</link>")
    lines.append(f"<description>{escape(name + '的通知公告')}</description>")
    lines.append("<language>zh-CN</language>")
    # 属性值必须用 quoteattr（escape 不转引号，值里有一个 " 整个属性就断了）
    lines.append(
        f"<atom:link href={quoteattr(feed_url)} rel=\"self\" type=\"application/rss+xml\"/>"
    )
    lines.append("<ttl>60</ttl>")

    # lastBuildDate 取**最新一条的发布时间**，不用 now()：用 now() 的话每次抓取
    # 这个时间都在变，阅读器会以为源一直在更新、白白重拉。
    dates = [n.publish_date for n in notices if n.publish_date]
    if dates:
        lines.append(f"<lastBuildDate>{_rfc822(max(dates))}</lastBuildDate>")

    for notice in notices:
        lines.append("<item>")
        lines.append(f"<title>{escape(_xml_clean(notice.title or ''))}</title>")
        lines.append(f"<link>{escape(f'{site_url}/#/notices?id={notice.id}')}</link>")
        # guid 用 id + 域名后缀，isPermaLink=false（它不是个能点的地址）。
        # **这个构成今后永远别改** —— 改了等于给所有订阅者把全部通知重推一遍
        lines.append(f'<guid isPermaLink="false">notice-{notice.id}@class-oa</guid>')
        if notice.publish_date:
            lines.append(f"<pubDate>{_rfc822(notice.publish_date)}</pubDate>")
        lines.append(f"<description>{escape(_summary(notice, site_url))}</description>")
        lines.append("</item>")

    lines.append("</channel>")
    lines.append("</rss>")
    return "\n".join(lines) + "\n"


def _summary(notice: Notice, site_url: str) -> str:
    """条目摘要：正文摘一句 + 附件链接

    不渲染 Markdown 全文 —— 后端没有这个能力，也不该为了 RSS 引一个 markdown
    库（前端那套 marked + DOMPurify 才是渲染的地方）。想看全文点条目链接回站内。
    """
    text = clip(markdown_to_text(notice.content or ""), SUMMARY_LIMIT)
    links = []
    for index, item in enumerate(_attachments(notice)):
        label = (item.get("name") or item.get("file") or f"附件 {index + 1}").strip()
        links.append(f"{label}：{site_url}/api/notices/{notice.id}/attachments/{index}")
    if links:
        joined = "；".join(links)
        text = f"{text}（附件：{joined}）" if text else f"附件：{joined}"
    return text or "点击查看详情"


def _attachments(notice: Notice) -> list:
    """读附件列表（JSON 串）；读不出来就当没有"""
    if not notice.attachments:
        return []
    try:
        items = json.loads(notice.attachments)
    except (ValueError, TypeError):
        return []
    return items if isinstance(items, list) else []


def _rfc822(day: date) -> str:
    """RSS 的 pubDate 格式：`Thu, 08 Oct 2026 00:00:00 +0800`

    用 email.utils.format_datetime 而不是手写星期/月份表：那几个英文缩写是它
    硬编码的，不受容器 locale 影响（locale 是 C 还是 zh_CN 输出都一样）。
    """
    return format_datetime(datetime.combine(day, datetime.min.time()).replace(tzinfo=CST))


def _xml_clean(text: str) -> str:
    """剔掉 XML 里非法的控制字符"""
    return _ILLEGAL_XML.sub("", text or "")
