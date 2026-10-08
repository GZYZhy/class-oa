"""我的日程模块测试

覆盖：CRUD、重复日程展开、导入解析、iCal 生成、权限隔离、通知默认关闭

cd backend && python -m pytest tests/test_schedules.py -q
"""
import re
from io import BytesIO
from datetime import date, datetime, time

import httpx
import openpyxl
import pytest

PW = "initpass123"

# 3 个学生：甲（管理员）、乙（普通）、丙（普通）
ROSTER = [
    ("2024000001", "甲", "010001"),  # 管理员
    ("2024000002", "乙", "010002"),  # 普通学生
    ("2024000003", "丙", "010003"),  # 普通学生
]
ADMIN_NO = ROSTER[0][0]


# ---------- fixture ----------

@pytest.fixture
def b(backend):
    """初始化完毕、管理员已登录的后端"""
    inst = backend(db="schedules.db", BOOTSTRAP_PASSWORD=PW)
    assert inst.login(password=PW).status_code == 200

    # 建 3 个学生
    for no, name, id_tail in ROSTER:
        r = inst.client.post("/api/students", json={
            "student_no": no, "name": name,
            "id_card": f"11010120060101{id_tail}",
        })
        assert r.status_code == 200, r.text

    # 指认甲为管理员
    r = inst.client.post("/api/setup/finish", json={"admin_student_no": ADMIN_NO})
    assert r.status_code == 200, r.text

    # 用管理员登录
    inst.logout()
    r = inst.login(ADMIN_NO, ROSTER[0][2])
    assert r.status_code == 200, r.text
    return inst


def as_student(b, idx):
    """以第 idx 个学生身份登录的新客户端"""
    no, _, tail = ROSTER[idx]
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": tail})
    assert r.status_code == 200, r.text
    return c


def _make_schedule(title="测试日程", start="2026-10-12T08:00:00",
                   end="2026-10-12T09:00:00", **kw):
    """构造日程创建参数"""
    return {
        "title": title,
        "start_time": start,
        "end_time": end,
        "location": "",
        "description": "",
        "all_day": False,
        "repeat_type": "none",
        "repeat_end_date": None,
        "notify_enabled": False,
        "notify_minutes_before": 10,
        "target_all": False,
        "target_student_ids": [],
        **kw,
    }


# ---------- 基础 CRUD ----------

def test_create_and_list(b):
    """创建单次日程，列表能查到"""
    data = _make_schedule(title="晨跑", start="2026-10-12T07:00:00", end="2026-10-12T07:30:00")
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "晨跑"

    # 列表查询
    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1
    assert items[0]["title"] == "晨跑"
    assert items[0]["repeat_type"] == "none"


def test_notify_default_off(b):
    """通知默认关闭——建日程时不传 notify_enabled，必须是 False"""
    data = _make_schedule(title="默认通知测试", notify_enabled=None)
    del data["notify_enabled"]  # 完全不传
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200
    assert r.json()["notify_enabled"] is False

    # 查库确认
    rows = b.rows("SELECT notify_enabled FROM schedules WHERE title = ?", "默认通知测试")
    assert rows[0][0] == 0  # SQLite 的 False 是 0


def test_update_and_delete(b):
    """编辑和删除单次日程"""
    # 建
    data = _make_schedule(title="原标题")
    r = b.client.post("/api/schedules", json=data)
    sid = r.json()["id"]
    inst_date = r.json()["instance_date"]

    # 改
    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": inst_date},
        json={"title": "新标题", "scope": "all"},
    )
    assert r.status_code == 200, r.text

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    assert r.json()[0]["title"] == "新标题"

    # 删
    r = b.client.delete(
        f"/api/schedules/item/{sid}",
        params={"instance_date": inst_date, "scope": "all"},
    )
    assert r.status_code == 200

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    assert len(r.json()) == 0


def test_end_before_start_rejected(b):
    """结束时间早于开始时间 → 400"""
    data = _make_schedule(start="2026-10-12T10:00:00", end="2026-10-12T09:00:00")
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 400


def test_timezone_aware_input_normalized(b):
    """带时区的时间（脚本 / PAT 客户端会这么传）换算成本地墙上时间

    以前一端带时区一端不带时，接口里比 end <= start 直接 TypeError → 500；
    两端都带时区则偏移被静默丢掉。容器里 TZ 是 Asia/Shanghai，所以 00:00Z 就是 08:00。
    """
    # 混着传：以前这一条 500
    data = _make_schedule(start="2026-10-12T08:00:00", end="2026-10-12T09:00:00+08:00")
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200, r.text

    # 两端都带 Z：按本地墙上时间落库，不再是「偏移直接消失」
    data = _make_schedule(title="UTC时间", start="2026-10-13T00:00:00Z", end="2026-10-13T01:00:00Z")
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200, r.text
    assert r.json()["start_time"] == "2026-10-13T08:00:00"


# ---------- 全天事件（学生自己建的，不是导入的） ----------

def test_all_day_create_drops_times(b):
    """全天事件不带时刻：传进来的 08:00–09:00 一律归到 00:00–23:59

    表单里全天事件只有日期、没有时间框，这里是直接调接口的那条路径。
    """
    data = _make_schedule(
        title="国庆放假",
        start="2026-10-05T08:00:00", end="2026-10-05T09:00:00",
        all_day=True,
    )
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["all_day"] is True
    assert body["start_time"] == "2026-10-05T00:00:00"
    assert body["end_time"] == "2026-10-05T23:59:00"

    # 查库确认存的也是这一天两头，不是传进来的那个时刻
    rows = b.rows("SELECT start_time, end_time FROM schedules WHERE title = ?", "国庆放假")
    assert rows[0][0].startswith("2026-10-05 00:00")
    assert rows[0][1].startswith("2026-10-05 23:59")


def test_all_day_multi_day_is_one_row_per_day(b):
    """跨天的全天事件是「一天一条」—— 前端按天建、这里逐条落库

    模型里没有跨天日程这个概念：`_to_instance` 只取时刻、日期用 instance_date，
    所以一条记 10-05~10-07 的记录在日历上只会出现在 10-05（iCal 导出倒是能表达
    跨天，但列表路径表达不了）。页面上那根连着的条是前端合出来的（allDayBars）。
    """
    for day in ("2026-10-05", "2026-10-06", "2026-10-07"):
        r = b.client.post("/api/schedules", json=_make_schedule(
            title="国庆放假", start=f"{day}T00:00:00", end=f"{day}T23:59:00", all_day=True,
        ))
        assert r.status_code == 200, r.text

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-05", "end_date": "2026-10-11",
    })
    items = r.json()
    assert [it["instance_date"] for it in items] == ["2026-10-05", "2026-10-06", "2026-10-07"]
    assert all(it["all_day"] and it["title"] == "国庆放假" for it in items)


def test_all_day_update_also_drops_times(b):
    """编辑成全天事件：时刻同样归到当天两头（前端会把日期一起传上来）"""
    r = b.client.post("/api/schedules", json=_make_schedule(title="大扫除"))
    sid = r.json()["id"]

    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": r.json()["instance_date"]},
        json={
            "all_day": True,
            "start_time": "2026-10-12T08:00:00",
            "end_time": "2026-10-12T09:00:00",
            "scope": "all",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["all_day"] is True
    assert body["start_time"] == "2026-10-12T00:00:00"
    assert body["end_time"] == "2026-10-12T23:59:00"


# ---------- 重复日程 ----------

def test_weekly_repeat_expands(b):
    """每周重复日程在列表中展开为多条"""
    data = _make_schedule(
        title="每周例会",
        start="2026-10-12T14:00:00",  # 周一
        end="2026-10-12T15:00:00",
        repeat_type="weekly",
        repeat_end_date="2026-11-02",
    )
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200, r.text

    # 查 10/12-10/25（两周），应该有 2 条
    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-25",
    })
    items = r.json()
    assert len(items) == 2
    assert items[0]["instance_date"] == "2026-10-12"
    assert items[1]["instance_date"] == "2026-10-19"


def test_delete_single_of_repeat(b):
    """删除重复日程的某一次：前后都还在，本次没了"""
    data = _make_schedule(
        title="周课",
        start="2026-10-12T08:00:00",  # 周一
        end="2026-10-12T09:00:00",
        repeat_type="weekly",
        repeat_end_date="2026-10-26",
    )
    r = b.client.post("/api/schedules", json=data)
    sid = r.json()["template_id"]

    # 初始 3 次
    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-26",
    })
    assert len(r.json()) == 3

    # 删中间那次（10/19）
    r = b.client.delete(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-19", "scope": "single"},
    )
    assert r.status_code == 200

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-26",
    })
    items = r.json()
    assert len(items) == 2
    dates = [it["instance_date"] for it in items]
    assert "2026-10-12" in dates
    assert "2026-10-19" not in dates
    assert "2026-10-26" in dates


def test_update_forward_of_repeat(b):
    """编辑「本次及以后」：前面不变，后面应用新值"""
    data = _make_schedule(
        title="原名称",
        start="2026-10-12T08:00:00",
        end="2026-10-12T09:00:00",
        repeat_type="weekly",
        repeat_end_date="2026-10-26",
    )
    r = b.client.post("/api/schedules", json=data)
    sid = r.json()["template_id"]

    # 从 10/19 起改名为「新名称」
    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-19"},
        json={"title": "新名称", "scope": "forward"},
    )
    assert r.status_code == 200, r.text

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-26",
    })
    items = r.json()
    assert len(items) == 3

    by_date = {it["instance_date"]: it for it in items}
    assert by_date["2026-10-12"]["title"] == "原名称"
    assert by_date["2026-10-19"]["title"] == "新名称"
    assert by_date["2026-10-26"]["title"] == "新名称"


def test_update_single_of_repeat_keeps_earlier(b):
    """编辑重复日程的「仅本次」：本次之前的那几次必须原样留着

    这个分支要同时表达「前半段」和「后半段」，只靠把模板的起始日挪到下一次的话，
    instance_date 之前的发生日会跟着起点一起消失 —— 改中间一天等于把前面几天
    静默删掉（后半段还在，所以看起来「改成功了」）。
    """
    data = _make_schedule(
        title="原名称",
        start="2026-10-12T08:00:00",  # 周一
        end="2026-10-12T09:00:00",
        repeat_type="weekly",
        repeat_end_date="2026-10-26",
    )
    r = b.client.post("/api/schedules", json=data)
    sid = r.json()["template_id"]

    # 只改中间那次（10/19）
    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-19"},
        json={"title": "临时改名", "scope": "single"},
    )
    assert r.status_code == 200, r.text

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-26",
    })
    items = r.json()
    dates = sorted(it["instance_date"] for it in items)
    assert dates == ["2026-10-12", "2026-10-19", "2026-10-26"], dates

    by_date = {it["instance_date"]: it for it in items}
    assert by_date["2026-10-12"]["title"] == "原名称"
    assert by_date["2026-10-19"]["title"] == "临时改名"
    # 本次之后仍是重复日程（后半段另立了一条模板）
    assert by_date["2026-10-26"]["title"] == "原名称"
    assert by_date["2026-10-26"]["repeat_type"] == "weekly"


def test_update_single_of_repeat_first_occurrence(b):
    """改「仅本次」且本次就是第一次：后面照常重复，前面本来就没有"""
    data = _make_schedule(
        title="原名称",
        start="2026-10-12T08:00:00",
        end="2026-10-12T09:00:00",
        repeat_type="weekly",
        repeat_end_date="2026-10-26",
    )
    r = b.client.post("/api/schedules", json=data)
    sid = r.json()["template_id"]

    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-12"},
        json={"title": "临时改名", "scope": "single"},
    )
    assert r.status_code == 200, r.text

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-26",
    })
    items = r.json()
    dates = sorted(it["instance_date"] for it in items)
    assert dates == ["2026-10-12", "2026-10-19", "2026-10-26"], dates

    by_date = {it["instance_date"]: it for it in items}
    assert by_date["2026-10-12"]["title"] == "临时改名"
    assert by_date["2026-10-19"]["title"] == "原名称"
    assert by_date["2026-10-26"]["title"] == "原名称"


def test_update_single_only_occurrence(b):
    """只剩一次发生的重复日程改成「仅本次」：改完就是一条不重复的日程

    这一次既是第一次也是最后一次，原模板没用了 —— 拆完必须被删掉，不能留一条
    展开为空的僵尸行（页面上看不见它，但「第几周」那类按全表算的东西还看得到）。
    顺带守住响应：原行没了之后接口不能去读一个已经删掉的对象。
    """
    data = _make_schedule(
        title="只有一次",
        start="2026-10-12T08:00:00",
        end="2026-10-12T09:00:00",
        repeat_type="weekly",
        repeat_end_date="2026-10-12",
    )
    r = b.client.post("/api/schedules", json=data)
    sid = r.json()["template_id"]

    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-12"},
        json={"title": "改过了", "scope": "single"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "改过了"
    assert r.json()["repeat_type"] == "none"

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-31",
    })
    items = r.json()
    assert [(it["instance_date"], it["title"], it["repeat_type"]) for it in items] == [
        ("2026-10-12", "改过了", "none"),
    ]
    # 原模板没了，只留下这一条
    assert b.rows("SELECT COUNT(*) FROM schedules")[0][0] == 1


def test_update_single_of_repeat_last_occurrence(b):
    """改「仅本次」且本次是最后一次：前面照常重复，后面另立的那条不该出现"""
    data = _make_schedule(
        title="原名称",
        start="2026-10-12T08:00:00",
        end="2026-10-12T09:00:00",
        repeat_type="weekly",
        repeat_end_date="2026-10-26",
    )
    r = b.client.post("/api/schedules", json=data)
    sid = r.json()["template_id"]

    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-26"},
        json={"title": "临时改名", "scope": "single"},
    )
    assert r.status_code == 200, r.text

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-12-31",
    })
    items = r.json()
    dates = sorted(it["instance_date"] for it in items)
    assert dates == ["2026-10-12", "2026-10-19", "2026-10-26"], dates

    by_date = {it["instance_date"]: it for it in items}
    assert by_date["2026-10-12"]["title"] == "原名称"
    assert by_date["2026-10-19"]["title"] == "原名称"
    assert by_date["2026-10-26"]["title"] == "临时改名"


# ---------- 权限隔离 ----------

def test_student_cannot_see_others(b):
    """学生只能看到自己的日程，看不到别人的"""
    student2 = as_student(b, 1)  # 乙

    # 管理员建一个「仅自己」的日程
    data = _make_schedule(title="管理员私人日程")
    b.client.post("/api/schedules", json=data)

    # 乙看不到
    r = student2.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    assert len(r.json()) == 0

    # 管理员自己能看到
    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    assert len(r.json()) == 1


def test_student_cannot_delete_others(b):
    """学生不能删除别人的日程（404）"""
    student2 = as_student(b, 1)

    # 管理员建一个自己的日程
    data = _make_schedule(title="管理员的")
    r = b.client.post("/api/schedules", json=data)
    sid = r.json()["id"]
    inst = r.json()["instance_date"]

    # 乙尝试删 → 404
    r = student2.delete(
        f"/api/schedules/item/{sid}",
        params={"instance_date": inst, "scope": "all"},
    )
    assert r.status_code == 404


def test_committee_batch_create(b):
    """班委批量创建：目标学生都能看到"""
    # 先拿到学生 ID
    r = b.client.get("/api/students", params={"page": 1, "page_size": 10})
    students = {s["student_no"]: s["id"] for s in r.json()["items"]}

    sid_yi = students[ROSTER[1][0]]  # 乙
    sid_bing = students[ROSTER[2][0]]  # 丙

    # 管理员给乙和丙批量建日程
    data = _make_schedule(
        title="班会",
        start="2026-10-13T16:00:00",
        end="2026-10-13T17:00:00",
        target_student_ids=[sid_yi, sid_bing],
    )
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200, r.text

    # 乙能看到
    student2 = as_student(b, 1)
    r = student2.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    items = r.json()
    assert len(items) >= 1
    assert any(it["title"] == "班会" for it in items)
    # 来源是 batch
    assert any(it["source_type"] == "batch" for it in items)

    # 丙也能看到
    student3 = as_student(b, 2)
    r = student3.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    assert any(it["title"] == "班会" for it in r.json())


def test_regular_student_cannot_batch(b):
    """普通学生传了 target_student_ids 也没用，只建自己的"""
    student2 = as_student(b, 1)

    r = b.client.get("/api/students", params={"page": 1, "page_size": 10})
    all_ids = [s["id"] for s in r.json()["items"]]

    data = _make_schedule(
        title="学生想批量发",
        target_all=True,
        target_student_ids=all_ids,
    )
    r = student2.post("/api/schedules", json=data)
    # 应该成功（建自己的），但不会批量
    assert r.status_code == 200

    # 丙那里不会有
    student3 = as_student(b, 2)
    r = student3.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    assert not any(it["title"] == "学生想批量发" for it in r.json())


# ---------- 导入解析 ----------

def _make_schedule_xlsx() -> bytes:
    """造一份简单的周课表 xlsx（两周）"""
    wb = openpyxl.Workbook()

    for week_idx in range(2):
        sheet_name = f"第{week_idx + 1}周"
        if week_idx == 0:
            ws = wb.active
            ws.title = sheet_name
        else:
            ws = wb.create_sheet(sheet_name)

        # 起始周一日期（10/12 是周一）
        monday = date(2026, 10, 12) + __import__('datetime').timedelta(weeks=week_idx)
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        # 表头
        ws.cell(row=1, column=1, value="时间")
        for i in range(7):
            d = monday + __import__('datetime').timedelta(days=i)
            ws.cell(row=1, column=i + 2,
                    value=f"{d.month}/{d.day} {weekdays[i]}")

        # 时间列（07:00 - 21:50，10 分钟一行 = 90 行）
        for row in range(90):
            hour = 7 + row // 6
            minute = (row % 6) * 10
            ws.cell(row=row + 2, column=1,
                    value=f"{hour:02d}:{minute:02d}")

        # 周一 08:00-09:50（第 1 行时间是 07:00 在 row2，08:00 在 row8）
        # 8:00 = (8-7)*6 + 0/10 = 6 → row = 6 + 2 = 8
        # 9:50 = (9-7)*6 + 50/10 = 12+5=17 → row = 17 + 2 = 19
        start_row = 8   # 08:00
        end_row = 19    # 09:50
        ws.merge_cells(start_row=start_row, start_column=2,
                       end_row=end_row, end_column=2)
        ws.cell(row=start_row, column=2,
                value="高等数学\n课程\n励学楼101")

        # 周三 14:00-15:50（单周才有，模拟单双周 —— 这里第 1 周有、第 2 周没有）
        if week_idx == 0:
            # 14:00 = (14-7)*6 = 42 → row = 42 + 2 = 44
            # 15:50 = (15-7)*6 + 5 = 48+5=53 → row = 53 + 2 = 55
            ws.merge_cells(start_row=44, start_column=4, end_row=55, end_column=4)
            ws.cell(row=44, column=4, value="大学英语\n课程\n语音室")

        # 底部全天事件区：事件写在它覆盖的那一天的列里（B–H = 周一–周日）
        ws.cell(row=92, column=1, value="事件1")
        ws.cell(row=92, column=2, value=f"正式活动 {monday.month}/{monday.day}")
        if week_idx == 0:
            # 跨周六、周日两天：同一段文字在 G、H 两列各写一遍
            ws.cell(row=92, column=7, value="运动会")
            ws.cell(row=92, column=8, value="运动会")
            # 同一天（周日）还有第二条事件
            ws.cell(row=93, column=1, value="事件2")
            ws.cell(row=93, column=8, value="收假返校")
            # 跨周三、四、五三天，写成**横向合并**（D–F 一格）—— 合并之后只有
            # 左上角 D94 有值，逐格取会让这件事件只落在周三一天
            ws.cell(row=94, column=1, value="事件3")
            ws.merge_cells(start_row=94, start_column=4, end_row=94, end_column=6)
            ws.cell(row=94, column=4, value="国庆放假")

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_preview_faithful(b):
    """导入预览：忠实展平，不推断重复——每周每块各一条独立日程"""
    xlsx_bytes = _make_schedule_xlsx()

    r = b.client.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["week_count"] == 2

    # 高数两周各一块 → 2 条独立日程，日期分别落在两个周一
    math_items = [it for it in data["items"] if "高等数学" in it["title"]]
    assert len(math_items) == 2
    dates = sorted(it["start_date"] for it in math_items)
    assert dates == ["2026-10-12", "2026-10-19"]
    # 全部不重复
    assert all(it["repeat_type"] == "none" for it in math_items)
    # 类型、地点解析正确；类型不再污染备注
    assert math_items[0]["event_type"] == "课程"
    assert "励学楼" in math_items[0]["location"]
    assert math_items[0]["description"] == ""

    # 大学英语只在第 1 周出现 → 恰好 1 条（周三 10/14）
    eng_items = [it for it in data["items"] if "大学英语" in it["title"]]
    assert len(eng_items) == 1
    assert eng_items[0]["start_date"] == "2026-10-14"


def test_all_day_section_reads_every_column(b):
    """全天事件区逐格取：跨天的事件每天各出一条，同一天可以有好几条

    三个曾经踩过的坑：
    1. 只读 B 列 —— 事件写在它覆盖的那一天的列里，真实课表的「国庆放假」
       横跨 7 列，只读 B 列会让后面 6 天整片消失；
    2. 把全天事件塞进以「星期+开始时间」为键的字典 —— 凌晨 00:00 撞车，
       同一天的第二条会把第一条覆盖掉；
    3. 跨天写成横向合并时只认左上角 —— 合并之后只有最左边那格存着文字，
       逐格读会让 D94:F94 的「国庆放假」只落在周三，后面两天整片消失。

    跨天的两种写法（逐列重复写、横向合并）都摊成**一天一条**，页面上再由
    allDayBars 把相邻的同名条连回一条 —— 模型里没有「跨天日程」这个概念。
    """
    xlsx_bytes = _make_schedule_xlsx()
    r = b.client.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    allday = [it for it in r.json()["items"] if it["all_day"]]
    assert [(it["start_date"], it["title"]) for it in allday] == [
        ("2026-10-12", "正式活动 10/12"),   # 第 1 周周一
        ("2026-10-14", "国庆放假"),         # 横向合并 D94:F94 → 周三
        ("2026-10-15", "国庆放假"),         #                   周四
        ("2026-10-16", "国庆放假"),         #                   周五
        ("2026-10-17", "运动会"),           # 周六（同一段文字写了两列）
        ("2026-10-18", "运动会"),           # 周日
        ("2026-10-18", "收假返校"),         # 周日同一天的第二条
        ("2026-10-19", "正式活动 10/19"),   # 第 2 周周一
    ]
    # 全天事件不参与重复推断，类型/地点为空
    assert all(it["repeat_type"] == "none" for it in allday)
    assert all(it["event_type"] == "" and it["location"] == "" for it in allday)


def _typed_cell_xlsx() -> bytes:
    """表头和时间列都是 Excel 的**真日期/真时间**格式（不是文本）

    这种表非常常见：别人把单元格格式设成日期，值就不是字符串了。早先的解析只认
    字符串，整张表会以「无法识别日期表头」「没有识别到时间列」被静默跳过 ——
    预览里一条日程都没有，用户只会以为文件选错了。
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "第1周"
    monday = date(2026, 10, 12)
    ws.cell(row=1, column=2, value=datetime(2026, 10, 12))          # 真日期
    ws.cell(row=1, column=3, value="10/13 周二")                    # 同一个表里混字符串
    for row in range(90):
        hour = 7 + row // 6
        minute = (row % 6) * 10
        ws.cell(row=row + 2, column=1, value=time(hour, minute))    # 真时间
    ws.merge_cells(start_row=8, start_column=2, end_row=19, end_column=2)
    ws.cell(row=8, column=2, value="高等数学\n课程\n励学楼101")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_accepts_real_date_and_time_cells(b):
    """表头 / 时间列是 Excel 的真日期、真时间格式时照样能导入"""
    r = b.client.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", _typed_cell_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["week_count"] == 1
    assert data["warnings"] == []
    items = [it for it in data["items"] if "高等数学" in it["title"]]
    assert len(items) == 1
    assert items[0]["start_date"] == "2026-10-12"
    # 结束时间 = 最后一行（第 19 行 = 09:50）再往后一格
    assert (items[0]["start_time"], items[0]["end_time"]) == ("08:00", "10:00")


def test_import_header_not_monday(b):
    """表头那天不是周一时按它所在周的周一算，并在警告里写清用了哪一天"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "第1周"
    ws.cell(row=1, column=2, value="10/14 周三")   # 2026-10-14 是周三
    for row in range(90):
        ws.cell(row=row + 2, column=1, value=f"{7 + row // 6:02d}:{(row % 6) * 10:02d}")
    ws.merge_cells(start_row=8, start_column=2, end_row=19, end_column=2)
    ws.cell(row=8, column=2, value="高等数学")
    buf = BytesIO()
    wb.save(buf)

    r = b.client.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert any("2026-10-12" in w for w in data["warnings"]), data["warnings"]
    # 块在 B 列（周一），所以落在那周的周一 10/12；表头那格 10/14 只用来定周
    assert data["items"][0]["start_date"] == "2026-10-12"


def test_import_confirm_writes_to_targets(b):
    """导入确认：目标学生都拿到了日程"""
    xlsx_bytes = _make_schedule_xlsx()

    r = b.client.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    preview_items = r.json()["items"]
    token = r.json()["token"]

    # 先拿学生 ID
    r2 = b.client.get("/api/students", params={"page": 1, "page_size": 10})
    all_ids = [s["id"] for s in r2.json()["items"]]

    # 确认导入给全部学生
    r = b.client.post("/api/schedules/import", json={
        "token": token,
        "batch_name": "秋季课表",
        "target_all": True,
        "target_student_ids": [],
        "selected_indices": [],
    })
    assert r.status_code == 200, r.text
    result = r.json()
    # 条数从预览里数，不写死：夹具展平出什么由 test_all_day_section_reads_every_column
    # 逐条钉着，这里只关心「每个目标学生都拿到了同样多的一份」
    expected = len(preview_items)
    assert result["target_count"] == len(all_ids)
    assert result["schedule_per_student"] == expected
    assert result["total_created"] == expected * len(all_ids)

    # 学生乙能看到导入的课
    student2 = as_student(b, 1)
    r = student2.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    titles = [it["title"] for it in r.json()]
    assert "高等数学" in titles


def test_regular_student_cannot_import(b):
    """普通学生不能调导入接口"""
    student2 = as_student(b, 1)
    xlsx_bytes = _make_schedule_xlsx()

    r = student2.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 403  # 权限不足


# ---------- iCal 订阅 ----------

def test_ical_token_and_feed(b):
    """获取订阅 token，用 token 能拿到 ics 文件"""
    # 获取 token
    r = b.client.get("/api/schedules/ical/token")
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert "url" in data
    assert len(data["token"]) > 10

    # 先建一条日程
    b.client.post("/api/schedules", json=_make_schedule(title="iCal测试课"))

    # 用 token 拉 iCal（直接走 HTTP，不通过已登录客户端的 cookies）
    base = str(b.client.base_url).rstrip("/")
    r = httpx.get(f"{base}/api/schedules/ical/{data['token']}.ics")
    assert r.status_code == 200
    assert "VCALENDAR" in r.text
    assert "VEVENT" in r.text
    assert "iCal测试课" in r.text


def _ical_text(b) -> str:
    """拿当前学生的订阅文件正文"""
    token = b.client.get("/api/schedules/ical/token").json()["token"]
    base = str(b.client.base_url).rstrip("/")
    r = httpx.get(f"{base}/api/schedules/ical/{token}.ics")
    assert r.status_code == 200, r.text
    return r.text


def test_ical_event_shape(b):
    """iCal 正文的几处格式：备注换行不被二次转义、行不超 75 字节、DTSTAMP 是 UTC"""
    b.client.post("/api/schedules", json=_make_schedule(
        title="远足", location="操场", description="带水\n带伞",
        start="2026-10-12T08:00:00", end="2026-10-12T09:00:00",
    ))
    text = _ical_text(b)

    # 换行写成「反斜杠 + n」两个字符。以前拼的是 '\\n'（本身就是两个字符），
    # 再转义一次变成 「\\n」，客户端看到的是字面的 \n，不是换行
    assert "DESCRIPTION:带水\\n带伞" in text
    assert "\\\\n" not in text
    # DTSTAMP 按 RFC5545 必须是 UTC（整行就是 CRLF 包的，别用 ^$ 匹配，
    # 行尾那个 \r 会让 $ 对不上）
    assert re.search(r"\r\nDTSTAMP:\d{8}T\d{6}Z\r\n", text)
    # 每行（含续行）不超过 75 字节 —— 中文一个字 3 字节，长备注很容易超
    for line in text.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, line


def test_ical_long_line_folded(b):
    """超长的一行要折行，续行以空格开头，且不劈开多字节字符"""
    b.client.post("/api/schedules", json=_make_schedule(
        title="很长的标题" * 20, description="备注" * 60,
    ))
    text = _ical_text(b)
    lines = text.split("\r\n")
    assert any(line.startswith(" ") for line in lines), "应该出现了续行"
    for line in lines:
        assert len(line.encode("utf-8")) <= 75
        assert "�" not in line  # 按字符折，不会出现半截汉字


def test_ical_repeat_dtstart_matches_page(b):
    """单双周：订阅里的 DTSTART 是页面上第一次出现的日子，不是模板里那个开始日

    奇偶按学期周次算（week_start 是导入时写进去的）。用户把开始日填在了相反的一周时，
    页面从下一次才出现；iCal 若直接拿模板开始日当 DTSTART，整条订阅会错开一周。
    """
    r = b.client.post("/api/schedules", json=_make_schedule(
        title="单双周课", start="2026-10-27T08:00:00", end="2026-10-27T09:00:00"))
    sid = r.json()["id"]
    # 学期第 1 周周一 = 2026-09-07；10/27 落在第 8 周（双周），而这条是单周课
    b.run(
        "UPDATE schedules SET repeat_type='odd_week', repeat_end_date='2026-12-31', "
        "week_start='2026-09-07' WHERE id=?",
        sid,
    )

    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-26", "end_date": "2026-11-08",
    })
    first_on_page = r.json()[0]["instance_date"]
    assert first_on_page == "2026-11-03"   # 第 9 周（单周）的周二

    text = _ical_text(b)
    assert "DTSTART:20261103T080000" in text, text
    assert "DTEND:20261103T090000" in text
    # UNTIL 与 DTSTART 同为浮动本地时间（给浮动时间配 Z 的 UNTIL 不合 RFC5545）
    assert "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU;UNTIL=20261231T090000" in text, text


def test_ical_monthly_last_day(b):
    """每月 31 号：页面那边没有 31 号的月份取月末，iCal 得用 BYMONTHDAY=-1 才对得上"""
    r = b.client.post("/api/schedules", json=_make_schedule(
        title="月末总结", start="2026-01-31T08:00:00", end="2026-01-31T09:00:00"))
    b.run(
        "UPDATE schedules SET repeat_type='monthly', repeat_end_date='2026-04-30' WHERE id=?",
        r.json()["id"],
    )
    text = _ical_text(b)
    assert "BYMONTHDAY=-1" in text, text
    # 全天事件的 UNTIL 是 DATE（DTSTART 也是 DATE）
    b.client.post("/api/schedules", json=_make_schedule(
        title="月末假", start="2026-01-31T00:00:00", end="2026-01-31T23:59:00", all_day=True))
    r2 = b.client.get("/api/schedules", params={"start_date": "2026-01-26", "end_date": "2026-02-01"})
    b.run(
        "UPDATE schedules SET repeat_type='monthly', repeat_end_date='2026-04-30' WHERE id=?",
        [it for it in r2.json() if it["title"] == "月末假"][0]["id"],
    )
    text = _ical_text(b)
    assert "DTSTART;VALUE=DATE:20260131" in text
    assert "UNTIL=20260430" in text, text


def test_ical_bad_token_404(b):
    """无效 token 返回 404（不泄露存在性）"""
    base = str(b.client.base_url).rstrip("/")
    r = httpx.get(f"{base}/api/schedules/ical/nonexistent_token_123.ics")
    assert r.status_code == 404


def test_ical_reset_token(b):
    """重置 token 后旧 token 失效"""
    r = b.client.get("/api/schedules/ical/token")
    old_token = r.json()["token"]

    r = b.client.post("/api/schedules/ical/token/reset")
    assert r.status_code == 200
    new_token = r.json()["token"]
    assert new_token != old_token

    base = str(b.client.base_url).rstrip("/")
    # 新 token 能用
    r = httpx.get(f"{base}/api/schedules/ical/{new_token}.ics")
    assert r.status_code == 200
    # 旧 token 失效
    r = httpx.get(f"{base}/api/schedules/ical/{old_token}.ics")
    assert r.status_code == 404

    # 再重置一次：唯一约束是 (student_id, is_active)，上一次那条 is_active=0 的行
    # 留着就会让「把当前这行置为无效」撞约束 → 500。500 的话订阅链接就作废不掉了
    r = b.client.post("/api/schedules/ical/token/reset")
    assert r.status_code == 200, r.text
    third = r.json()["token"]
    assert third not in (old_token, new_token)
    assert httpx.get(f"{base}/api/schedules/ical/{third}.ics").status_code == 200
    # 上上轮那条也不该复活
    assert httpx.get(f"{base}/api/schedules/ical/{new_token}.ics").status_code == 404


# ---------- 批次管理 ----------

def test_batch_list_and_delete(b):
    """班委能看到自己创建的批次，并能撤销"""
    # 先批量建一个
    r = b.client.get("/api/students", params={"page": 1, "page_size": 10})
    all_ids = [s["id"] for s in r.json()["items"]]

    data = _make_schedule(
        title="临时活动",
        target_student_ids=all_ids,
    )
    # 用批量创建（走 batch 路径）
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200

    # 看批次列表。上面那次批量创建其实也产生了批次（班委分支走的就是 create_batch），
    # 这里另外导入一个是为了按名字认得出「撤销的是哪一个」
    xlsx_bytes = _make_schedule_xlsx()
    r = b.client.post(
        "/api/schedules/import/preview",
        files={"file": ("x.xlsx", xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    token = r.json()["token"]
    r = b.client.post("/api/schedules/import", json={
        "token": token, "batch_name": "测试批次",
        "target_all": True, "target_student_ids": [],
        "selected_indices": [],
    })
    batch_id = r.json()["batch_id"]

    # 批次列表有它
    r = b.client.get("/api/schedules/batches")
    assert r.status_code == 200
    batches = r.json()
    assert any(b["id"] == batch_id for b in batches)

    # 删批次
    r = b.client.delete(f"/api/schedules/batches/{batch_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] > 0

    # 学生那边没了
    student2 = as_student(b, 1)
    r = student2.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-18",
    })
    assert not any(it["title"] == "高等数学" for it in r.json())


# ---------- 跨学生下发 ----------
#
# 班委建的多条日程，实现上是给每个学生各写一条（create_batch），同一条原始日程的
# 副本共用 source_series_id。默认改/删只动自己那条；带上 share=true 才下发到其他人
# 的表里 —— 这个能力只属于「当初把这条日程分配出去的人」。

def _list(client, start="2026-10-12", end="2026-11-08"):
    """某个客户端（某个学生）看到的一段日程"""
    r = client.get("/api/schedules", params={"start_date": start, "end_date": end})
    assert r.status_code == 200, r.text
    return r.json()


def _items_of(items, title):
    """按标题筛出实例，按日期排好——断言展开结果时用它比对着看"""
    return sorted(
        [(it["instance_date"], it["title"], it["share_count"]) for it in items
         if it["title"].startswith(title)],
    )


def _student_ids(b):
    r = b.client.get("/api/students", params={"page": 1, "page_size": 10})
    return {s["student_no"]: s["id"] for s in r.json()["items"]}


def test_share_count_in_list(b):
    """列表里能看出这条日程发给了几个人；收件人看到的是 1"""
    ids = _student_ids(b)
    b.client.post("/api/schedules", json=_make_schedule(
        title="班会", target_student_ids=[ids[ROSTER[1][0]], ids[ROSTER[2][0]]]))
    b.client.post("/api/schedules", json=_make_schedule(
        title="自己的", start="2026-10-14T08:00:00", end="2026-10-14T09:00:00"))

    by = {it["title"]: it for it in _list(b.client)}
    # 自己 + 乙 + 丙 = 3
    assert by["班会"]["share_count"] == 3
    assert by["自己的"]["share_count"] == 1

    # 乙是收件人：没有资格再往下发，所以只算他自己那份
    student2 = as_student(b, 1)
    assert [it["share_count"] for it in _list(student2) if it["title"] == "班会"] == [1]


def test_share_update_fans_out(b):
    """建这条日程的人改标题，勾了「所有人的」就下发到乙丙的表里"""
    ids = _student_ids(b)
    b.client.post("/api/schedules", json=_make_schedule(
        title="班会", target_student_ids=[ids[ROSTER[1][0]], ids[ROSTER[2][0]]]))
    sid = [it for it in _list(b.client) if it["title"] == "班会"][0]["id"]

    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-12", "share": True},
        json={"title": "班会（改）", "scope": "all"},
    )
    assert r.status_code == 200, r.text

    assert _items_of(_list(b.client), "班会") == [("2026-10-12", "班会（改）", 3)]
    for idx in (1, 2):
        assert _items_of(_list(as_student(b, idx)), "班会") == [
            ("2026-10-12", "班会（改）", 1),
        ]
    # 三条都在库里（每人一条），不是只改了自己那条
    assert b.rows("SELECT COUNT(*) FROM schedules WHERE title='班会（改）'")[0][0] == 3


def test_share_update_single_fans_out(b):
    """「仅本次」下发：三个人表里都只剩本次改名，前后几次照样在

    这是分配出去的重复日程最常见的改法。它在每个人表里都要把模板切成
    前半段/后半段（见 update_schedule 的 SCOPE_SINGLE），任何一段没落好，
    下发之后别人的页面上就会多一次或者少一次。
    """
    ids = _student_ids(b)
    data = _make_schedule(
        title="班会", start="2026-10-12T08:00:00", end="2026-10-12T09:00:00",
        repeat_type="weekly", repeat_end_date="2026-10-26",
        target_student_ids=[ids[ROSTER[1][0]], ids[ROSTER[2][0]]],
    )
    assert b.client.post("/api/schedules", json=data).status_code == 200

    sid = [it for it in _list(b.client)
           if it["title"] == "班会" and it["instance_date"] == "2026-10-19"][0]["id"]
    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-19", "share": True},
        json={"title": "班会（本次改的）", "scope": "single"},
    )
    assert r.status_code == 200, r.text

    titles = [("2026-10-12", "班会"), ("2026-10-19", "班会（本次改的）"),
              ("2026-10-26", "班会")]
    # 甲自己看到 share_count=3，收件人看到 1；日期和标题三个人必须一模一样
    assert [(d, t) for d, t, _ in _items_of(
        _list(b.client, "2026-10-12", "2026-10-31"), "班会")] == titles
    for idx in (1, 2):
        got = _items_of(_list(as_student(b, idx), "2026-10-12", "2026-10-31"), "班会")
        assert got == [(d, t, 1) for d, t in titles], got
    # 每人被拆成三条：前半段、本次、后半段
    assert b.rows("SELECT COUNT(*) FROM schedules WHERE title LIKE '班会%'")[0][0] == 9


def test_update_without_share_keeps_others(b):
    """不带 share 就只改自己那份——「也允许只改自己的」"""
    ids = _student_ids(b)
    b.client.post("/api/schedules", json=_make_schedule(
        title="班会", target_student_ids=[ids[ROSTER[1][0]], ids[ROSTER[2][0]]]))
    sid = [it for it in _list(b.client) if it["title"] == "班会"][0]["id"]

    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-12"},
        json={"title": "班会（只改我的）", "scope": "all"},
    )
    assert r.status_code == 200, r.text

    assert _items_of(_list(b.client), "班会") == [("2026-10-12", "班会（只改我的）", 3)]
    for idx in (1, 2):
        assert _items_of(_list(as_student(b, idx)), "班会") == [("2026-10-12", "班会", 1)]


def test_share_delete_fans_out(b):
    """勾了「所有人的」删除，乙丙表里那条也一并没掉"""
    ids = _student_ids(b)
    b.client.post("/api/schedules", json=_make_schedule(
        title="班会", target_student_ids=[ids[ROSTER[1][0]], ids[ROSTER[2][0]]]))
    sid = [it for it in _list(b.client) if it["title"] == "班会"][0]["id"]

    r = b.client.delete(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-12", "scope": "all", "share": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 3

    for client in (b.client, as_student(b, 1), as_student(b, 2)):
        assert not [it for it in _list(client) if it["title"] == "班会"]

    # 对照组：不勾就只删自己那条
    b.client.post("/api/schedules", json=_make_schedule(
        title="春游", target_student_ids=[ids[ROSTER[1][0]], ids[ROSTER[2][0]]]))
    sid = [it for it in _list(b.client) if it["title"] == "春游"][0]["id"]
    r = b.client.delete(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-12", "scope": "all"},
    )
    assert r.json()["deleted"] == 1
    assert not [it for it in _list(b.client) if it["title"] == "春游"]
    assert [it for it in _list(as_student(b, 1)) if it["title"] == "春游"]


def test_share_only_by_creator(b):
    """收到的日程只能改自己那份：勾「所有人的」返回 403，不是静默降级"""
    ids = _student_ids(b)
    b.client.post("/api/schedules", json=_make_schedule(
        title="班会", target_student_ids=[ids[ROSTER[1][0]]]))
    sid = [it for it in _list(b.client) if it["title"] == "班会"][0]["id"]

    # 乙点开的是**自己那条**（库里每人一行，ID 各不同）
    student2 = as_student(b, 1)
    own = [it for it in _list(student2) if it["title"] == "班会"][0]["id"]

    r = student2.put(
        f"/api/schedules/item/{own}",
        params={"instance_date": "2026-10-12", "share": True},
        json={"title": "乙偷改全班", "scope": "all"},
    )
    assert r.status_code == 403, r.text
    # 报错之前不能已经动过库（哪怕只动了他自己那条）
    assert b.rows("SELECT COUNT(*) FROM schedules WHERE title='乙偷改全班'")[0][0] == 0
    assert _items_of(_list(b.client), "班会") == [("2026-10-12", "班会", 2)]

    # 不勾就随便改，只动自己那条
    r = student2.put(
        f"/api/schedules/item/{own}",
        params={"instance_date": "2026-10-12"},
        json={"title": "班会（乙改的）", "scope": "all"},
    )
    assert r.status_code == 200, r.text
    assert _items_of(_list(b.client), "班会") == [("2026-10-12", "班会", 2)]
    assert _items_of(_list(student2), "班会") == [("2026-10-12", "班会（乙改的）", 1)]


def test_import_share_fans_out(b):
    """导入的课表也能下发，且只命中同一条原始日程，不波及同批次别的课"""
    xlsx_bytes = _make_schedule_xlsx()
    r = b.client.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    r = b.client.post("/api/schedules/import", json={
        "token": r.json()["token"], "batch_name": "秋季课表",
        "target_all": True, "target_student_ids": [], "selected_indices": [],
    })
    assert r.status_code == 200, r.text

    # 高数两周两块，是**两条**互不相干的日程（同批次、同标题、不同日期）
    mine = _items_of(_list(b.client), "高等数学")
    assert mine == [("2026-10-12", "高等数学", 3), ("2026-10-19", "高等数学", 3)]
    sid = [it for it in _list(b.client)
           if it["title"] == "高等数学" and it["instance_date"] == "2026-10-12"][0]["id"]

    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-12", "share": True},
        json={"title": "高等数学（改）", "scope": "all"},
    )
    assert r.status_code == 200, r.text

    for idx in (1, 2):
        # 10-12 那天跟着变了；10-19 那条纹丝不动
        assert _items_of(_list(as_student(b, idx)), "高等数学") == [
            ("2026-10-12", "高等数学（改）", 1),
            ("2026-10-19", "高等数学", 1),
        ]
    # 三人各两条高数：10-12 那三条都改了名，剩下三条是 10-19 的
    assert b.rows("SELECT COUNT(*) FROM schedules WHERE title='高等数学'")[0][0] == 3
    assert b.rows("SELECT COUNT(*) FROM schedules WHERE title='高等数学（改）'")[0][0] == 3


def test_share_skips_drifted_copy(b):
    """别人自己把某一次删掉了，下发不能把他的日程静默改没

    乙先自己删掉 10-26 那一次 —— 他那条模板当场被拆成两段。甲再用
    「本次及以后」下发时，乙那两段其实都不包含 10-26，必须整个跳过：
    硬套的话，后半段（11-02）会被截到 10-25 截止，展开成空区间，
    在乙的页面上等于那次日程凭空消失。
    """
    ids = _student_ids(b)
    data = _make_schedule(
        title="班会", start="2026-10-12T08:00:00", end="2026-10-12T09:00:00",
        repeat_type="weekly", repeat_end_date="2026-11-02",
        target_student_ids=[ids[ROSTER[1][0]], ids[ROSTER[2][0]]],
    )
    assert b.client.post("/api/schedules", json=data).status_code == 200

    # 乙自己删掉中间那次（10-26）
    student2 = as_student(b, 1)
    sid = [it for it in _list(student2) if it["title"] == "班会"][0]["id"]
    r = student2.delete(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-26", "scope": "single"},
    )
    assert r.status_code == 200, r.text
    assert [d for d, _, _ in _items_of(_list(student2), "班会")] == [
        "2026-10-12", "2026-10-19", "2026-11-02",
    ]
    assert b.rows("SELECT COUNT(*) FROM schedules WHERE title='班会' AND student_id=?",
                  ids[ROSTER[1][0]])[0][0] == 2  # 被拆成两段

    # 甲用「本次及以后」下发 10-26 起的那一段
    sid = [it for it in _list(b.client)
           if it["title"] == "班会" and it["instance_date"] == "2026-10-26"][0]["id"]
    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-26", "share": True},
        json={"title": "班会（改）", "scope": "forward"},
    )
    assert r.status_code == 200, r.text

    # 丙正常收到：10-26 和 11-02 变成新标题
    assert _items_of(_list(as_student(b, 2)), "班会") == [
        ("2026-10-12", "班会", 1),
        ("2026-10-19", "班会", 1),
        ("2026-10-26", "班会（改）", 1),
        ("2026-11-02", "班会（改）", 1),
    ]
    # 乙那两段都没被动过：还是两行、11-02 那次还在、标题还是旧的
    assert b.rows("SELECT COUNT(*) FROM schedules WHERE title LIKE '班会%' AND student_id=?",
                  ids[ROSTER[1][0]])[0][0] == 2
    assert _items_of(_list(student2), "班会") == [
        ("2026-10-12", "班会", 1),
        ("2026-10-19", "班会", 1),
        ("2026-11-02", "班会", 1),
    ]


def test_share_multi_day_all_day(b):
    """跨天的全天事件是「一天一条」，每天各自能下发；新增的天沿用原来那批人"""
    ids = _student_ids(b)
    targets = [ids[ROSTER[1][0]], ids[ROSTER[2][0]]]
    # 前端的 saveAllDay 就是一天一次请求，这里照做
    for day in ("2026-10-12", "2026-10-13", "2026-10-14"):
        r = b.client.post("/api/schedules", json=_make_schedule(
            title="运动会", start=f"{day}T00:00:00", end=f"{day}T23:59:00",
            all_day=True, target_student_ids=targets,
        ))
        assert r.status_code == 200, r.text

    student2 = as_student(b, 1)
    assert [d for d, _, _ in _items_of(_list(student2), "运动会")] == [
        "2026-10-12", "2026-10-13", "2026-10-14",
    ]

    # 改中间那天：只有那天跟着变，首尾两天不受影响
    sid = [it for it in _list(b.client)
           if it["title"] == "运动会" and it["instance_date"] == "2026-10-13"][0]["id"]
    r = b.client.put(
        f"/api/schedules/item/{sid}",
        params={"instance_date": "2026-10-13", "share": True},
        json={"title": "运动会（改）", "scope": "all"},
    )
    assert r.status_code == 200, r.text
    assert [t for _, t, _ in _items_of(_list(student2), "运动会")] == [
        "运动会", "运动会（改）", "运动会",
    ]

    # 往后拖一天：新加的那天得发给原来那批人（share_from 沿用分组），
    # 不然「3 天改成 4 天」之后，第 4 天只有甲自己有
    r = b.client.post("/api/schedules", json=_make_schedule(
        title="运动会", start="2026-10-15T00:00:00", end="2026-10-15T23:59:00",
        all_day=True, share_from=sid,
    ))
    assert r.status_code == 200, r.text
    assert [d for d, _, _ in _items_of(_list(student2), "运动会")] == [
        "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15",
    ]

    # share_from 指向自己收来的（不是自己分配的）日程时不认账，只建给自己 ——
    # 不然班委之间互相传个日程 ID 就能往别人表里塞东西。
    # 得先把乙提成班委，否则被「不是班委」这一层挡住，测不到这个判断
    r = b.client.put(f"/api/admin/users/{ROSTER[1][0]}/role", json={"role": "committee"})
    assert r.status_code == 200, r.text
    committee2 = as_student(b, 1)
    received = [it for it in _list(committee2) if it["title"] == "运动会"][0]
    r = committee2.post("/api/schedules", json=_make_schedule(
        title="乙私自加的", start="2026-10-16T00:00:00", end="2026-10-16T23:59:00",
        all_day=True, share_from=received["id"],
    ))
    assert r.status_code == 200, r.text
    assert [it["title"] for it in _list(committee2) if it["title"] == "乙私自加的"]
    assert not [it for it in _list(b.client) if it["title"] == "乙私自加的"]


# ---------- 查询范围限制 ----------

def test_range_limit(b):
    """查询超过 92 天会被拒绝"""
    r = b.client.get("/api/schedules", params={
        "start_date": "2026-01-01", "end_date": "2026-12-31",
    })
    assert r.status_code == 400
    assert "92" in r.json()["detail"]


# ---------- 回归：重复必设结束日、单双周基准 ----------

def test_repeat_without_end_rejected(b):
    """后端兜底：重复日程必须设结束日期，直接调接口也不能漏"""
    data = _make_schedule(
        title="缺结束日的重复",
        start="2026-10-12T08:00:00",
        end="2026-10-12T09:00:00",
        repeat_type="weekly",
        repeat_end_date=None,
    )
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 400
    assert "结束日期" in r.json()["detail"]


def test_odd_week_expansion_honors_week_start(b):
    """单双周展开以持久化的 week_start 为基准，而非开始日期所在周

    这里直接构造模板：week_start=2026-09-01（第1周·单），
    日程 start=2026-09-08（第2周·双），repeat_type=even_week。
    基准生效的话 09-08 本身就该是「双周」并出现；
    若退化到「以 start 所在周为第1周」，09-08 会被当成第1周·单而被跳过。
    """
    from app.services.schedule_service import _next_occurrence
    from app.models.schedule import REPEAT_EVEN_WEEK
    from app.models import Schedule

    tpl = Schedule(
        student_id=1, title="双周课", location="", description="",
        start_time=datetime(2026, 9, 8, 9, 0),
        end_time=datetime(2026, 9, 8, 10, 0),
        repeat_type=REPEAT_EVEN_WEEK,
        repeat_end_date=date(2026, 9, 30),
        week_start=date(2026, 9, 1),  # 第1周周一，单周
        notify_enabled=False, notify_minutes_before=10,
        source_type="personal",
    )
    assert _next_occurrence(tpl, date(2026, 9, 8)) == date(2026, 9, 8)
    # 下一个偶数周（第4周）
    assert _next_occurrence(tpl, date(2026, 9, 9)) == date(2026, 9, 22)


def test_manual_odd_week_fallback_consistent(b):
    """手动创建单双周（没有 week_start）时，以开始日期所在周为第1周，自洽不崩"""
    data = _make_schedule(
        title="双周值班",
        start="2026-10-12T08:00:00",  # 被当作第1周（单）
        end="2026-10-12T09:00:00",
        repeat_type="even_week",
        repeat_end_date="2026-10-26",
    )
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200, r.text

    # 第1周（单）当天、第3周都不该出现；第2周（双）出现
    r = b.client.get("/api/schedules", params={
        "start_date": "2026-10-12", "end_date": "2026-10-25",
    })
    items = r.json()
    dates = [it["instance_date"] for it in items]
    assert "2026-10-12" not in dates
    assert "2026-10-19" in dates


# ---------- 周次（跟表名，不靠前端估算） ----------

def test_semester_week_follows_sheet_name(b):
    """周次跟表名走：导入时记下「学期第 1 周的周一」，页面按它算第几周

    夹具第 1 周周一是 10/12、第 2 周是 10/19，由表名折算出的基准两周边有同一个。
    前端曾经按「9 月 1 日所在周」自己估第 1 周，比表名早两周 —— 表名「第4周」
    的课在页面上会显示成第 6 周（用户报的就是这个）。
    """
    r = b.client.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", _make_schedule_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    r = b.client.post("/api/schedules/import", json={
        "token": r.json()["token"],
        "batch_name": "秋季课表",
        "target_all": True,
        "target_student_ids": [],
        "selected_indices": [],
    })
    assert r.status_code == 200, r.text

    # 两个 sheet 折算出的基准必须一致，并且都落到了日程上
    assert b.rows("SELECT DISTINCT week_start FROM schedules") == [("2026-10-12",)]

    # 接口把基准交回前端（页面上的「第几周」按它算）
    info = b.client.get("/api/schedules/semester")
    assert info.status_code == 200, info.text
    assert info.json()["week_start"] == "2026-10-12"


def test_semester_info_falls_back_to_earliest_schedule(b):
    """没写过 week_start 的老数据：退回最早那条日程所在周的周一

    升级前导入的课表没有这一列，不能让周次因此整个消失。
    """
    data = _make_schedule(title="老日程", start="2026-10-15T08:00:00", end="2026-10-15T09:40:00")
    r = b.client.post("/api/schedules", json=data)
    assert r.status_code == 200, r.text
    # 手动创建的日程不带基准（只有课表导入才写）
    assert b.rows("SELECT DISTINCT week_start FROM schedules") == [(None,)]

    info = b.client.get("/api/schedules/semester")
    assert info.status_code == 200, info.text
    assert info.json()["week_start"] == "2026-10-12"   # 10/15 是周四，所在周周一


def test_semester_info_empty_without_schedules(b):
    """一条日程都没有时返回空 —— 前端就不显示周次，而不是硬估一个错的"""
    info = b.client.get("/api/schedules/semester")
    assert info.status_code == 200, info.text
    assert info.json()["week_start"] is None
