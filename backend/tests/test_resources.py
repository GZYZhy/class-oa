"""资料下载：分类之间的展示顺序由管理员设置

    cd backend && python -m pytest tests/test_resources.py -q

分类在 resources 表里只是字符串，原先的先后是「分类里最靠前那条资料的
sort_order / id」撞出来的，管理员没法把「常用表格」整体挪到最前面。
现在顺序记在 resource_categories 表里，调它只动分类之间，分类里面的
资料顺序（resources.sort_order）一根手指都不碰。

全新库启动时会自动导入旧版 RESOURCE_CATALOG 的三类资料（见 main.py），
所以这里不用自己造数据，直接拿那三类当测试对象。
"""

import pytest

PW = "initpass123"
ADMIN_NO = "2024000001"

CATALOG_ORDER = ["徽章标志", "班级名单", "常用表格"]


@pytest.fixture
def b(backend):
    """初始化完毕、管理员已登录的后端

    资料分类的接口挂在 /api/admin 下，临时账号在初始化完成前调不动；
    建一个学生把他指认为管理员，再用他本人登录（密码 = 身份证后 6 位）。
    """
    inst = backend(db="resources.db", BOOTSTRAP_PASSWORD=PW)
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


def _categories(b) -> list[str]:
    r = b.client.get("/api/resources")
    assert r.status_code == 200, r.text
    return [group["category"] for group in r.json()]


def _admin_categories(b) -> list[str]:
    """管理员列表里分类首次出现的顺序（前端就是这么分组的）"""
    r = b.client.get("/api/admin/resources")
    assert r.status_code == 200, r.text
    out = []
    for row in r.json():
        if not out or out[-1] != row["category"]:
            out.append(row["category"])
    return out


def _reorder(b, order):
    r = b.client.put("/api/admin/resources/categories/order", json=order)
    assert r.status_code == 200, r.text
    return r


def test_admin_can_set_category_order(b):
    """调一次顺序，前台和管理后台都得跟着变"""
    assert _categories(b) == CATALOG_ORDER, "没设置过时沿用原来的顺序"
    assert _admin_categories(b) == CATALOG_ORDER

    new_order = ["常用表格", "徽章标志", "班级名单"]
    _reorder(b, new_order)

    assert _categories(b) == new_order, "Downloads 页面的分类顺序"
    assert _admin_categories(b) == new_order, "后台分组顺序也跟着走，否则像没保存"

    # 顺序落库了，不是只改了内存
    saved = b.rows("SELECT name FROM resource_categories ORDER BY sort_order, id")
    assert [row[0] for row in saved] == new_order


def test_category_order_does_not_touch_items_inside(b):
    """分类挪动是整组挪，分类里面的资料顺序保持原样"""
    before = {
        group["category"]: [item["id"] for item in group["items"]]
        for group in b.client.get("/api/resources").json()
    }

    _reorder(b, ["班级名单", "常用表格", "徽章标志"])

    after = {
        group["category"]: [item["id"] for item in group["items"]]
        for group in b.client.get("/api/resources").json()
    }
    assert after == before, "只该动分类之间，分类内的条目顺序不许变"


def test_a_new_category_goes_to_the_end(b):
    """管理员的顺序定好之后，新出现的分类排到最后，等他再挪"""
    _reorder(b, ["常用表格", "徽章标志", "班级名单"])

    # 新分类：直接塞一行，文件不存在也不影响分组（list_resources 会给 url=None）
    b.run(
        "INSERT INTO resources (name, file_name, original_name, category, sort_order, download_count)"
        " VALUES ('新资料', 'new.pdf', 'new.pdf', '新分类', 0, 0)"
    )
    assert _categories(b) == ["常用表格", "徽章标志", "班级名单", "新分类"]

    # 挪到中间，顺序能继续保持
    _reorder(b, ["常用表格", "新分类", "徽章标志", "班级名单"])
    assert _categories(b) == ["常用表格", "新分类", "徽章标志", "班级名单"]
