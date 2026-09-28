"""
电动车通行证相关文档生成

两份文档：
1. 电动车通行证.docx — 2 行 8 列表格，第一行标签、第二行填值
2. 电动车承诺书.docx — 纯文本段落，替换姓名/学号等信息

住址统一填「示例公寓」，毕业时间统一填「2030年6月」。
"""

from datetime import datetime
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from ..config import BASE_DIR, settings
from ..models import Student, EvPassRequest


TEMPLATE_DIR = BASE_DIR / "data" / "downloads"
PASS_TEMPLATE = TEMPLATE_DIR / "电动车通行证.docx"
PROMISE_TEMPLATE = TEMPLATE_DIR / "电动车承诺书.docx"

# 固定项
FIXED_ADDRESS = "示例公寓"
FIXED_GRADUATION = "2030年6月"


def _set_cell_text(cell, text: str, font_size: float = 11) -> None:
    """设置单元格文本（保留第一段，清空其他）"""
    for p in cell.paragraphs[1:]:
        p._element.getparent().remove(p._element)
    if cell.paragraphs:
        p = cell.paragraphs[0]
        for run in p.runs:
            run.text = ""
        if p.runs:
            p.runs[0].text = text
            p.runs[0].font.size = Pt(font_size)
        else:
            run = p.add_run(text)
            run.font.size = Pt(font_size)


def generate_pass_docx(student: Student, req: EvPassRequest) -> bytes:
    """生成「电动车通行证」Word 文档

    模板是 2 行 8 列的表格：
    行0（标签）：姓名 | 车牌号 | 联系电话 | 单位（学院） | 专业年级 | 毕业时间 | 电动自行车品牌 | 住址
    行1（值）：对应填入
    """
    if not PASS_TEMPLATE.exists():
        raise FileNotFoundError(f"通行证模板不存在：{PASS_TEMPLATE}")

    doc = Document(str(PASS_TEMPLATE))
    table = doc.tables[0]

    # 第二行（行1）填入值
    _set_cell_text(table.cell(1, 0), student.name or "")           # 姓名
    _set_cell_text(table.cell(1, 1), req.plate_number or "")        # 车牌号
    _set_cell_text(table.cell(1, 2), student.phone or "")           # 联系电话
    _set_cell_text(table.cell(1, 3), settings.college or "")    # 单位（学院）
    _set_cell_text(table.cell(1, 4), student.class_name or "")      # 专业年级（用班级名）
    _set_cell_text(table.cell(1, 5), FIXED_GRADUATION)              # 毕业时间
    _set_cell_text(table.cell(1, 6), req.brand or "")               # 品牌
    _set_cell_text(table.cell(1, 7), FIXED_ADDRESS)                 # 住址

    # 表格下方加落款（右对齐）
    today = datetime.now()
    college = settings.college or ""
    doc.add_paragraph("")
    p1 = doc.add_paragraph()
    p1.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p1.add_run("本批次共1人")
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p2.add_run(f"示例大学{college}{student.class_name or ''}委员会")
    p3 = doc.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p3.add_run(f"{today.year}年{today.month}月{today.day}日")

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def generate_promise_docx(student: Student, req: EvPassRequest) -> bytes:
    """生成「电动自行车使用承诺书」Word 文档

    模板正文段形如：
        本人              （学号：202600001    ），系示例大学示例学院示例专业专业示例班学生，现申请办理电动车校内通行证。

    要替换的是姓名、学号、学院、专业班级；签字和日期留在模板里的空行由学生手签。
    """
    if not PROMISE_TEMPLATE.exists():
        raise FileNotFoundError(f"承诺书模板不存在：{PROMISE_TEMPLATE}")

    doc = Document(str(PROMISE_TEMPLATE))

    target = None
    for p in doc.paragraphs:
        if "本人" in p.text and "学号" in p.text and "系示例大学" in p.text:
            target = p
            break

    if target is not None:
        # 逐 run 替换而不是整段重写：模板里「（学号：…）」这段是带下划线的填空位，
        # 整段压进第一个 run 会把下划线连同字体一起丢掉，填出来的表就不像原表了
        #
        # 模板里写死的示例值 → 实际值。用字面替换而不是正则：正则写成
        # [^，。\s]+专业…班 会把前面的「系示例大学示例学院」一起吞掉。
        # 前提是模板正文保持原样，改模板（data/downloads/电动车承诺书.docx）时这里要同步改
        pairs = [("学号：202600001", f"学号：{student.student_no}")]
        if settings.college:
            pairs.append(("示例大学示例学院", f"示例大学{settings.college}"))
        if student.major and student.class_name:
            pairs.append(("示例专业专业示例班", f"{student.major}专业{student.class_name}"))

        for run in target.runs:
            text = run.text
            # 姓名占的位置就是「本人」后面那段下划线空格
            if "（学号：" in text:
                text = f"{student.name or ''}（学号：" + text.split("（学号：", 1)[1]
            for sample, real in pairs:
                text = text.replace(sample, real)
            if text != run.text:
                run.text = text

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
