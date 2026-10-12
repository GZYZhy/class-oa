"""学生照片接口的回归：换/删照片时，日志文案得跟着 type 走

    cd backend && python -m pytest tests -q

盯的是一件事。照片类型有 gaokao / on_site / id 三种，但日志的 detail 一度写成
「是 gaokao 吗？不是就当实地采集」这种二元判断 —— 管理员给自备证件照换图，
日志里记的是「实地采集照片」。加了第三种类型之后它才暴露出来。

这不是好看不好看的问题：查「谁动过这张照片」的时候，二元判断会把两个不同列
的操作混成一条线，事后没法还原当时改的到底是哪张。

（这个 bug 在 1.9.0 及以前一直在线上跑着，2026-10-07 的 40a149c 修掉。当时只改
了代码、没留断言，所以线上一眼就看出问题、仓库里却没有任何东西拦着它复发 ——
这个文件就是补上的那道守卫。）
"""
from types import SimpleNamespace

import pytest

from conftest import png_bytes

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"
PNG = png_bytes()

# 三种类型各自的正确文案。顺序与 PHOTO_FIELDS 一致
TYPES = [("gaokao", "高考照片"), ("on_site", "实地采集照片"), ("id", "自备证件照")]


# ---------- 小工具 ----------

def upload(sp, type_, filename="x.png"):
    return sp.b.client.post(
        f"/api/students/{sp.sid}/photo?type={type_}",
        files={"file": (filename, PNG, "image/png")},
    )


def last_detail(sp) -> str:
    """最近一条操作日志的详情。直连库：要断言的就是「库里到底记了什么」"""
    return sp.b.rows("SELECT detail FROM operation_logs ORDER BY id DESC LIMIT 1")[0][0]


@pytest.fixture
def sp(backend):
    """初始化完毕、只有一名学生、且他已登录成管理员"""
    b = backend(db="photos.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200

    r = b.client.post("/api/students", json={
        "student_no": ADMIN, "name": "甲", "id_card": "110101200501010001",
    })
    assert r.status_code < 300, r.text

    assert b.client.post("/api/setup/finish", json={"admin_student_no": ADMIN}).status_code == 200
    b.logout()
    assert b.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200

    sid = b.rows("SELECT id FROM students WHERE student_no = ?", ADMIN)[0][0]
    return SimpleNamespace(b=b, sid=sid)


# ---------- 日志文案 ----------

@pytest.mark.parametrize("type_, label", TYPES)
def test_upload_logs_the_right_type(sp, type_, label):
    """换哪一张，日志就说哪一张的名字"""
    assert upload(sp, type_).status_code == 200
    assert last_detail(sp) == label


@pytest.mark.parametrize("type_, label", TYPES)
def test_delete_logs_the_right_type(sp, type_, label):
    """删也一样 —— 两处曾经各写各的二元判断，一个都别漏"""
    assert upload(sp, type_).status_code == 200
    assert sp.b.client.delete(f"/api/students/{sp.sid}/photo?type={type_}").status_code == 200
    assert last_detail(sp) == label


# ---------- 类型白名单 ----------

def test_unknown_type_is_rejected_and_lists_all_three(sp):
    """非法类型的 400 文案要按 PHOTO_FIELDS 现取，别写死

    原先那句「照片类型只能是 gaokao 或 on_site」在加了自备证件照之后就变成误报：
    正当的 type=id 请求也被它指着说「只能是什么什么」。
    """
    r = upload(sp, "avatar")
    assert r.status_code == 400
    detail = r.json()["detail"]
    for type_, _ in TYPES:
        assert type_ in detail, f"{type_} 是合法类型，得在报错里列出来"
    assert "avatar" not in detail


def test_every_import_photo_field_has_a_log_label():
    """每列都配得上一个标签

    少一个键，日志那一行就 KeyError 500 —— 加照片类型时最容易漏的就是这里，
    因为漏了以后上传图片照样成功，只有翻日志才看得出来。

    比的是**打包导入**那个清单（四种，含签字）：日志的 target 写的是
    PHOTO_TYPE_LABELS[photo_type]，而能走到那一步的 photo_type 只有它能取。
    """
    from app.services.student_photo_service import IMPORT_PHOTO_FIELDS, PHOTO_TYPE_LABELS

    assert set(IMPORT_PHOTO_FIELDS) == set(PHOTO_TYPE_LABELS)


def test_sign_is_not_a_regular_photo_type():
    """签字**不在**通用照片接口的清单里 —— 这是权限设计的一部分，不是遗漏

    通用照片接口（GET /students/{id}/photo?type=）的权限是「能看这个学生就能看他的
    照片」；签字要凭管理员审批（见 api/sign_photos.py）。签字一旦混进 PHOTO_FIELDS，
    班委在名单页点开学生就能直接取到签字图，那条审批链形同虚设。

    所以这个断言是在守一条安全边界，不是在对齐数据结构。真要有意放开，
    得先想清楚「申请-审批」这条链还要不要。
    """
    from app.services.student_photo_service import (
        IMPORT_PHOTO_FIELDS,
        PHOTO_FIELDS,
        PHOTO_TYPE_LABELS,
    )

    assert "sign" not in PHOTO_FIELDS
    # 但打包导入认它（管理员动作，跟传照片没区别）
    assert IMPORT_PHOTO_FIELDS["sign"] == "sign_photo"
    assert set(PHOTO_FIELDS) < set(IMPORT_PHOTO_FIELDS)
    # 标签表是给打包导入用的，两种都要在
    assert PHOTO_TYPE_LABELS["sign"] == "签字图"
