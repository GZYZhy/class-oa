"""电动车申请表 / 承诺书两份 PDF 的版式契约

    cd backend && python -m pytest tests/test_ev_pass_pdf.py -q

盯的三件事都是**静默失效**：字号忘了显式传会印成 pdf_kit 默认的 12pt、
横向溢出被 reportlab 直接画到页边距外面、段内 `<img>` 骑基线往上冒却不占行高会压住上一行
—— 一个错都不报，肉眼扫一眼也未必看得出。这里各配一条探测器。

用例不起后端：生成函数只读 student / req 的属性、不碰库，鸭子类型的假对象就够
（见 [[pydantic-model-construct-ignores-extra]]）。
"""

import io
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from PIL import Image

from app.config import settings
from app.utils.ev_pass_pdf import (
    PASS_BATCH_TEXT, PASS_COL_W, PASS_CONTENT_W, PASS_GRID_W, PASS_MARGIN_LR,
    PROMISE_BODY_SIZE, _line_height,
)

# 签字框的声明宽度（4.5cm ≈ 127.6pt），给 1pt 余量。上限这么宽是为了抓
# 「图按原生像素 1px=1pt 铺开」——4000px 的图一次就顶穿整页
MAX_SIGN_W = 4.5 * 72 / 2.54 + 1


def _sample():
    """一对鸭子类型的假学生 / 假申请"""
    student = SimpleNamespace(
        name="张三", student_no="20260000001", class_name="示例",
        phone="13800138000", major="",
    )
    req = SimpleNamespace(
        brand="雅迪", plate_number="京A1234567",
        # 落款日期取申请当天，不是生成当天（见 ev_pass_pdf._pass_date）
        created_at=datetime(2026, 10, 12, 9, 30),
    )
    return student, req


def _sign(path: Path, px_w: int, px_h: int) -> Path:
    """造一张真图当签字，返回路径

    尺寸要真实：**宽高比是「有没有被拉伸」的唯一依据**，1×1 的图比不出来。
    Pillow 不用另外装 —— 它是 reportlab 的硬依赖。
    """
    buf = io.BytesIO()
    Image.new("RGB", (px_w, px_h), (20, 20, 200)).save(buf, format="PNG")
    path.write_bytes(buf.getvalue())
    return path


def _pass_page(student, req, sign=None):
    from app.utils.ev_pass_pdf import generate_pass_pdf

    blob = generate_pass_pdf(student, req, committee_sign=sign)
    return pymupdf.open(stream=blob, filetype="pdf")


def _promise_page(student, req, sign=None):
    from app.utils.ev_pass_pdf import generate_promise_pdf

    blob = generate_promise_pdf(student, req, applicant_sign=sign)
    return pymupdf.open(stream=blob, filetype="pdf")


def _spans(page):
    return [
        span
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
    ]


def _flat(page) -> str:
    """整页文字去掉所有换行与空格

    表格格子窄，一个标签常折成两行印出来（`2.车牌号：京XXXXXX` 实际是
    `2.车牌号` / `：京XXXX` / `XX` 三行），`get_text()` 是**按排版行**给文本的，
    直接 `in` 必红。要断言的是「这些字印上去了」，折在哪儿是版式的事 ——
    版式另有 test_nothing_is_drawn_past_the_right_margin 盯着。
    """
    return "".join(page.get_text().split())


def _font_sizes(page) -> set:
    """页面上出现过的所有字号（一位小数）"""
    return {round(span["size"], 1) for span in _spans(page)}


def _line_tops(page) -> list:
    """每行文字的顶端 y，从上到下（同一排版行里的多个片段去重）

    空行是**取不到**的：Spacer 一个字都不印。所以「空了几行」只能靠相邻两行之间的
    空白量反推 —— 比正常行距大一截的，就是中间夹了空行。
    """
    return sorted({round(line["bbox"][1], 1) for b in page.get_text("dict")["blocks"]
                   for line in b.get("lines", [])})


def _hline_lengths(page) -> list:
    """页面上所有横线的长度（表格框线、下划线都算）"""
    out = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l" and abs(item[1].y - item[2].y) < 0.1:
                out.append(abs(item[2].x - item[1].x))
    return out


def _sentinel_branding():
    """把六项品牌配置换成哨兵值

    不换的话断言的就是本机 .env 里的真校名真年级 —— 那种测试只有本机过，
    换台机器就红，而且分不清是代码错了还是 .env 没配。
    `major` 故意不带「专业」二字：模板里是「{MAJOR}专业」，配成「示例专业」的话
    印出来会多一个「专业」（见 ev_pass_pdf.generate_promise_pdf）。
    """
    settings.school = "测试大学"
    settings.college = "测试学院"
    settings.major = "测试学科"
    settings.ev_pass_grade = "测试年级26级"
    settings.ev_pass_graduation = "2099年6月"
    settings.ev_pass_address = "测试公寓1号楼"


BRANDING_FIELDS = (
    "school", "college", "major", "ev_pass_grade",
    "ev_pass_graduation", "ev_pass_address",
)


@pytest.fixture(autouse=True)
def _restore_branding():
    """哨兵值用完还回去，别污染同一次 pytest 里的其它用例"""
    before = {name: getattr(settings, name) for name in BRANDING_FIELDS}
    yield
    for name, value in before.items():
        setattr(settings, name, value)


# ---------- 申请表：横版、不溢出、字号别串 ----------

def test_pass_is_one_landscape_page():
    student, req = _sample()
    doc = _pass_page(student, req)
    assert doc.page_count == 1
    page = doc[0]
    assert page.rect.width > page.rect.height, "申请表是 A4 横版"


def test_pass_table_fits_the_content_area():
    """八列宽之和必须等于版心 —— 模板里表格比版心宽 6.4pt，照抄会溢出到页边距外"""
    assert sum(PASS_COL_W) == pytest.approx(PASS_CONTENT_W, abs=0.5)


def test_nothing_is_drawn_past_the_right_margin():
    """横向溢出是静默的：字画到页边距外面，reportlab 不报错也不换行"""
    student, req = _sample()
    req.plate_number = "京A1234567890"        # 往长了填，逼出折行
    req.brand = "雅迪冠能探索版E10"
    _sentinel_branding()
    page = _pass_page(student, req)[0]

    limit = PASS_MARGIN_LR + PASS_CONTENT_W + 1
    for span in _spans(page):
        assert span["bbox"][2] <= limit, f"有文字画到版心外了：{span['text']!r}"
    for info in page.get_image_info():
        assert info["bbox"][2] <= limit, "有图片画到版心外了"


def test_pass_table_has_thin_grid_lines():
    """表框线是后加的（模板走 Normal Table，一格线都没有），线宽 0.5pt"""
    student, req = _sample()
    page = _pass_page(student, req)[0]
    widths = [d.get("width") for d in page.get_drawings()]
    assert any(w is not None and abs(w - PASS_GRID_W) < 0.01 for w in widths), \
        f"没找到 {PASS_GRID_W}pt 的框线，实际线宽有：{sorted(set(widths), key=str)}"


def test_pass_keeps_the_blank_line_under_the_table():
    """表格下沿与落款之间空一行

    原模板里那是个 sz=32 的空段落。**写成 `_ep("", size)` 就没了** —— reportlab 给空字符串
    算出的高度是 0，一声不响；落款会紧贴表格下边框（实测只隔 1.5pt），看着像落款也成了
    表格的最后一行。
    """
    student, req = _sample()
    page = _pass_page(student, req)[0]

    hits = page.search_for(PASS_BATCH_TEXT)
    assert hits, f"落款「{PASS_BATCH_TEXT}」不见了"
    gap = hits[0].y0 - _table_hlines(page)[-1]
    assert gap > 12, f"表格下沿到落款只有 {gap:.1f}pt，空行丢了"


def test_pass_has_all_labels_and_values():
    """八个值一个都不能少（标签归 test_pass_labels_carry_no_number_colon_or_sample 管）"""
    student, req = _sample()
    _sentinel_branding()
    text = _flat(_pass_page(student, req)[0])

    for value in ("张三", "京A1234567", "13800138000", "测试学院",
                  "测试年级26级", "2099年6月", "雅迪", "测试公寓1号楼"):
        assert value in text, f"值「{value}」没印上去"


def test_pass_only_uses_its_own_font_sizes(tmp_path):
    """整页字号必须是声明的那几种，**12.0 一个都不许有**

    这条同时是「忘了给 _sign_line 显式传 size」的探测器：那个参数默认是请假表的
    BODY=12pt，漏传就静默印成 12pt —— 版面上看着只是略小一点，量才量得出来。
    """
    student, req = _sample()
    page = _pass_page(student, req, sign=_sign(tmp_path / "sign.png", 300, 120))[0]

    sizes = _font_sizes(page)
    assert 12.0 not in sizes, f"出现 12pt 了，八成是哪里漏传了 size：{sorted(sizes)}"
    assert sizes <= {22.0, 15.0, 11.0, 10.5}, f"有意料之外的字号：{sorted(sizes)}"


# ---------- 表头那行：不带编号、冒号、示例值 ----------

def _table_hlines(page) -> list:
    """表格的横线（从上到下）—— 顶边、两行之间、底边"""
    return sorted({round(it[1].y, 1) for d in page.get_drawings() for it in d["items"]
                   if it[0] == "l" and abs(it[1].y - it[2].y) < 0.1})


def _table_row_text(page, row: int) -> str:
    """表格第 row 行的文字 —— 按横线切行

    不能拿整页文字量：那会把落款旁边「经办班委：」的冒号也算进来（那是印上去的成品
    内容，跟给人手填的标签不是一码事）。
    """
    ys = _table_hlines(page)
    top, bottom = ys[row], ys[row + 1]
    spans = [s for s in _spans(page) if top <= s["bbox"][1] and s["bbox"][3] <= bottom + 1]
    return "".join(s["text"] for s in spans)


def test_table_cells_are_centred():
    """格内的字左右居中

    标签去掉编号与冒号后只剩两三个字，还贴着格子左边就会明显偏在一头。
    量的是每个 span 中心到所在格子左右边的距离，两边得一样。
    """
    _sentinel_branding()                       # 空配置时这几格没有值，片段数会随环境变
    student, req = _sample()
    page = _pass_page(student, req)[0]

    edges = [PASS_MARGIN_LR]
    for width in PASS_COL_W:
        edges.append(edges[-1] + width)
    top, bottom = _table_hlines(page)[0], _table_hlines(page)[-1]

    checked = 0
    for span in _spans(page):
        x0, _, x1, y1 = span["bbox"]
        if not (top <= span["bbox"][1] and y1 <= bottom + 1):
            continue                                  # 只看表格里的字
        middle = (x0 + x1) / 2
        col = next(i for i in range(len(PASS_COL_W)) if edges[i] <= middle < edges[i + 1])
        gap_l, gap_r = middle - edges[col], edges[col + 1] - middle
        assert abs(gap_l - gap_r) < 2, \
            f"「{span['text']}」没居中：左边空 {gap_l:.1f}、右边空 {gap_r:.1f}"
        checked += 1
    assert checked >= 16, f"表格里的字只量到 {checked} 个片段，格子没画全？"


def test_pass_labels_carry_no_number_colon_or_sample():
    """标签一律不带编号、冒号、示例值

    旧模板上写的是「1.姓名：」「2.车牌号：京XXXXXX」「7.毕业时间／XX年XX月」：
    这张表是打印出来手写的，冒号会和写上去的字粘在一起，示例值容易被当成「已经填好了」，
    编号则是一排格子并排摆着本来就数得清。
    """
    student, req = _sample()
    head = _table_row_text(_pass_page(student, req)[0], 0)

    for junk in ("1", "2", "：", ":", "X"):
        assert junk not in head, f"表头里还有「{junk}」：{head}"
    assert head == "姓名车牌号联系电话单位（学院）专业年级毕业时间电动自行车品牌住址", head


# ---------- 经办班委签字那一行 ----------

def test_committee_line_is_absent_without_a_signature():
    """选「暂不签署」时整行都不出现 —— 连「经办班委」四个字都不印"""
    student, req = _sample()
    page = _pass_page(student, req)[0]
    assert "经办班委" not in page.get_text()
    assert not page.get_image_info()


def test_committee_line_appears_with_a_signature(tmp_path):
    student, req = _sample()
    page = _pass_page(student, req, sign=_sign(tmp_path / "sign.png", 300, 120))[0]
    assert "经办班委：" in page.get_text()
    assert len(page.get_image_info()) == 1


def test_committee_signature_sits_between_tail_and_date(tmp_path):
    """签字图夹在落款与日期之间，上下都不压

    段内 `<img>` 骑基线往正上方冒、且不计入行高，留白全靠 _sign_line 里那句
    「段首空行 + 撑开 leading」算出来 —— 这条就是那个留白算没算够的验收。
    """
    student, req = _sample()
    _sentinel_branding()
    page = _pass_page(student, req, sign=_sign(tmp_path / "sign.png", 300, 120))[0]

    tail = page.search_for("测试大学测试学院示例班委员会")
    date = page.search_for("2026年10月12日")
    assert tail and date, "落款或日期不见了"

    img = pymupdf.Rect(page.get_image_info()[0]["bbox"])
    assert img.y0 >= tail[0].y1 - 0.5, "签字图冒上去压住落款了"
    assert img.y1 <= date[0].y0 + 0.5, "签字图压住日期了"


def test_committee_signature_is_not_stretched_or_oversized(tmp_path):
    student, req = _sample()
    page = _pass_page(student, req, sign=_sign(tmp_path / "sign.png", 400, 130))[0]

    info = page.get_image_info()[0]
    x0, y0, x1, y1 = info["bbox"]
    assert (x1 - x0) <= MAX_SIGN_W, f"图宽 {x1 - x0:.1f}pt，框没框住"
    assert (x1 - x0) / (y1 - y0) == pytest.approx(info["width"] / info["height"], rel=0.02)


# ---------- 承诺书 ----------

def test_promise_keeps_its_blank_lines():
    """承诺书的四处空行：标题下、抬头下、正文两段之间、签字前

    前三处是原模板里的空段落（P1 / P3 / P6），第四处是后加的。**照原样写成空段落是白搭**：
    reportlab 给空字符串算出的高度是 0，四处会一处不剩地全丢掉，整篇挤成一坨 ——
    代码上看不出任何异常，只有量相邻行距才发现（会一律等于 16.8pt 的行距）。
    """
    student, req = _sample()
    tops = _line_tops(_promise_page(student, req)[0])
    gaps = [round(b - a, 1) for a, b in zip(tops, tops[1:])]

    body = _line_height(PROMISE_BODY_SIZE)
    blanks = [gap for gap in gaps if gap > body * 1.5]
    assert len(blanks) == 4, f"空行该有 4 处，实际 {len(blanks)} 处：{gaps}"
    assert max(gaps) < body * 3, f"有一段空得离谱：{gaps}"


def test_promise_is_one_portrait_page_with_full_date():
    student, req = _sample()
    _sentinel_branding()
    doc = _promise_page(student, req)
    assert doc.page_count == 1
    page = doc[0]
    assert page.rect.height > page.rect.width, "承诺书是 A4 纵向"

    assert "本人签字：" in page.get_text()
    text = _flat(page)
    assert "电动自行车使用承诺书" in text
    # 模板里只填了年份（20XX年　　月　　日），现在是实日期，取申请当天
    assert "2026年10月12日" in text, "落款日期没填全"
    # 模板里是「{校名}{学院}{专业}专业{班级}班学生」——
    # major 配成「示例专业」的话这里会印成「示例专业专业」
    assert "测试大学测试学院测试学科专业示例班学生" in text


def test_promise_underlines_the_name_and_student_no():
    """「姓名（学号：…）」那一段照模板带单下划线

    下划线是画出来的线不是文字，只能按长度找：这一条约 180pt，
    而「本人签字：」后面那条手签线只有 105pt，两者分得开
    """
    student, req = _sample()
    page = _promise_page(student, req)[0]
    lengths = [round(n) for n in _hline_lengths(page)]
    assert any(length > 150 for length in lengths), f"姓名那条下划线不见了：{lengths}"


def test_promise_keeps_a_blank_line_when_student_has_no_signature():
    """学生没传签字图时留一条能手写的下划线，不是什么都不印（105pt ≈ 15 个空格）"""
    student, req = _sample()
    page = _promise_page(student, req)[0]
    assert "本人签字：" in page.get_text()
    lengths = [round(n) for n in _hline_lengths(page)]
    assert any(90 < length < 120 for length in lengths), f"没有可手写的下划线：{lengths}"


def test_promise_signature_drops_onto_the_line(tmp_path):
    student, req = _sample()
    page = _promise_page(student, req, sign=_sign(tmp_path / "sign.png", 300, 120))[0]

    assert len(page.get_image_info()) == 1
    img = pymupdf.Rect(page.get_image_info()[0]["bbox"])
    for rect in page.search_for("本人签字："):
        assert not img.intersects(rect), "签字图压住「本人签字：」了"


# ---------- 没图 / 坏图都不能把人打死 ----------

@pytest.mark.parametrize("kind", ["none", "missing", "broken"])
def test_both_documents_survive_a_bad_signature(tmp_path, kind):
    """路径为空、文件不在盘上、文件在但不是图 —— 三种都得照样出单页

    「库里留着文件名、图早被删了」是真会发生的情况（换图 / 删图接口只改库），
    这条路上不能把整张表打死。
    """
    student, req = _sample()
    if kind == "none":
        sign = None
    elif kind == "missing":
        sign = tmp_path / "deleted.png"          # 故意不创建
    else:
        sign = tmp_path / "not-an-image.png"
        sign.write_bytes("这不是图片".encode("utf-8"))

    assert _pass_page(student, req, sign=sign).page_count == 1
    assert _promise_page(student, req, sign=sign).page_count == 1
    assert "本人签字：" in _promise_page(student, req, sign=sign)[0].get_text()


# ---------- 品牌来自配置 ----------

def test_no_placeholder_survives():
    """生成物里不许留下 {{...}} —— 那是 Word 模板时代的占位符写法"""
    student, req = _sample()
    _sentinel_branding()
    for page in (_pass_page(student, req)[0], _promise_page(student, req)[0]):
        text = _flat(page)
        assert "{{" not in text and "}}" not in text


@pytest.mark.parametrize("kind", ["pass", "promise"])
def test_empty_config_prints_blank_not_none(kind):
    """配置没配就印成空白，别把「None」印到要盖章的表格上

    留空是运维自己看得见的事；而「None」印出来，收表的人只会当成乱码。
    造这一页的是 ev_pass_pdf._txt()（`value or ""`）—— 漏了它就会 `f"{settings.school}"`
    那种地方悄悄印出「None」，一个错都不报。
    """
    student, req = _sample()
    for name in BRANDING_FIELDS:
        setattr(settings, name, "")

    page = (_pass_page(student, req) if kind == "pass" else _promise_page(student, req))[0]
    text = _flat(page)
    for junk in ("None", "nan", "{{"):
        assert junk not in text, f"{kind} 印出了「{junk}」"
