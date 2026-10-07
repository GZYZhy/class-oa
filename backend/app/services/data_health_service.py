"""学生数据体检：把「肉眼翻半天也看不出来」的脏数据逐项查出来

**只报告、不改数据。** 比如「身份证推出来的生日和库里的对不上」，两边必有一边是错的，
但错的是哪一边只有人知道 —— 拿推测去覆盖人工录入的值，比留着这条提示危险得多。

扫描范围永远是全表（一个班几十人，一次查完最省事，也免了「体检还要先选范围」）。
所有判定都只是**提示**：判定不准的地方宁可少报（比如号码校验位对不上时就不再拿它
去比生日和性别），体检报告里堆一堆假警报等于没有报告。
"""

import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Student
from ..utils.email_addr import is_valid_email
from ..utils.student_fields import field_label
from .student_import_service import PHOTO_DIR

# 18 位身份证的校验位算法（GB 11643-1999）：前 17 位各乘一个加权因子，
# 和模 11 之后查表得到末位（模 11 有 11 种余数，所以表里是 10X98765432 这 11 个字符）
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_CODES = "10X98765432"

# 手机号：允许前面带 +86 / 86（有人真的这么存），分隔符在比对前先去掉。
# 只查「本人电话」不查「家庭电话」—— 后者本来就可能填座机，报了也是噪音
_PHONE_RE = re.compile(r"^(?:\+?86)?1[3-9]\d{9}$")
_PHONE_SEPARATORS = re.compile(r"[\s\-()（）]")

# 体检项归并成几张卡片。顺序就是前端卡片的顺序，level 取组内最严重的那一项
_CATEGORIES = (
    ("id_card", "身份证"),
    ("contact", "联系方式"),
    ("missing", "必填字段"),
    ("photo", "照片"),
)

# 「必填字段」查哪些。**不含身份证号** —— 它缺失由身份证那张卡片报，
# 同一件事报两遍只会让人以为有两个问题
_REQUIRED_PROPS = (
    "name",
    "gender",
    "birth_date",
    "phone",
    "ethnicity",
    "political_status",
    "dormitory",
)

_PHOTO_PROPS = ("gaokao_photo", "on_site_photo", "id_photo")


def check_data(db: Session) -> dict:
    """跑一遍全部体检项，返回按卡片分组的报告"""
    students = db.query(Student).order_by(Student.student_no).all()

    groups = {
        key: {"key": key, "label": label, "level": "warn", "items": []}
        for key, label in _CATEGORIES
    }

    for student in students:
        _check_id_card(student, groups)
        _check_phone(student, groups)
        _check_email(student, groups)
        _check_required(student, groups)
        _check_photo(student, groups)
    _check_duplicate_id_cards(students, groups)

    # 同一张卡片里按学号排一次。各项检查各扫各的，不排的话同一张卡片里
    # 会一会儿学号正序、一会儿按「重复身份证」的先后冒出来
    for group in groups.values():
        group["items"].sort(key=lambda item: item["student_no"] or "")

    return {
        "checked_at": datetime.now(),
        "total_students": len(students),
        "groups": [group for group in groups.values() if group["items"]],
    }


def _add(groups: dict, category: str, student: Student, reason: str, error: bool = False) -> None:
    """记一条问题。error=True 的会把整张卡片标红（提示级的不改）"""
    group = groups[category]
    if error:
        group["level"] = "error"
    group["items"].append({
        "id": student.id,
        "student_no": student.student_no,
        "name": student.name,
        "reason": reason,
    })


def _check_code(first17: str) -> str:
    """算出 18 位身份证该有的校验位"""
    total = sum(int(ch) * weight for ch, weight in zip(first17, _ID_WEIGHTS))
    return _ID_CHECK_CODES[total % 11]


def _check_id_card(student: Student, groups: dict) -> None:
    """身份证：缺 / 位数不对 / 校验位错 / 与生日不符 / 与性别不符

    与生日、性别比对只对**位数和校验位都对**的号码做：号码本身敲错了一位时，
    从它推出来的生日和性别同样是错的，拿错的去比只会多报一条，把人引偏。
    """
    raw = (student.id_card or "").strip()
    if not raw:
        _add(groups, "id_card", student, "没有填身份证号")
        return

    # 末位可能是小写的 x，比校验位前先统一成大写；两种写法都是有效的，
    # 只是「库里的写法」而已，不当问题报
    value = raw.upper()
    if not re.fullmatch(r"\d{17}[\dX]", value):
        _add(groups, "id_card", student, f"不是 18 位身份证号（实际是「{raw}」）", error=True)
        return

    expect = _check_code(value[:17])
    if value[17] != expect:
        _add(groups, "id_card", student, f"校验位应是 {expect}，实际是 {value[17]}", error=True)
        return

    _check_id_birth(student, value, groups)
    _check_id_gender(student, value, groups)


def _check_id_birth(student: Student, value: str, groups: dict) -> None:
    """身份证第 7~14 位是出生日期，和库里的出生日期对一下"""
    if student.birth_date is None:
        return  # 没填出生日期的，由「必填字段」那张卡片报
    text = value[6:14]
    try:
        born = datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        _add(groups, "id_card", student, f"身份证里的出生日期 {text} 不是有效日期", error=True)
        return
    if born != student.birth_date:
        _add(
            groups, "id_card", student,
            f"身份证是 {born.isoformat()}，库里记的是 {student.birth_date.isoformat()}",
        )


def _check_id_gender(student: Student, value: str, groups: dict) -> None:
    """身份证第 17 位奇数=男、偶数=女"""
    gender = (student.gender or "").strip()
    if gender not in ("男", "女"):
        return  # 空着或写了别的，同样是「必填字段」那张卡片的事
    expect = "男" if int(value[16]) % 2 else "女"
    if gender != expect:
        _add(groups, "id_card", student, f"身份证对应{expect}，库里记的是{gender}")


def _check_duplicate_id_cards(students: list[Student], groups: dict) -> None:
    """两个学生共用同一个身份证号。

    按**去空格 + 转大写**之后的值比：`…123x` 和 `…123X` 是同一个号码，
    直接拿库里的字符串比会把它们当成两个人。
    """
    by_value: dict[str, list[Student]] = {}
    for student in students:
        value = (student.id_card or "").strip().upper()
        if value:
            by_value.setdefault(value, []).append(student)

    for owners in by_value.values():
        if len(owners) < 2:
            continue
        for owner in owners:
            others = "、".join(
                f"{o.name}（{o.student_no}）" for o in owners if o is not owner
            )
            _add(groups, "id_card", owner, f"与 {others}的身份证号重复", error=True)


def _check_phone(student: Student, groups: dict) -> None:
    raw = (student.phone or "").strip()
    if not raw:
        return  # 没填的同上
    if not _PHONE_RE.match(_PHONE_SEPARATORS.sub("", raw)):
        _add(groups, "contact", student, f"「{raw}」不像手机号")


def _check_email(student: Student, groups: dict) -> None:
    raw = (student.email or "").strip()
    if not raw or is_valid_email(raw):
        return
    _add(groups, "contact", student, f"「{raw}」不是有效邮箱")


def _check_required(student: Student, groups: dict) -> None:
    """必填字段有没有空着。一次列全，一个问题一行太吵"""
    missing = [
        field_label(prop)
        for prop in _REQUIRED_PROPS
        if _is_empty(getattr(student, prop, None))
    ]
    if missing:
        _add(groups, "missing", student, "缺" + "、".join(missing))


def _is_empty(value) -> bool:
    """空值判定：None 和只有空白字符的字符串都算空（Excel 导入的常见产物）"""
    return not str(value or "").strip()


def _check_photo(student: Student, groups: dict) -> None:
    """照片：没上传的、以及**库里记着但磁盘上找不到的**

    后一种在页面上表现为一个裂图，从数据库里完全看不出来，只有体检能发现
    （删学生漏删了文件、手工清理过 photos 目录都会留下这种）。
    """
    missing = []
    for prop in _PHOTO_PROPS:
        label = field_label(prop)
        raw = getattr(student, prop, None)
        name = "" if _is_empty(raw) else str(raw).strip()
        if not name:
            missing.append(label)
        elif not (PHOTO_DIR / Path(name).name).exists():
            # 现在库里只存裸文件名，但老库里有存成 /static/photos/xxx.jpg 的，
            # 所以先取 basename（与删照片、读照片那几处一个口径，见 _remove_photo）
            _add(groups, "photo", student, f"{label}的文件在服务器上找不到（{Path(name).name}）")
    if missing:
        _add(groups, "photo", student, "缺" + "、".join(missing))
