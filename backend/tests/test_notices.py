"""通知公告 RSS 订阅测试

覆盖：订阅链接要不要登录、feed 能不能被真 XML 解析器读、条目形状、
「共用日程令牌」这条约定、50 条上限、附件链接、Markdown 摘要。

cd backend && python -m pytest tests/test_notices.py -q
"""
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import httpx
import pytest

from app.services.notice_rss_service import MAX_ITEMS
from app.utils.notify_text import markdown_to_text

PW = "initpass123"

ROSTER = [
    ("2024000001", "甲", "010001"),  # 管理员
    ("2024000002", "乙", "010002"),  # 普通学生
]
ADMIN_NO = ROSTER[0][0]

# 建通知一律直接写库，不走 POST：那条路要 multipart、还会顺带落一堆站内信，
# 而这个文件要验的是 feed 的形状，不是发布流程。
_INSERT = (
    "INSERT INTO notices (title, publisher, editors, publish_date, content, attachments) "
    "VALUES (?, ?, '', ?, ?, ?)"
)


@pytest.fixture
def b(backend):
    """初始化完毕、管理员已登录的后端"""
    inst = backend(db="notices.db", BOOTSTRAP_PASSWORD=PW)
    assert inst.login(password=PW).status_code == 200

    for no, name, id_tail in ROSTER:
        r = inst.client.post("/api/students", json={
            "student_no": no, "name": name,
            "id_card": f"11010120060101{id_tail}",
        })
        assert r.status_code == 200, r.text

    r = inst.client.post("/api/setup/finish", json={"admin_student_no": ADMIN_NO})
    assert r.status_code == 200, r.text

    inst.logout()
    assert inst.login(ADMIN_NO, ROSTER[0][2]).status_code == 200
    return inst


# 公开端点得用**不带 cookie** 的客户端拉：带 cookie 的话测的是「登录了能拿到」，
# 而这里要证明的恰恰是「不登录也能拿到内容、但拿不到链接」。
def _anon_get(b, path):
    return httpx.get(str(b.client.base_url) + path, timeout=10)


def _text(resp) -> str:
    return resp.content.decode("utf-8")


# ---------- 「需要登录」这条线 ----------

def test_rss_token_requires_login(b):
    """没登录拿不到订阅链接"""
    b.logout()
    r = b.client.get("/api/notices/rss/token")
    assert r.status_code == 401, r.text


def test_rss_token_returns_url_for_logged_in(b):
    """登录后能拿到完整链接，且 token 已经落库（不然链接当场 404）"""
    r = b.client.get("/api/notices/rss/token")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["token"]
    assert data["url"].endswith(f"/api/notices/rss/{data['token']}.xml")

    rows = b.rows("SELECT token FROM ical_tokens WHERE is_active = 1")
    assert data["token"] in [row[0] for row in rows]


def test_rss_feed_bad_token_404(b):
    """token 不对一律 404，且不带 cookie 也一样"""
    assert _anon_get(b, "/api/notices/rss/deadbeef.xml").status_code == 404
    assert b.client.get("/api/notices/rss/deadbeef.xml").status_code == 404


# ---------- feed 本身 ----------

def test_rss_feed_needs_no_cookie(b):
    """feed 端点不带 cookie 也能拉（阅读器不携带会话）"""
    b.run(_INSERT, "关于开展学风建设的通知", "甲", "2026-10-08", "请大家按时参加。", "")
    token = b.client.get("/api/notices/rss/token").json()["token"]

    r = _anon_get(b, f"/api/notices/rss/{token}.xml")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/rss+xml")
    body = _text(r)
    assert body.startswith("<?xml")
    assert "关于开展学风建设的通知" in body
    # 整份 feed 必须是 well-formed 的：只断言字符串的话，漏一个未声明的
    # atom 前缀、或一个没转义的 & 都测不出来
    ET.fromstring(body)


def test_rss_item_shape(b):
    """条目的 guid / pubDate / link / 频道必填项"""
    b.run(_INSERT, "开班会", "甲", "2026-10-08", "周三下午两点。", "")
    token = b.client.get("/api/notices/rss/token").json()["token"]
    root = ET.fromstring(_text(_anon_get(b, f"/api/notices/rss/{token}.xml")))

    channel = root.find("channel")
    # RSS 2.0 里 channel 的这三项都是必填
    assert channel.findtext("title")
    assert channel.findtext("link")
    assert channel.findtext("description")
    # 取最新一条的时间，不是 now()（用 now() 每次抓取都在变，阅读器会以为源一直在更新）
    assert channel.findtext("lastBuildDate").endswith("+0800")

    item = channel.find("item")
    assert item.findtext("title") == "开班会"
    # 前端是 hash 路由，写成 /notices?id=1 会被 try_files 兜到 index.html、
    # 再被当成根路径静默跳到 /dashboard
    assert "/#/notices?id=" in item.findtext("link")
    assert item.findtext("guid") == f"notice-{b.rows('SELECT id FROM notices')[0][0]}@class-oa"
    assert item.find("guid").get("isPermaLink") == "false"
    assert item.findtext("pubDate") == "Thu, 08 Oct 2026 00:00:00 +0800"


def test_rss_survives_xml_hostile_text(b):
    """标题里的 & < 和一个非法控制字符都不该让整份 feed 崩掉"""
    # \x0b（软换行）从 Word / 微信里粘进来太常见了，而 XML 1.0 里它是非法的 ——
    # escape() 对它完全不起作用，一个这样的字符整份文档就不是 well-formed
    b.run(_INSERT, "A & B <会议>\x0b开始", "甲", "2026-10-08", "正文", "")
    token = b.client.get("/api/notices/rss/token").json()["token"]
    root = ET.fromstring(_text(_anon_get(b, f"/api/notices/rss/{token}.xml")))

    assert root.find("channel/item/title").text == "A & B <会议>开始"


def test_rss_description_has_attachment_link(b):
    """带附件的通知：摘要里有能点的绝对地址"""
    attachments = '[{"file": "abc.pdf", "name": "会议纪要.pdf", "size": 12}]'
    b.run(_INSERT, "带附件的通知", "甲", "2026-10-08", "详见附件。", attachments)
    notice_id = b.rows("SELECT id FROM notices")[0][0]
    token = b.client.get("/api/notices/rss/token").json()["token"]
    root = ET.fromstring(_text(_anon_get(b, f"/api/notices/rss/{token}.xml")))

    desc = root.find("channel/item/description").text
    assert "会议纪要.pdf" in desc
    assert f"/api/notices/{notice_id}/attachments/0" in desc


def test_rss_limits_to_max_items(b):
    """超过上限时只出最新的 MAX_ITEMS 条"""
    total = MAX_ITEMS + 5
    for i in range(total):
        # 发布时间严格递增，i=0 是最旧的一条
        day = date(2026, 1, 1) + timedelta(days=i)
        b.run(_INSERT, f"第 {i} 条通知", "甲", day.isoformat(), "正文", "")

    token = b.client.get("/api/notices/rss/token").json()["token"]
    root = ET.fromstring(_text(_anon_get(b, f"/api/notices/rss/{token}.xml")))
    titles = [item.findtext("title") for item in root.findall("channel/item")]

    assert len(titles) == MAX_ITEMS
    assert titles[0] == f"第 {total - 1} 条通知"  # 最新的在最前
    assert f"第 {total - MAX_ITEMS} 条通知" in titles
    assert "第 0 条通知" not in titles  # 最旧的 5 条被丢掉


def test_rss_empty_channel_is_valid(b):
    """一条通知都没有时，feed 仍然是一份合法 XML（不能少 channel 必填项）"""
    token = b.client.get("/api/notices/rss/token").json()["token"]
    root = ET.fromstring(_text(_anon_get(b, f"/api/notices/rss/{token}.xml")))
    assert root.findall("channel/item") == []
    assert root.findtext("channel/description")


# ---------- 和日程共用一个令牌 ----------

def test_rss_shares_token_with_ical(b):
    """RSS 和 iCal 用的是同一个令牌：在日程页重置，RSS 链接一起失效"""
    rss_token = b.client.get("/api/notices/rss/token").json()["token"]
    assert _anon_get(b, f"/api/notices/rss/{rss_token}.xml").status_code == 200

    # 日程页那套接口拿到的就是同一个 token
    ical = b.client.get("/api/schedules/ical/token").json()
    assert ical["token"] == rss_token

    new_token = b.client.post("/api/schedules/ical/token/reset").json()["token"]
    assert new_token != rss_token
    # 旧链接立即失效（在**RSS** 端点上失效，这正是「共用」的证据）
    assert _anon_get(b, f"/api/notices/rss/{rss_token}.xml").status_code == 404
    assert _anon_get(b, f"/api/notices/rss/{new_token}.xml").status_code == 200


# ---------- Markdown 摘要 ----------

def test_markdown_to_text_strips_syntax():
    """标题/列表/链接/行内标记都要摘掉，且各段用空格拼"""
    md = (
        "# 关于**期末**考试的通知\n"
        "\n"
        "- 时间：1 月 5 日\n"
        "- 地点：`励学楼511`\n"
        "\n"
        "详见 [教务处网站](https://example.com/x)。\n"
        "\n"
        "```\n"
        "这段代码不该出现\n"
        "```\n"
    )
    text = markdown_to_text(md)
    assert text == "关于期末考试的通知 时间：1 月 5 日 地点：励学楼511 详见 教务处网站。"


def test_markdown_to_text_joins_with_space():
    """两段之间必须有空格：直接粘成「第一句第二句」比多一个空格难看得多"""
    # clip 只在最后把换行换成空格，管不了已经粘上的
    assert markdown_to_text("第一句\n\n第二句") == "第一句 第二句"
    assert markdown_to_text("") == ""
    assert markdown_to_text(None) == ""


# ---------- 列表接口的 limit（首页「最新通知」用） ----------

def _titles(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [item["title"] for item in resp.json()]


def test_notice_list_limit_keeps_the_newest(b):
    """limit=N 只返回最新的 N 条

    首页只要 5 条标题，但它**必须在 SQL 里限**：每条通知都带着整篇 Markdown 正文，
    取回来再切片等于为 5 行标题把全班历来通知的全文拉一遍。
    顺序也要对：按发布时间降序，所以截断留下的该是「最新那几条」，不是最早那几条。
    """
    for i in range(5):
        b.run(_INSERT, f"通知{i}", "甲", f"2026-10-{i + 1:02d}", f"正文{i}", "")

    assert _titles(b.client.get("/api/notices?limit=2")) == ["通知4", "通知3"]
    assert _titles(b.client.get("/api/notices?limit=1")) == ["通知4"]


def test_notice_list_without_limit_returns_all(b):
    """不传 limit = 全都要：通知页那一整页靠的就是这条，行为一个字都不能变"""
    for i in range(5):
        b.run(_INSERT, f"通知{i}", "甲", f"2026-10-{i + 1:02d}", f"正文{i}", "")

    assert len(_titles(b.client.get("/api/notices"))) == 5


def test_notice_list_limit_out_of_range_422(b):
    """limit 是 1~100 的正整数：0 和超上限都当参数错误，别悄悄返回空表"""
    assert b.client.get("/api/notices?limit=0").status_code == 422
    assert b.client.get("/api/notices?limit=101").status_code == 422
    assert b.client.get("/api/notices?limit=abc").status_code == 422
