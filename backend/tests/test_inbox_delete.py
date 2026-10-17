"""站内信：分页形状 + 「删除已读」

    cd backend && python -m pytest tests/test_inbox_delete.py -q

删除这件事只有一条判定：**自己的、已读的**。这组用例盯的就是这两条边界 ——
未读的一条都不能少，别人的一条都不能碰。消息一律直接写库：走 notify() 那条路
要点火一堆推送渠道，而这里验的是列表和删除本身。

注意 conftest 的 backend fixture 每个用例都是全新进程 + 临时库（见 tests/host.py），
本机那份生产数据拷贝不会被读写。
"""
import pytest

PW = "initpass123"

# (学号, 姓名, 身份证后 6 位 —— 也就是默认密码)
ROSTER = [
    ("2024000001", "甲", "010001"),  # 管理员（只用来跑初始化）
    ("2024000002", "乙", "010002"),  # 被测的普通学生
    ("2024000003", "丙", "010003"),  # 另一个学生，用来证明删不到别人头上
]
ADMIN_NO = ROSTER[0][0]
ME, ME_PW = ROSTER[1][0], ROSTER[1][2]
OTHER = ROSTER[2][0]

# created_at / read_at 都是 SQLAlchemy 的 DateTime，SQLite 里存成
# "YYYY-MM-DD HH:MM:SS.ffffff" 这样的字符串；这里按同一格式写，语义才对得上
_INSERT = (
    "INSERT INTO inbox_messages (student_no, title, body, level, created_at, read_at) "
    "VALUES (?, ?, ?, 'active', ?, ?)"
)


@pytest.fixture
def b(backend):
    """初始化完毕、乙（普通学生）已登录的后端"""
    inst = backend(db="inbox.db", BOOTSTRAP_PASSWORD=PW)
    assert inst.login(password=PW).status_code == 200

    for no, name, tail in ROSTER:
        r = inst.client.post("/api/students", json={
            "student_no": no, "name": name,
            "id_card": f"11010120060101{tail}",
        })
        assert r.status_code == 200, r.text

    r = inst.client.post("/api/setup/finish", json={"admin_student_no": ADMIN_NO})
    assert r.status_code == 200, r.text

    inst.logout()
    assert inst.login(ME, ME_PW).status_code == 200
    return inst


def _seed(b):
    """乙：2 条已读 + 1 条未读；丙：1 条已读（必须原封不动）"""
    b.run(_INSERT, ME, "我的已读 1", "正文", "2026-10-01 08:00:00", "2026-10-01 09:00:00")
    b.run(_INSERT, ME, "我的已读 2", "正文", "2026-10-02 08:00:00", "2026-10-02 09:00:00")
    b.run(_INSERT, ME, "我的未读", "正文", "2026-10-03 08:00:00", None)
    b.run(_INSERT, OTHER, "丙的已读", "正文", "2026-10-01 08:00:00", "2026-10-01 09:00:00")


# ---------- 删除已读 ----------

def test_delete_read_only_removes_my_read(b):
    """只删自己的已读：未读留下，别人的一条不动"""
    _seed(b)

    r = b.client.delete("/api/inbox/read")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 2}

    mine = [row[0] for row in b.rows(
        "SELECT title FROM inbox_messages WHERE student_no = ?", ME
    )]
    assert mine == ["我的未读"]
    assert b.rows(
        "SELECT COUNT(*) FROM inbox_messages WHERE student_no = ?", OTHER
    )[0][0] == 1


def test_delete_read_twice_is_noop(b):
    """重复调用返回 0：确认框连点两下、或者另一台设备先删了，都不该报错"""
    _seed(b)

    assert b.client.delete("/api/inbox/read").json() == {"deleted": 2}
    assert b.client.delete("/api/inbox/read").json() == {"deleted": 0}


def test_delete_read_requires_login(b):
    b.logout()
    assert b.client.delete("/api/inbox/read").status_code == 401


def test_list_reflects_deletions(b):
    """删完再拉列表：总数、未读数和条目一起变（红点靠的是 unread）"""
    _seed(b)
    b.client.delete("/api/inbox/read")

    data = b.client.get("/api/inbox").json()
    assert data["total"] == 1
    assert data["unread"] == 1
    assert [x["title"] for x in data["items"]] == ["我的未读"]


# ---------- 分页 ----------

def test_list_paginates_newest_first(b):
    """20 条一页；total/unread 是全量，不跟着当前页走"""
    for i in range(25):
        b.run(_INSERT, ME, f"消息{i}", "正文", f"2026-10-01 08:00:{i:02d}", None)

    p1 = b.client.get("/api/inbox?page=1&page_size=20").json()
    p2 = b.client.get("/api/inbox?page=2&page_size=20").json()

    assert p1["total"] == p2["total"] == 25
    assert len(p1["items"]) == 20
    assert len(p2["items"]) == 5
    assert p1["items"][0]["title"] == "消息24"   # 最新在最前
    assert p2["items"][-1]["title"] == "消息0"   # 最旧的落在最后一页
    # 未读数是全量：翻到第二页看到的还是 25，不是这一页的 5
    assert p1["unread"] == p2["unread"] == 25


def test_page_size_over_limit_422(b):
    """page_size 上限 100：防手工构造请求一次把全表拉走"""
    assert b.client.get("/api/inbox?page_size=101").status_code == 422
    assert b.client.get("/api/inbox?page=0").status_code == 422
