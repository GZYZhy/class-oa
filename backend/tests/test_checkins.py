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
import base64
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook

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


def _world(backend, db_name, **env):
    """初始化完毕、库里 1 个管理员 + 5 个学生，管理员已登录（同 test_polls）

    `**env` 原样传给后端子进程；测开页凭证时要把 SESSION_SECRET_KEY 钉死，
    测试进程才签得出服务端认得出的 Cookie。
    """
    b = backend(db=db_name, BOOTSTRAP_PASSWORD=PW, **env)
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


def _upload_photo(b, code, photo=PNG):
    """先在选照片时上传，拿回签到用的令牌"""
    r = b.client.post(
        f"/api/checkins/public/{code}/photo",
        files={"photo": ("签到.png", photo, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _sign(b, code, *, lat=None, lng=None, photo_token=None):
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
    if photo_token:
        data["photo_token"] = photo_token
    return b.client.post(f"/api/checkins/public/{code}/sign", data=data)


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


def _open_token(secret, checkin_id, opened_at, student_no=""):
    """照后端 `_open_token` 的样子签一张开页凭证

    只有显式配了 SESSION_SECRET_KEY 的用例才能调 —— 平时服务端密钥是启动时
    随机生成、存在数据目录里的，测试进程拿不到，也不该去拿。
    """
    payload = f"{checkin_id}:{student_no}:{int(opened_at.timestamp())}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


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

def test_targets_and_creator_in_range_get_inbox_message(cb):
    checkin = _create(cb, [PEOPLE[0][0], ADMIN])
    code = checkin["code"]

    _login(cb, PEOPLE[0][0])
    r = cb.client.get("/api/inbox")
    assert r.status_code == 200, r.text
    hits = [m for m in r.json()["items"] if m["title"] == "新签到：晚点名"]
    assert len(hits) == 1, "目标学生应当收到一条站内信"
    assert hits[0]["page"] == f"/checkin?code={code}"
    assert hits[0]["level"] == "timeSensitive"

    # 发布人自己在范围内时同样要签到，也该收到这条信
    _as_admin(cb)
    r = cb.client.get("/api/inbox")
    assert r.status_code == 200, r.text
    hits = [m for m in r.json()["items"] if m["title"] == "新签到：晚点名"]
    assert len(hits) == 1, "发布人在范围内时应当收到站内信"

    # 不在范围内就不发（再发一次，范围只有别人）
    _create(cb, [PEOPLE[1][0]], title="晚点名二")
    r = cb.client.get("/api/inbox")
    hits = [m for m in r.json()["items"] if m["title"] == "新签到：晚点名二"]
    assert not hits, "不在范围内的发布人不该收到"


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


def test_public_info_still_readable_after_end(cb):
    """截止之后链接照样能打开：地点、地图和要求的字段都还在，只是不能再签"""
    loc = {"lat": LAT, "lng": LNG, "radius_m": 80, "name": "一公寓门口"}
    checkin = _create(cb, [PEOPLE[0][0]], require_photo=True, location=loc)
    _force_end(cb, checkin["id"])
    cb.logout()

    r = cb.client.get(f"/api/checkins/public/{checkin['code']}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ended"
    assert data["title"] == "晚点名"
    assert data["require_photo"] is True
    assert data["location"] == {
        "lat": LAT, "lng": LNG, "radius_m": 80, "name": "一公寓门口",
    }
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

    token = _upload_photo(cb, code)
    r = _sign(cb, code, photo_token=token)
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


def test_photo_uploaded_before_deadline_still_signs_after(cb):
    """照片选中就先传；截止前开始传的，传完过点也能签上，并改回「到」

    真实场景：19:59 开始传一张大照片，20:00 才传完、点签到。服务端收到
    「签到」时已经过点，但照片令牌签着 19:59 的上传开始时间，应当接受。
    """
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]], require_photo=True)
    code = checkin["code"]

    _login(cb, PEOPLE[0][0])
    token = _upload_photo(cb, code)

    # 别人的照片令牌不能用（学号对不上）
    _login(cb, PEOPLE[1][0])
    r = _sign(cb, code, photo_token=token)
    assert r.status_code == 400
    assert "照片凭证无效" in r.json()["detail"]

    # 改过令牌的签名也不行
    _login(cb, PEOPLE[0][0])
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert _sign(cb, code, photo_token=tampered).status_code == 400

    # 把截止时间挪到「上传开始之后、现在之前」，再读一次考勤触发结算：
    # 这一刻本人还没签，结算会把他记成「无应答」
    end_at = datetime.now() + timedelta(seconds=1)
    cb.run(
        "UPDATE checkins SET end_at=? WHERE id=?",
        end_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        checkin["id"],
    )
    time.sleep(1.2)
    _as_admin(cb)
    assert _attendance_of(cb, "签到·2人") is not None
    # 列表里签到行的 id 不是考勤记录 id，明细要用 checkins 表里记的那个
    record_id = cb.rows(
        "SELECT attendance_record_id FROM checkins WHERE id=?", checkin["id"]
    )[0][0]
    assert record_id

    # 过了点，但照片是截止前开始传的：仍可签到，状态是「到」
    _login(cb, PEOPLE[0][0])
    r = _sign(cb, code, photo_token=token)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ended"
    assert data["signed_at"] is not None

    # 结算生成的考勤明细跟着改回来，不能签到页说到、明细里却还是无应答
    _as_admin(cb)
    detail = cb.client.get(f"/api/attendance/{record_id}").json()
    items = {i["student_no"]: i["status"] for i in detail["items"]}
    assert items[PEOPLE[0][0]] == "present"
    assert items[PEOPLE[1][0]] == "absent"

    # 没带照片令牌的人，过了点就是不能签
    _login(cb, PEOPLE[1][0])
    r = _sign(cb, code)
    assert r.status_code == 400
    assert "已经结束" in r.json()["detail"]

    # 截止后才开始选照片上传，同样拒绝
    _as_admin(cb)
    ended = _create(cb, [PEOPLE[2][0]], require_photo=True)
    _force_end(cb, ended["id"])
    _login(cb, PEOPLE[2][0])
    r = cb.client.post(
        f"/api/checkins/public/{ended['code']}/photo",
        files={"photo": ("签到.png", PNG, "image/png")},
    )
    assert r.status_code == 400
    assert "已经结束" in r.json()["detail"]


def test_page_opened_before_deadline_signs_after_login(cb):
    """打开链接时还没登录：登录花掉的时间不该让人白跑一趟

    真实路径：群里发链接 → 学生点开（没登录，只看到标题和地点）→ 找学号、
    输密码 → 回来时截止时间已经过了。只要页面是截止前打开的，截止后 10 分钟内
    仍能签上，并且要求照片的也能在这段时间里传照片。
    """
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]], require_photo=True)
    code, cid = checkin["code"], checkin["id"]
    cookie_name = f"checkin_open_{cid}"

    # 游客点开链接：信息照常可读，同时拿到一张开页凭证
    cb.logout()
    assert cb.client.get(f"/api/checkins/public/{code}").status_code == 200
    assert cb.client.cookies.get(cookie_name), "进行中的页面打开时就该发凭证"

    # 登录期间截止时间到了
    end_at = datetime.now() + timedelta(seconds=1)
    cb.run(
        "UPDATE checkins SET end_at=? WHERE id=?",
        end_at.strftime("%Y-%m-%d %H:%M:%S.%f"), cid,
    )
    time.sleep(1.2)

    # 登录回来：页面已结束，但公开信息明说还在补签宽限内
    _login(cb, PEOPLE[0][0])
    data = cb.client.get(f"/api/checkins/public/{code}").json()
    assert data["status"] == "ended"
    assert data["grace_until"] is not None
    assert data["can_sign"] is True

    # 要求照片的签到：宽限内照片照样能传，传完再签
    token = _upload_photo(cb, code)
    r = _sign(cb, code, photo_token=token)
    assert r.status_code == 200, r.text
    assert r.json()["signed_at"] is not None
    # 结算已经跑过（这个人本来是「无应答」），签到后明细要改回「到」
    _as_admin(cb)
    record_id = cb.rows(
        "SELECT attendance_record_id FROM checkins WHERE id=?", cid
    )[0][0]
    detail = cb.client.get(f"/api/attendance/{record_id}").json()
    items = {i["student_no"]: i["status"] for i in detail["items"]}
    assert items[PEOPLE[0][0]] == "present"

    # 同浏览器里没打开过页面的人：清掉凭证后过了点就是签不上
    cb.client.cookies.delete(cookie_name)
    _login(cb, PEOPLE[1][0])
    data = cb.client.get(f"/api/checkins/public/{code}").json()
    assert data["grace_until"] is None
    assert data["can_sign"] is False
    r = _sign(cb, code)
    assert r.status_code == 400
    assert "已经结束" in r.json()["detail"]


def test_open_grace_is_bounded_and_forged_token_rejected(backend):
    """补签宽限有线：开页早于截止，但过了 10 分钟照样签不上；伪造凭证不算数

    服务端密钥在这里钉死，测试进程才签得出合法凭证 —— 正常部署时它是启动
    时随机生成的，外部拿不到，这正是伪造不了的原因。
    """
    secret = "checkins-grace-test-secret"
    cb = _world(backend, "checkin_grace.db", SESSION_SECRET_KEY=secret)
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]])
    code, cid = checkin["code"], checkin["id"]
    cookie_name = f"checkin_open_{cid}"

    def set_end_and_cookie(reference, *, student_no=""):
        cb.run(
            "UPDATE checkins SET end_at=? WHERE id=?",
            reference.strftime("%Y-%m-%d %H:%M:%S.%f"), cid,
        )
        token = _open_token(secret, cid, reference - timedelta(minutes=1), student_no)
        cb.client.cookies.set(cookie_name, token, path="/api/checkins")
        return token

    # 40 分钟前截止：开页凭证是真的，但 10 分钟宽限早过了
    set_end_and_cookie(datetime.now() - timedelta(minutes=40))
    _login(cb, PEOPLE[0][0])
    data = cb.client.get(f"/api/checkins/public/{code}").json()
    assert data["status"] == "ended"
    assert data["grace_until"] is None
    assert data["can_sign"] is False
    r = _sign(cb, code)
    assert r.status_code == 400
    assert "已经结束" in r.json()["detail"]

    # 截止刚过 5 分钟：凭证本身合法，但故意改坏最后一个字符就不认了
    token = set_end_and_cookie(datetime.now() - timedelta(minutes=5))
    cb.client.cookies.set(
        cookie_name, token[:-1] + ("A" if token[-1] != "A" else "B"),
        path="/api/checkins",
    )
    r = _sign(cb, code)
    assert r.status_code == 400, "篡改过的凭证不能放行"
    assert "已经结束" in r.json()["detail"]

    # 换回真凭证：同一个截止时刻、同一个人，就签得上 —— 差别只在凭证
    cb.client.cookies.set(cookie_name, token, path="/api/checkins")
    data = cb.client.get(f"/api/checkins/public/{code}").json()
    assert data["grace_until"] is not None
    assert data["can_sign"] is True
    r = _sign(cb, code)
    assert r.status_code == 200, r.text


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


def test_extend_deadline_by_five_minutes(cb):
    """截止前可以反复延 5 分钟；到点或结束后就不行了"""
    checkin = _create(cb, [PEOPLE[0][0]])
    cid = checkin["id"]
    old = datetime.fromisoformat(checkin["end_at"])

    r = cb.client.post(f"/api/checkins/{cid}/extend")
    assert r.status_code == 200, r.text
    new = datetime.fromisoformat(r.json()["end_at"])
    assert new - old == timedelta(minutes=5)

    # 无限续杯：再点一次还是 +5 分钟
    r = cb.client.post(f"/api/checkins/{cid}/extend")
    assert r.status_code == 200, r.text
    assert datetime.fromisoformat(r.json()["end_at"]) - new == timedelta(minutes=5)

    # 已经过了截止时间（哪怕还没懒结算）就不能再延长
    _force_end(cb, cid)
    r = cb.client.post(f"/api/checkins/{cid}/extend")
    assert r.status_code == 400
    assert "不能再延长" in r.json()["detail"]

    # 已结束的签到同样拒绝
    closed = _create(cb, [PEOPLE[1][0]], title="另一场")
    assert cb.client.post(f"/api/checkins/{closed['id']}/close").status_code == 200
    r = cb.client.post(f"/api/checkins/{closed['id']}/extend")
    assert r.status_code == 400
    assert "已经结束" in r.json()["detail"]

    # 普通学生没有这个权限
    _login(cb, PEOPLE[1][0])
    assert cb.client.post(f"/api/checkins/{closed['id']}/extend").status_code == 403


def test_remind_only_unsigned_targets(cb):
    """提醒只发给还没签到的人，可以反复提醒；结束后不能提醒"""
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]])
    cid = checkin["id"]

    _login(cb, PEOPLE[0][0])
    assert _sign(cb, checkin["code"]).status_code == 200
    _as_admin(cb)

    r = cb.client.post(f"/api/checkins/{cid}/remind")
    assert r.status_code == 200, r.text
    assert r.json()["reminded"] == 1

    # 没签到的那位收到提醒，已签到的那位不再被打扰
    _login(cb, PEOPLE[1][0])
    inbox = cb.client.get("/api/inbox").json()["items"]
    hits = [m for m in inbox if m["title"] == "提醒签到：晚点名"]
    assert len(hits) == 1
    assert hits[0]["page"] == f"/checkin?code={checkin['code']}"

    _login(cb, PEOPLE[0][0])
    inbox = cb.client.get("/api/inbox").json()["items"]
    assert not [m for m in inbox if m["title"] == "提醒签到：晚点名"]

    # 反复提醒仍然只找没签的人
    _as_admin(cb)
    r = cb.client.post(f"/api/checkins/{cid}/remind")
    assert r.status_code == 200, r.text
    assert r.json()["reminded"] == 1

    # 结束后不能提醒
    closed = _create(cb, [PEOPLE[2][0]], title="即将结束")
    assert cb.client.post(f"/api/checkins/{closed['id']}/close").status_code == 200
    assert cb.client.post(f"/api/checkins/{closed['id']}/remind").status_code == 400

    # 普通学生没有这个权限
    _login(cb, PEOPLE[1][0])
    assert cb.client.post(f"/api/checkins/{cid}/remind").status_code == 403


def test_last_signature_ends_and_settles_immediately(cb):
    """应到的人都签完 → 不用等截止，立即结束并结算"""
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]])

    _login(cb, PEOPLE[0][0])
    r = _sign(cb, checkin["code"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ongoing", "还有一个人没签，继续进行"

    _login(cb, PEOPLE[1][0])
    r = _sign(cb, checkin["code"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ended", "最后一个人签完应立即结束"
    assert data["signed_at"] is not None

    # 结算当场生成，所有人都算「到」
    _as_admin(cb)
    record = _attendance_of(cb, "签到·2人")
    detail = cb.client.get(f"/api/attendance/{record['id']}").json()
    assert {i["status"] for i in detail["items"]} == {"present"}

    # 已结束的签到不能再手动结束
    assert cb.client.post(f"/api/checkins/{checkin['id']}/close").status_code == 400


def test_deleting_generated_attendance_also_removes_checkin(cb):
    """删签到生成的那条考勤 = 删那次签到：链接、照片、考勤一起走

    统一列表里两种记录挨着排，用户分不清也不该关心谁是谁生成的。
    """
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]], require_photo=True)
    _login(cb, PEOPLE[0][0])
    token = _upload_photo(cb, checkin["code"])
    assert _sign(cb, checkin["code"], photo_token=token).status_code == 200
    _as_admin(cb)
    assert cb.client.post(f"/api/checkins/{checkin['id']}/close").status_code == 200
    record = _attendance_of(cb, "签到·2人")

    photo = cb.rows("SELECT photo_file FROM checkin_targets WHERE checkin_id=?",
                    checkin["id"])[0][0]
    photo_path = cb.db.parent / "checkins" / photo
    assert photo_path.is_file()

    r = cb.client.delete(f"/api/attendance/{record['id']}")
    assert r.status_code == 200, r.text
    assert cb.client.get(f"/api/checkins/{checkin['id']}").status_code == 404
    assert cb.client.get(f"/api/checkins/public/{checkin['code']}").status_code == 404
    assert _attendance_of(cb, "签到·2人") is None
    assert not photo_path.exists()

    # 普通点名生成的记录仍然单独删（别把级联做成一刀切）
    r = cb.client.post("/api/attendance", json={
        "scope": "临时集合",
        "records": [{"student_no": PEOPLE[0][0], "name": "学生02", "status": "present"}],
    })
    assert r.status_code == 200, r.text
    assert cb.client.delete(f"/api/attendance/{r.json()['id']}").status_code == 200


def test_batch_delete_selected_records(cb):
    """复选框批量删除：签到连带照片和结算考勤，普通点名只删自己

    签到生成的那条考勤即使没勾签到，也要把身后的签到一起删掉 ——
    否则会留下指空的历史签到。
    """
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]], require_photo=True)
    _login(cb, PEOPLE[0][0])
    token = _upload_photo(cb, checkin["code"])
    assert _sign(cb, checkin["code"], photo_token=token).status_code == 200
    _as_admin(cb)
    assert cb.client.post(f"/api/checkins/{checkin['id']}/close").status_code == 200
    generated = _attendance_of(cb, "签到·2人")
    photo = cb.rows("SELECT photo_file FROM checkin_targets WHERE checkin_id=?",
                    checkin["id"])[0][0]
    photo_path = cb.db.parent / "checkins" / photo

    ids = {}
    for scope in ("要删的", "留着的"):
        r = cb.client.post("/api/attendance", json={
            "scope": scope,
            "records": [{"student_no": PEOPLE[0][0], "name": "学生02", "status": "present"}],
        })
        assert r.status_code == 200, r.text
        ids[scope] = r.json()["id"]

    # 只勾「签到生成的考勤」和一条普通点名，不勾签到本身
    r = cb.client.post("/api/attendance/batch-delete", json={
        "record_ids": [generated["id"], ids["要删的"]],
    })
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 2

    assert _attendance_of(cb, "签到·2人") is None
    assert _attendance_of(cb, "要删的") is None
    assert _attendance_of(cb, "留着的") is not None
    assert cb.client.get(f"/api/checkins/{checkin['id']}").status_code == 404
    assert cb.client.get(f"/api/checkins/public/{checkin['code']}").status_code == 404
    assert not photo_path.exists()

    # 什么都不勾：前端按钮是禁用的，接口自己也要拦住
    r = cb.client.post("/api/attendance/batch-delete", json={})
    assert r.status_code == 400


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


def test_settled_status_can_be_edited_like_rollcall(cb):
    """结算后和点名一样，能逐人改状态；签到详情读的是同一份考勤明细"""
    checkin = _create(cb, [PEOPLE[0][0]])
    assert cb.client.post(f"/api/checkins/{checkin['id']}/close").status_code == 200

    data = cb.client.get(f"/api/checkins/{checkin['id']}").json()
    assert data["attendance_record_id"]
    assert data["targets"][0]["status"] == "absent"

    r = cb.client.patch(
        f"/api/attendance/{data['attendance_record_id']}/items/{PEOPLE[0][0]}",
        json={"status": "present"},
    )
    assert r.status_code == 200, r.text

    # 签到详情跟着变，不会一边说「无应答」一边说「到」
    data = cb.client.get(f"/api/checkins/{checkin['id']}").json()
    assert data["targets"][0]["status"] == "present"


def test_export_contains_rollcall_and_checkin_sheets(cb):
    """一个文件两个页签：点名/签到结算的考勤明细 + 签到本人的签到情况"""
    checkin = _create(cb, [PEOPLE[0][0]])
    _login(cb, PEOPLE[0][0])
    assert _sign(cb, checkin["code"]).status_code == 200
    # 唯一的应到人签完即自动结算，不用再手动结束
    _as_admin(cb)

    r = cb.client.post("/api/attendance", json={
        "scope": "临时集合",
        "records": [{"student_no": PEOPLE[1][0], "name": "学生03", "status": "present"}],
    })
    assert r.status_code == 200, r.text

    r = cb.client.get("/api/attendance/export")
    assert r.status_code == 200, r.text
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["考勤记录", "签到记录"]

    # 第一张表里两种记录都在
    scopes = {row[1] for row in wb["考勤记录"].iter_rows(min_row=2, values_only=True)}
    assert {"签到·1人", "临时集合"} <= scopes

    # 第二张表带签到本人的时间与最终状态
    header = [c.value for c in wb["签到记录"][1]]
    assert header[:5] == ["截止日期", "标题", "发布人", "截止时间", "签到状态"]
    rows = list(wb["签到记录"].iter_rows(min_row=2, values_only=True))
    assert len(rows) == 1, rows
    row = dict(zip(header, rows[0]))
    assert row["标题"] == "晚点名"
    assert row["签到情况"] == "已签到"
    assert row["签到时间"]
    assert row["出勤状态"] == "到"


# ---------- 合并列表与按勾选导出 ----------

def _export(b, **params):
    r = b.client.get("/api/attendance/export", params=params)
    assert r.status_code == 200, r.text
    return load_workbook(BytesIO(r.content))


def test_overview_merges_rollcall_and_checkin(cb):
    """一张列表里同时有点名和签到；签到结算后本行换成标准格式，不再多出一条"""
    checkin = _create(cb, [PEOPLE[0][0], PEOPLE[1][0]])
    _login(cb, PEOPLE[0][0])
    assert _sign(cb, checkin["code"]).status_code == 200
    _as_admin(cb)
    assert cb.client.post(f"/api/checkins/{checkin['id']}/close").status_code == 200

    r = cb.client.post("/api/attendance", json={
        "scope": "全班",
        "records": [
            {"student_no": PEOPLE[0][0], "name": "学生02", "status": "present"},
            {"student_no": PEOPLE[1][0], "name": "学生03", "status": "absent"},
        ],
    })
    assert r.status_code == 200, r.text

    data = cb.client.get("/api/attendance/overview").json()
    # 签到行 + 手动点名，一共两条：结算生成的那条考勤不再单独占一行
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert not any(
        i["type"] == "attendance" and i["title"] == "签到·2人"
        for i in data["items"]
    )

    chk = next(i for i in data["items"] if i["type"] == "checkin")
    assert chk["title"] == "晚点名"
    assert chk["status"] == "ended"
    assert chk["time"] is not None
    assert chk["link"].endswith(checkin["code"])
    # 结算后人数就是标准四计数：签到的算到，没签的算无应答
    assert (chk["total"], chk["present"], chk["leave"], chk["absent"]) == (2, 1, 0, 1)

    rollcall = next(
        i for i in data["items"]
        if i["type"] == "attendance" and i["title"] == "全班"
    )
    assert (rollcall["total"], rollcall["present"], rollcall["leave"], rollcall["absent"]) \
        == (2, 1, 0, 1)

    # 分页后 total 仍是全部条数
    page = cb.client.get(
        "/api/attendance/overview", params={"page": 1, "page_size": 1}
    ).json()
    assert page["total"] == 2 and len(page["items"]) == 1


def test_overview_keyword_matches_rollcall_remark_or_checkin_title(cb):
    """搜索口径固定：点名查备注、签到查标题（签到的补充说明不参与）"""
    checkin = _create(cb, [PEOPLE[0][0]], title="周六晚点名", remark="宿舍区集合")
    r = cb.client.post("/api/attendance", json={
        "scope": "全班",
        "records": [{"student_no": PEOPLE[0][0], "name": "学生02", "status": "present"}],
    })
    assert r.status_code == 200, r.text
    assert cb.client.patch(
        f"/api/attendance/{r.json()['id']}", json={"remark": "学院临时集合"}
    ).status_code == 200

    def types_of(keyword):
        data = cb.client.get(
            "/api/attendance/overview", params={"keyword": keyword}
        ).json()
        return sorted(i["type"] for i in data["items"])

    assert types_of("学院") == ["attendance"]
    assert types_of("周六晚") == ["checkin"]
    assert types_of("宿舍区") == []
    assert types_of("") == ["attendance", "checkin"]

    # 结算后也不多出一条：生成的那条考勤备注里带着标题和说明，
    # 但它归签到那一行管，搜索不会把它翻出来
    assert cb.client.post(f"/api/checkins/{checkin['id']}/close").status_code == 200
    assert types_of("学院") == ["attendance"]
    assert types_of("周六晚") == ["checkin"]
    assert types_of("宿舍区") == []
    assert types_of("") == ["attendance", "checkin"]


def test_export_only_selected_records(cb):
    """勾选导出：点名和签到各按 id 取，没勾的不进文件"""
    c1 = _create(cb, [PEOPLE[0][0]], title="签到一")
    c2 = _create(cb, [PEOPLE[1][0]], title="签到二")
    ids = []
    for no, name, scope in (
        (PEOPLE[0][0], "学生02", "第一次"),
        (PEOPLE[1][0], "学生03", "第二次"),
    ):
        r = cb.client.post("/api/attendance", json={
            "scope": scope,
            "records": [{"student_no": no, "name": name, "status": "present"}],
        })
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])

    wb = _export(cb, record_ids=[ids[0]], checkin_ids=[c2["id"]])
    scopes = {row[1] for row in wb["考勤记录"].iter_rows(min_row=2, values_only=True)}
    assert scopes == {"第一次"}
    titles = {row[1] for row in wb["签到记录"].iter_rows(min_row=2, values_only=True)}
    assert titles == {"签到二"}
    assert c1["title"] == "签到一"  # 没被选中的那条确实存在


def test_export_filtered_by_keyword(cb):
    """不勾选时导出当前筛选结果，关键词口径与列表一致"""
    _create(cb, [PEOPLE[0][0]], title="周六晚点名")
    r = cb.client.post("/api/attendance", json={
        "scope": "全班",
        "records": [{"student_no": PEOPLE[0][0], "name": "学生02", "status": "present"}],
    })
    assert r.status_code == 200, r.text
    assert cb.client.patch(
        f"/api/attendance/{r.json()['id']}", json={"remark": "学院临时集合"}
    ).status_code == 200

    wb = _export(cb, keyword="周六晚")
    assert list(wb["考勤记录"].iter_rows(min_row=2, values_only=True)) == []
    titles = [row[1] for row in wb["签到记录"].iter_rows(min_row=2, values_only=True)]
    assert titles == ["周六晚点名"]

    wb = _export(cb, keyword="学院")
    scopes = [row[1] for row in wb["考勤记录"].iter_rows(min_row=2, values_only=True)]
    assert scopes == ["全班"]
    assert list(wb["签到记录"].iter_rows(min_row=2, values_only=True)) == []


# ---------- 签到自身的备注与删除 ----------

def test_checkin_title_can_be_edited_and_is_searchable(cb):
    """列表里的「备注」列就是标题：改完搜索跟着变，标题不能清空"""
    checkin = _create(cb, [PEOPLE[0][0]], title="晚点名", remark="宿舍区集合")

    r = cb.client.patch(
        f"/api/checkins/{checkin['id']}", json={"title": " 补点名 "}
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "补点名"
    # 发布时那句补充说明是另一回事，不会被标题接口改掉
    assert r.json()["remark"] == "宿舍区集合"

    def checkins_of(keyword):
        data = cb.client.get(
            "/api/attendance/overview", params={"keyword": keyword}
        ).json()
        return [i for i in data["items"] if i["type"] == "checkin"]

    assert checkins_of("补点名")[0]["title"] == "补点名"
    assert checkins_of("晚点名") == []
    assert checkins_of("宿舍区") == []

    r = cb.client.patch(f"/api/checkins/{checkin['id']}", json={"title": "  "})
    assert r.status_code == 400
    assert "标题不能为空" in r.json()["detail"]

    _login(cb, PEOPLE[0][0])
    assert cb.client.patch(
        f"/api/checkins/{checkin['id']}", json={"title": "学生改不了"}
    ).status_code == 403


def test_delete_checkin_also_removes_generated_attendance(cb):
    """删除签到连同它结算出的考勤：否则那条记录会永远删不掉"""
    checkin = _create(cb, [PEOPLE[0][0]])
    assert cb.client.post(f"/api/checkins/{checkin['id']}/close").status_code == 200
    assert _attendance_of(cb, "签到·1人")

    r = cb.client.delete(f"/api/checkins/{checkin['id']}")
    assert r.status_code == 200, r.text
    assert cb.client.get(f"/api/checkins/{checkin['id']}").status_code == 404
    assert _attendance_of(cb, "签到·1人") is None

    # 链接也失效了，公开页拿到的是一句能直接给用户看的话
    r = cb.client.get(f"/api/checkins/public/{checkin['code']}")
    assert r.status_code == 404
    assert "已被删除" in r.json()["detail"]
