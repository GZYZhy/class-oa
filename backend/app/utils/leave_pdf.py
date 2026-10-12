"""生成请假审批表 PDF

以前是拿 backend/templates/请假审批表.docx 套模板（python-docx 改单元格）。改用 reportlab
照着模板的排版数值重画，是因为两件事：

1. **签字图要落在「请假人(签字):」后面那条打印线上**。docx 那边得翻 run 拆 run 才插得进去；
   reportlab 就是段内写一句 ``<img>``，简单得多。
2. **成品要能带不可见溯源水印**（services/pdf_watermark_service.py），那条链路本来就只认 PDF
   （export_service 生成学生信息表跑的也是它）。

模板的排版数值（列宽、行高、行距、单元格内缩进）全部量自那份 docx，见下面的常量；表外内容
（标题、学院、三行备注）照模板复刻。字体用 assets/fonts/SimSun.ttf，reportlab 会把它**子集嵌入**
PDF，于是拿到 PDF 的机器不装宋体也不会变方块。

**reportlab 那几条脾气**（连续空格被折叠、没有避头尾、段内 `<img>` 不计行高、横向溢出是静默的）
和对付它们的机件都在 utils/pdf_kit.py —— 那是这个文件与电动车那两份**共用**的一份，
这个文件只管请假表自己的版式数值。
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from ..config import settings
# 公共机件（见 pdf_kit 模块头）。名字照旧带下划线、照旧从这个模块也能 import 到，
# 所以下面几百行正文与既有测试一个字都不用改 —— 这几行 noqa 别当「没用的导入」删了
from .pdf_kit import (  # noqa: F401
    BODY,
    FALLBACK_FONT,
    FONT_NAME,
    FONT_PATH,
    FRAME_PAD,
    LINE_H,
    MIN_SIGN_W,
    SHRINK,
    _BoldParagraph,
    _c,
    _CANNOT_START,
    _date_cn,
    _font,
    _height,
    _leading_for,
    _p,
    _Paragraph,
    _shrink_to_fit,
    _sign_line,
    _sign_tag,
    _sp,
    _style,
    _w,
)

# ---------- 排版数值（twips ÷ 20 = pt，全部量自模板 templates/请假审批表.docx）----------

MARGIN_TB = 1440 / 20  # 上下页边距 2.54cm
MARGIN_LR = 1800 / 20  # 左右页边距 3.175cm
# FRAME_PAD（Frame 自带的 6pt 内边距）从 pdf_kit 来。这里的页边距必须减掉它 ——
# 表格 421.65pt 本来就比可用宽 415.3pt 宽 6.35pt（模板就这样），再叠 6pt 就明显偏心了

# 六列宽，合计 421.65pt（8433tw）。**比页面可用宽 415.3pt 宽 6.35pt** —— 模板就这样，
# Word 里表格本来就允许探出页边距，照抄（不裁列宽，免得整套比例走样）
COL_W = (62.4, 78.35, 45.85, 83.75, 35.4, 115.9)

# 十二行的声明行高（425tw 那几行就是 21.25pt）。模板里没写 hRule，是「至少这么高」，
# 所以实际行高取 max(声明, 内容高) —— 见 _build_table
ROW_H = (21.25, 21.25, 21.25, 21.25, 15.0, 43.75, 21.25, 21.25, 99.5, 82.2, 77.75, 37.25)

CELL_PAD_X = 5.4  # 单元格左右内缩进：模板没写 tblCellMar，取 Word 默认 108tw
CELL_PAD_Y = 3.0
NOTE_SIZE = 10.5  # 表外备注用 Normal 样式的 sz=21
TITLE_SIZE = 15.0  # 标题 sz=30

TITLE_SUFFIX = "学生请假审批表"

# 表外三行备注，照模板抄：(左缩进 pt, 首行额外回缩 pt, 文字)。模板是 ind left=630 那些
NOTES = (
    (31.5, 31.5, "备注：1.病假在一周内，由班导师审批，学院备案；病假在一周以上、六周以内由学院审批"
                  "并报学生工作部（处）备案：病假在六周以上者，须到教务处办理休学手续。"),
    (31.5, 0, "2.事假三天以内（含三天）由班导师审批，学院备案；事假三天以上，由学院审批并报学生"
              "工作部（处）备案。事假时间最长不超过二周。"),
    (31.5, -10.5, "3.公假由学院审批及办理相关手续并报学生工作部（处）备案。公假一般不得超过二周。"),
)

# 行 11 那一行给签字腾地方：模板的 34 个空格把日期顶在最右边、中间没处插图，这里减到 17 个。
# 比原先的 21 个少 4 个，是因为那一行的日期从空白的「年 月 日」（60pt）换成了实日期
# 「2026年10月17日」（84pt）—— 减少 4 个空格正好把多出来的 24pt 还回去，字和图的位置一点不变
ROW11_SPACES = 17


def _fit_cell(text: str | None, width: float, limit: float, align=TA_CENTER):
    """一格里的文字：折行了就缩字号，宁可小一号也别折成两行

    学生填写区那几行是全表最窄也最该矮的地方（邮箱、地址一折行，行高就从 21.6pt 翻到
    37.2pt），而这几行一胖，请假事由就没地方长了 —— 当年「写一点就两页」的根。
    _shrink_to_fit 只在**确实变矮**时才换小字号，所以装得下的格子仍是原样的 12pt。
    """
    return _shrink_to_fit(
        lambda s: [_p(text or "", size=s, align=align)], width, limit)


# ---------- 表格 ----------


def _rows(student, leave, *, applicant_sign: Path | None, advisor_sign: Path | None) -> list:
    """按 (行, 起列, 止列, 内容) 描述整张表；跨列的格只在左上角放东西，其余由 SPAN 合并

    行号列号与文字都照原来那份模板（backend/templates/请假审批表.docx，已删）的实际结构 ——
    当年是用 python-docx 一格一格量出来的，改这里前先看一眼 constants 上边那段说明。
    """
    start, end = leave.start_at, leave.end_at
    if isinstance(start, str):  # 模型给了字符串时（直读 sqlite）自己转一下
        start = datetime.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.fromisoformat(end)
    days = (end.date() - start.date()).days + 1  # 跨几个日历天（含起止当天）
    time_text = (
        f"{start.year}年{start.month}月{start.day}日 {start.hour}时 至 "
        f"{end.year}年{end.month}月{end.day}日 {end.hour}时（共 {days} 天）"
    )
    reason_text = f"[{leave.leave_type}] {leave.reason}" if leave.leave_type else leave.reason

    full_w = sum(COL_W) - 2 * CELL_PAD_X        # 跨 6 列的内宽 410.85pt
    c1_w = sum(COL_W[1:]) - 2 * CELL_PAD_X      # 跨 5 列的内宽 348.45pt

    cells: list[tuple[int, int, int, list]] = []

    def put(row: int, c0: int, c1: int, *flows):
        """往一个格里堆内容；**同一个格必须合并成一整条**

        网格是按 (行, 列) 认格的，同一个格写成两条的话后一条会把前一条整个盖掉 ——
        行 8 那五段（本人承诺 / 1、 / 2、 / 签字行 / 日期）曾经只剩最后那个日期。
        """
        for cell in cells:
            if cell[0] == row and cell[1] == c0:
                cell[3].extend(f for f in flows if f != "")
                return
        cells.append((row, c0, c1, [f for f in flows if f != ""]))

    def val(row: int, c0: int, c1: int, text):
        """值格：居中的短文本，放不下就缩字号。

        行 3 / 7 的值格只跨两列（内宽 113.4pt），邮箱那一格也才 105pt —— 长一点就折行，
        折一行行高就从 21.6pt 翻到 37.2pt。学生填写区那几行必须矮，事由才有地方长。
        """
        inner = sum(COL_W[c0:c1 + 1]) - 2 * CELL_PAD_X
        put(row, c0, c1, *_fit_cell(text, inner, ROW_H[row] - 2 * CELL_PAD_Y))

    # 行 0-7：学生填的内容（值一律居中，与模板一致）
    put(0, 0, 0, _c("学生姓名")); val(0, 1, 1, student.name)
    put(0, 2, 2, _c("性别"));     val(0, 3, 3, student.gender)
    put(0, 4, 4, _c("班级"));     val(0, 5, 5, student.class_name)

    put(1, 0, 0, _c("学号"));     val(1, 1, 1, student.student_no)
    put(1, 2, 2, _c("电话"));     val(1, 3, 3, student.phone)
    put(1, 4, 4, _c("邮箱"));     val(1, 5, 5, student.email)

    put(2, 0, 0, _c("身份证号")); val(2, 1, 2, student.id_card)
    put(2, 3, 3, _c("QQ/微信"));  val(2, 4, 5, student.qq)

    put(3, 0, 0, _c("家庭地址")); val(3, 1, 2, student.family_address)
    put(3, 3, 3, _c("家人联系电话")); val(3, 4, 5, student.family_phone)

    put(4, 0, 0, _c("请假时间")); val(4, 1, 5, time_text)

    put(5, 0, 0, _c("请假事由"))
    put(5, 1, 5, *_shrink_to_fit(
        lambda s: [_p(reason_text or "", size=s)],
        full_w, ROW_H[5] - 2 * CELL_PAD_Y,
    ))

    put(6, 0, 0, _c("出行方式")); val(6, 1, 2, leave.travel_mode)
    put(6, 3, 3, _c("行程(车次等)")); val(6, 4, 5, leave.travel_detail)

    put(7, 0, 0, _c("去向地址")); val(7, 1, 2, leave.destination)
    put(7, 3, 3, _c("去向联系电话")); val(7, 4, 5, leave.destination_phone)

    # 行 8：本人承诺（模板是一个段落里塞了三个 <w:br>，这里拆成三段，排出来一样）+ 申请人签字。
    # 签字行在模板里是「43 个空格 + 请假人(签字):」（左对齐），空格把签字推到行的右边
    put(8, 0, 5, _p("本人承诺:"))
    put(8, 0, 5, _p("1、请假期间保持与班导师和辅导员的联系,请假期满按时返校并办理销假手续。"))
    put(8, 0, 5, _p("2、请假期间个人人身安全及财产安全责任自负。"))
    put(8, 0, 5, _sign_line("请假人(签字):", applicant_sign,
                            inner_w=full_w, boxes=(2.4 * cm, 1.1 * cm), spaces_before=43))
    # 承诺段末那个日期 = **申请当天**（学生签这份承诺就是在提交申请那天）
    put(8, 0, 5, _p(_date_cn(leave.created_at), align=TA_RIGHT))

    # 行 9：班导师意见（批准时填）+ 班导师签字。
    # 签字行在模板里是「居中 + 21 个空格」，等价于从内宽中点起排；这里换成固定的左缩进 ——
    # 起点一样，但右边给签字留了多少能直接算出来
    put(9, 0, 0, _c("班导师<br/>意见"))
    put(9, 1, 5, *_shrink_to_fit(
        lambda s: [
            _p(leave.advisor_opinion or "", size=s),
            _sign_line("签字：", advisor_sign, inner_w=c1_w, indent_pt=93.2,
                       boxes=(4.5 * cm, 1.1 * cm), spaces_before=21),
            # 班导师签字旁边的日期 = **批准当天**。当时选了「暂不签字」、事后补签的，
            # 这里还是批准那天 —— 补的是签字，批准确实是那天批的（补签接口不动 reviewed_at）
            _p(_sp(3) + _date_cn(leave.reviewed_at), align=TA_RIGHT),
        ],
        c1_w, ROW_H[9] - 2 * CELL_PAD_Y,
    ))

    # 行 10：学院意见 —— 系统不管，原样印出来给人手签（两个空格数都照模板抄）。
    # 模板这一格是 `ind left=480 hanging=480`：**首行不缩进、续行缩进 24pt**。
    # 少了 firstLineIndent=-24 就会连首行也缩进 24pt，可用宽变小，行尾那个「：」被挤到第二行
    put(10, 0, 0, _c("学院意见"))
    put(10, 1, 5,
        _p("辅导员签字:" + _sp(22) + "学院领导签字（盖章）：", leftIndent=24, firstLineIndent=-24),
        _p(_sp(35) + "年" + _sp(2) + "月" + _sp(2) + "日", leftIndent=24))

    # 行 11：销假记录 + 申请人签字（同一行）。销假的日期 = **假期结束日**（请到哪天就哪天销假）
    put(11, 0, 0, _c("销假记录"))
    put(11, 1, 5, _sign_line(
        "请假人(签字):", applicant_sign, inner_w=c1_w, boxes=(2.4 * cm, 0.7 * cm),
        spaces_after=ROW11_SPACES, tail=_date_cn(end),
    ))
    return cells


# 跨列的合并：(起列, 行) 到 (止列, 行)，与 _rows 里的 put 一一对应
_SPANS = (
    ((1, 2), (2, 2)), ((4, 2), (5, 2)),   # 行2 身份证号 / QQ微信
    ((1, 3), (2, 3)), ((4, 3), (5, 3)),   # 行3 地址 / 家人电话
    ((1, 4), (5, 4)),                     # 行4 请假时间
    ((1, 5), (5, 5)),                     # 行5 请假事由
    ((1, 6), (2, 6)), ((4, 6), (5, 6)),   # 行6 出行方式 / 行程
    ((1, 7), (2, 7)), ((4, 7), (5, 7)),   # 行7 去向地址 / 去向电话
    ((0, 8), (5, 8)),                     # 行8 本人承诺
    ((1, 9), (5, 9)),                     # 行9 班导师意见
    ((1, 10), (5, 10)),                   # 行10 学院意见
    ((1, 11), (5, 11)),                   # 行11 销假记录
)


def _build_table(student, leave, *, applicant_sign, advisor_sign) -> Table:
    cells = _rows(student, leave, applicant_sign=applicant_sign, advisor_sign=advisor_sign)

    # 网格：跨列的格只在左上角放内容，被合并掉的格子留空
    grid = [["" for _ in range(len(COL_W))] for _ in range(len(ROW_H))]
    for row, c0, _c1, flows in cells:
        if flows:
            grid[row][c0] = flows[0] if len(flows) == 1 else flows

    # 行高：模板声明的是「至少这么高」，内容放不下就按内容撑高（签字那一行是靠 _sign_line
    # 撑开行距、再在这里体现成行变高的）
    heights = list(ROW_H)
    for row, c0, c1, flows in cells:
        if not flows:
            continue
        inner = sum(COL_W[c0:c1 + 1]) - 2 * CELL_PAD_X
        heights[row] = max(heights[row], _height(flows, inner) + 2 * CELL_PAD_Y)

    style = [
        # 模板里没有 tblBorders（边框来自 Word 默认的表格样式），画出来是细黑线
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), CELL_PAD_X),
        ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PAD_X),
        ("TOPPADDING", (0, 0), (-1, -1), CELL_PAD_Y),
        ("BOTTOMPADDING", (0, 0), (-1, -1), CELL_PAD_Y),
    ] + [("SPAN", a, b) for a, b in _SPANS]

    return Table(grid, colWidths=list(COL_W), rowHeights=heights,
                 style=TableStyle(style), hAlign="LEFT")


def generate_leave_pdf(
    student,
    leave,
    *,
    applicant_sign: Path | None = None,
    advisor_sign: Path | None = None,
) -> bytes:
    """根据学生信息和请假申请，生成填好的请假审批表 PDF（返回二进制内容）

    两个签字图路径由**调用方**解析好传进来：这个模块不认识 PHOTO_DIR / LEAVE_DIR，也不碰数据库
    （单测直接塞临时文件就行）。路径为空或者文件不在盘上都当没图，表照常生成 ——
    少一个签字不该让管理员下载不到表。

    水印不在这里加（接口层调 pdf_watermark_service.add_invisible_watermark）。
    """
    story = [
        _BoldParagraph(f"{settings.school}{TITLE_SUFFIX}", _style(TITLE_SIZE, 18, TA_CENTER)),
        _p(f"学院：{settings.college}"),
        _build_table(student, leave, applicant_sign=applicant_sign, advisor_sign=advisor_sign),
    ]
    for left, first, text in NOTES:
        # 行距显式给 LINE_H：这三行备注虽说字号小，模板里也是压在 15.6pt 的行网格上的
        story.append(_p(text, NOTE_SIZE, LINE_H, leftIndent=left, firstLineIndent=-first))

    buf = BytesIO()
    SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN_LR - FRAME_PAD, rightMargin=MARGIN_LR - FRAME_PAD,
        topMargin=MARGIN_TB - FRAME_PAD, bottomMargin=MARGIN_TB - FRAME_PAD,
        title=f"{leave.student_name}请假审批表", author=settings.school,
    ).build(story)
    return buf.getvalue()
