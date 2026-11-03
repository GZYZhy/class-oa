"""班委查看学生档案的字段级权限，以及「申请完整档案」这条审批链

    cd backend && python -m pytest tests/test_student_archive_access.py -q

班委能看的是：照片（高考照、自备证件照）、学号姓名性别班级专业民族政治面貌、
生源地、宿舍、班委/团学会职务、在校状态、本人电话、考勤和办件记录、备注及附件。

其余敏感字段（身份证号、出生日期、家庭电话、家庭地址、邮箱/QQ、考生信息、高考分数、
报到信息、床位、贫困生、实地采集照片）在班委看别人时必须隐藏，**且不能从列表接口
的搜索、筛选、排序里反查出来**。需要时走「申请完整档案」：管理员批准后，只有申请人
在一小时内能看到完整字段。
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from conftest import png_bytes

PW = "initpass123"
ADMIN = "2024000001"
CM1 = "2024000002"
CM2 = "2024000003"
TARGET = "2024000004"
STUDENT = "2024000005"
ROSTER = [
    (ADMIN, "甲", "010001"),
    (CM1, "乙", "010002"),
    (CM2, "丙", "010003"),
    (TARGET, "丁", "010004"),
    (STUDENT, "戊", "010005"),
]
TARGET_ID_CARD = "110101200605010004"
PNG = png_bytes()


def as_student(b, no) -> httpx.Client:
    """另开一个客户端以某个学生身份登录 —— 会话是按 client 存的"""
    tail = dict((n, t) for n, _, t in ROSTER)[no]
    c = httpx.Client(base_url=str(b.client.base_url), timeout=10)
    r = c.post("/api/auth/login", json={"student_no": no, "password": tail})
    assert r.status_code == 200, r.text
    return c


def sid_of(b, no) -> int:
    return b.rows("SELECT id FROM students WHERE student_no = ?", no)[0][0]


@pytest.fixture
def world(backend):
    """管理员已登录；两个班委、一个被查看的学生、一个普通学生都已建好

    被查看的学生填了全部敏感字段，照片三张都传了 —— 这样「哪些能看到」才有东西可测。
    """
    b = backend(db="archive.db", BOOTSTRAP_PASSWORD=PW)
    assert b.login(password=PW).status_code == 200

    for no, name, tail in ROSTER:
        # 身份证后 6 位就是初始密码（建号规则），所以让最后 6 位正好等于 tail
        payload = {
            "student_no": no,
            "name": name,
            "id_card": f"11010120060501{tail[-4:]}",
        }
        if no == TARGET:
            payload.update({
                "id_card": TARGET_ID_CARD,
                "birth_date": "2006-05-04",
                "gender": "男",
                "major": "计算机科学与技术",
                "class_name": "1",
                "ethnicity": "汉族",
                "political_status": "共青团员",
                "hometown": "河北省石家庄市",
                "phone": "13800000004",
                "family_phone": "031100000004",
                "qq": "123456789",
                "email": "target@example.com",
                "family_address": "河北省石家庄市某街道 4 号",
                "postal_code": "050000",
                "dormitory": "3-701",
                "bed": "4",
                "class_position": "学习委员",
                "league_position": "无",
                "school_status": "正常",
                "exam_no": "0610100004",
                "exam_category": "城镇应届",
                "subject_type": "物理类",
                "exam_type": "夏季高考",
                "admission_batch": "本科批",
                "gaokao_score": 612,
                "high_school": "石家庄市第一中学",
                "registration_status": "已报到",
                "registration_time": "2026-09-01 08:00:00",
                "is_poor": "否",
                "remark": "班委内部备注",
            })
        r = b.client.post("/api/students", json=payload)
        assert r.status_code < 300, r.text

    assert b.client.post(
        "/api/setup/finish", json={"admin_student_no": ADMIN}
    ).status_code == 200
    b.logout()
    assert b.login(student_no=ADMIN, password="010001").status_code == 200

    for no in (CM1, CM2):
        r = b.client.put(f"/api/admin/users/{no}/role", json={"role": "committee"})
        assert r.status_code == 200, r.text

    target = sid_of(b, TARGET)
    for type_ in ("gaokao", "on_site", "id"):
        r = b.client.post(
            f"/api/students/{target}/photo?type={type_}",
            files={"file": (f"{type_}.png", PNG, "image/png")},
        )
        assert r.status_code == 200, r.text

    return SimpleNamespace(
        b=b,
        target=target,
        cm1=as_student(b, CM1),
        cm2=as_student(b, CM2),
        student=as_student(b, STUDENT),
    )


def detail(world, client, sid=None):
    r = client.get(f"/api/students/{sid or world.target}")
    assert r.status_code == 200, r.text
    return r.json()


def apply_for_archive(world, client):
    return client.post("/api/archive-views/requests", json={"student_id": world.target})


def archive_status(world, client):
    return client.get(f"/api/archive-views/status/{world.target}")


# ---------- 字段裁剪 ----------

def test_committee_only_sees_the_allowed_fields(world):
    body = detail(world, world.cm1)
    assert body["sensitive_hidden"] is True

    # 允许看的：一项都不能少
    assert body["student_no"] == TARGET
    assert body["name"] == "丁"
    assert body["gender"] == "男"
    assert body["class_name"] == "1"
    assert body["major"] == "计算机科学与技术"
    assert body["ethnicity"] == "汉族"
    assert body["political_status"] == "共青团员"
    assert body["hometown"] == "河北省石家庄市"
    assert body["dormitory"] == "3-701"
    assert body["class_position"] == "学习委员"
    assert body["school_status"] == "正常"
    assert body["phone"] == "13800000004"
    assert body["remark"] == "班委内部备注"
    assert body["gaokao_photo"]
    assert body["id_photo"]

    # 隐藏的：全部置空，一个都不许漏
    for field in (
        "id_card", "birth_date", "family_phone", "qq", "email", "family_address",
        "postal_code", "bed", "exam_no", "exam_category", "subject_type",
        "exam_type", "admission_batch", "gaokao_score", "high_school",
        "registration_status", "registration_time", "is_poor", "on_site_photo",
    ):
        assert body[field] is None, f"{field} 不该给班委看"


def test_committee_own_record_is_not_hidden(world):
    """班委看自己那条时不裁剪，否则连自己的身份证号都看不到"""
    body = detail(world, world.cm1, sid_of(world.b, CM1))
    assert body["sensitive_hidden"] is False
    assert body["id_card"] == "110101200605010002"


def test_admin_sees_everything(world):
    body = detail(world, world.b.client)
    assert body["sensitive_hidden"] is False
    assert body["id_card"] == TARGET_ID_CARD
    assert body["gaokao_score"] == 612
    assert body["on_site_photo"]


# ---------- 列表不能成为反查后门 ----------

def test_list_hides_sensitive_fields_and_blocks_sensitive_filters(world):
    r = world.cm1.get("/api/students", params={"page_size": 100})
    assert r.status_code == 200, r.text
    item = {i["student_no"]: i for i in r.json()["items"]}[TARGET]
    assert item["sensitive_hidden"] is True
    assert item["id_card"] is None
    assert item["gaokao_score"] is None
    assert item["on_site_photo"] is None

    # 关键词只能搜公开字段：拿身份证号搜不到，姓名仍然搜得到
    assert world.cm1.get(
        "/api/students", params={"keyword": TARGET_ID_CARD}
    ).json()["total"] == 0
    assert world.cm1.get(
        "/api/students", params={"keyword": "丁"}
    ).json()["total"] == 1
    # 管理员不受这条限制
    assert world.b.client.get(
        "/api/students", params={"keyword": TARGET_ID_CARD}
    ).json()["total"] == 1

    # 生日、贫困生、敏感排序都只给管理员
    assert world.cm1.get(
        "/api/students", params={"birthday_days": 7}
    ).status_code == 403
    assert world.cm1.get(
        "/api/students", params={"is_poor": "是"}
    ).status_code == 403
    assert world.cm1.get(
        "/api/students", params={"sort_by": "gaokao_score"}
    ).status_code == 403

    assert world.b.client.get(
        "/api/students", params={"birthday_days": 365}
    ).status_code == 200
    assert world.b.client.get(
        "/api/students", params={"is_poor": "否"}
    ).status_code == 200
    assert world.b.client.get(
        "/api/students", params={"sort_by": "gaokao_score"}
    ).status_code == 200


def test_statistics_hides_sensitive_distributions(world):
    """统计页也不能绕：分数段、年龄、贫困、考生信息这些分布只给管理员"""
    cm = world.cm1.get("/api/students/statistics")
    assert cm.status_code == 200, cm.text
    body = cm.json()
    for key in (
        "poor_student", "score_ranges", "score_summary", "ages", "birth_months",
        "exam_category", "subject_type", "admission_batch", "exam_type", "high_schools",
    ):
        assert key not in body, f"班委的统计里不该有 {key}"
    # 可见范围内的统计照常给
    assert "gender" in body and "ethnicity" in body and "class_positions" in body

    admin = world.b.client.get("/api/students/statistics").json()
    assert admin["poor_student"] and admin["score_ranges"]
    assert admin["score_summary"]["max"] == 612


def test_change_requests_do_not_leak_hidden_fields(world):
    """信息修改也是一条查看档案的路：班委不能从「原值 → 新值」里看到隐藏字段"""
    target = as_student(world.b, TARGET)
    r = target.post("/api/change-requests", json={"family_phone": "0311-88888888"})
    assert r.status_code == 200, r.text
    req_id = r.json()["id"]

    rows = world.cm1.get("/api/change-requests").json()
    row = next(i for i in rows if i["id"] == req_id)
    assert row["sensitive_hidden"] is True
    assert "family_phone" not in row["changes"]
    assert "family_phone" not in row["current"]

    admin_row = next(
        i for i in world.b.client.get("/api/change-requests").json() if i["id"] == req_id
    )
    assert admin_row["changes"]["family_phone"] == "0311-88888888"
    assert admin_row["current"]["family_phone"] == "031100000004"

    # 班委闭着眼睛批不了；管理员可以
    assert world.cm1.post(f"/api/change-requests/{req_id}/approve").status_code == 403
    assert world.b.client.post(
        f"/api/change-requests/{req_id}/approve"
    ).status_code == 200

    # 只改班委能看的字段（本人电话）时，班委仍可正常审
    r = target.post("/api/change-requests", json={"phone": "13800009999"})
    assert r.status_code == 200, r.text
    visible_id = r.json()["id"]
    row = next(i for i in world.cm1.get("/api/change-requests").json() if i["id"] == visible_id)
    assert row["sensitive_hidden"] is False
    assert row["changes"]["phone"] == "13800009999"
    assert world.cm1.post(f"/api/change-requests/{visible_id}/approve").status_code == 200


# ---------- 实地采集照片 ----------

def photo(world, client, type_):
    return client.get(f"/api/students/{world.target}/photo?type={type_}")


def test_committee_can_see_gaokao_and_id_but_not_on_site_photo(world):
    assert photo(world, world.cm1, "gaokao").status_code == 200
    assert photo(world, world.cm1, "id").status_code == 200
    r = photo(world, world.cm1, "on_site")
    assert r.status_code == 403
    assert "完整档案" in r.json()["detail"]
    # 管理员仍然能看
    assert photo(world, world.b.client, "on_site").status_code == 200


# ---------- 完整档案申请 ----------

def test_archive_request_grants_full_detail_to_the_applicant_only(world):
    r = apply_for_archive(world, world.cm1)
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["status"] == "pending"
    assert archive_status(world, world.cm1).json()["status"] == "pending"

    # 待审核期间还是看不见
    assert detail(world, world.cm1)["id_card"] is None
    # 同一个人不能重复提
    assert apply_for_archive(world, world.cm1).status_code == 400

    r = world.b.client.get("/api/archive-views/requests", params={"status": "pending"})
    assert r.status_code == 200, r.text
    rows = r.json()["items"]
    assert len(rows) == 1 and rows[0]["applicant_no"] == CM1

    assert world.b.client.post(
        f"/api/archive-views/requests/{req['id']}/approve"
    ).status_code == 200

    st = archive_status(world, world.cm1).json()
    assert st["status"] == "approved" and st["expires_at"]

    body = detail(world, world.cm1)
    assert body["sensitive_hidden"] is False
    assert body["id_card"] == TARGET_ID_CARD
    assert body["gaokao_score"] == 612
    assert photo(world, world.cm1, "on_site").status_code == 200

    # 另一个班委不会因为 CM1 被批准就跟着能看
    assert detail(world, world.cm2)["id_card"] is None
    assert photo(world, world.cm2, "on_site").status_code == 403

    # 列表仍然按行裁剪：一次批准只对详情页那一个学生有效
    r = world.cm1.get("/api/students", params={"page_size": 100})
    item = {i["student_no"]: i for i in r.json()["items"]}[TARGET]
    assert item["id_card"] is None


def test_archive_grant_expires_after_one_hour(world):
    r = apply_for_archive(world, world.cm1)
    assert r.status_code == 200, r.text
    assert world.b.client.post(
        f"/api/archive-views/requests/{r.json()['id']}/approve"
    ).status_code == 200
    assert detail(world, world.cm1)["id_card"] == TARGET_ID_CARD

    old = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S.%f")
    world.b.run(
        "UPDATE archive_view_requests SET reviewed_at = ? WHERE applicant_no = ?",
        old, CM1,
    )

    assert archive_status(world, world.cm1).json()["status"] == "expired"
    assert detail(world, world.cm1)["id_card"] is None
    assert photo(world, world.cm1, "on_site").status_code == 403
    # 过期后可以重新申请
    assert apply_for_archive(world, world.cm1).status_code == 200


def test_only_committee_can_apply_and_admin_does_not_need_to(world):
    assert apply_for_archive(world, world.student).status_code == 403
    # 管理员直接看，提申请反而会被拒绝
    r = apply_for_archive(world, world.b.client)
    assert r.status_code == 400
    assert "无需申请" in r.json()["detail"]
    # 班委看自己也不需要申请
    r = world.cm1.post(
        "/api/archive-views/requests", json={"student_id": sid_of(world.b, CM1)}
    )
    assert r.status_code == 400
