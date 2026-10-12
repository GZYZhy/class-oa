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
TEMPLATES = (BACKEND / "templates").resolve()

# 学生填写区那几行的行距：模板声明是 425tw = 21.25pt，加单元格上下内边距实测 21.6pt。
# 这几行是全表最该盯的地方 —— 它们一胖，事由就没地方长了（当年「写一点就两页」的根）
SHORT_ROW_PITCH = 22.0


def _sample():
    """一对鸭子类型的假学生 / 假请假条 —— 生成函数只读属性，够用了"""
    student = SimpleNamespace(
        name="张三", gender="男", class_name="统26-1", student_no="26102030101",
        phone="13800138000", email="zhangsan@example.com", id_card="110101200601011234",
        qq="123456789", family_address="北京市石景山区晋元庄路5号", family_phone="13900139000",
    )
    leave = SimpleNamespace(
        student_name="张三", start_at=datetime(2026, 10, 15, 8), end_at=datetime(2026, 10, 17, 18),
        leave_type="事假", reason="家里有事需要回去一趟", travel_mode="高铁",
        travel_detail="G123 次", destination="山东省济南市历下区解放路1号",
        destination_phone="13700137000", advisor_opinion="",
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


def test_ev_pass_templates_live_in_the_repo():
    """电动车那两份还是要套 Word 模板（请假审批表改 PDF 后已经不套了）"""
    from app.utils import ev_pass_docx

    for path in (ev_pass_docx.PASS_TEMPLATE, ev_pass_docx.PROMISE_TEMPLATE):
        assert path.exists(), f"模板不见了：{path}"
        assert path.resolve().parent == TEMPLATES, f"该在 {TEMPLATES}，实际在 {path.parent}"


# ---------- 一页装得下 ----------

LONG_CASES = {
    "长事由": lambda st, lv: setattr(lv, "reason", "回家办理身份证并陪伴家人前往医院复查，" * 4),
    "长地址": lambda st, lv: setattr(
        st, "family_address", "北京市石景山区晋元庄路5号北方工业大学金鼎公寓12号楼3单元502室"),
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

    xs = [_x(page, t) for t in ("学生姓名", "张三", "性别", "男", "班级", "统26-1")]
    assert xs == sorted(xs), f"第一行的格子串位了：{['%.1f' % x for x in xs]}"

    row_ys = {t: _y(page, t) for t in ("学生姓名", "张三", "统26-1")}
    assert max(row_ys.values()) - min(row_ys.values()) < 2, f"不在同一行上：{row_ys}"


def test_filled_values_are_on_the_page():
    """该填的字段一个都不能少（漏填是静默的：表格照样生成，格子空着）"""
    student, leave = _sample()
    text = _doc(student, leave)[0].get_text()

    for token in ("张三", "男", "统26-1", "26102030101", "13800138000",
                  "zhangsan@example.com", "110101200601011234", "123456789",
                  "北京市石景山区晋元庄路5号", "13900139000"):
        assert token in text, f"「{token}」没印上去"

    assert "2026年10月15日 8时" in text and "2026年10月17日 18时" in text
    assert "共 3 天" in text, "请假天数要算出来（含起止当天）"
    assert "[事假] 家里有事需要回去一趟" in text
    assert "高铁" in text and "G123 次" in text


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


def test_no_hardcoded_branding():
    """不配置也不该冒出别的学校名 —— 当年的模板里写死着「北方工业大学」「理学院」"""
    from app.utils import leave_pdf

    source = Path(leave_pdf.__file__).read_text(encoding="utf-8")
    for word in ("北方工业大学", "理学院"):
        assert word not in source, f"leave_pdf.py 里又写死了「{word}」，该从配置取"
