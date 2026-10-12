"""请假审批表 PDF 的排版契约：一页装得下、格子没串、字体跟着仓库走

    cd backend && python -m pytest tests/test_leave_template.py -q

以前测的是 templates/请假审批表.docx 套模板的排版 —— 那套行高声明得太高，手写两行事由
就顶到第二页，所以当年专门盯着「学生填写区那几行够不够矮」。现在改成 app/utils/leave_pdf.py
用 reportlab 直接画（行高按内容自己算），「声明行高」这套东西没有了，但同一批契约还在，
而且量得更直接：把生成出来的 PDF 用 PyMuPDF 读回来数页面、量行距、查格子。

签字的图片位置、下载接口、水印在 tests/test_leave_pdf.py 与 tests/test_leave_sign_api.py，
这个文件只管版式。

用例不起后端：生成函数只读 student / leave 的属性、不碰库，鸭子类型的假对象就够
（见 [[pydantic-model-construct-ignores-extra]]）。配置值一律用 monkeypatch 换成哨兵 ——
本机开发会读到仓库根的 .env，直接断言 settings 里的真值就成了「只有本机过」的测试。
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from app.config import settings

BACKEND = Path(__file__).resolve().parent.parent

# 学生填写区那几行的行距：模板声明是 425tw = 21.25pt，加单元格上下内边距实测 21.6pt。
# 这几行是全表最该盯的地方 —— 它们一胖，事由就没地方长了（当年「写一点就两页」的根）
SHORT_ROW_PITCH = 22.0


def _sample():
    """一对鸭子类型的假学生 / 假请假条 —— 生成函数只读属性，够用了"""
    student = SimpleNamespace(
        name="张三", gender="男", class_name="示例", student_no="20260000001",
        phone="13800138000", email="zhangsan@example.com", id_card="110101200601011234",
        qq="123456789", family_address="示例市示例区示例路1号", family_phone="13900139000",
    )
    leave = SimpleNamespace(
        student_name="张三", start_at=datetime(2026, 10, 15, 8), end_at=datetime(2026, 10, 17, 18),
        leave_type="事假", reason="家里有事需要回去一趟", travel_mode="高铁",
        travel_detail="G123 次", destination="山东省济南市历下区解放路1号",
        destination_phone="13700137000", advisor_opinion="",
        # 三处签名旁的日期就取这三个字段（见 test_signature_dates_come_from_the_right_day）
        created_at=datetime(2026, 10, 12, 9, 30), reviewed_at=datetime(2026, 10, 13, 14, 20),
    )
    return student, leave


def _doc(student, leave, **kw):
    """生成 PDF 并读回来"""
    from app.utils.leave_pdf import generate_leave_pdf

    return pymupdf.open(stream=generate_leave_pdf(student, leave, **kw), filetype="pdf")


def _y(page, text: str) -> float:
    """某段文字在页面上的上沿（找不到就报出来是哪一段）"""
    hits = page.search_for(text)
    assert hits, f"PDF 里找不到「{text}」"
    return hits[0].y0


def _x(page, text: str) -> float:
    hits = page.search_for(text)
    assert hits, f"PDF 里找不到「{text}」"
    return hits[0].x0


# ---------- 生成模板放哪儿 ----------

def test_leave_font_lives_in_the_repo():
    """字体必须在仓库里跟着 git 走，不能指望运行环境自己装

    reportlab 靠它排中文（生成出的 PDF 里是子集嵌入的 AAAAAA+SimSun，换机器不变方块）。
    放到数据卷或让运维往系统里装字体，等于把「印得出来」押在部署细节上。
    """
    from app.utils.leave_pdf import FONT_PATH

    assert FONT_PATH.exists(), f"字体不见了：{FONT_PATH}"
    assert FONT_PATH.resolve().parent == (BACKEND / "assets" / "fonts").resolve()
    # 必须是纯 TTF —— reportlab 的 TTFont 不认 .ttc（微软那个 simsun.ttc 是字体集）
    assert FONT_PATH.read_bytes()[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO"), \
        f"{FONT_PATH.name} 不是 TTF 字体文件"


def test_no_docx_templates_left():
    """仓库里已经没有 Word 生成模板了，templates/ 目录本身也该没了

    请假表和电动车那两份都改成 reportlab 手绘 PDF（`utils/leave_pdf.py`、
    `utils/ev_pass_pdf.py`），排版在代码里。留这条是防「谁哪天又往 templates/
    里塞一份模板」—— 真塞了也不会生效（生成时根本不读它），只会在下次改版式时
    让人对着模板改半天、发现改了个寂寞。
    """
    assert not (BACKEND / "templates").exists()


# ---------- 一页装得下 ----------

LONG_CASES = {
    "长事由": lambda st, lv: setattr(lv, "reason", "回家办理身份证并陪伴家人前往医院复查，" * 4),
    "长地址": lambda st, lv: setattr(
        st, "family_address", "示例市示例区示例路1号示例大学示例公寓12号楼3单元502室"),
    "满额意见": lambda st, lv: setattr(lv, "advisor_opinion", "同意。" * 66),  # 198 字，schema 上限 200
    "全拉满": lambda st, lv: (
        setattr(lv, "reason", "回家办理身份证并陪伴家人前往医院复查，" * 4),
        setattr(lv, "advisor_opinion", "同意。" * 66),
        setattr(lv, "travel_detail", "G1234 次列车 北京南站 → 天津西站（二等座 07 车 12A）"),
        setattr(lv, "destination", "天津市和平区南京路某某花园小区12号楼"),
    ),
}


def test_one_page():
    """正常内容就一页"""
    student, leave = _sample()
    assert _doc(student, leave).page_count == 1


@pytest.mark.parametrize("name", list(LONG_CASES))
def test_one_page_even_with_long_content(name):
    """内容再长也不能翻页 —— 请假表翻页等于半张表加三行备注孤零零留在第二页

    缩字号的那几档（_shrink_to_fit）就是为了这个：框住的是「最多一页」这条硬底线。
    """
    student, leave = _sample()
    LONG_CASES[name](student, leave)
    assert _doc(student, leave).page_count == 1, f"{name} 排到第二页去了"


# ---------- 折行：标点不许独占行首 ----------

# 表格右边框的 x 坐标：左边距 90 + 表宽 421.65。越过它就是在格子外面
TABLE_RIGHT = 511.65


def _drawn_lines(page) -> list[str]:
    """页面上真正画出来的每一行（按排版行拼回整行文字）"""
    return ["".join(s["text"] for s in line["spans"])
            for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", [])]


@pytest.mark.parametrize("name", ["普通"] + list(LONG_CASES))
def test_promise_line_keeps_the_full_stop_with_the_char_before_it(name):
    """承诺段结尾的句号跟着「续」走，不许自己占一行

    Word 排中文有「避头尾」：句号这类不能出现在行首的标点会连着前一个字一起被推下去。
    reportlab 没这条规矩，它按宽度硬切汉字 —— 那句 41 字的承诺前 40 字正好占满格内版心，
    句号就自己落到第二行去了（见 leave_pdf._Paragraph）。
    """
    student, leave = _sample()
    if name != "普通":
        LONG_CASES[name](student, leave)

    lines = _drawn_lines(_doc(student, leave)[0])
    promise = [ln for ln in lines if "销假" in ln]
    assert promise, "承诺段整段不见了"
    # 承诺段排两行，末尾那行就是「续。」；句号自己占一行时，这一行只剩一个「。」
    assert lines[lines.index(promise[0]) + 1].startswith("续。"), \
        f"承诺段第二行该以「续。」开头，实际整页这几行是 {lines}"


def test_no_punctuation_starts_a_line():
    """正常内容下，整页没有一个标点独占行首（首行不算 —— 那是各格自己开的头）"""
    from app.utils.leave_pdf import _CANNOT_START

    student, leave = _sample()
    lines = _drawn_lines(_doc(student, leave)[0])
    bad = [ln for ln in lines[1:] if ln[:1] in _CANNOT_START]
    assert not bad, f"这些行的行首是标点：{bad}"


@pytest.mark.parametrize("name", ["普通"] + list(LONG_CASES))
def test_drawn_content_stays_inside_the_table(name):
    """字和图都不越过表格右边框 —— 横向溢出是静默的，只能事后量

    推标点的那套（把标点连着前一个字挤到下一行）也是往右推东西，弄不好正好把它推出格子。
    """
    student, leave = _sample()
    if name != "普通":
        LONG_CASES[name](student, leave)
    page = _doc(student, leave)[0]

    boxes = [pymupdf.Rect(s["bbox"]) for b in page.get_text("dict")["blocks"]
             for l in b.get("lines", []) for s in l["spans"]]
    boxes += [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
    overs = [r for r in boxes if r.x1 > TABLE_RIGHT + 0.5]
    assert not overs, f"{name}：有 {len(overs)} 处越过表格右边框，最右到 {max(r.x1 for r in overs):.1f}"


def test_long_content_shrinks_the_font_before_turning_the_page():
    """长意见是「缩字号」换来的单页，不是把字排到格子外面

    PyMuPDF 读到的字号：正常 12pt；意见写满 200 字时会逐档缩到 9pt（SHRINK 的底线）。
    """
    student, leave = _sample()
    page = _doc(student, leave)[0]
    normal = {s["size"] for b in page.get_text("dict")["blocks"] for l in b.get("lines", [])
              for s in l["spans"]}
    assert 12.0 in {round(s, 1) for s in normal} - {9.0}, "正文该是 12pt"

    leave.advisor_opinion = "同意。" * 66
    page = _doc(student, leave)[0]
    sizes = {round(s["size"], 1) for b in page.get_text("dict")["blocks"] for l in b.get("lines", [])
             for s in l["spans"]}
    assert min(sizes) < 12.0, "200 字的意见该缩字号才对"


# ---------- 学生填写区还是矮的 ----------

def test_student_rows_stay_short():
    """前几行还是 21.25pt 一档，余量留给事由

    行高按内容自己算之后，这几行有可能被「撑胖」而没人发现 —— 单行短文本撑到 30pt 一行，
    事由就没地方长了，这正是当年一填字就两页的根。
    """
    student, leave = _sample()
    page = _doc(student, leave)[0]
    ys = [_y(page, t) for t in ("学生姓名", "学号", "身份证号")]
    pitches = [b - a for a, b in zip(ys, ys[1:])]
    assert max(pitches) <= SHORT_ROW_PITCH, (
        f"学生填写区的行距变高了：{ ['%.1f' % p for p in pitches] }（上限 {SHORT_ROW_PITCH}pt）"
    )


# ---------- 字段落在正确的格子里 ----------

def test_fields_land_in_the_right_cells():
    """抽查第一行的六个格子：左右顺序对、都在同一行上（错一列就整表串行）"""
    student, leave = _sample()
    page = _doc(student, leave)[0]

    xs = [_x(page, t) for t in ("学生姓名", "张三", "性别", "男", "班级", "示例")]
    assert xs == sorted(xs), f"第一行的格子串位了：{['%.1f' % x for x in xs]}"

    row_ys = {t: _y(page, t) for t in ("学生姓名", "张三", "示例")}
    assert max(row_ys.values()) - min(row_ys.values()) < 2, f"不在同一行上：{row_ys}"


def test_filled_values_are_on_the_page():
    """该填的字段一个都不能少（漏填是静默的：表格照样生成，格子空着）"""
    student, leave = _sample()
    text = _doc(student, leave)[0].get_text()

    for token in ("张三", "男", "示例", "20260000001", "13800138000",
                  "zhangsan@example.com", "110101200601011234", "123456789",
                  "示例市示例区示例路1号", "13900139000"):
        assert token in text, f"「{token}」没印上去"

    assert "2026年10月15日 8时" in text and "2026年10月17日 18时" in text
    assert "共 3 天" in text, "请假天数要算出来（含起止当天）"
    assert "[事假] 家里有事需要回去一趟" in text
    assert "高铁" in text and "G123 次" in text


# ---------- 三处签名旁的日期 ----------

def test_signature_dates_come_from_the_right_day():
    """三处手签旁的日期各是各的日子：承诺签字处 = 申请当天、班导师签字处 = 批准当天、
    销假处 = 假期结束日

    这三个日子在库里是三个字段（created_at / reviewed_at / end_at），印错了没人看得出来 ——
    表上都是「2026年10月○○日」，长得一模一样。
    """
    student, leave = _sample()
    text = _doc(student, leave)[0].get_text()

    assert "2026年10月12日" in text, "承诺段签字处该是申请那天（created_at）"
    assert "2026年10月13日" in text, "班导师签字处该是批准那天（reviewed_at）"
    assert "2026年10月17日" in text, "销假处该是假期结束那天（end_at）"


def test_missing_review_time_still_leaves_a_blank_to_sign():
    """批准时间缺失（老记录 / 手工导的数据）时留白给人手签，不印个编出来的日子

    这表本来就是打印出来手签的，日期缺了还能手写补上；印成「2026年 月 日」或者「None」
    就真没法看了。
    """
    student, leave = _sample()
    assert "2026年10月13日" in _doc(student, leave)[0].get_text(), "前提：有批准时间时印这一天"

    leave.reviewed_at = None
    text = _doc(student, leave)[0].get_text()
    assert "2026年10月13日" not in text, "批准时间没了就没这一天"
    assert "None" not in text, "别把 None 印到表上"
    assert "2026年10月12日" in text and "2026年10月17日" in text, "另外两处不受影响"


def test_template_rows_are_all_there():
    """12 行的行头一个不少，三块手签区（班导师 / 学院 / 销假）也都在"""
    student, leave = _sample()
    text = _doc(student, leave)[0].get_text()

    for label in ("学生姓名", "学号", "身份证号", "家庭地址", "请假时间", "请假事由",
                  "出行方式", "去向地址", "本人承诺", "班导师", "学院意见", "销假记录"):
        assert label in text, f"「{label}」那一行没了"

    assert "请假人(签字):" in text, "承诺段末与销假记录的签字行"
    assert "辅导员签字:" in text and "学院领导签字（盖章）：" in text, "学院意见那两处手签"


# ---------- 表外内容 ----------

def test_outside_content_comes_from_config(monkeypatch):
    """标题、学院那行都从配置取（换学校只改 .env），表外三行备注照模板原样印"""
    monkeypatch.setattr(settings, "school", "测试大学")
    monkeypatch.setattr(settings, "college", "测试学院")
    student, leave = _sample()
    text = _doc(student, leave)[0].get_text()

    assert "测试大学学生请假审批表" in text
    assert "学院：测试学院" in text
    for note in ("备注：1.病假在一周内", "2.事假三天以内", "3.公假由学院审批"):
        assert note in text, f"备注少了「{note}」"


# 不该出现在源码里的**本部署的真实值** —— 每一项都有对应的配置键，都该从 .env 取。
# 值取自仓库根的 .env（SITE_* 品牌族 + EV_PASS_* 三项），换学校 / 换届时会变。
# 「示例专业」既是 SITE_MAJOR 又含在 EV_PASS_GRADE「示例专业26级」里，一个词守两处。
HARDCODED_BRANDING = {
    "示例大学": "SITE_SCHOOL",
    "示例学院": "SITE_COLLEGE",
    "示例专业": "SITE_MAJOR",
    "示例公寓": "EV_PASS_ADDRESS",
    "2030年": "EV_PASS_GRADUATION",
    "202600001": "学号（学生自己填的那个，不该有示例值）",
}


def test_no_hardcoded_branding():
    """源码里不许写死本部署的品牌字样 —— 当年的 Word 模板里就写着「示例大学」「示例学院」

    写死的值不报错、也不会让哪条用例红，只是让下次换学校 / 换届的人对着 .env 改半天
    发现没生效。所以只能回来扫源码文本。

    三份都要扫：机件搬去 pdf_kit.py 之后，只盯 leave_pdf.py 会漏掉共享那部分
    （真正画版式的是各自那份，pdf_kit 里反过来可能有通用的示例字样）。

    「值确实是从配置取的」另有一批哨兵断言（tests/test_ev_pass_pdf.py），
    那条证明配置能进文档，这条证明源码里没有第二份值 —— 两条都要。
    """
    from app.utils import ev_pass_pdf, leave_pdf, pdf_kit

    for module in (leave_pdf, ev_pass_pdf, pdf_kit):
        name = Path(module.__file__).name
        source = Path(module.__file__).read_text(encoding="utf-8")
        for word, config in HARDCODED_BRANDING.items():
            assert word not in source, f"{name} 里又写死了「{word}」，该从配置取（{config}）"
