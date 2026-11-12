"""考勤 Excel 导入：解析、预览缓存、状态归一化

表格约定：
- 第一行是表头，至少包含「学号」或「姓名」列；
- 「序号」「性别」「班级」等信息列会被忽略；
- 其余非空表头都当作一个场次，表头就是场次标题；
- 每个格子是某人在该场次的状态，空白 / 无 / - / / 表示不在该场次范围内。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from io import BytesIO
from typing import Optional

from openpyxl import load_workbook

_PREVIEW_CACHE: dict[str, dict] = {}
_PREVIEW_TTL_SECONDS = 900

INFO_HEADERS = {
    "学号", "姓名", "学生学号", "学生姓名", "序号", "编号", "性别",
    "班级", "年级", "专业", "备注",
}
OUT_OF_SCOPE = {"", "无", "-", "--", "/", "—", "－－"}
PRESENT = {"到", "出勤", "出席", "准时", "正常"}
LATE = {"迟到"}
ABSENT = {"无应答", "缺勤", "未出勤", "未到", "旷课"}

# Excel 里常见的对勾 / 叉号。先去掉 VS16 等不可见选择符再判断，
# 避免「✓️」这种带变体选择符的字符漏掉。
CHECK_MARKS = {"✓", "✔", "√", "☑", "✅", "🗸"}
CROSS_MARKS = {"X", "x", "×", "✗", "✘", "✕", "✖", "╳", "❌", "❎", "☒", "☓", "⨯"}
INVISIBLE_MARKS = {"\ufe0f", "\ufe0e", "\u20e3"}


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _header(value) -> str:
    return "".join(_text(value).split())


def _status(value, row: int, title: str) -> Optional[str]:
    text = _text(value)
    if text in OUT_OF_SCOPE:
        return None
    if text in PRESENT:
        return "present"
    if text in LATE:
        return "late"
    if text in ABSENT:
        return "absent"

    marks = "".join(
        char for char in text if char not in INVISIBLE_MARKS and not char.isspace()
    )
    if marks and all(char in CHECK_MARKS for char in marks):
        return "present"
    if marks and all(char in CROSS_MARKS for char in marks):
        return "absent"
    if text.endswith("假"):
        return "leave"
    raise ValueError(f"第 {row} 行「{title}」无法识别状态：{text}")


def parse_excel(data: bytes, filename: str) -> dict:
    workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Excel 是空的")

    header_index = None
    no_col = name_col = None
    for index, row in enumerate(rows[:10]):
        headers = [_header(value) for value in row]
        no = next((i for i, text in enumerate(headers) if "学号" in text), None)
        name = next((i for i, text in enumerate(headers) if "姓名" in text), None)
        if no is not None or name is not None:
            header_index, no_col, name_col = index, no, name
            break
    if header_index is None:
        raise ValueError("没有找到「学号」或「姓名」列")

    headers = [_header(value) for value in rows[header_index]]
    session_cols = [
        (index, title)
        for index, title in enumerate(headers)
        if title and title not in INFO_HEADERS
    ]
    if not session_cols:
        raise ValueError("没有识别到任何场次列")

    warnings = []
    seen_titles = set()
    sessions = []
    for index, title in session_cols:
        if title in seen_titles:
            warnings.append(f"场次标题「{title}」重复，按两场处理")
        seen_titles.add(title)
        sessions.append({"key": str(index), "title": title})

    parsed_rows = []
    seen_students = set()
    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        no = _text(row[no_col]) if no_col is not None and no_col < len(row) else ""
        name = _text(row[name_col]) if name_col is not None and name_col < len(row) else ""
        if not no and not name:
            continue
        if no and no in seen_students:
            warnings.append(f"第 {offset} 行学号 {no} 重复，已跳过")
            continue

        values = {}
        for index, title in session_cols:
            cell = row[index] if index < len(row) else None
            status = _status(cell, offset, title)
            if status:
                values[str(index)] = status

        if not values:
            continue
        if no:
            seen_students.add(no)
        parsed_rows.append({
            "row": offset,
            "student_no": no,
            "name": name,
            "values": values,
        })

    if not parsed_rows:
        raise ValueError("没有识别到任何有出勤状态的学生行")

    return {
        "sheet_name": sheet.title,
        "filename": filename,
        "sessions": sessions,
        "rows": parsed_rows,
        "warnings": warnings,
    }


def save_preview(parsed: dict) -> str:
    token = uuid.uuid4().hex
    _PREVIEW_CACHE[token] = {
        **parsed,
        "created_at": datetime.now(),
    }
    _purge_expired()
    return token


def load_preview(token: str) -> Optional[dict]:
    _purge_expired()
    data = _PREVIEW_CACHE.get(token)
    if not data:
        return None
    if (datetime.now() - data["created_at"]).total_seconds() > _PREVIEW_TTL_SECONDS:
        _PREVIEW_CACHE.pop(token, None)
        return None
    return data


def drop_preview(token: str) -> None:
    _PREVIEW_CACHE.pop(token, None)


def _purge_expired() -> None:
    now = datetime.now()
    for key, value in list(_PREVIEW_CACHE.items()):
        if (now - value["created_at"]).total_seconds() > _PREVIEW_TTL_SECONDS:
            _PREVIEW_CACHE.pop(key, None)
