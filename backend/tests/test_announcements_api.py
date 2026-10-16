"""文件公开的访问记录：删文件时连带清理、超期清理、以及清完之后水印怎么说

    cd backend && python -m pytest tests/test_announcements_api.py -q

file_access_logs 记的是「谁看了/下载了哪份公开文件」，一条记录只有两种消失方式，
每种都有一个「就差一点」的错误写法：

1. **文件被删掉**时连它的记录一起删。少写这一步，列表里就攒着一批 file_id
   指向空处的孤儿行；写宽一点（不带 file_id 条件）又会把别的文件的记录一起抹掉。
2. **超过保留期**的记录在写入新记录时顺手清掉。这是这条链路唯一会自己跑起来的
   清理时机 —— 服务连着跑几个月、期间没人看过任何文件时，只剩启动那次兜底。
   切在「保留期」两边各造一条，才能同时证明「该清的清了」和「不该清的没清」。
3. 清完之后水印溯源**要说得出这是「文件被删了」**，而不是继续显示成
   「动作未知 + 文件#5」——那个编号此刻已经指不回任何东西了。反过来，老令牌
   没有来源段（公告和导出都查不到，分不清是哪一个），照样只说「动作未知」。

公告 PDF 的目录被隔离了（conftest 给后端指了 tmp_path/announcements），
所以上传接口的文件不会落进本机演示库的真目录。
"""
import time
from datetime import datetime, timedelta

import pytest
from pymupdf import open as open_pdf

from app.services import add_invisible_watermark
from app.services.log_service import FILE_ACCESS_KEEP_DAYS

PW = "initpass123"
ADMIN = "2024000001"     # 管理员：传、删、取文件，都是他
ROSTER = [
    (ADMIN, "甲", "010001"),
    ("2024000002", "乙", "010002"),
]

EXTRACT = "/api/admin/file-access-logs/extract"


# ---------- 小工具 ----------

def _pdf() -> bytes:
    """一张真的单页 PDF

    不能用 b"%PDF-1.4\\n" 那种空壳：文件公开的**每一次下发都要现打水印**，
    PyMuPDF 打不开的字节会当场 500（请假那边能拿空壳凑数是因为它压根不解流）。
    """
    doc = open_pdf()          # 不带参数 = 新建空文档
    doc.new_page()
    return doc.tobytes()


def upload(b, title: str) -> dict:
    r = b.client.post("/api/announcements", data={
        "title": title, "publish_date": "2026-10-01",
    }, files={"file": (f"{title}.pdf", _pdf(), "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def fetch(b, row, download=False) -> bytes:
    """按列表里那个 file_path 取一次文件，返回拿到的（打过水印的）字节

    取一次就是记一条访问记录 —— 这是全项目唯一的写入点。
    """
    url = row["file_path"] + ("?download=true" if download else "")
    r = b.client.get(url)
    assert r.status_code == 200, r.text
    return r.content


def extract(b, pdf: bytes) -> dict:
    r = b.client.post(EXTRACT, files={"file": ("x.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def log_count(b) -> int:
    return b.rows("SELECT COUNT(*) FROM file_access_logs")[0][0]


def _insert_log(b, file_id: int, days_ago: float, title="旧文件"):
    """直接往库里塞一条指定时间的访问记录

    接口造不出历史时间（created_at 是写入那一刻的 datetime.now），
    而「超过保留期」这件事只能靠造。时间格式要和 SQLAlchemy 写进去的一致
    （零补齐 + 微秒），不然 SQLite 那边是按字符串比大小的
    """
    when = datetime.now() - timedelta(days=days_ago)
    b.run(
        "INSERT INTO file_access_logs"
        " (created_at, user_no, user_name, file_id, file_title, action, ip)"
        " VALUES (?, ?, ?, ?, ?, 'view', '127.0.0.1')",
        when.strftime("%Y-%m-%d %H:%M:%S.%f"), ADMIN, "甲", file_id, title,
    )


@pytest.fixture
def b(backend):
    """初始化完毕、管理员已登录的后端"""
    inst = backend(db="ann.db", BOOTSTRAP_PASSWORD=PW)
    assert inst.login(password=PW).status_code == 200

    for no, name, tail in ROSTER:
        r = inst.client.post("/api/students", json={
            "student_no": no, "name": name, "id_card": f"11010120060101{tail}",
        })
        assert r.status_code == 200, r.text

    r = inst.client.post("/api/setup/finish", json={"admin_student_no": ADMIN})
    assert r.status_code == 200, r.text

    inst.logout()
    assert inst.login(ADMIN, ROSTER[0][2]).status_code == 200
    return inst


# ---------- 删文件时连带清理 ----------

def test_deleting_a_file_takes_its_access_logs_with_it(b):
    """删文件只带走它自己的记录，别的文件一条都不许动"""
    first = upload(b, "甲文件")
    second = upload(b, "乙文件")
    fetch(b, first)
    fetch(b, second)
    fetch(b, second, download=True)
    assert log_count(b) == 3

    assert b.client.delete(f"/api/announcements/{first['id']}").status_code == 200

    left = b.rows("SELECT file_id, action FROM file_access_logs ORDER BY id")
    assert log_count(b) == 2, "删文件没把它自己的记录带走（或者顺手多删了别的）"
    assert all(row[0] == second["id"] for row in left), "误伤了别的文件的记录"
    assert [row[1] for row in left] == ["view", "download"]


def test_the_delete_log_says_how_many_records_went_with_it(b):
    """记录删掉了，但「当时有几个人看过」得留在操作日志里 —— 这是唯一的线索了"""
    row = upload(b, "甲文件")
    fetch(b, row)
    fetch(b, row)

    assert b.client.delete(f"/api/announcements/{row['id']}").status_code == 200

    action, detail = b.rows("SELECT action, detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0]
    assert action == "删除文件"
    assert "2 条" in detail, f"操作日志里没记下清理了几条：{detail!r}"


def test_deleting_a_file_that_nobody_ever_opened_is_quiet(b):
    """没人看过就删：不留一条「连带清理 0 条」的废话"""
    row = upload(b, "甲文件")
    assert b.client.delete(f"/api/announcements/{row['id']}").status_code == 200

    action, detail = b.rows("SELECT action, detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0]
    assert action == "删除文件"
    assert not detail, f"没人看过就不该留下「连带清理 0 条」这种废话：{detail!r}"


# ---------- 保留期 ----------

def test_expired_logs_are_purged_when_a_new_one_is_written(b):
    """保留期两边各造一条：过期的被清掉，期内的留着，新写的那条也在"""
    assert FILE_ACCESS_KEEP_DAYS == 30, "用户口径是「记录保留一个月」"

    row = upload(b, "甲文件")
    _insert_log(b, row["id"], days_ago=FILE_ACCESS_KEEP_DAYS + 1, title="过了保留期")
    _insert_log(b, row["id"], days_ago=FILE_ACCESS_KEEP_DAYS - 1, title="还在期内")
    assert log_count(b) == 2

    fetch(b, row)          # 写新记录 = 顺手清一次旧的

    titles = [t[0] for t in b.rows("SELECT file_title FROM file_access_logs ORDER BY id")]
    assert titles == ["还在期内", "甲文件"], "该清的没清干净，或者把期内的也清了"


def test_startup_purges_expired_logs(backend):
    """启动时兜底清一次

    正常是「来一条新的就清一次」在跑，但服务连着跑几个月、期间没人看过任何文件时，
    那条路径根本不触发 —— 重启那一刻至少得是干净的。
    """
    b = backend(db="ann-purge.db", BOOTSTRAP_PASSWORD=PW)
    _insert_log(b, file_id=1, days_ago=FILE_ACCESS_KEEP_DAYS + 1)
    assert log_count(b) == 1

    b2 = backend(db="ann-purge.db", BOOTSTRAP_PASSWORD=PW)   # 同一个库再起一次 = 重启
    assert log_count(b2) == 0, "重启没清掉过期的访问记录"


def test_purge_only_touches_the_access_logs(b):
    """清理只动 file_access_logs —— 操作日志是台账，谁都别顺手动它"""
    _insert_log(b, file_id=1, days_ago=FILE_ACCESS_KEEP_DAYS + 1)
    before = b.rows("SELECT COUNT(*) FROM operation_logs")[0][0]

    row = upload(b, "甲文件")
    fetch(b, row)

    assert log_count(b) == 1, "过期的访问记录该清掉的"
    # 上传写了一条「上传文件」；取文件不写操作日志（那是台账，不是查询流水）
    assert b.rows("SELECT COUNT(*) FROM operation_logs")[0][0] == before + 1


# ---------- 水印溯源 ----------

def test_the_extract_says_the_file_was_deleted(b):
    """文件还在时能核到动作；删掉之后要改口说「这份文件已经删了」"""
    row = upload(b, "甲文件")
    pdf = fetch(b, row, download=True)

    alive = extract(b, pdf)
    assert alive["found"] is True
    assert alive["source_type"] == "announcement"
    assert alive["file_deleted"] is False
    assert alive["log_matched"] is True
    assert alive["action"] == "download"
    assert alive["file_title"] == "甲文件"

    assert b.client.delete(f"/api/announcements/{row['id']}").status_code == 200

    gone = extract(b, pdf)
    assert gone["found"] is True, "文件删了，水印还在，认得出人"
    assert gone["user_no"] == ADMIN
    assert gone["file_deleted"] is True
    assert gone["log_matched"] is False, "记录都清了，不许再报「核到了」"
    assert gone["file_title"] is None
    assert "删除" in gone["message"]


def test_a_token_without_a_source_is_not_reported_as_deleted(b):
    """老令牌没写来源段：公告和导出都查不到，分不清是哪一个，只能说「动作未知」

    分不清就报「已删除」是没依据的猜想（导出文件同样可能查不到）。
    """
    token = f"OA-WM:{999}:{ADMIN}:{int(time.time())}"
    data = extract(b, add_invisible_watermark(_pdf(), token))

    assert data["found"] is True
    assert data["source_type"] is None
    assert data["file_deleted"] is False
    assert data["log_matched"] is False


def test_a_living_file_still_wins_over_the_deleted_branch(b):
    """公告查得到时就不能报「已删除」—— 两个分支挨着写，最容易把条件抄反"""
    row = upload(b, "甲文件")
    pdf = fetch(b, row)

    data = extract(b, pdf)
    assert data["file_id"] == row["id"]
    assert data["file_deleted"] is False
    assert data["log_matched"] is True
    assert data["action"] == "view"
