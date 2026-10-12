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

四条 reportlab 的脾气（都实测过，改这个文件前先看一眼）：

* **连续空格会被折叠**。`"a" + " "*10 + "b"` 与 `"a b"` 排出来一模一样 —— 模板里那套
  「43 个空格把签字推到右边」靠的就是空格，在 PDF 里必须换成不折叠的 U+00A0（见 _sp）。
* **没有「避头尾」，标点会自己占一行**。它按宽度硬切汉字，句号被切到行首就独立成行（Word 不会：
  句号会连着前一个字一起下移）。见 _Paragraph。
* **段内 `<img>` 不计入行高**。图比行高也照样画出去、还不会自己换行，而且是骑在基线上**往正上方
  冒**的；行距变大只推开下面的行、管不到上面。所以留白要在签字行**上面**留（见 _sign_line 里
  那个段首空行），行高要按内容自己算（见 _build_table）。
* **横向溢出是静默的**。一行总宽超出单元格时既不换行也不报错，直接画到格子外面 —— 所以图宽必须
  用 pdfmetrics.stringWidth 反算余量（见 _sign_line），绝不能凭感觉给。
"""

import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.textsplit import ALL_CANNOT_START
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from ..config import BASE_DIR, settings

logger = logging.getLogger(__name__)

# ---------- 字体 ----------

FONT_NAME = "SimSun"
# 找不到字体文件时的兜底：reportlab 内置的中文 CID 字体，**不嵌入**（换机器可能变方块）。
# 正常走不到这儿 —— assets/fonts 随镜像走（backend/Dockerfile 是 COPY . .）
FALLBACK_FONT = "STSong-Light"
FONT_PATH = BASE_DIR / "assets" / "fonts" / "SimSun.ttf"

_font_cache: str | None = None


def _font() -> str:
    """注册中文字体（进程内一次），返回字体名"""
    global _font_cache
    if _font_cache is None:
        if FONT_PATH.exists():
            # 必须是纯 TTF：TTFont 不认 .ttc（微软那个 simsun.ttc 是字体集）
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
            _font_cache = FONT_NAME
        else:
            pdfmetrics.registerFont(UnicodeCIDFont(FALLBACK_FONT))
            logger.warning("找不到字体 %s，改用不嵌入的 %s（换机器可能显示成方块）",
                           FONT_PATH, FALLBACK_FONT)
            _font_cache = FALLBACK_FONT
    return _font_cache


# ---------- 排版数值（twips ÷ 20 = pt，全部量自模板 templates/请假审批表.docx）----------

MARGIN_TB = 1440 / 20  # 上下页边距 2.54cm
MARGIN_LR = 1800 / 20  # 左右页边距 3.175cm
# reportlab 的 Frame 四周自带 6pt 内边距（SimpleDocTemplate.build 建 Frame 时没传 padding，
# 吃的是默认值），会让整块内容右移、下移各 6pt。页边距要先减掉它，内容区才正好落在页边距上 ——
# 表格 421.65pt 本来就比可用宽 415.3pt 宽 6.35pt（模板就这样），再叠 6pt 就明显偏心了
FRAME_PAD = 6

# 六列宽，合计 421.65pt（8433tw）。**比页面可用宽 415.3pt 宽 6.35pt** —— 模板就这样，
# Word 里表格本来就允许探出页边距，照抄（不裁列宽，免得整套比例走样）
COL_W = (62.4, 78.35, 45.85, 83.75, 35.4, 115.9)

# 十二行的声明行高（425tw 那几行就是 21.25pt）。模板里没写 hRule，是「至少这么高」，
# 所以实际行高取 max(声明, 内容高) —— 见 _build_table
ROW_H = (21.25, 21.25, 21.25, 21.25, 15.0, 43.75, 21.25, 21.25, 99.5, 82.2, 77.75, 37.25)

LINE_H = 15.6  # docGrid linePitch=312tw：正文每行的行距（缩字号也不改它，Word 的行网格也这么钉）
CELL_PAD_X = 5.4  # 单元格左右内缩进：模板没写 tblCellMar，取 Word 默认 108tw
CELL_PAD_Y = 3.0
BODY = 12.0  # 正文 sz=24
NOTE_SIZE = 10.5  # 表外备注用 Normal 样式的 sz=21
TITLE_SIZE = 15.0  # 标题 sz=30

# 长内容逐档缩字号（模板那套「按字数估着缩」换成了实测高度，见 _shrink_to_fit）。
# 9pt 是底线：再小印出来不好认，宁可让行变高
SHRINK = (12.0, 11.0, 10.5, 9.0)

# 签字图最小可用宽度：余量比它还小就干脆不签 —— 宁可空着，也不能把后面的日期挤出格子
MIN_SIGN_W = 1.5 * cm

TITLE_SUFFIX = "学生请假审批表"

# 表外三行备注，照模板抄：(左缩进 pt, 首行额外回缩 pt, 文字)。模板是 ind left=630 那些
NOTES = (
    (31.5, 31.5, "备注：1.病假在一周内，由班导师审批，学院备案；病假在一周以上、六周以内由学院审批"
                  "并报学生工作部（处）备案：病假在六周以上者，须到教务处办理休学手续。"),
    (31.5, 0, "2.事假三天以内（含三天）由班导师审批，学院备案；事假三天以上，由学院审批并报学生"
              "工作部（处）备案。事假时间最长不超过二周。"),
    (31.5, -10.5, "3.公假由学院审批及办理相关手续并报学生工作部（处）备案。公假一般不得超过二周。"),
)

# 行 11 那一行给签字腾地方：模板的 34 个空格把日期顶在最右边、中间没处插图，这里减到 21 个
ROW11_SPACES = 21


def _sp(n: int) -> str:
    """用于排版的 n 个不折叠空格

    **不能直接用半角空格**：reportlab 把连续空格（含全角「　」）折叠成一个，实测
    `"a" + " "*10 + "b"` 与 `"a b"` 排出来一模一样 —— 模板里那套「几十个空格」会整段失效。
    这里用 U+00A0（就是 XML 里的 &nbsp;），量宽和排版用同一个字符，算术才对得上。
    """
    return "\u00a0" * n   # 显式转义：别写成字面量字符，编辑器"顺手改成空格"就静默失效了


# ---------- 段落 ----------


def _style(size: float = BODY, leading: float = LINE_H, align=TA_LEFT, **kw) -> ParagraphStyle:
    return ParagraphStyle(
        "leave", fontName=_font(), fontSize=size, leading=leading, alignment=align,
        spaceBefore=0, spaceAfter=0, **kw,
    )


def _leading_for(size: float) -> float:
    """字号对应的行距

    正文（12pt）钉在 Word 行网格的 15.6pt 上，和模板一模一样。**缩过字号的行距要跟着缩**：
    长内容排不下时 _shrink_to_fit 会逐档缩字号，行距还顶在 15.6 的话，一个 9pt 的字照样占
    一行 15.6pt，缩了字号也省不出高度、内容一多就顶出第二页（实测 198 字的意见正是这样）。
    """
    return LINE_H if size >= BODY else size * 1.3


# reportlab 自己那份「不能出现在行首」的标点表：。、，）】》」』 这些
_CANNOT_START = frozenset(ALL_CANNOT_START)


class _Paragraph(Paragraph):
    """段落：不让标点独占一行

    Word 排中文有「避头尾」：句号、逗号、右括号这类**不能出现在行首**的标点，会连着前一个字
    一起被推到下一行。reportlab 没有这条规矩，它是按宽度硬切汉字的 —— 实测承诺段那句「1、请假
    期间保持与班导师和辅导员的联系,请假期满按时返校并办理销假手续。」，前 40 字正好占满格内
    版心，句号就自己落到第二行去了。

    这里在折完行之后查一遍：真有标点落在行首（**首行不算**，那是段落自己开的头），就把版心
    **窄掉那个标点本身的宽度**再折一次。窄一个标点宽必定能把前一个字一起挤下去 —— 标点放不下
    本身就说明上一行已经占满到「版心 − 标点宽」之后 —— 于是它就跟前一个字待在同一行了。
    只动真有问题的段落，别的段落一个字都不会挪。**推标点要是让这一段落多占一行，就不推** ——
    标点自己占个行首只是不好看，整张表多出一页是真不能用（见下面 wrap 里那段注释）。
    """

    def wrap(self, availWidth, availHeight):
        width, height = Paragraph.wrap(self, availWidth, availHeight)
        punct = self._orphan_punct()
        if not punct:
            return width, height

        kept = self.style, self.blPara
        self.style = self.style.clone(self.style.name,
                                      rightIndent=_w(punct, self.style.fontSize))
        width2, height2 = Paragraph.wrap(self, availWidth, availHeight)
        if height2 <= height:
            return width2, height2

        # 把标点推下去要多占一行 —— 这一行会一级级传下去，最坏能把整张表挤到第二页
        # （实测：200 字意见 + 长事由 + 长地址那种组合，修了就从一页变两页）。
        # 标点独自占个行首只是不好看，多一页是真不能用，所以这种情况宁可不推。
        self.style, self.blPara, self.height = kept[0], kept[1], height
        return width, height

    def _orphan_punct(self) -> str | None:
        """折行后落在行首的那个标点，没有就是 None

        只看 kind == 0 的折行结果（整段一种字体、纯文字），它的每行是 `(剩余宽, [整行文字])`，
        读起来最省事。带 `<img>` 的签字行是 kind == 1，那种段的宽度本来就是按格内余量算死的、
        折不了行，没有这个问题。rightIndent 非 0 = 这一遍已经在按窄版心折了，不再重复判断。
        """
        blPara = self.blPara
        if blPara.kind != 0 or self.style.rightIndent:
            return None
        for _extra, words in blPara.lines[1:]:
            head = words[0] if words else ""
            if head[:1] in _CANNOT_START:
                return head[0]
        return None


def _p(text: str, size: float = BODY, leading: float | None = None, **kw) -> Paragraph:
    return _Paragraph(text, _style(size, leading if leading is not None else _leading_for(size), **kw))


def _c(text: str | None) -> Paragraph | str:
    """一个居中显示的格；空内容给空串（不要给空段落 —— 那会白占一行高）"""
    return _p(text, align=TA_CENTER) if text else ""


def _fit_cell(text: str | None, width: float, limit: float, align=TA_CENTER):
    """一格里的文字：折行了就缩字号，宁可小一号也别折成两行

    学生填写区那几行是全表最窄也最该矮的地方（邮箱、地址一折行，行高就从 21.6pt 翻到
    37.2pt），而这几行一胖，请假事由就没地方长了 —— 当年「写一点就两页」的根。
    _shrink_to_fit 只在**确实变矮**时才换小字号，所以装得下的格子仍是原样的 12pt。
    """
    return _shrink_to_fit(
        lambda s: [_p(text or "", size=s, align=align)], width, limit)


class _BoldParagraph(Paragraph):
    """标题的假粗体：同一行往右挪 0.35pt 描两遍，笔画就厚了一圈

    模板里的标题是加粗的，不这样处理 PDF 上的标题会比原样细一圈。reportlab 也不是不能真描边
    （``2 Tr``），但那个操作符只挂在 textobject 上、段落内部又自己建 textobject，
    插不进手 —— 描两遍只要三行，也不改任何度量。
    """

    def draw(self):
        super().draw()
        self.canv.saveState()
        self.canv.translate(0.35, 0)
        super().draw()
        self.canv.restoreState()


def _w(text: str, size: float = BODY) -> float:
    """一段文字的精确宽度。**用这个反算余量，不要字面数空格**"""
    return pdfmetrics.stringWidth(text, _font(), size)


def _height(flows, width: float) -> float:
    """一叠 flowable 在给定宽度下占的高度"""
    return sum(f.wrap(width, 1e6)[1] for f in flows)


def _shrink_to_fit(build, width: float, limit: float):
    """长内容逐档缩字号，返回**高度最小**的那一档里字号最大的那个

    缩字号买来的是「每行多放几个字」而不是「行变矮」—— 行距由 Word 的行网格钉死在 15.6pt，
    字号小了行高不变（这点和模板一致）。所以判据是「能不能少一行」：
    **只有确实变矮才换小字号**，否则短内容会被白白缩到 9pt（一行内容高 15.6pt 恒大于
    「声明行高 − 上下内边距」，光比 limit 的话每一档都算「不合格」）。
    limit 只用来提前收工：已经装得下就不必再试更小的字号。
    """
    flows = build(SHRINK[0])
    best = _height(flows, width)
    for size in SHRINK[1:]:
        if best <= limit:
            break
        candidate = build(size)
        h = _height(candidate, width)
        if h < best:
            flows, best = candidate, h
    return flows


# ---------- 签字图 ----------


def _sign_tag(path: Path | None, max_w: float, max_h: float) -> tuple[str, float]:
    """按框等比缩放签字图，返回 (<img> 标签, 图高 pt)

    路径为空 / 读不出尺寸 / **框本身**窄于 MIN_SIGN_W 都返回 ("", 0)，调用方留空 ——
    少一个签字不该让整张表生不出来。

    MIN_SIGN_W 比的是**框宽**，不是缩放完的图宽：行 11 那个框高只有 0.7cm，
    认字条（宽扁）缩完还有 2.5cm 宽，而同样一张方形图就只能缩到 0.7cm 见方 ——
    按缩放后的宽度判会把它整个丢掉，库里却记着「已签字」，表和界面就此对不上。
    图小一点也照印，静默不印才要命。
    """
    if not path or max_w <= 0 or max_h <= 0 or max_w < MIN_SIGN_W:
        return "", 0.0
    try:
        px_w, px_h = ImageReader(str(path)).getSize()
    except Exception:
        logger.warning("签字图读不出尺寸，这一处留空：%s", path)
        return "", 0.0
    if not px_w or not px_h:
        return "", 0.0
    # 按**像素**等比缩放到框内：宽高一起给。只给一边时 reportlab 会按原生比例推另一边，
    # 就没法同时限宽又限高了（边框高、宽图会顶出去）
    scale = min(max_w / px_w, max_h / px_h)
    w, h = px_w * scale, px_h * scale
    return f'<img src="{path}" width="{w:.1f}" height="{h:.1f}" valign="-3"/>', h


def _sign_line(
    label: str,
    sign: Path | None,
    *,
    inner_w: float,
    boxes: tuple[float, float],
    indent_pt: float = 0,
    spaces_before: int = 0,
    spaces_after: int = 0,
    tail: str = "",
    align=TA_LEFT,
) -> Paragraph:
    """一行「……签字：<签字图>……」

    图宽取「框宽」与「该行剩余横向余量」里小的那个。余量是**算**出来的（stringWidth），
    不是估的 —— reportlab 横向溢出既不报错也不换行，会把后面的字直接画到格子外面。

    *inner_w* 是该格的内宽（跨几列不一样，别拿整表宽糊弄）；*indent_pt* 是这一行相对格左的
    起点（模板用前导空格或居中把签字推到右边，这里换算成固定缩进，好处是右边还剩多少能直接算）。
    """
    plain = _sp(spaces_before) + label + _sp(spaces_after) + tail
    avail = inner_w - indent_pt - _w(plain)
    tag, img_h = _sign_tag(sign, min(boxes[0], avail), boxes[1])

    body = _sp(spaces_before) + label + tag + _sp(spaces_after) + tail
    if not tag:
        return _p(body, align=align, leftIndent=indent_pt)

    # 有图时，段首多一个空行当「留白」。实测：段内 <img> 是骑在基线上、只往**上**冒的
    # （图高 31pt 时，字的位置不随图变，图的顶跑到基线上方 28pt），而且冒出去的那一块不占
    # 本行高度；本行行距变大只会把**下面**的行推开，对上面没用 —— 所以留白必须在签字行**上面**。
    # 放同一个段落里最省事：段内每行行距一样，第一行空着，图正好冒在这段留白里，
    # 不用去撑开上一行（上一行是承诺正文，平白撑开会很难看）。
    #
    # 行距取 max(LINE_H, 图高/2 + 2)：**空行 + 签字行两行合起来盖住图高**就够，不必按图高整个撑开。
    # 实测图高 31.2 时 leading=15.6（两行 31.2）图就落在 90.0–121.2、上一行 88.7、下一行 123.5
    # 两边都不压；+2 是留点余地。行距给大了只会白白把整张表撑到第二页
    return _p("<br/>" + body, leading=max(LINE_H, img_h / 2 + 2),
              align=align, leftIndent=indent_pt)


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
    put(8, 0, 5, _p("年" + _sp(2) + "月" + _sp(2) + "日", align=TA_RIGHT))

    # 行 9：班导师意见（批准时填）+ 班导师签字。
    # 签字行在模板里是「居中 + 21 个空格」，等价于从内宽中点起排；这里换成固定的左缩进 ——
    # 起点一样，但右边给签字留了多少能直接算出来
    put(9, 0, 0, _c("班导师<br/>意见"))
    put(9, 1, 5, *_shrink_to_fit(
        lambda s: [
            _p(leave.advisor_opinion or "", size=s),
            _sign_line("签字：", advisor_sign, inner_w=c1_w, indent_pt=93.2,
                       boxes=(4.5 * cm, 1.1 * cm), spaces_before=21),
            _p(_sp(3) + "年" + _sp(2) + "月" + _sp(2) + "日", align=TA_RIGHT),
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

    # 行 11：销假记录 + 申请人签字（同一行）
    put(11, 0, 0, _c("销假记录"))
    put(11, 1, 5, _sign_line(
        "请假人(签字):", applicant_sign, inner_w=c1_w, boxes=(2.4 * cm, 0.7 * cm),
        spaces_after=ROW11_SPACES, tail="年" + _sp(2) + "月" + _sp(2) + "日",
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
