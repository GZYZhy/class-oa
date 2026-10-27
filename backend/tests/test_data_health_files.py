"""数据体检的文件部分：签字图缺失、登记了但文件丢了、孤儿文件与一键清理

    cd backend && python -m pytest tests/test_data_health_files.py -q

三条规矩：
  * 库里有记录、盘上没文件 → 报告，不修（怎么补得人决定）；
  * 盘上有文件、库里没记录 → 报告，可一键清理；
  * 刚写盘不到一小时的文件不算孤儿，避免把「正在上传」误判成垃圾。
"""

import json
import os
import time

import pytest

PW = "initpass123"
ADMIN_NO = "2024000001"
STUDENT_NO = "2024000002"


@pytest.fixture
def b(backend, tmp_path):
    """初始化完毕、管理员已登录；tmp_path 里就是这次的文件目录

    conftest 把 PHOTO_DIR / RESOURCE_DIR 等全部指到了 tmp_path 下，
    用例可以直接往里面放文件、也可以验证它们有没有被删掉。
    """
    inst = backend(db="health-files.db", BOOTSTRAP_PASSWORD=PW)
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

    # 再建一个普通学生：签字图、照片这些都以他为对象
    r = inst.client.post("/api/students", json={
        "student_no": STUDENT_NO, "name": "张三",
        "id_card": "110101200602020002",
    })
    assert r.status_code == 200, r.text
    return inst


def _groups(b) -> dict:
    r = b.client.get("/api/admin/data-health")
    assert r.status_code == 200, r.text
    return {group["key"]: group for group in r.json()["groups"]}


def _files(group) -> list[str]:
    return [item["file"] for item in group["items"]]


def _missing_domains(b) -> set[str]:
    """「文件丢失」涉及哪些目录

    不能断言整张卡片不存在：测试库启动时会从旧版 RESOURCE_CATALOG 导几条资料进
    resources 表，而测试环境没有对应的文件，那几条会一直报丢失（真实部署里由
    scripts/setup_resources.py 放文件）。所以只关心本次用例涉及的那个目录。
    """
    groups = _groups(b)
    return {item["domain"] for item in groups.get("file_missing", {}).get("items", [])}


def _old_file(path, content=b"old"):
    """写一个「一小时前」的文件：孤儿检查会跳过太新的文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    old = time.time() - 2 * 3600
    os.utime(path, (old, old))
    return path


def test_missing_sign_photo_is_reported(b):
    """签字图：库里有名字、盘上没文件 —— 页面上就是个裂图，只有体检看得出来"""
    b.run("UPDATE students SET sign_photo = 'no-such-sign.jpg' WHERE student_no = ?", STUDENT_NO)

    groups = _groups(b)
    assert "sign_photo" in groups
    item = next(i for i in groups["sign_photo"]["items"] if i["file"] == "no-such-sign.jpg")
    assert item["subject"] == "张三（2024000002）"
    assert "签字图" in item["reason"]
    assert item["id"] is None, "文件类行不挂学生 ID，避免前端误给「查看」"


def test_missing_sign_photo_is_not_reported_when_file_exists(b, tmp_path):
    """盘上有文件就不该报 —— 反过来「没上传签字图」也不算问题（多数人没有）"""
    photos = tmp_path / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    (photos / "sign-ok.jpg").write_bytes(b"img")
    b.run("UPDATE students SET sign_photo = 'sign-ok.jpg' WHERE student_no = ?", STUDENT_NO)

    assert "sign_photo" not in _groups(b)


def test_registered_resource_file_missing_is_reported(b, tmp_path):
    """数据库登记的资料，磁盘文件被删了 → 「文件丢失」卡片"""
    r = b.client.post(
        "/api/admin/resources",
        data={"name": "体检用资料", "category": "常用表格"},
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 200, r.text

    downloads = tmp_path / "downloads"
    saved = list(downloads.iterdir())
    assert len(saved) == 1
    saved[0].unlink()

    groups = _groups(b)
    assert "file_missing" in groups
    item = next(i for i in groups["file_missing"]["items"] if "体检用资料" in i["subject"])
    assert item["domain"] == "resources"
    assert "找不到" in item["reason"]


def test_orphan_files_are_reported_and_cleanable(b, tmp_path):
    """孤儿文件：报出来，并且能一键清掉；刚写的新文件不动"""
    photos = tmp_path / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    orphan = _old_file(photos / "orphan-old.jpg")
    fresh = photos / "just-uploaded.jpg"
    fresh.write_bytes(b"new")

    groups = _groups(b)
    assert "file_orphan" in groups
    assert groups["file_orphan"]["can_cleanup"] is True
    files = _files(groups["file_orphan"])
    assert "orphan-old.jpg" in files
    assert "just-uploaded.jpg" not in files, "一小时内写的新文件不算孤儿"

    r = b.client.post("/api/admin/data-health/orphans/cleanup", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deleted"] >= 1
    assert not orphan.exists()
    assert fresh.exists(), "太新的文件清理时也要跳过"

    # 清完再体检，孤儿那张卡片就没了
    assert "file_orphan" not in _groups(b)

    action, detail = b.rows(
        "SELECT action, detail FROM operation_logs ORDER BY id DESC LIMIT 1"
    )[0]
    assert action == "清理孤儿文件"
    assert "删除" in detail


def test_cleanup_never_touches_database_records(b, tmp_path):
    """只删没人认领的文件：正被资料引用的文件即使没入库也不会被删"""
    r = b.client.post(
        "/api/admin/resources",
        data={"name": "要留着的资料", "category": "常用表格"},
        files={"file": ("keep.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 200, r.text
    kept = next((tmp_path / "downloads").iterdir())

    b.client.post("/api/admin/data-health/orphans/cleanup", json={})

    assert kept.exists(), "被数据库引用的文件不是孤儿"
    listed = b.client.get("/api/resources").json()
    names = [item["name"] for group in listed for item in group["items"]]
    assert "要留着的资料" in names, "清理不动数据库记录"


def test_cleanup_can_be_limited_to_one_domain(b, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    in_photos = _old_file(photos / "p.jpg")

    notices = tmp_path / "notices"
    notices.mkdir(parents=True, exist_ok=True)
    in_notices = _old_file(notices / "n.pdf")

    r = b.client.post(
        "/api/admin/data-health/orphans/cleanup", json={"domains": ["photos"]}
    )
    assert r.status_code == 200, r.text
    assert not in_photos.exists()
    assert in_notices.exists(), "名单之外的目录一律不动"


def test_feedback_attachments_are_checked(b, tmp_path):
    """意见反馈附件：库里 JSON 记着、盘上没有 → 文件丢失"""
    b.run(
        "INSERT INTO feedbacks (student_no, student_name, title, content, attachments, status)"
        " VALUES (?, ?, ?, ?, ?, 'unread')",
        STUDENT_NO, "张三", "意见", "正文",
        json.dumps([{"file": "fb-missing.pdf", "name": "附件.pdf", "size": 3}],
                   ensure_ascii=False),
    )

    groups = _groups(b)
    item = next(i for i in groups["file_missing"]["items"] if i["domain"] == "feedbacks")
    assert "意见反馈" in item["subject"]
    assert item["file"] == "fb-missing.pdf"

    feedbacks = tmp_path / "feedbacks"
    feedbacks.mkdir(parents=True, exist_ok=True)
    (feedbacks / "fb-missing.pdf").write_bytes(b"pdf")
    assert "feedbacks" not in _missing_domains(b), "文件补上之后就不该再报"


def test_student_remark_attachments_are_checked(b, tmp_path):
    """学生备注附件：JSON 列表里的文件同样要存在"""
    b.run(
        "UPDATE students SET remark_attachments = ? WHERE student_no = ?",
        json.dumps([{"file": "remark-missing.pdf", "name": "备注.pdf", "size": 3}],
                   ensure_ascii=False),
        STUDENT_NO,
    )

    groups = _groups(b)
    item = next(
        i for i in groups["file_missing"]["items"] if i["domain"] == "remark_attachments"
    )
    assert item["subject"] == "张三（2024000002）"
    assert item["file"] == "remark-missing.pdf"

    folder = tmp_path / "remark_attachments"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "remark-missing.pdf").write_bytes(b"pdf")
    assert "remark_attachments" not in _missing_domains(b)


def test_export_artifacts_are_checked(b, tmp_path):
    """导出产物：生成的 Excel / PDF 丢了，申请人点了就是 404"""
    b.run(
        "INSERT INTO export_requests (student_no, student_name, export_type, status, file_name)"
        " VALUES (?, ?, 'excel_list', 'generated', 'missing.xlsx')",
        STUDENT_NO, "张三",
    )

    groups = _groups(b)
    item = next(i for i in groups["file_missing"]["items"] if i["domain"] == "exports")
    assert "导出申请" in item["subject"]
    assert item["file"] == "missing.xlsx"

    exports = tmp_path / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "missing.xlsx").write_bytes(b"xlsx")
    assert "exports" not in _missing_domains(b)


def test_collection_attachments_use_subdirectories(b, tmp_path):
    """收集附件按收集 ID 分子目录：相对路径参与比对，同名文件不会互相顶掉"""
    b.run(
        "INSERT INTO collection_submissions (collection_id, student_no, seq_no)"
        " VALUES (?, ?, 1)",
        7, STUDENT_NO,
    )
    submission_id = b.rows("SELECT id FROM collection_submissions ORDER BY id DESC LIMIT 1")[0][0]
    b.run(
        "INSERT INTO collection_answers (submission_id, files) VALUES (?, ?)",
        submission_id,
        json.dumps([{"name": "c1.jpg", "original": "x.jpg", "size": 3}],
                   ensure_ascii=False),
    )

    groups = _groups(b)
    item = next(
        i for i in groups["file_missing"]["items"] if i["domain"] == "collection_files"
    )
    assert item["file"] == "7/c1.jpg", "要带收集 ID，否则和别的收集里同名文件会撞"

    # 补上这份图片，再放两个孤儿：一个和它同目录、一个独占目录
    folder = tmp_path / "collection_files" / "7"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "c1.jpg").write_bytes(b"img")
    _old_file(folder / "orphan.jpg")
    lonely = tmp_path / "collection_files" / "8"
    _old_file(lonely / "orphan2.jpg")

    groups = _groups(b)
    assert "collection_files" not in _missing_domains(b)
    orphans = [
        i["file"] for i in groups["file_orphan"]["items"]
        if i["domain"] == "collection_files"
    ]
    assert orphans == ["7/orphan.jpg", "8/orphan2.jpg"]

    r = b.client.post(
        "/api/admin/data-health/orphans/cleanup", json={"domains": ["collection_files"]}
    )
    assert r.status_code == 200, r.text
    assert (folder / "c1.jpg").exists(), "有记录指着的图片不能删"
    assert not (folder / "orphan.jpg").exists()
    assert not lonely.exists(), "删空之后连带把空子目录收掉"


def test_student_cannot_cleanup(b):
    b.run("UPDATE students SET sign_photo = 'x.jpg' WHERE student_no = ?", STUDENT_NO)
    b.logout()
    assert b.login(STUDENT_NO, "020002").status_code == 200

    assert b.client.get("/api/admin/data-health").status_code == 403
    assert b.client.post("/api/admin/data-health/orphans/cleanup", json={}).status_code == 403
