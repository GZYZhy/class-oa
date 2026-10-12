"""生成电动车通行证申请表与使用承诺书两份 PDF

以前是套 backend/templates/电动车*.docx（python-docx 逐个 run 换占位符）。改用 reportlab
照模板的排版数值重画，理由是那两条：签字图要落在打印线上，成品要能带不可见溯源水印
（见 services/pdf_watermark_service.py）—— 和请假审批表当初改 PDF 是同一个原因。

**版式数值全部量自那两份 docx**（本机用 qlmanage 渲成图，逐行量出来的）：标题字号、列宽、
行高、行距、首行缩进都写在下面的常量里。改之前先看一眼它们各自上边那句说明 ——
那份模板是别人在 Word 里一格一格摆出来的，数值看着零碎，但动一个整块版面就走样。

**字体**：模板里混用了「华文中宋」「黑体」「方正仿宋_GB2312」「等线」四种，仓库里只有
assets/fonts/SimSun.ttf 这一份能嵌入的中文字体（见 pdf_kit），PDF 一律用它 ——
**字形会比原 Word 细一点，字号与版面位置不变**。要真复刻字形得把那些字体也打进镜像
（授权 + 体积），不值得。

reportlab 那几条脾气（连续空格被折叠、没有避头尾、段内 <img> 不计行高、横向溢出是静默的）
与对付它们的机件都在 utils/pdf_kit.py，这个文件只管这两份文档自己的版式数值。
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from ..config import settings
from .pdf_kit import FRAME_PAD, _date_cn, _height, _Paragraph, _sign_line, _sp, _style

# 单倍行距下一个字号占多高。**两份模板的 docGrid（linePitch=312tw）都没起作用** ——
# 把原 Word 渲成图量过：表格内 15pt 的行距是 17.2pt、承诺书正文 14pt 是 16.6pt，
# 都不是 15.6pt 的整数倍（网格若生效，15pt 该凑成 2 格 = 31.2pt，整块版面会胖一倍）。
LINE_FACTOR = 1.2


def _line_height(size: float) -> float:
    """字号对应的行距

    1.2 是从那两张参照图实测的行距反推的近似值（实测 1.15~1.19）。真实值随字体走，
    而模板里混用了四种字体（华文中宋 / 黑体 / 方正仿宋_GB2312 / 等线），逐个复刻没意义 ——
    PDF 反正一律用 SimSun。它决定的是「一行文字占多高」，差一点只影响行与行的松紧，
    版面结构与内容一个字都不会变。
    """
    return size * LINE_FACTOR


def _ep(text: str, size: float, **kw) -> _Paragraph:
    """这两份文档的段落：字号必给，行距按行网格推（见 _line_height）

    **不走 pdf_kit._p**：那个的默认字号/行距是请假表那一套（12pt / 15.6pt），
    这里字号是 10.5 到 22pt 五种，忘了传就会静默印成 12pt 的错版。
    """
    return _Paragraph(text, _style(size, _line_height(size), **kw))


def _txt(value) -> str:
    """可空字段：None 当空串，别把「None」印到表上"""
    return value or ""


# ---------- 申请表（A4 横版）----------
#
# 「电动自行车通行证补办登记表」—— 前端与学生都叫它「申请表」。2 行 8 列的表格 + 表外四段。

PASS_PAGE = landscape(A4)          # 841.89 × 595.28pt
PASS_MARGIN_TB = 1800 / 20         # pgMar 上下 1800tw = 90pt
PASS_MARGIN_LR = 1440 / 20         # pgMar 左右 1440tw = 72pt
# 版心 697.89 × 415.28pt，减掉 Frame 自带的 6pt 内边距才落在页边距上（见 pdf_kit.FRAME_PAD）
PASS_CONTENT_W = PASS_PAGE[0] - 2 * PASS_MARGIN_LR

PASS_TITLE = "电动自行车通行证补办登记表"
PASS_TITLE_SIZE = 22.0             # P0 的 sz=44

# 八列宽。模板 tblW 14085tw = 704.25pt，**比版心 697.89pt 还宽 6.4pt**（Word 里表格本来就
# 允许探出页边距），这里按 697.89 等比缩一遍 —— 不缩就会溢出到页边距外面。
# 顺带不抄 tblInd 那 4.65pt：reportlab 的 Table 不认 tblInd，要复刻得自己加左缩进，
# 而这是张满宽带框的表，偏 4.65pt 看得出来，不如贴版心左边（左右页边距就对称了）
PASS_COL_W = (73.58, 78.04, 93.65, 78.04, 88.44, 104.05, 93.65, 88.44)

# 两行的 trHeight 922 / 1841 tw = 46.1 / 92.05pt。模板写的是「至少这么高」，
# 内容放不下要照内容撑高（见 _build_table 里的行高算法）
PASS_ROW_H = (46.1, 92.05)

PASS_LABEL_SIZE = 15.0             # 标签行 sz=30（模板里是黑体）
PASS_VALUE_SIZE = 11.0             # 值行 sz=22（模板里是等线）
PASS_CELL_PAD_X = 5.4              # 模板没写 tblCellMar，取 Word 默认 108tw
PASS_CELL_PAD_Y = 3.0

# 表外那几段（本批次人数 / 落款 / 经办班委 / 日期）：模板没给 rPr，继承 docDefaults sz=21
PASS_TAIL_SIZE = 10.5
# 表格与落款之间那个空段：模板里是个 sz=32 的空段落，不是一个固定高度的间隔
PASS_BLANK_SIZE = 16.0

# 照模板原文抄的常量。一个人一张表，本来就只会是 1 —— 提成常量是为了测试能断言
PASS_BATCH_TEXT = "本批次共1人"

PASS_GRID_W = 0.5                  # 细框线。模板走的是 Normal Table，一格线都没有

# 签字图的框。经办班委的签字落在落款与日期之间，纵向才是真约束（见 _sign_line）
SIGN_BOX_W = 4.5 * cm
SIGN_BOX_H = 1.1 * cm

# 八列的标签与取值来源，按列序一一对应。
# 标签**不带编号、不带冒号、不带示例值**（原模板是「1.姓名：」「2.车牌号：京XXXXXX」）：
# 这张表是打印出来手填的，冒号会和手写的字粘在一起，示例值容易被当成「已经填好了」，
# 编号则是从旧版纸质表继承下来的，一排格子并排摆着本来就数得清。
PASS_COLUMNS = (
    ("姓名", lambda s, r: _txt(s.name)),
    ("车牌号", lambda s, r: _txt(r.plate_number)),
    ("联系电话", lambda s, r: _txt(s.phone)),
    ("单位（学院）", lambda s, r: _txt(settings.college)),
    ("专业年级", lambda s, r: _txt(settings.ev_pass_grade)),
    ("毕业时间", lambda s, r: _txt(settings.ev_pass_graduation)),
    ("电动自行车品牌", lambda s, r: _txt(r.brand)),
    ("住址", lambda s, r: _txt(settings.ev_pass_address)),
)


def _build_table(student, req) -> Table:
    """2 行 8 列的表：第一行标签、第二行值"""
    labels = [_ep(label, PASS_LABEL_SIZE) for label, _ in PASS_COLUMNS]
    values = [_ep(get(student, req), PASS_VALUE_SIZE) for _, get in PASS_COLUMNS]
    grid = [labels, values]

    # 行高取「模板声明值」与「实测内容高」里大的那个：trHeight 是「至少这么高」，
    # 照 46.1pt 硬套的话，「电动自行车品牌」在 83.66pt 的内宽里折两行就顶出格子了
    heights = list(PASS_ROW_H)
    for row, cells in enumerate(grid):
        tallest = max(
            _height([cell], PASS_COL_W[i] - 2 * PASS_CELL_PAD_X) for i, cell in enumerate(cells)
        )
        heights[row] = max(heights[row], tallest + 2 * PASS_CELL_PAD_Y)

    style = [
        ("GRID", (0, 0), (-1, -1), PASS_GRID_W, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), PASS_CELL_PAD_X),
        ("RIGHTPADDING", (0, 0), (-1, -1), PASS_CELL_PAD_X),
        ("TOPPADDING", (0, 0), (-1, -1), PASS_CELL_PAD_Y),
        ("BOTTOMPADDING", (0, 0), (-1, -1), PASS_CELL_PAD_Y),
    ]
    return Table(grid, colWidths=list(PASS_COL_W), rowHeights=heights,
                 style=TableStyle(style), hAlign="LEFT")


def _pass_date(req) -> datetime:
    """落款日期取**申请当天**（req.created_at）

    现在模板填的是生成当天，同一条申请今天下、下周下日期会不一样，跟台账对不上。
    库里 created_at 为空（手工导数据）时才退回生成当天。
    """
    return req.created_at or datetime.now()


def generate_pass_pdf(student, req, *, committee_sign: Path | None = None) -> bytes:
    """生成「电动自行车通行证补办登记表」PDF（返回二进制内容）

    *committee_sign* 是经办班委的签字图路径（管理员批准时定下来的那张快照），**由调用方
    解析好传进来**：这个模块不认识 EV_PASS_DIR，也不碰数据库（单测直接塞临时文件）。
    为空或文件不在盘上时，「经办班委」那一行**整行都不出现** —— 连标签都不印。

    水印不在这里加（接口层调 pdf_watermark_service.add_invisible_watermark）。
    """
    story = [
        _ep(PASS_TITLE, PASS_TITLE_SIZE, align=TA_CENTER),
        _build_table(student, req),
        _ep("", PASS_BLANK_SIZE, align=TA_CENTER),
        _ep(PASS_BATCH_TEXT, PASS_TAIL_SIZE, align=TA_RIGHT),
        _ep(f"{settings.school}{settings.college}{_txt(student.class_name)}班委员会",
            PASS_TAIL_SIZE, align=TA_RIGHT),
    ]
    if committee_sign:
        # 签字落在落款与日期之间。横向根本不紧（「经办班委：」才 52.5pt，版心 697.89pt），
        # **纵向才是真约束**：段内 <img> 骑基线只往上冒、不计入行高，全靠 _sign_line 里
        # 那句「段首加空行 + 撑开行距」给它腾地方，不然图会冒上去压住落款
        story.append(_sign_line(
            "经办班委：", committee_sign,
            inner_w=PASS_CONTENT_W, boxes=(SIGN_BOX_W, SIGN_BOX_H),
            align=TA_RIGHT, base_leading=_line_height(PASS_TAIL_SIZE), size=PASS_TAIL_SIZE,
        ))
    story.append(_ep(_date_cn(_pass_date(req)), PASS_TAIL_SIZE, align=TA_RIGHT))

    buf = BytesIO()
    SimpleDocTemplate(
        buf, pagesize=PASS_PAGE,
        leftMargin=PASS_MARGIN_LR - FRAME_PAD, rightMargin=PASS_MARGIN_LR - FRAME_PAD,
        topMargin=PASS_MARGIN_TB - FRAME_PAD, bottomMargin=PASS_MARGIN_TB - FRAME_PAD,
        title=f"{student.name}电动车通行证补办登记表", author=settings.school,
    ).build(story)
    return buf.getvalue()


# ---------- 使用承诺书（A4 纵向）----------

PROMISE_PAGE = A4                  # 595.28 × 841.89pt
PROMISE_MARGIN_TB = 1440 / 20      # pgMar 上下 1440tw = 72pt
PROMISE_MARGIN_LR = 1800 / 20      # pgMar 左右 1800tw = 90pt
PROMISE_CONTENT_W = PROMISE_PAGE[0] - 2 * PROMISE_MARGIN_LR   # 版心 415.28pt

PROMISE_TITLE = "电动自行车使用承诺书"
PROMISE_TITLE_SIZE = 16.0          # P0 的 sz=32
PROMISE_BODY_SIZE = 14.0           # 正文 sz=28
PROMISE_INDENT = 560 / 20          # 正文段落的 firstLine 560tw = 28pt

# 模板里「本人签字：」后面那 15 个带下划线的空格 = 15 × 0.5em = 105pt。
# 没签字图时照原样留一条能手写的线（学生的表还是可能打印出来手签的）
PROMISE_SIGN_BLANKS = 15


def generate_promise_pdf(student, req, *, applicant_sign: Path | None = None) -> bytes:
    """生成「电动自行车使用承诺书」PDF（返回二进制内容）

    *applicant_sign* 是**学生本人**的签字图路径（`sign_photo_path(student)`，由调用方解析），
    落在「本人签字：」后面那条线上。没给图时留着一条空白下划线让人手签，不是什么都不印。

    落款日期同样取申请当天（见 _pass_date）。水印不在这里加。
    """
    major = settings.major or getattr(student, "major", "") or ""
    story = [
        _ep(PROMISE_TITLE, PROMISE_TITLE_SIZE, align=TA_CENTER),
        _ep("", PROMISE_TITLE_SIZE, align=TA_CENTER),
        _ep(f"{settings.school}安稳部：", PROMISE_BODY_SIZE),
        _ep("", PROMISE_BODY_SIZE),
        # 模板里「姓名（学号：…）」那一段带单下划线，照画
        _ep(f"本人<u>{_txt(student.name)}（学号：{_txt(student.student_no)}）</u>，系"
            f"{settings.school}{settings.college}{major}专业{_txt(student.class_name)}班学生，"
            f"现申请办理电动车校内通行证。", PROMISE_BODY_SIZE, firstLineIndent=PROMISE_INDENT),
        _ep("本人承诺申请通行证所对应车辆为本人实际使用，绝不进行代办、伪造、线上买卖通行证等"
            "违反校规的行为。", PROMISE_BODY_SIZE, firstLineIndent=PROMISE_INDENT),
        _ep("", PROMISE_BODY_SIZE, firstLineIndent=PROMISE_INDENT),
    ]

    if applicant_sign:
        story.append(_sign_line(
            "本人签字：", applicant_sign,
            inner_w=PROMISE_CONTENT_W, boxes=(SIGN_BOX_W, SIGN_BOX_H),
            align=TA_RIGHT, base_leading=_line_height(PROMISE_BODY_SIZE), size=PROMISE_BODY_SIZE,
        ))
    else:
        story.append(_ep("本人签字：<u>" + _sp(PROMISE_SIGN_BLANKS) + "</u>",
                         PROMISE_BODY_SIZE, align=TA_RIGHT))
    story.append(_ep(_date_cn(_pass_date(req)), PROMISE_BODY_SIZE, align=TA_RIGHT))

    buf = BytesIO()
    SimpleDocTemplate(
        buf, pagesize=PROMISE_PAGE,
        leftMargin=PROMISE_MARGIN_LR - FRAME_PAD, rightMargin=PROMISE_MARGIN_LR - FRAME_PAD,
        topMargin=PROMISE_MARGIN_TB - FRAME_PAD, bottomMargin=PROMISE_MARGIN_TB - FRAME_PAD,
        title=f"{student.name}电动自行车使用承诺书", author=settings.school,
    ).build(story)
    return buf.getvalue()
