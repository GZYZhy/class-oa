"""我的日程模块测试

覆盖：CRUD、重复日程展开、导入解析、iCal 生成、权限隔离、通知默认关闭

cd backend && python -m pytest tests/test_schedules.py -q
"""
from io import BytesIO
from datetime import date, datetime

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

    两个曾经踩过的坑：
    1. 只读 B 列 —— 事件写在它覆盖的那一天的列里，真实课表的「国庆放假」
       横跨 7 列，只读 B 列会让后面 6 天整片消失；
    2. 把全天事件塞进以「星期+开始时间」为键的字典 —— 凌晨 00:00 撞车，
       同一天的第二条会把第一条覆盖掉。
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
        ("2026-10-17", "运动会"),           # 周六
        ("2026-10-18", "运动会"),           # 周日（同一段文字的第二列）
        ("2026-10-18", "收假返校"),         # 周日同一天的第二条
        ("2026-10-19", "正式活动 10/19"),   # 第 2 周周一
    ]
    # 全天事件不参与重复推断，类型/地点为空
    assert all(it["repeat_type"] == "none" for it in allday)
    assert all(it["event_type"] == "" and it["location"] == "" for it in allday)


def test_import_confirm_writes_to_targets(b):
    """导入确认：目标学生都拿到了日程"""
    xlsx_bytes = _make_schedule_xlsx()

    r = b.client.post(
        "/api/schedules/import/preview",
        files={"file": ("课表.xlsx", xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
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
    # 夹具忠实展平共 8 条（高数2 + 英语1 + 全天5），每人一份
    assert result["target_count"] == len(all_ids)
    assert result["schedule_per_student"] == 8
    assert result["total_created"] == 8 * len(all_ids)

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

    # 看批次列表 —— 上面是单条日程的批量创建，不会产生 schedule_batch 记录
    # 只有导入才产生批次。所以这里用导入来测
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
