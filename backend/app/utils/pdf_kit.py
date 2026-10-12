"""两份 PDF 共用的排版机件：字体、不折叠空格、避头尾段落、按框缩放的签字图

请假审批表（leave_pdf.py）与电动车那两份（ev_pass_pdf.py）共用这一份。搬出来的都是
**与「哪一份文档」无关**的东西 —— 字号、行距、列宽、行高这些版式数值留在各自模块，
一份文档一套，谁也影响不到谁。

四条 reportlab 的脾气（都实测过，改这些函数前先看一眼）：

* **连续空格会被折叠**。`"a" + " "*10 + "b"` 与 `"a b"` 排出来一模一样 —— 模板里那套
  「43 个空格把签字推到右边」靠的就是空格，在 PDF 里必须换成不折叠的 U+00A0（见 _sp）。
* **没有「避头尾」，标点会自己占一行**。它按宽度硬切汉字，句号被切到行首就独立成行（Word 不会：
  句号会连着前一个字一起下移）。见 _Paragraph。
* **段内 `<img>` 不计入行高**。图比行高也照样画出去、还不会自己换行，而且是骑在基线上**往正上方
  冒**的；行距变大只推开下面的行、管不到上面。所以留白要在签字行**上面**留（见 _sign_line 里
  那个段首空行）。
* **横向溢出是静默的**。一行总宽超出单元格时既不换行也不报错，直接画到格子外面 —— 所以图宽必须
  用 pdfmetrics.stringWidth 反算余量（见 _sign_line），绝不能凭感觉给。

两个默认值（BODY=12pt / LINE_H=15.6pt）是照着请假审批表的正文与 Word 行网格钉死的，
leave_pdf 里几百处 `_p(...)` 才不用每处补参数。**别的文档别沾这两个默认值** ——
电动车那两份没有行网格，一律走它自己的 `_ep()`（字号与行距都必填，忘了给直接报错）。
"""

import logging
from datetime import datetime
from pathlib import Path

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.textsplit import ALL_CANNOT_START
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph

from ..config import BASE_DIR

logger = logging.getLogger(__name__)

# ---------- 字体 ----------

FONT_NAME = "SimSun"
# 找不到字体文件时的兜底：reportlab 内置的中文 CID 字体，**不嵌入**（换机器可能变方块）。
# 正常走不到这儿 —— assets/fonts 随镜像走（backend/Dockerfile 是 COPY . .）
FALLBACK_FONT = "STSong-Light"
FONT_PATH = BASE_DIR / "assets" / "fonts" / "SimSun.ttf"

# _p() / _style() 的默认字号与行距，见模块头上那段说明
BODY = 12.0
LINE_H = 15.6

# reportlab 的 Frame 四周自带 6pt 内边距（SimpleDocTemplate.build 建 Frame 时没传 padding，
# 吃的是默认值），会让整块内容右移、下移各 6pt。页边距要先减掉它，内容区才正好落在页边距上。
# 与具体哪份文档无关，所以放这儿共用 —— 两份 PDF 的页边距都得减这一下
FRAME_PAD = 6

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


def _sp(n: int) -> str:
    """用于排版的 n 个不折叠空格

    **不能直接用半角空格**：reportlab 把连续空格（含全角「　」）折叠成一个，实测
    `"a" + " "*10 + "b"` 与 `"a b"` 排出来一模一样 —— 模板里那套「几十个空格」会整段失效。
    这里用 U+00A0（就是 XML 里的 &nbsp;），量宽和排版用同一个字符，算术才对得上。
    """
    return "\u00a0" * n   # 显式转义：别写成字面量字符，编辑器"顺手改成空格"就静默失效了


# ---------- 段落 ----------


def _style(size: float = BODY, leading: float = LINE_H, align=TA_LEFT, *, name: str = "pdfkit",
           **kw) -> ParagraphStyle:
    """一个段落样式。*name* 只是给人看的：ParagraphStyle 不进全局 stylesheet，重名无害"""
    return ParagraphStyle(
        name, fontName=_font(), fontSize=size, leading=leading, alignment=align,
        spaceBefore=0, spaceAfter=0, **kw,
    )


def _leading_for(size: float, base_leading: float = LINE_H, body: float = BODY) -> float:
    """字号对应的行距

    正文（12pt）钉在 Word 行网格的 15.6pt 上，和模板一模一样。**缩过字号的行距要跟着缩**：
    长内容排不下时 _shrink_to_fit 会逐档缩字号，行距还顶在 15.6 的话，一个 9pt 的字照样占
    一行 15.6pt，缩了字号也省不出高度、内容一多就顶出第二页（实测 198 字的意见正是这样）。
    """
    return base_leading if size >= body else size * 1.3


# reportlab 自己那份「不能出现在行首」的标点表：。、，）】》」』 这些。
# **必须是这一个对象**被 _Paragraph.wrap 用着 —— 两边各建一个 frozenset 会静默分叉
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


# 长内容逐档缩字号的档位。9pt 是底线：再小印出来不好认，宁可让行变高
SHRINK = (12.0, 11.0, 10.5, 9.0)


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

# 签字图最小可用宽度：余量比它还小就干脆不签 —— 宁可空着，也不能把后面的日期挤出格子
MIN_SIGN_W = 1.5 * cm


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
    base_leading: float = LINE_H,
    size: float = BODY,
) -> Paragraph:
    """一行「……签字：<签字图>……」

    图宽取「框宽」与「该行剩余横向余量」里小的那个。余量是**算**出来的（stringWidth），
    不是估的 —— reportlab 横向溢出既不报错也不换行，会把后面的字直接画到格子外面。

    *inner_w* 是该格的内宽（跨几列不一样，别拿整表宽糊弄）；*indent_pt* 是这一行相对格左的
    起点（模板用前导空格或居中把签字推到右边，这里换算成固定缩进，好处是右边还剩多少能直接算）。
    *base_leading* 是没签字时这一行该有的行距 —— 各文档的行网格不一样，默认值只伺候请假表。
    *size* 是这一行的字号，**不传就是请假表的 12pt**：电动车那两份的字号跟请假不一样
    （10.5 / 14pt），忘了传就会把「经办班委：」印成 12pt —— 页面上看不出错，只有拿尺子量才看得见。
    """
    plain = _sp(spaces_before) + label + _sp(spaces_after) + tail
    avail = inner_w - indent_pt - _w(plain, size)
    tag, img_h = _sign_tag(sign, min(boxes[0], avail), boxes[1])

    body = _sp(spaces_before) + label + tag + _sp(spaces_after) + tail
    if not tag:
        return _p(body, size, align=align, leftIndent=indent_pt)

    # 有图时，段首多一个空行当「留白」。实测：段内 <img> 是骑在基线上、只往**上**冒的
    # （图高 31pt 时，字的位置不随图变，图的顶跑到基线上方 28pt），而且冒出去的那一块不占
    # 本行高度；本行行距变大只会把**下面**的行推开，对上面没用 —— 所以留白必须在签字行**上面**。
    # 放同一个段落里最省事：段内每行行距一样，第一行空着，图正好冒在这段留白里，
    # 不用去撑开上一行（上一行是承诺正文，平白撑开会很难看）。
    #
    # 行距取 max(本行基准行距, 图高/2 + 2)：**空行 + 签字行两行合起来盖住图高**就够，
    # 不必按图高整个撑开。实测图高 31.2 时 leading=15.6（两行 31.2）图就落在
    # 90.0–121.2、上一行 88.7、下一行 123.5 两边都不压；+2 是留点余地。
    # 行距给大了只会白白把整张表撑到第二页
    return _p("<br/>" + body, size, leading=max(base_leading, img_h / 2 + 2),
              align=align, leftIndent=indent_pt)


def _date_cn(value) -> str:
    """模板里那串空白的「年　　月　　日」，给得出日期就换成「2026年10月17日」

    **给不出日期就原样留白**：这些表都是打印出来手签的，日期缺了还能手写补上，印个空的
    「2026年 月 日」或者「None」就真没法看了。历史记录里 reviewed_at 本来就可能为空。
    """
    if isinstance(value, str):  # 模型给了字符串时（直读 sqlite）自己转一下
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            value = None
    if not value:
        return "年" + _sp(2) + "月" + _sp(2) + "日"
    return f"{value.year}年{value.month}月{value.day}日"
