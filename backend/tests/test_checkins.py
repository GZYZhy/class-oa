"""签到式点名的回归：发布、站内信、签到、定位、照片与结算

    cd backend && python -m pytest tests/test_checkins.py -q

盯的是结算规则本身（用户口径）：

- 签到了 → 「到」。持有有效请假的人**同样能签**，签了也算「到」；
- 没签、且截止那一刻在已批准请假区间内 → 「请假」；
- 其余 → 「无应答」。

第二容易写丢的是结算的参考时刻：要按 `closed_at or end_at` 算，不是按
「懒结算碰巧被触发的那一刻」算 —— 否则班委隔一天才打开考勤页，截止之后
才开始的请假会被误算进来，而且这种错在页面上看不出来，只是一片「请假」。

第三个坑是路由顺序：`/public/{code}` 必须排在 `/{checkin_id}` 前面，
不然公开页会撞上数字解析直接 422（本文件第一条用例就用未登录请求兜住它）。
"""
from datetime import datetime, timedelta

import pytest

from conftest import png_bytes

PW = "initpass123"
ADMIN = "2024000001"
ADMIN_PW = "010001"

# 学号 → 姓名。密码是身份证后 6 位，即 010002 起的这一串
PEOPLE = [
    ("2024000002", "学生02"),
    ("2024000003", "学生03"),
    ("2024000004", "学生04"),
    ("2024000005", "学生05"),
    ("2024000006", "学生06"),
]
# 身份证是「11010120050101」+ 学号后四位，所以后六位是 01 + 后四位
STUDENT_PW = {no: "01" + no[-4:] for no, _ in PEOPLE}

# 发布时用的坐标（武汉一带随便取的一点，GCJ-02）
LAT, LNG = 30.5000, 114.3000
PNG = png_bytes()


def _world(backend, db_name):
    """初始化完毕、库里 1 个管理员 + 5 个学生，管理员已登录（同 test_polls）"""
    b = backend(db=db_name, BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200

    r = b.client.post("/api/students", json={
        "student_no": ADMIN, "name": "甲", "id_card": "110101200501010001",
    })
    assert r.status_code < 300, r.text

    for no, name in PEOPLE:
        r = b.client.post("/api/students", json={
            "student_no": no,
            "name": name,
            "id_card": f"11010120050101{no[-4:]}",
        })
        assert r.status_code < 300, r.text

    assert b.client.post("/api/setup/finish", json={"admin_student_no": ADMIN}).status_code == 200
    b.logout()
    assert b.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200
    return b


@pytest.fixture
def cb(backend):
    return _world(backend, "checkins.db")


# ---------- 小工具 ----------

def _login(b, student_no):
    b.logout()
    r = b.login(student_no=student_no, password=STUDENT_PW[student_no])
    assert r.status_code == 200, r.text


def _as_admin(b):
    b.logout()
    assert b.login(student_no=ADMIN, password=ADMIN_PW).status_code == 200


def _end_at(minutes=30):
    return datetime.now() + timedelta(minutes=minutes)


def _create(b, targets, *, minutes=30, title="晚点名", remark="宿舍区集合",
            require_photo=False, location=None, end_at=None):
    payload = {
        "title": title,
        "remark": remark,
        "targets": list(targets),
        "end_at": (end_at or _end_at(minutes)).strftime("%Y-%m-%dT%H:%M:%S"),
        "require_photo": require_photo,
        "location": location,
    }
    r = b.client.post("/api/checkins", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _sign(b, code, *, lat=None, lng=None, photo=None):
    """提交签到。

    总带一个占位表单字段：Starlette 在 Content-Type 不是表单时会抛断言，
    而 FastAPI 的 Form(None) 只认 multipart / urlencoded。真实前端用 FormData
    没这个问题，测试里空 body 会直接 500，别被误导成「签到接口炸了」。
    """
    data = {"source": "test"}
    if lat is not None:
        data["lat"] = str(lat)
    if lng is not None:
        data["lng"] = str(lng)
    files = {"photo": ("签到.png", photo, "image/png")} if photo is not None else None
    return b.client.post(
        f"/api/checkins/public/{code}/sign", data=data, files=files
    )


def _add_leave(b, student_no, start, end, status="approved"):
    """直接往库里塞一条请假。接口那条链路（审批、签字）不是本文件要测的"""
    sid = b.rows("SELECT id FROM students WHERE student_no=?", student_no)[0][0]
    name = dict(PEOPLE).get(student_no, "")
    fmt = "%Y-%m-%d %H:%M:%S.%f"
    b.run(
        "INSERT INTO leave_requests "
        "(student_id, student_no, student_name, leave_type, start_at, end_at, "
        " reason, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        sid, student_no, name, "事假",
        start.strftime(fmt), end.strftime(fmt), "回家", status,
        datetime.now().strftime(fmt),
    )


def _force_end(b, checkin_id, past_minutes=5):
    """把截止时间拨到过去，模拟「到点」；结算由下一次读接口触发"""
    end_at = datetime.now() - timedelta(minutes=past_minutes)
    b.run(
        "UPDATE checkins SET end_at=? WHERE id=?",
        end_at.strftime("%Y-%m-%d %H:%M:%S.%f"), checkin_id,
    )


def _attendance_of(b, scope):
    """拉考勤列表（内部会先做懒结算），返回 scope 对应的那一条"""
    r = b.client.get("/api/attendance")
    assert r.status_code == 200, r.text
    return next((x for x in r.json()["items"] if x["scope"] == scope), None)


# ---------- 发布与权限 ----------

def test_create_returns_code_and_link(cb):
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]])
    code = checkin["code"]

    assert code and len(code) >= 10
    base = str(cb.client.base_url).rstrip("/")
    assert checkin["link"] == f"{base}/#/checkin?code={code}"
    assert checkin["status"] == "ongoing"
    assert checkin["target_count"] == 2
    assert checkin["signed_count"] == 0
    assert checkin["created_by_no"] == ADMIN
    # 姓名以 Student 表为准
    assert {t["student_name"] for t in checkin["targets"]} == {"学生02", "学生03"}
    assert all(t["signed_at"] is None for t in checkin["targets"])

    # 普通学生既不能发布，也看不到班委端的列表
    _login(cb, PEOPLE[0][0])
    r = cb.client.post("/api/checkins", json={
        "title": "偷偷点名", "targets": [PEOPLE[0][0]],
        "end_at": _end_at().strftime("%Y-%m-%dT%H:%M:%S"),
    })
    assert r.status_code == 403, r.text
    assert cb.client.get("/api/checkins").status_code == 403


def test_create_rejects_past_end_and_unknown_student(cb):
    past = datetime.now() - timedelta(minutes=1)
    r = cb.client.post("/api/checkins", json={
        "title": "迟到", "targets": [PEOPLE[0][0]],
        "end_at": past.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    assert r.status_code == 400
    assert "截止时间" in r.json()["detail"]

    r = cb.client.post("/api/checkins", json={
        "title": "幽灵", "targets": ["9999999999"],
        "end_at": _end_at().strftime("%Y-%m-%dT%H:%M:%S"),
    })
    assert r.status_code == 400
    assert "不在名单中" in r.json()["detail"]

    # 带时区的写法直接拒：naive 的 now() 和 aware 的时间没法比
    r = cb.client.post("/api/checkins", json={
        "title": "时区", "targets": [PEOPLE[0][0]],
        "end_at": "2099-01-01T10:00:00+08:00",
    })
    assert r.status_code == 400
    assert "不带时区" in r.json()["detail"]


# ---------- 站内信 ----------

def test_targets_get_inbox_message_and_creator_does_not(cb):
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]])
    code = checkin["code"]

    _login(cb, PEOPLE[0][0])
    r = cb.client.get("/api/inbox")
    assert r.status_code == 200, r.text
    hits = [m for m in r.json()["items"] if m["title"] == "新签到：晚点名"]
    assert len(hits) == 1, "目标学生应当收到一条站内信"
    assert hits[0]["page"] == f"/checkin?code={code}"
    assert hits[0]["level"] == "timeSensitive"

    # 发起人自己不该收到「我刚发布的签到」
    _as_admin(cb)
    r = cb.client.get("/api/inbox")
    assert r.status_code == 200, r.text
    assert not [m for m in r.json()["items"] if m["title"] == "新签到：晚点名"]


# ---------- 公开信息 ----------

def test_public_info_works_anonymously(cb):
    checkin = _create(cb, [PEOPLE[0][0]])
    code = checkin["code"]
    cb.logout()

    # 未登录可看（这条同时兜住路由顺序：撞上 /{checkin_id} 会是 422 而不是 200）
    r = cb.client.get(f"/api/checkins/public/{code}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["title"] == "晚点名"
    assert data["is_login"] is False
    assert data["is_target"] is False
    assert data["can_sign"] is False

    assert cb.client.get("/api/checkins/public/notthere").status_code == 404

    _login(cb, PEOPLE[0][0])
    data = cb.client.get(f"/api/checkins/public/{code}").json()
    assert data["is_login"] is True
    assert data["is_target"] is True
    assert data["can_sign"] is True

    _login(cb, PEOPLE[4][0])   # 不在范围内
    data = cb.client.get(f"/api/checkins/public/{code}").json()
    assert data["is_target"] is False
    assert data["can_sign"] is False


# ---------- 签到 ----------

def test_sign_success_repeat_and_outsider(cb):
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]])
    code = checkin["code"]

    cb.logout()
    assert _sign(cb, code).status_code == 401, "未登录不能签到"

    _login(cb, PEOPLE[0][0])
    r = _sign(cb, code)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["signed_at"] is not None
    assert data["can_sign"] is False

    r = _sign(cb, code)
    assert r.status_code == 400
    assert "已签到" in r.json()["detail"]

    _login(cb, PEOPLE[4][0])
    r = _sign(cb, code)
    assert r.status_code == 400
    assert "不在本次签到范围内" in r.json()["detail"]


def test_location_radius_and_distance(cb):
    loc = {"lat": LAT, "lng": LNG, "radius_m": 100, "name": "宿舍楼下"}
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]], location=loc)
    code = checkin["code"]
    assert checkin["location"]["radius_m"] == 100

    _login(cb, PEOPLE[0][0])
    # 没带坐标直接拒
    r = _sign(cb, code)
    assert r.status_code == 400
    assert "需要获取你的位置" in r.json()["detail"]

    # 半径外（纬度差 0.01° ≈ 1.1 公里）
    r = _sign(cb, code, lat=LAT + 0.01, lng=LNG)
    assert r.status_code == 400
    assert "超出允许范围" in r.json()["detail"]

    # 半径内（约 55 米）
    r = _sign(cb, code, lat=LAT + 0.0005, lng=LNG)
    assert r.status_code == 200, r.text
    distance = r.json()["my_distance_m"]
    assert 30 <= distance <= 80, distance

    _login(cb, PEOPLE[1][0])
    r = cb.client.get(f"/api/checkins/public/{code}")
    assert r.json()["my_distance_m"] is None


def test_photo_required_and_photo_access(cb):
    checkin = _create(cb, [PEOPLE[0][0]], require_photo=True)
    code = checkin["code"]

    _login(cb, PEOPLE[0][0])
    r = _sign(cb, code)
    assert r.status_code == 400
    assert "需要上传一张照片" in r.json()["detail"]

    r = _sign(cb, code, photo=PNG)
    assert r.status_code == 200, r.text

    # 照片确实落进了 CHECKIN_DIR（conftest 把它指到临时目录的 checkins 下）
    rows = cb.rows(
        "SELECT photo_file FROM checkin_targets WHERE student_no=?", PEOPLE[0][0]
    )
    assert rows and rows[0][0]
    path = cb.db.parent / "checkins" / rows[0][0]
    assert path.is_file() and path.read_bytes() == PNG

    # 班委能看，普通学生不能
    _as_admin(cb)
    r = cb.client.get(f"/api/checkins/{checkin['id']}/targets/{PEOPLE[0][0]}/photo")
    assert r.status_code == 200
    assert r.content == PNG
    assert r.headers.get("cache-control") == "no-store"

    _login(cb, PEOPLE[1][0])
    r = cb.client.get(f"/api/checkins/{checkin['id']}/targets/{PEOPLE[0][0]}/photo")
    assert r.status_code == 403


# ---------- 结算 ----------

def test_settlement_three_states(cb):
    # 02 签到；03、04 有已批准请假但不签；05 没假也不签
    checkin = _create(cb, [no for no, _ in PEOPLE[:4]])
    code, cid = checkin["code"], checkin["id"]

    now = datetime.now()
    _add_leave(cb, PEOPLE[1][0], now - timedelta(hours=1), now + timedelta(hours=2))
    _add_leave(cb, PEOPLE[2][0], now - timedelta(hours=1), now + timedelta(hours=2))

    _login(cb, PEOPLE[0][0])
    assert _sign(cb, code).status_code == 200

    _force_end(cb, cid)
    _as_admin(cb)

    record = _attendance_of(cb, "签到·4人")
    assert record is not None, "到点后应自动生成一条签到考勤"
    assert record["total"] == 4

    detail = cb.client.get(f"/api/attendance/{record['id']}").json()
    status = {i["student_no"]: i["status"] for i in detail["items"]}
    assert status == {
        PEOPLE[0][0]: "present",
        PEOPLE[1][0]: "leave",
        PEOPLE[2][0]: "leave",
        PEOPLE[3][0]: "absent",
    }

    # 签到本身也翻成已结束，详情里请假标记对得上
    data = cb.client.get(f"/api/checkins/{cid}").json()
    assert data["status"] == "ended"
    assert data["finalized_at"] is not None
    by_no = {t["student_no"]: t for t in data["targets"]}
    assert by_no[PEOPLE[0][0]]["signed_at"] is not None
    assert by_no[PEOPLE[1][0]]["on_leave"] is True
    assert by_no[PEOPLE[3][0]]["on_leave"] is False


def test_student_on_leave_can_sign_and_counts_present(cb):
    checkin = _create(cb, [PEOPLE[0][0]])
    now = datetime.now()
    _add_leave(cb, PEOPLE[0][0], now - timedelta(hours=1), now + timedelta(hours=2))

    _login(cb, PEOPLE[0][0])
    r = cb.client.get(f"/api/checkins/public/{checkin['code']}")
    assert r.json()["on_leave"] is True, "有效请假不影响签到资格"

    r = _sign(cb, checkin["code"])
    assert r.status_code == 200, r.text

    _force_end(cb, checkin["id"])
    _as_admin(cb)
    record = _attendance_of(cb, "签到·1人")
    detail = cb.client.get(f"/api/attendance/{record['id']}").json()
    assert detail["items"][0]["status"] == "present", "签了就是到"


def test_close_ends_immediately_and_blocks_late_sign(cb):
    checkin = _create(cb, [PEOPLE[0][0]])
    cid = checkin["id"]

    r = cb.client.post(f"/api/checkins/{cid}/close")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ended"
    assert data["finalized_at"] is not None

    # 提前结束也当场结算
    record = _attendance_of(cb, "签到·1人")
    assert record is not None
    detail = cb.client.get(f"/api/attendance/{record['id']}").json()
    assert detail["items"][0]["status"] == "absent"

    _login(cb, PEOPLE[0][0])
    r = _sign(cb, checkin["code"])
    assert r.status_code == 400
    assert "已经结束" in r.json()["detail"]

    # 再结束一次是 400，不是又生成一条考勤
    _as_admin(cb)
    assert cb.client.post(f"/api/checkins/{cid}/close").status_code == 400


def test_generated_attendance_cannot_be_deleted(cb):
    checkin = _create(cb, [PEOPLE[0][0]])
    assert cb.client.post(f"/api/checkins/{checkin['id']}/close").status_code == 200
    record = _attendance_of(cb, "签到·1人")

    r = cb.client.delete(f"/api/attendance/{record['id']}")
    assert r.status_code == 400
    assert "签到自动生成" in r.json()["detail"]

    # 普通点名生成的记录仍然能删（别把保护做成一刀切）
    r = cb.client.post("/api/attendance", json={
        "scope": "临时集合",
        "records": [{"student_no": PEOPLE[0][0], "name": "学生02", "status": "present"}],
    })
    assert r.status_code == 200, r.text
    assert cb.client.delete(f"/api/attendance/{r.json()['id']}").status_code == 200


def test_settlement_uses_deadline_not_trigger_moment(cb):
    """截止时刻之后才开始的请假，不能算进这次签到

    这正是「按 closed_at or end_at 结算」的意义：班委隔天才打开页面时，
    懒结算发生在请假开始之后，用「现在」当参考时刻会把无应答洗成请假。
    """
    checkin = _create(cb, [PEOPLE[0][0]])
    # 截止拨到 2 小时前；请假从 1 小时前开始 —— 截止那一刻这个人并不在假期里
    _force_end(cb, checkin["id"], past_minutes=120)
    now = datetime.now()
    _add_leave(cb, PEOPLE[0][0], now - timedelta(hours=1), now + timedelta(hours=2))

    record = _attendance_of(cb, "签到·1人")
    detail = cb.client.get(f"/api/attendance/{record['id']}").json()
    assert detail["items"][0]["status"] == "absent"
