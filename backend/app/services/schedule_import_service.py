"""日程 Excel 导入解析

解析格式（与样例「统26-1秋季学期周课表.xlsx」一致）：
- 多 sheet，每个 sheet 名形如「第N周」
- A 列=时间（10 分钟粒度，07:00–21:50）
- B–H 列=周一至周日（表头含日期+星期）
- 日程块通过纵向合并单元格表示
- 单元格内容三行：标题\n类型\n地点（类型和地点可缺）
- 底部 5 行（事件1–事件5）= 全天事件区。跨天的事件写成横向合并单元格
  （或退化成在覆盖的每一列里重复写同一段文字），两种写法都认
"""

import re
import tempfile
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import openpyxl

from ..models.schedule import (
    DAY_END_HOUR,
    DAY_START_HOUR,
    REPEAT_NONE,
    TIME_SLOT_MINUTES,
)


# 预览缓存（内存里，进程重启丢失；预览 token 10 分钟过期）
_PREVIEW_CACHE: dict[str, dict] = {}
_PREVIEW_TTL_SECONDS = 600


def save_preview(items: list[dict], warnings: list[str], meta: dict) -> str:
    """保存预览结果到内存缓存，返回 token

    meta 是 parse_schedule_excel 给的解析概要（周次范围、锚点），确认导入时只用到
    items / warnings，meta 留着方便排查。
    """
    token = uuid.uuid4().hex
    _PREVIEW_CACHE[token] = {
        "items": items,
        "warnings": warnings,
        "meta": meta,
        "created_at": datetime.now(),
    }
    _purge_expired()
    return token


def load_preview(token: str) -> Optional[dict]:
    """加载预览结果。过期或不存在返回 None"""
    _purge_expired()
    data = _PREVIEW_CACHE.get(token)
    if not data:
        return None
    age = (datetime.now() - data["created_at"]).total_seconds()
    if age > _PREVIEW_TTL_SECONDS:
        del _PREVIEW_CACHE[token]
        return None
    return data


def drop_preview(token: str) -> None:
    """删除预览缓存（确认导入后清掉）"""
    _PREVIEW_CACHE.pop(token, None)


def _purge_expired() -> None:
    """清理过期的预览缓存（懒清理，有新预览时顺手清）"""
    now = datetime.now()
    expired = [
        k for k, v in _PREVIEW_CACHE.items()
        if (now - v["created_at"]).total_seconds() > _PREVIEW_TTL_SECONDS
    ]
    for k in expired:
        del _PREVIEW_CACHE[k]


# ---------- 主解析函数 ----------

def parse_schedule_excel(
    file_bytes: bytes, anchor_monday: Optional[date] = None,
) -> tuple[list[dict], list[str], dict]:
    """解析 xlsx 日程文件

    返回 (items, warnings, meta)，meta = {week_count, week_first, week_last, anchor_monday}

    **日期一律由「周次锚点」推算**。锚点 = 文件里最小周次那一周的周一，上传后由用户
    指认（页面上的「周次锚点」）。文件覆盖第 8–10 周时，用户只要说清「第 8 周的周一
    是哪天」，第 9、10 周以及学期第 1 周的周一（week_start，页面上的「第几周」靠它算）
    就全推得出来。

    为什么不直接认表头里的日期：表头写的「9/14」不带年份，只能靠「比今天早半年就是
    明年」反推，跨年、补课表经常整整错一年；表头被删掉时旧逻辑还会把整张表静默跳过。
    表头日期现在只当**建议锚点**（anchor_monday 传 None 时），用户不认就改。

    **忠实导入，不做任何重复推断**：Excel 每个 sheet 里的每个课程块都展开成
    一条独立（repeat_type=none）日程，日期 = 该 sheet 周一 + 星期偏移。
    items 字段：title, event_type, location, description, start_date, weekday,
                start_time, end_time, all_day, repeat_type, repeat_end_date,
                sheet, cell_ref, week_start
    week_start = 学期第 1 周的周一，用来对齐页面上的周次
    """
    meta = {"week_count": 0, "week_first": 0, "week_last": 0, "anchor_monday": None}

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        f.write(file_bytes)
        tmp_path = f.name

    try:
        wb = openpyxl.load_workbook(tmp_path, data_only=True)
    except Exception as exc:
        return [], [f"文件解析失败：{exc}"], meta
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    all_items: list[dict] = []
    warnings: list[str] = []

    # 先摸清文件覆盖了哪几周：锚点、每张表的日期都以 sheet 名为准
    week_sheets: list[tuple[str, int]] = []
    for sheet_name in wb.sheetnames:
        week_match = re.search(r"第(\d+)周", sheet_name)
        if not week_match:
            warnings.append(f"跳过无法识别周次的工作表：{sheet_name}")
            continue
        week_sheets.append((sheet_name, int(week_match.group(1))))

    if not week_sheets:
        warnings.append("没有找到「第N周」格式的工作表，请检查文件")
        return [], warnings, meta

    week_sheets.sort(key=lambda x: x[1])
    first_week_no = week_sheets[0][1]
    meta["week_count"] = len(week_sheets)
    meta["week_first"] = first_week_no
    meta["week_last"] = week_sheets[-1][1]

    if anchor_monday is None:
        # 没指定：拿表头日期猜一个当建议值，猜不出就一直等用户选
        anchor_monday = _suggest_anchor(wb, week_sheets, warnings)
    elif anchor_monday.weekday() != 0:
        # 页面上只让选周一，但接口是谁都能调的，手动传进来也得归到周一
        monday = anchor_monday - timedelta(days=anchor_monday.weekday())
        warnings.append(f"锚点 {anchor_monday} 不是周一，已按它所在周的周一（{monday}）计算")
        anchor_monday = monday
    meta["anchor_monday"] = anchor_monday

    if anchor_monday is None:
        warnings.append(
            f"请先指定第 {first_week_no} 周的周一 —— 所有日程的日期都由它推算"
        )

    for sheet_name, week_no in week_sheets:
        ws = wb[sheet_name]
        if anchor_monday is None:
            continue

        # 本表周一 = 锚点往后数（本表是第几周 - 最小周次）周
        monday_date = anchor_monday + timedelta(weeks=week_no - first_week_no)

        # 表头自己写了日期、和锚点推算的对不上就说一声：锚点选错全靠这条发现。
        # 警告用一个临时列表接 —— 表头日期现在只是参考，不值得为它再报一遍
        header_date = _parse_monday_from_header(ws, [], sheet_name)
        if header_date and header_date != monday_date:
            warnings.append(
                f"{sheet_name}：表头写的是 {header_date}，按锚点推算为 {monday_date}，已按锚点算"
            )

        # 解析时间行映射：行号 -> HH:MM 时间字符串
        time_map = _parse_time_column(ws, warnings, sheet_name)
        if not time_map:
            warnings.append(f"工作表 {sheet_name} 没有识别到时间列，已跳过")
            continue

        # 解析合并单元格 —— 每个合并区域就是一个日程块
        week_items = _parse_merged_blocks(ws, time_map, monday_date, warnings, sheet_name)

        # 全天事件区单独收集：一天可能有好几条（第16周周日就同时有「期末考试」
        # 和「寒假」），塞进上面那个以「星期+开始时间」为键的字典会互相覆盖
        all_day_items = _parse_all_day_section(ws, monday_date, warnings, sheet_name)
        for item in all_day_items:
            item["all_day"] = True

        # 忠实展平：本周每个块 = 一条独立日程，日期按星期偏移落到具体那天
        for item in list(week_items.values()) + all_day_items:
            block_date = monday_date + timedelta(days=item["weekday"] - 1)
            flat = dict(item)
            flat["start_date"] = block_date
            flat["week_start"] = anchor_monday - timedelta(weeks=first_week_no - 1)
            all_items.append(flat)

    # 按日期、开始时间排序，方便预览核对
    all_items.sort(key=lambda x: (x["start_date"], x["start_time"]))

    return all_items, warnings, meta


# ---------- 表头解析 ----------

def _parse_monday_from_header(ws, warnings: list[str], sheet_name: str) -> Optional[date]:
    """从第一行 B 列（周一）的表头里解析出日期

    表头格式：「9/14 周一」；单元格被 Excel 设成日期格式时读出来是真 date/datetime，
    也照收 —— 只认字符串的话，这样的表整张都会被「无法识别日期表头」跳过。
    """
    cell_value = ws.cell(row=1, column=2).value  # B1
    if not cell_value:
        return None

    if isinstance(cell_value, date):
        # 真日期单元格自带年月日，不用按今天反推年份
        d = cell_value.date() if isinstance(cell_value, datetime) else cell_value
    else:
        # 匹配 "M/D 周一" 格式
        match = re.search(r"(\d{1,2})/(\d{1,2})", str(cell_value).strip())
        if not match:
            return None
        month, day = int(match.group(1)), int(match.group(2))
        # 年份：课表都是秋季学期（9 月开学），先按今年算；比今天早半年以上，
        # 说明表里写的是跨学年的「明年」那个日期
        today = date.today()
        try:
            d = date(today.year, month, day)
        except ValueError:
            return None
        if (today - d).days > 180:
            try:
                d = date(today.year + 1, month, day)
            except ValueError:
                pass  # 2/29：明年没有这一天，按今年的算，别为一天崩掉整张表

    # 表头未必正好落在周一（转手来的表常这样），按它所在周的周一算
    if d.weekday() != 0:
        monday = d - timedelta(days=d.weekday())
        warnings.append(f"{sheet_name}：表头日期 {d} 不是周一，已按它所在周的周一（{monday}）计算")
        d = monday
    return d


def _suggest_anchor(wb, week_sheets: list[tuple[str, int]], warnings: list[str]) -> Optional[date]:
    """从表头猜一个锚点（最小周次那一周的周一）当建议值，猜不出返回 None

    只是建议：表头里的日期不带年份，_parse_monday_from_header 只能靠
    「比今天早半年就是明年」反推，跨年、补课表经常错一整年，所以页面会让用户
    确认或改掉它（真正的日期一律由用户确认后的锚点推算）。
    """
    first_week_no = week_sheets[0][1]
    for sheet_name, week_no in week_sheets:
        monday = _parse_monday_from_header(wb[sheet_name], warnings, sheet_name)
        if monday:
            return monday - timedelta(weeks=week_no - first_week_no)
    return None


# ---------- 时间列解析 ----------

def _parse_time_column(ws, warnings: list[str], sheet_name: str) -> dict[int, str]:
    """解析 A 列时间，返回 {行号: "HH:MM"}

    只识别 07:00–21:50 范围内、10 分钟对齐的时间。
    A 列被 Excel 设成「时间」格式时读出来是 datetime.time（或 datetime），
    不只是字符串 —— 只认字符串的话整张表会被「没有识别到时间列」跳过。
    """
    time_map: dict[int, str] = {}
    for row in range(2, ws.max_row + 1):
        cell = ws.cell(row=row, column=1)
        val = cell.value
        if val is None:
            continue

        if isinstance(val, datetime):
            val = val.time()
        if isinstance(val, time):
            hour, minute = val.hour, val.minute
        else:
            # 匹配 HH:MM（容忍表里写成 HH:MM:SS）
            match = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", str(val).strip())
            if not match:
                continue
            hour, minute = int(match.group(1)), int(match.group(2))

        if not (DAY_START_HOUR <= hour < DAY_END_HOUR):
            continue
        if minute % TIME_SLOT_MINUTES != 0:
            continue
        time_map[row] = f"{hour:02d}:{minute:02d}"
    return time_map


# ---------- 合并单元格解析 ----------

def _parse_merged_blocks(
    ws, time_map: dict[int, str], monday: date, warnings: list[str], sheet_name: str,
) -> dict[tuple[int, str], dict]:
    """解析所有纵向合并单元格，返回 {(星期几, 开始时间): 日程信息}"""
    blocks: dict[tuple[int, str], dict] = {}

    for merged_range in ws.merged_cells.ranges:
        min_row, min_col, max_row, max_col = merged_range.min_row, merged_range.min_col, merged_range.max_row, merged_range.max_col

        # 只看 B–H 列（2–7 列是周一到周日）
        if min_col < 2 or min_col > 8:
            continue
        # 至少要 2 行才算块
        if max_row - min_row + 1 < 2:
            continue
        # 横跨几天的横向合并按**最左列**那一天算（下面 weekday 取 min_col）。
        # 真实课表只有底部全天事件区会横跨，那边由 _parse_all_day_section 逐日摊开；
        # 课程区若出现横向合并，宁可只落一天，也不凭空给没课的几天加日程

        weekday = min_col - 1  # B列=周一=1
        if weekday < 1 or weekday > 7:
            continue

        # 起始行和结束行必须都在 time_map 里
        if min_row not in time_map:
            continue
        # 结束行：找合并区域最后一个有时间的行
        end_row = max_row
        while end_row >= min_row and end_row not in time_map:
            end_row -= 1
        if end_row < min_row:
            continue

        start_time_str = time_map[min_row]
        # 结束时间 = 最后一行的时间 + 10 分钟
        end_time_str = _add_minutes(time_map[end_row], TIME_SLOT_MINUTES)

        # 取单元格值（左上角）
        cell_value = ws.cell(row=min_row, column=min_col).value
        if not cell_value:
            continue

        title, event_type, location, desc = _parse_cell_content(str(cell_value))
        if not title:
            continue

        cell_ref = ws.cell(row=min_row, column=min_col).coordinate

        blocks[(weekday, start_time_str)] = {
            "title": title,
            "event_type": event_type,
            "location": location,
            "description": desc,
            "weekday": weekday,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "all_day": False,
            "repeat_type": REPEAT_NONE,
            "repeat_end_date": None,
            "sheet": sheet_name,
            "cell_ref": cell_ref,
        }

    return blocks


def _parse_cell_content(text: str) -> tuple[str, str, str, str]:
    """解析单元格内容：标题\n类型\n地点

    返回 (title, event_type, location, description)
    - 1 行：只有标题
    - 2 行：标题 + 类型
    - 3 行及以上：标题 + 类型 + 地点
    Excel 里没有「备注」信息，description 恒为空串（类型不再被误塞进备注）。
    """
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return "", "", "", ""
    title = lines[0]
    event_type = ""
    location = ""
    description = ""
    if len(lines) >= 2:
        event_type = lines[1]  # 类型，如「课程」「体育」「网络课」
    if len(lines) >= 3:
        location = lines[2]     # 第三行是地点
    return title, event_type, location, description


def _add_minutes(time_str: str, minutes: int) -> str:
    """给 HH:MM 格式的时间加 N 分钟"""
    h, m = map(int, time_str.split(":"))
    total = h * 60 + m + minutes
    h2, m2 = divmod(total, 60)
    return f"{h2:02d}:{m2:02d}"


# ---------- 全天事件解析 ----------

def _parse_all_day_section(
    ws, monday: date, warnings: list[str], sheet_name: str,
) -> list[dict]:
    """解析底部全天事件区（事件1–事件5）

    样例里第 92–96 行，A 列标「事件N」，B–H 列对应周一–周日。

    跨天的事件有两种写法，都要认：
    - **横向合并**（B5:D5 一格）—— 合并之后只有左上角存着文字，其余格子读出来
      是空的，纯逐格取会让这件事件只落在周一那一天；
    - 在它覆盖的每一天的列里**重复写**同一段文字（真实课表的「国庆放假」在
      E/F/G/H 四列各写一遍）。

    两种都展开成「一天一条」，和上面的课程块一样逐日忠实 —— 模型里没有
    「跨天日程」这个概念，连成一条是页面上的事（见 Schedule.vue 的 allDayBars）。
    也不从文字里猜日期：文字里的「1/4-1/15」可能指向表外，按它落位会把事件
    挪到别的周去。
    """
    items: list[dict] = []
    # 从底部往上找「事件1」开头的行
    event_start_row = None
    for row in range(max(1, ws.max_row - 10), ws.max_row + 1):
        val = ws.cell(row=row, column=1).value
        if val and str(val).strip().startswith("事件1"):
            event_start_row = row
            break
    if event_start_row is None:
        return items

    event_end_row = event_start_row + 4

    # 先把横向合并摊平：合并区域的文字只在左上角，摊到覆盖的每一列上。
    # 纵向合并不在这个区域里有语义（行号就是事件槽位），照旧只认左上角
    merged: dict[tuple[int, int], str] = {}
    for rng in ws.merged_cells.ranges:
        if not (event_start_row <= rng.min_row <= event_end_row):
            continue
        if rng.max_col == rng.min_col:
            continue
        val = ws.cell(row=rng.min_row, column=rng.min_col).value
        if val is None or not str(val).strip():
            continue
        for col in range(max(2, rng.min_col), min(8, rng.max_col) + 1):
            merged[(rng.min_row, col)] = str(val).strip()

    for offset in range(5):
        row = event_start_row + offset
        if row > ws.max_row:
            break
        # B–H = 周一–周日，逐列取
        for col in range(2, 9):
            content = merged.get((row, col))
            if content is None:
                raw = ws.cell(row=row, column=col).value
                content = str(raw).strip() if raw is not None else ""
            if not content:
                continue
            items.append({
                "title": content,
                "event_type": "",
                "location": "",
                "description": "",
                "weekday": col - 1,
                "start_time": "00:00",
                "end_time": "23:59",
                "sheet": sheet_name,
                "cell_ref": f"{chr(64 + col)}{row}",
            })

    return items
