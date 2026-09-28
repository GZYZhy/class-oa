"""学生信息导出服务

两种导出：
1. Excel 名单（excel_list）：选字段，一张表
2. 个人信息表 PDF（pdf_individual）：每人一页完整信息，打包 zip

PDF 导出打不可见水印（复用 pdf_watermark_service），溯源是谁导出的。
"""

import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..models.student import Student
from .pdf_watermark_service import add_invisible_watermark

# ---------------------------------------------------------------------------
# 字段白名单：prop → {label, group, getter}
# getter 用来从 Student 对象取值并做格式化（日期、空值等）
# ---------------------------------------------------------------------------

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

# 扁平化字典：prop → (label, getter)
FIELD_MAP = {}
for g in FIELD_GROUPS:
    for prop, label, getter in g["fields"]:
        FIELD_MAP[prop] = {"label": label, "getter": getter}

# 默认选中的字段（Excel 导出时前端默认勾上的）
DEFAULT_FIELDS = [
    "student_no", "name", "gender", "ethnicity", "political_status",
    "dormitory", "bed", "phone", "class_position", "gaokao_score",
]


def get_field_groups():
    """返回字段分组信息（给前端渲染复选框用），只含 prop 和 label，不含 getter"""
    return [
        {
            "key": g["key"],
            "label": g["label"],
            "fields": [{"prop": prop, "label": label} for prop, label, _ in g["fields"]],
        }
        for g in FIELD_GROUPS
    ]


def get_default_fields():
    """默认选中的字段列表"""
    return DEFAULT_FIELDS


def _get_student_value(student: Student, prop: str) -> str:
    """从 Student 对象取字段值，格式化后返回字符串"""
    info = FIELD_MAP.get(prop)
    if not info:
        return ""
    val = getattr(student, prop, None)
    return info["getter"](val)


# ---------------------------------------------------------------------------
# Excel 导出
# ---------------------------------------------------------------------------

def generate_excel(students: List[Student], fields: List[str]) -> bytes:
    """生成学生名单 Excel，返回二进制

    fields 是 prop 列表，顺序就是列的顺序。
    """
    # 过滤掉不在白名单里的字段
    valid_fields = [f for f in fields if f in FIELD_MAP]
    if not valid_fields:
        # 如果一个都没选（不应该发生），退回默认字段
        valid_fields = DEFAULT_FIELDS

    wb = Workbook()
    ws = wb.active
    ws.title = "学生名单"

    # 表头行
    header_font = Font(bold=True)
    header_fill = PatternFill(start_color="E8F0FE", end_color="E8F0FE", fill_type="solid")
    for col_idx, prop in enumerate(valid_fields, 1):
        cell = ws.cell(row=1, column=col_idx, value=FIELD_MAP[prop]["label"])
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # 数据行
    for row_idx, stu in enumerate(students, 2):
        for col_idx, prop in enumerate(valid_fields, 1):
            val = _get_student_value(stu, prop)
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    # 列宽：按内容估算，中文占 2 个字符宽度
    for col_idx, prop in enumerate(valid_fields, 1):
        label_len = len(FIELD_MAP[prop]["label"]) * 2
        # 取「表头宽度」和「最长内容宽度」的较大值，再加 2 个 padding
        max_content = max(
            (len(_get_student_value(s, prop)) for s in students),
            default=0
        ) * 2
        width = min(max(label_len, max_content) + 2, 40)  # 最宽 40，别太夸张
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # 首行冻结
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF 个人信息表
# ---------------------------------------------------------------------------

# 中文字体：优先找系统里的，找不到就回退到 Helvetica（中文会变方块，但不崩）
def _register_cjk_font():
    """注册中文字体，返回字体名。注册过一次就直接返回。"""
    if hasattr(_register_cjk_font, "_font_name"):
        return _register_cjk_font._font_name

    candidates = [
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        # Linux (常见发行版)
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        # 容器里如果安装了
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    font_name = "Helvetica"  # 兜底
    for path in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("CJK", path))
                font_name = "CJK"
                break
            except Exception:
                continue
    _register_cjk_font._font_name = font_name
    return font_name


def generate_student_pdf(student: Student, photos_dir: Path) -> bytes:
    """生成单个学生的个人信息表 PDF（一页 A4），返回二进制"""
    font_name = _register_cjk_font()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"{student.name} 个人信息表",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCN", parent=styles["Title"],
        fontName=font_name, fontSize=18, leading=24, alignment=1, spaceAfter=16,
    )
    h2_style = ParagraphStyle(
        "H2CN", parent=styles["Heading2"],
        fontName=font_name, fontSize=13, leading=18, spaceBefore=10, spaceAfter=6,
    )
    normal_style = ParagraphStyle(
        "NormalCN", parent=styles["Normal"],
        fontName=font_name, fontSize=10, leading=15,
    )

    story = []

    # 标题
    story.append(Paragraph("学生个人信息表", title_style))
    story.append(Spacer(1, 0.3 * cm))

    # ---- 照片区：左右两张照片 ----
    photo_items = []
    for label, attr in [("高考照片", "gaokao_photo"), ("实地照片", "on_site_photo")]:
        photo_path = getattr(student, attr, None)
        if photo_path:
            # 路径可能是 /static/photos/xxx，实际文件在 photos_dir
            fname = Path(photo_path).name
            full_path = photos_dir / fname
            if full_path.exists():
                try:
                    img = Image(str(full_path), width=4 * cm, height=5.6 * cm, kind="proportional")
                    photo_items.append([img])
                    photo_items.append([Paragraph(label, normal_style)])
                except Exception:
                    photo_items.append([Paragraph("（无照片）", normal_style)])
                    photo_items.append([Paragraph(label, normal_style)])
            else:
                photo_items.append([Paragraph("（无照片）", normal_style)])
                photo_items.append([Paragraph(label, normal_style)])
        else:
            photo_items.append([Paragraph("（无照片）", normal_style)])
            photo_items.append([Paragraph(label, normal_style)])

    if photo_items:
        # 两列：左边基本信息，右边两张照片
        info_data = _build_info_table_data(student, font_name, normal_style)
        info_table = Table(info_data, colWidths=[3 * cm, 5.5 * cm])
        info_table.setStyle(_info_table_style())

        photo_table_data = [[photo_items[0][0], photo_items[2][0]],
                            [photo_items[1][0], photo_items[3][0]]]
        photo_table = Table(photo_table_data, colWidths=[4.2 * cm, 4.2 * cm])
        photo_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))

        top_layout = Table([[info_table, photo_table]], colWidths=[9 * cm, 9 * cm])
        top_layout.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(top_layout)
    else:
        # 没有照片时直接放信息表
        info_data = _build_info_table_data(student, font_name, normal_style)
        info_table = Table(info_data, colWidths=[3 * cm, 12 * cm])
        info_table.setStyle(_info_table_style())
        story.append(info_table)

    story.append(Spacer(1, 0.5 * cm))

    # ---- 分组信息 ----
    sections = [
        ("联系方式", [
            ("本人电话", "phone"), ("QQ", "qq"), ("电子邮箱", "email"),
            ("家庭电话", "family_phone"), ("家庭通信地址", "family_address"),
            ("邮政编码", "postal_code"),
        ]),
        ("学习信息", [
            ("考生号", "exam_no"), ("考生类别", "exam_category"),
            ("科类", "subject_type"), ("考试类型", "exam_type"),
            ("录取批次", "admission_batch"), ("高考总分", "gaokao_score"),
            ("毕业中学", "high_school"), ("报到状态", "registration_status"),
            ("报到时间", "registration_time"), ("在校状态", "school_status"),
        ]),
        ("宿舍与职务", [
            ("宿舍", "dormitory"), ("床位", "bed"),
            ("班委职务", "class_position"), ("团学会职务", "league_position"),
            ("是否贫困生", "is_poor"), ("备注", "remark"),
        ]),
    ]

    for sec_title, sec_fields in sections:
        story.append(Paragraph(sec_title, h2_style))
        data = []
        row = []
        for i, (label, prop) in enumerate(sec_fields):
            val = _get_student_value(student, prop)
            row.append(Paragraph(f"<b>{label}</b>", normal_style))
            row.append(Paragraph(str(val), normal_style))
            if (i + 1) % 2 == 0:  # 每行两列（标签+值 × 2 组 = 4 列）
                data.append(row)
                row = []
        if row:
            # 奇数个字段，最后一行补空
            row.extend(["", ""])
            data.append(row)

        if data:
            t = Table(data, colWidths=[2.5 * cm, 4.5 * cm, 2.5 * cm, 4.5 * cm])
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D7DE")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F7FA")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F5F7FA")),
            ]))
            story.append(t)

    doc.build(story)
    return buf.getvalue()


def _build_info_table_data(student, font_name, style):
    """顶部基本信息表（左侧）"""
    basic_fields = [
        ("学号", "student_no"), ("姓名", "name"), ("性别", "gender"),
        ("出生日期", "birth_date"), ("民族", "ethnicity"),
        ("政治面貌", "political_status"), ("生源地", "hometown"),
        ("身份证号", "id_card"), ("专业", "major"), ("班级", "class_name"),
    ]
    data = []
    for label, prop in basic_fields:
        val = _get_student_value(student, prop)
        data.append([
            Paragraph(f"<b>{label}</b>", style),
            Paragraph(str(val), style),
        ])
    return data


def _info_table_style():
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _register_cjk_font()),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D7DE")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F7FA")),
    ])


def generate_individual_pdfs(
    students: List[Student],
    photos_dir: Path,
    watermark_token: str,
) -> bytes:
    """生成多个学生的个人信息表 PDF，打包成 zip 返回二进制

    每个 PDF 单独打不可见水印（用同一个 token），然后打包 zip。
    zip 内文件名：「学号-姓名-个人信息表.pdf」
    """
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for stu in students:
            pdf_bytes = generate_student_pdf(stu, photos_dir)
            # 打不可见水印
            try:
                pdf_bytes = add_invisible_watermark(pdf_bytes, watermark_token)
            except Exception:
                # 水印失败不影响导出，至少文件要能拿到
                pass
            safe_name = f"{stu.student_no}-{stu.name}-个人信息表.pdf"
            zf.writestr(safe_name, pdf_bytes)
    return zip_buf.getvalue()


# ---------------------------------------------------------------------------
# 工具：按 scope_type + scope_param 从数据库取学生列表
# ---------------------------------------------------------------------------

def resolve_students(db, scope_type: str, scope_param) -> List[Student]:
    """根据范围类型和参数，解析出学生列表

    scope_param 是 dict 或 None：
    - all: 全部学生
    - filtered: { keyword, gender, ethnicity, political_status, dormitory, is_poor }
    - selected: { ids: [1, 2, 3] }
    - id_range: { start_no: "26102030101", end_no: "26102030110" }
    """
    from .student_service import get_students  # 延迟导入，避免循环依赖

    if scope_type == "all":
        result, _ = get_students(db, skip=0, limit=9999)
        return result

    if scope_type == "selected":
        ids = (scope_param or {}).get("ids", [])
        if not ids:
            return []
        return db.query(Student).filter(Student.id.in_(ids)).order_by(Student.student_no).all()

    if scope_type == "id_range":
        start = (scope_param or {}).get("start_no", "")
        end = (scope_param or {}).get("end_no", "")
        q = db.query(Student)
        if start:
            q = q.filter(Student.student_no >= start)
        if end:
            q = q.filter(Student.student_no <= end)
        return q.order_by(Student.student_no).all()

    if scope_type == "filtered":
        params = scope_param or {}
        result, _ = get_students(
            db,
            skip=0,
            limit=9999,
            keyword=params.get("keyword") or None,
            gender=params.get("gender") or None,
            ethnicity=params.get("ethnicity") or None,
            political_status=params.get("political_status") or None,
            dormitory=params.get("dormitory") or None,
            is_poor=params.get("is_poor") or None,
            sort_by=params.get("sort_by") or None,
            sort_order=params.get("sort_order") or "asc",
        )
        return result

    return []
