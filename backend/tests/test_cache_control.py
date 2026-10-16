"""接口的 Cache-Control 由后端说了算：没表态的补 no-store，表了态的别动它

    cd backend && python -m pytest tests -q

盯的是两件事：

1. **默认不缓存**。含隐私数据的接口绝大多数什么也没设，它们必须拿到 no-store。
   这条规矩原先写在前端 nginx 的 `location ^~ /api/` 里
   （`add_header Cache-Control "no-store"`），2026-10 搬到了后端的
   DefaultCacheControlMiddleware —— 搬的原因就是下面第 2 条。

2. **后端自己设的不被覆盖**。学生照片接口特意设了
   「private, max-age=31536000」：地址里带文件名当版本号，换图后地址会变，
   所以敢缓存一年（见 student_photo_service.photo_response）。可 nginx 那句
   add_header 是**追加**不是覆盖 —— 响应上于是挂着两个 Cache-Control，
   而 no-store 只要出现一个就生效，那张一年的缓存白设了：学生名单页三十多张
   照片每进一次重下一遍，弱网下就是几 MB 的白流量。

所以这里除了看最终值，还逐条数了 Cache-Control 头的**条数**（get_list）。
两个头正是当年那个病的形态；断言成列表就顺带把它钉住了。
"""
from types import SimpleNamespace

import pytest

from conftest import png_bytes

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"
PNG = png_bytes()

# 照片接口自己设的那一份，改策略时会连带要改这里
PHOTO_CACHE = "private, max-age=31536000"


@pytest.fixture
def b(backend):
    """初始化完毕、只有一名学生、且他已登录成管理员"""
    bk = backend(db="cache.db", BOOTSTRAP_PASSWORD=PW)
    assert bk.login(password=PW).status_code == 200

    r = bk.client.post("/api/students", json={
        "student_no": ADMIN, "name": "甲", "id_card": "110101200501010001",
    })
    assert r.status_code < 300, r.text

    assert bk.client.post("/api/setup/finish", json={"admin_student_no": ADMIN}).status_code == 200
    bk.logout()
    assert bk.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200

    sid = bk.rows("SELECT id FROM students WHERE student_no = ?", ADMIN)[0][0]
    return SimpleNamespace(b=bk, sid=sid)


def caches(resp) -> list:
    """响应上 Cache-Control 的值，**逐个**列出来（不是合并成一个字符串）"""
    return resp.headers.get_list("cache-control")


# ---------- 默认那档 ----------

def test_json_接口默认不缓存(b):
    """什么也没设的接口，补上的必须是 no-store —— 和它原先是 nginx 给的一样"""
    r = b.b.client.get("/api/students")
    assert r.status_code == 200
    assert caches(r) == ["no-store"]


def test_健康检查也不缓存(b):
    """不走会话的那条也一样。默认值是在中间件里加的，与鉴权无关"""
    r = b.b.client.get("/api/health")
    assert r.status_code == 200
    assert caches(r) == ["no-store"]


# ---------- 自己表态那档 ----------

def test_照片缓存的是一年后端设的那份(b):
    """后端设了什么就该是什么，中间件一个字都不许改"""
    up = b.b.client.post(
        f"/api/students/{b.sid}/photo?type=gaokao",
        files={"file": ("x.png", PNG, "image/png")},
    )
    assert up.status_code == 200, up.text

    r = b.b.client.get(f"/api/students/{b.sid}/photo")
    assert r.status_code == 200
    # 列表比对：只有一个头，值也和后端设的一模一样
    assert caches(r) == [PHOTO_CACHE]


def test_三种照片类型都带这份缓存(b):
    """类型走的是同一个出口，别哪一张漏了"""
    for type_ in ("gaokao", "on_site", "id"):
        up = b.b.client.post(
            f"/api/students/{b.sid}/photo?type={type_}",
            files={"file": ("x.png", PNG, "image/png")},
        )
        assert up.status_code == 200, up.text
        r = b.b.client.get(f"/api/students/{b.sid}/photo?type={type_}")
        assert r.status_code == 200
        assert caches(r) == [PHOTO_CACHE], type_


def test_同一页上的列表与照片各拿各的策略(b):
    """打开学生名单页会同时打这两个接口，一个该不缓存、一个该缓存一年。

    这正是当年 nginx 那句 add_header 做不到的事：它对 `/api/` 一视同仁，
    连照片那份也一并顶成 no-store。按接口分档只能在应用这一层做。
    """
    up = b.b.client.post(
        f"/api/students/{b.sid}/photo",
        files={"file": ("x.png", PNG, "image/png")},
    )
    assert up.status_code == 200, up.text

    lst = b.b.client.get("/api/students")
    photo = b.b.client.get(f"/api/students/{b.sid}/photo")
    assert caches(lst) == ["no-store"]
    assert caches(photo) == [PHOTO_CACHE]
