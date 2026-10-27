"""资料下载的分享外链：

  * 分享人选择有效期（1 天 / 7 天 / 30 天 / 永久），链接落地在 /share/resource/{token}
  * 任何人（不登录）都能经链接下载，下载计入这条链接的统计，也计入资料总下载次数
  * 创建外链写操作日志；管理员能看到创建人、有效期、下载次数、最近下载时间并吊销

    cd backend && python -m pytest tests/test_resource_shares.py -q
"""

import pytest

PW = "initpass123"
ADMIN_NO = "2024000001"
STUDENT_NO = "2024000002"
FILE_BYTES = b"%PDF-1.4 resource share payload"


@pytest.fixture
def b(backend):
    """初始化完毕、管理员已登录的后端（和 test_resources 同一套起步流程）"""
    inst = backend(db="resource-shares.db", BOOTSTRAP_PASSWORD=PW)
    assert inst.login(password=PW).status_code == 200
    r = inst.client.post("/api/students", json={
        "student_no": ADMIN_NO, "name": "管理员",
        "id_card": "110101200601010001",
    })
    assert r.status_code == 200, r.text
    r = inst.client.post("/api/setup/finish", json={"admin_student_no": ADMIN_NO})
    assert r.status_code == 200, r.text
    inst.logout()
    assert inst.login(ADMIN_NO, "010001").status_code == 200
    return inst


@pytest.fixture
def resource(b):
    """上传一份真资料：后面的外链、下载都要落到盘上的文件"""
    r = b.client.post(
        "/api/admin/resources",
        data={"name": "分享用材料", "category": "常用表格"},
        files={"file": ("share.pdf", FILE_BYTES, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _share(b, resource_id, days=7):
    r = b.client.post(f"/api/resources/{resource_id}/share", json={"days": days})
    assert r.status_code == 200, r.text
    return r.json()


def _link_row(b, token):
    rows = b.rows(
        "SELECT id, resource_id, created_by_no, created_by_name, expires_at,"
        " revoked_at, download_count, last_download_at"
        " FROM resource_share_links WHERE token = ?",
        token,
    )
    assert rows, "外链没落库"
    return rows[0]


def test_share_link_lands_on_the_share_page(b, resource):
    """地址形状必须是 /share/resource/{token}：nginx 和 index.html 只认这个"""
    body = _share(b, resource, days=7)

    assert body["path"] == f"/share/resource/{body['token']}"
    assert body["url"].endswith(body["path"]), "复制/二维码用的是绝对地址"
    assert body["expires_at"], "7 天有效期要算出到期时间"

    row = _link_row(b, body["token"])
    assert row[1] == resource
    assert row[2] == ADMIN_NO, "创建人账号"
    assert row[3] == "管理员", "创建人姓名快照"
    assert row[4] is not None


def test_forever_link_has_no_expiry(b, resource):
    body = _share(b, resource, days=0)
    assert body["expires_at"] is None
    assert _link_row(b, body["token"])[4] is None


def test_only_four_choices_of_validity(b, resource):
    r = b.client.post(f"/api/resources/{resource}/share", json={"days": 3})
    assert r.status_code == 400
    assert "有效期" in r.json()["detail"]


def test_creating_a_link_is_logged(b, resource):
    body = _share(b, resource, days=30)

    action, target, detail = b.rows(
        "SELECT action, target, detail FROM operation_logs ORDER BY id DESC LIMIT 1"
    )[0]
    assert action == "分享资料"
    assert target == "常用表格/分享用材料"
    assert "30 天" in detail and body["token"] in detail


def test_public_info_and_download_without_login(b, resource):
    """外链的本意就是「拿到链接的人都能下」：不登录也要能看能下"""
    token = _share(b, resource, days=1)["token"]
    b.logout()

    info = b.client.get(f"/api/resources/share/{token}/info")
    assert info.status_code == 200, info.text
    data = info.json()
    assert data["valid"] is True
    assert data["resource_name"] == "分享用材料"
    assert data["category"] == "常用表格"
    assert data["file_ext"] == ".pdf"
    assert data["size"] == len(FILE_BYTES)
    assert data["download_name"] == "分享用材料.pdf", "存盘名和站内下载同一口径"
    assert data["download_url"] == f"/api/resources/share/{token}/file"

    first = b.client.get(data["download_url"])
    assert first.status_code == 200
    assert first.content == FILE_BYTES
    assert first.headers["content-type"].startswith("application/pdf")

    # 再下一次：计数是累加的
    assert b.client.get(data["download_url"]).status_code == 200
    assert _link_row(b, token)[6] == 2
    assert _link_row(b, token)[7] is not None, "最近下载时间要记下来"
    assert b.rows("SELECT download_count FROM resources WHERE id = ?", resource)[0][0] == 2


def test_expired_link_stops_working(b, resource):
    token = _share(b, resource, days=7)["token"]
    b.run(
        "UPDATE resource_share_links SET expires_at = ? WHERE token = ?",
        "2000-01-01 00:00:00", token,
    )

    info = b.client.get(f"/api/resources/share/{token}/info")
    assert info.status_code == 200
    assert info.json()["valid"] is False
    assert info.json()["reason"] == "expired"
    assert b.client.get(f"/api/resources/share/{token}/file").status_code == 404
    assert _link_row(b, token)[6] == 0, "打不开的链接不该涨下载数"


def test_admin_sees_and_revokes_links(b, resource):
    token = _share(b, resource, days=30)["token"]
    b.client.get(f"/api/resources/share/{token}/file")

    links = b.client.get("/api/admin/resource-shares")
    assert links.status_code == 200, links.text
    row = next(item for item in links.json() if item["token"] == token)
    assert row["resource_name"] == "分享用材料"
    assert row["created_by_no"] == ADMIN_NO
    assert row["created_by_name"] == "管理员"
    assert row["status"] == "valid"
    assert row["status_label"] == "有效"
    assert row["download_count"] == 1
    assert row["last_download_at"] is not None
    assert row["created_at"] and row["expires_at"]

    r = b.client.post(f"/api/admin/resource-shares/{row['id']}/revoke")
    assert r.status_code == 200, r.text

    info = b.client.get(f"/api/resources/share/{token}/info")
    assert info.json()["valid"] is False
    assert info.json()["reason"] == "revoked"
    assert b.client.get(f"/api/resources/share/{token}/file").status_code == 404

    # 重复吊销不报错（管理员连点两下不该看到一个失败）
    assert b.client.post(f"/api/admin/resource-shares/{row['id']}/revoke").status_code == 200

    action, detail = b.rows(
        "SELECT action, detail FROM operation_logs ORDER BY id DESC LIMIT 1"
    )[0]
    assert action == "吊销资料外链"
    assert ADMIN_NO in detail


def test_student_can_share_but_not_manage(b, resource):
    """普通学生也能分享（资料本来就对登录用户开放），但管理列表只给管理员"""
    r = b.client.post("/api/students", json={
        "student_no": STUDENT_NO, "name": "张三",
        "id_card": "110101200602020002",
    })
    assert r.status_code == 200, r.text
    b.logout()
    assert b.login(STUDENT_NO, "020002").status_code == 200

    body = _share(b, resource, days=1)
    assert _link_row(b, body["token"])[2] == STUDENT_NO

    assert b.client.get("/api/admin/resource-shares").status_code == 403
    link_id = _link_row(b, body["token"])[0]
    assert b.client.post(f"/api/admin/resource-shares/{link_id}/revoke").status_code == 403


def test_crawler_card_and_invalid_link(b, resource):
    """爬虫不执行 JS：卡片信息由 SSI 子请求给出，失效后必须 noindex"""
    token = _share(b, resource, days=7)["token"]

    ok = b.client.get(f"/api/share-meta/share/resource/{token}")
    assert ok.status_code == 200
    assert "资料：分享用材料" in ok.text
    assert "常用表格" in ok.text
    assert "index,follow" in ok.text

    # 伪造的 token：仍然 200，但给统一失效卡片，不能被收录
    bad = b.client.get("/api/share-meta/share/resource/not-a-real-token")
    assert bad.status_code == 200
    assert "链接已失效" in bad.text
    assert "noindex, nofollow" in bad.text


def test_deleting_resource_removes_its_links(b, resource):
    token = _share(b, resource, days=7)["token"]
    assert b.client.delete(f"/api/admin/resources/{resource}").status_code == 200

    assert b.rows("SELECT COUNT(*) FROM resource_share_links WHERE token = ?", token)[0][0] == 0
    assert b.client.get(f"/api/resources/share/{token}/info").status_code == 404
