"""
电动车通行证相关文档生成

两份文档都是「模板 + 占位符」：
1. 电动车通行证.docx — 2 行 8 列表格，第一行标签、第二行是 {{...}} 占位符；
   表格下面还有右对齐的落款（本批次人数 / 委员会 / 日期）
   （表格标题是「电动车通行证补办登记表」，前端下载时按「申请表」称呼它）
2. 电动车承诺书.docx — 纯文本段落，姓名 / 学号 / 校名 / 学院 / 专业班级都是占位符

模板放在仓库的 backend/templates/ 里（进 git、也随镜像走），本身**不含任何学校、
班级的具体信息** —— 「北方工业大学」「理学院」「统计学26级」「金鼎公寓」这些都在配置里
（SITE_* 品牌族 + EV_PASS_* 四项，见 .env.example）。换学校、换届只改 .env，
不用动模板、也不用改代码。

占位符的替换规则见 docx_template.py。
"""

from datetime import datetime
from io import BytesIO

from docx import Document

from ..config import BASE_DIR, settings
from ..models import Student, EvPassRequest
from .docx_template import fill


# 这两份是纯生成模板（不像请假审批表那样还要当「资料下载」给学生），
# 所以放在仓库的 templates/ 里：进 git、也随镜像走，不受数据卷与
# scripts/setup_resources.py 的影响
TEMPLATE_DIR = BASE_DIR / "templates"
PASS_TEMPLATE = TEMPLATE_DIR / "电动车通行证.docx"
PROMISE_TEMPLATE = TEMPLATE_DIR / "电动车承诺书.docx"


def _common_values(student: Student) -> dict[str, str]:
    """两份文档共用的一份值：校名 / 学院 / 专业班级 / 今天的日期

    专业取 SITE_MAJOR（「关于班级」页显示的所属专业就是它），没配时退回学生自己的专业。
    日期同理，填的是生成当天 —— 不再写死年份，否则过一年就成了过期文档。
    """
    today = datetime.now()
    return {
        "SCHOOL": settings.school,
        "COLLEGE": settings.college,
        "MAJOR": settings.major or student.major or "",
        "CLASS": student.class_name or "",
        "DATE": f"{today.year}年{today.month}月{today.day}日",
        "YEAR": str(today.year),
    }


def _render(template, values: dict[str, str]) -> bytes:
    """读模板 → 填占位符 → 返回 docx 字节"""
    if not template.exists():
        raise FileNotFoundError(f"模板不存在：{template}")

    doc = Document(str(template))
    fill(doc, values)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def generate_pass_docx(student: Student, req: EvPassRequest) -> bytes:
    """生成「电动车通行证」Word 文档"""
    return _render(PASS_TEMPLATE, {
        **_common_values(student),
        "NAME": student.name or "",
        "PLATE_NUMBER": req.plate_number or "",
        "PHONE": student.phone or "",
        # 专业年级那一栏要的是全称「统计学26级」，班级名「统26-1」是简写，表格里不合适
        "GRADE": settings.ev_pass_grade,
        "GRADUATION": settings.ev_pass_graduation,
        "BRAND": req.brand or "",
        "ADDRESS": settings.ev_pass_address,
        # 车牌号示例的省份 / 直辖市简称（模板上那句「车牌号：__XXXXXX」）
        "PLATE_PREFIX": settings.ev_pass_plate_prefix,
    })


def generate_promise_docx(student: Student, req: EvPassRequest) -> bytes:
    """生成「电动自行车使用承诺书」Word 文档

    签字和日期留在模板里的空行，由学生手签。
    """
    return _render(PROMISE_TEMPLATE, {
        **_common_values(student),
        "NAME": student.name or "",
        "STUDENT_NO": student.student_no or "",
    })
