"""学生字段的中文名、取值格式化和「改了啥」的描述

导出（Excel / PDF）和操作日志都要把字段名说成人话，所以清单只存这一份。
分开写两份的下场是：加一个字段只改了导出的那份，日志里就开始冒英文 prop。

日志侧的核心是 describe_changes()：前端保存时会把整个表单都提交上来，
照单全收的话改一个备注也会记成三十多个字段，翻半天看不出改了啥。
"""

from datetime import date, datetime


def _fmt_date(val):
    if val is None:
        return ""
    if isinstance(val, date):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M")
    return str(val)


def _fmt_str(val):
    return "" if val is None else str(val)


def _fmt_int(val):
    return "" if val is None else str(val)


# 字段定义：按组排列，顺序就是 Excel 默认列的顺序
# (prop, label, getter)
FIELD_GROUPS = [
    {
        "key": "basic",
        "label": "基本信息",
        "fields": [
            ("student_no", "学号", _fmt_str),
            ("name", "姓名", _fmt_str),
            ("gender", "性别", _fmt_str),
            ("birth_date", "出生日期", _fmt_date),
            ("ethnicity", "民族", _fmt_str),
            ("political_status", "政治面貌", _fmt_str),
            ("hometown", "生源地", _fmt_str),
            ("id_card", "身份证号", _fmt_str),
            ("major", "专业", _fmt_str),
            ("class_name", "班级", _fmt_str),
        ],
    },
    {
        "key": "contact",
        "label": "联系方式",
        "fields": [
            ("phone", "本人电话", _fmt_str),
            ("qq", "QQ", _fmt_str),
            ("email", "电子邮箱", _fmt_str),
            ("family_phone", "家庭电话", _fmt_str),
            ("family_address", "家庭通信地址", _fmt_str),
            ("postal_code", "邮政编码", _fmt_str),
        ],
    },
    {
        "key": "study",
        "label": "学习信息",
        "fields": [
            ("exam_no", "考生号", _fmt_str),
            ("exam_category", "考生类别", _fmt_str),
            ("subject_type", "科类", _fmt_str),
            ("exam_type", "考试类型", _fmt_str),
            ("admission_batch", "录取批次", _fmt_str),
            ("gaokao_score", "高考总分", _fmt_int),
            ("high_school", "毕业中学", _fmt_str),
            ("registration_status", "报到状态", _fmt_str),
            ("registration_time", "报到时间", _fmt_date),
            ("school_status", "在校状态", _fmt_str),
        ],
    },
    {
        "key": "dorm",
        "label": "宿舍与职务",
        "fields": [
            ("dormitory", "宿舍", _fmt_str),
            ("bed", "床位", _fmt_str),
            ("class_position", "班委职务", _fmt_str),
            ("league_position", "团学会职务", _fmt_str),
            ("is_poor", "是否贫困生", _fmt_str),
        ],
    },
    {
        "key": "other",
        "label": "其他",
        "fields": [
            ("remark", "备注", _fmt_str),
        ],
    },
]

# 扁平化字典：prop → {label, getter}
FIELD_MAP = {}
for g in FIELD_GROUPS:
    for prop, label, getter in g["fields"]:
        FIELD_MAP[prop] = {"label": label, "getter": getter}

# 两个照片字段不参与导出（PDF 里单独排版），所以不在上面的组里；
# 但它们能通过改学生信息的接口写进去，日志里也得有个中文名，不能漏出英文 prop
_EXTRA_LABELS = {
    "gaokao_photo": "高考照片",
    "on_site_photo": "实地照片",
    "id_photo": "自备证件照",
}


def field_label(prop: str) -> str:
    """字段名 → 中文名；不认识的字段原样返回，好过在日志里写个「未知字段」"""
    entry = FIELD_MAP.get(prop)
    return entry["label"] if entry else _EXTRA_LABELS.get(prop, prop)


def format_value(prop: str, value) -> str:
    """按该字段在导出里用的同一套规则格式化，日志和导出看到的值才一致"""
    entry = FIELD_MAP.get(prop)
    return (entry["getter"] if entry else _fmt_str)(value)


def describe_changes(old: dict, new: dict) -> str:
    """把「改前 / 改后」两组值写成一句人话，只列**真的变了**的字段

    改一条备注就该只有「备注：无 → 走读」这一句。

    比较的是格式化之后的字符串而不是对象本身：库里 birth_date 是 date、
    表单提交上来的是字符串，直接比对象会把「压根没改」误判成「改了」。
    空值（NULL 和空串）在格式化后都是空串，天然等价。
    """
    parts = []
    for prop, new_value in new.items():
        before = format_value(prop, old.get(prop))
        after = format_value(prop, new_value)
        if before == after:
            continue
        parts.append(f"{field_label(prop)}：{before or '（空）'} → {after or '（空）'}")
    return "；".join(parts)
