"""「关于班级」页的可配置内容：班级简介 + 任职表的顺序

和生日设置一样是单行表的两套读写（读不写库、写时补行），见 services/birthday_service.py。
"""

import json

from sqlalchemy.orm import Session

from ..models import AboutSettings, Student

SETTINGS_ID = 1

# 与「有职务的人」这套判定保持一致：空串和「无」都算没职务
EMPTY_POSITIONS = ("", "无")


def get_settings(db: Session) -> AboutSettings:
    """读设置。**纯读，不写库**

    行不存在时返回一个「未入库」的默认对象：读接口不该有写副作用，
    而正常启动会由 main.py 的 ensure_settings 把行补出来。
    """
    row = db.get(AboutSettings, SETTINGS_ID)
    return row if row is not None else AboutSettings(id=SETTINGS_ID)


def get_or_create_settings(db: Session) -> AboutSettings:
    """要往设置行上写东西时用这个（只 flush，事务边界交给调用方）"""
    row = db.get(AboutSettings, SETTINGS_ID)
    if row is None:
        row = AboutSettings(id=SETTINGS_ID)
        db.add(row)
        db.flush()
    return row


def ensure_settings(db: Session) -> None:
    """启动时把单行设置补出来（幂等，重复启动无副作用）"""
    if db.get(AboutSettings, SETTINGS_ID) is None:
        db.add(AboutSettings(id=SETTINGS_ID))
        db.commit()


def parse_order(raw: str) -> list[str]:
    """读顺序（JSON 数组 → list）。坏值一律当空，不抛

    库里那串是历史数据，不能因为一次手工改库就让关于页 500
    （同 birthday_service.parse_notify_nos 的处理）。
    """
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


def dump_order(order) -> str:
    """去重保序：存的就是管理员排好的那串顺序"""
    return json.dumps(list(dict.fromkeys(str(x) for x in order)), ensure_ascii=False)


def committee_members(db: Session, order: list[str] | None = None) -> list[Student]:
    """有职务的学生，按管理员定的顺序排

    只影响展示顺序，**不回写学生表** —— 学生表按学号排是它的本分。
    order 里没有的人接在最后，保持学号顺序（sorted 是稳定排序）。
    """
    members = (
        db.query(Student)
        .filter(Student.class_position.isnot(None), Student.class_position.notin_(list(EMPTY_POSITIONS)))
        .order_by(Student.student_no)
        .all()
    )
    rank = parse_order(get_settings(db).roster_order) if order is None else order
    position = {no: i for i, no in enumerate(rank)}
    return sorted(members, key=lambda m: position.get(m.student_no, len(position)))


def put_settings(db: Session, data) -> AboutSettings:
    """保存设置（整体覆盖）"""
    row = get_or_create_settings(db)
    row.intro_enabled = bool(data.intro_enabled)
    row.intro_markdown = (data.intro_markdown or "").strip()
    row.roster_enabled = bool(data.roster_enabled)
    row.roster_order = dump_order(data.order)
    db.commit()
    db.refresh(row)
    return row
