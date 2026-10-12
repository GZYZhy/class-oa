"""生成模板里不写死学校 / 班级信息

    cd backend && python -m pytest tests/test_docx_branding.py -q

三份生成模板（请假审批表、电动车通行证、电动车承诺书）里，电动车那两份已经换成
{{TOKEN}} 占位符：校名、学院、专业年级、住址、车牌号前缀这些都从配置读
（SITE_* 品牌族 + EV_PASS_* 四项）。换学校、换届只改 .env，不用动模板也不用改代码。

**请假审批表是例外**：它的标题「示例大学学生请假审批表」和「学院：示例学院」还是
写死的（本轮没动它）。它同时还要当「资料下载」里给学生手填的空白表，两处共用一份
模板，改动面比电动车那两份大，留给以后单独做。

这些用例不起后端：模板是仓库里的文件，生成函数只读 student / req 的属性、不碰库，
所以鸭子类型的假对象就够（见 [[pydantic-model-construct-ignores-extra]]）。
配置值一律用 monkeypatch 换成哨兵 —— 本机开发会读到仓库根的 .env，CI 上没有这份文件，
直接断言 settings 里的真值就成了「只有本机过」的测试。
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document

from app.config import settings

BACKEND = Path(__file__).resolve().parent.parent
TEMPLATES = (BACKEND / "templates").resolve()

# 模板里不该出现的字样。校名 / 学院 / 专业年级 / 住址 / 毕业年份 / 车牌简称 / 学号示例
HARDCODED = ("示例大学", "示例学院", "示例专业", "示例公寓", "2030年", "北京", "202600001")


def _all_text(doc) -> str:
    """文档全文：正文段落 + 每张表格每个单元格"""
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.extend(p.text for p in cell.paragraphs)
    return "\n".join(parts)


def _sample():
    """一对鸭子类型的假学生 / 假申请 —— 生成函数只读属性，够用了"""
    student = SimpleNamespace(
        name="张三", student_no="20202600001123", class_name="示例",
        phone="13800138000", major="示例专业",
    )
    req = SimpleNamespace(plate_number="京A12345", brand="雅迪")
    return student, req


def _branded(monkeypatch, **overrides):
    """把品牌配置全换成一眼看得出的哨兵值，返回那组值

    用哨兵而不是真值：生成结果里出现「测试大学」就证明值是从配置来的，
    而不是模板里本来就写着它。
    """
    values = {
        "school": "测试大学",
        "college": "测试学院",
        "major": "测试专业",
        "ev_pass_grade": "测试专业26级",
        "ev_pass_graduation": "2099年6月",
        "ev_pass_address": "测试公寓",
        "ev_pass_plate_prefix": "测A",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    return values


def _pass_doc():
    from app.utils.ev_pass_docx import generate_pass_docx

    student, req = _sample()
    return Document(BytesIO(generate_pass_docx(student, req)))


def _promise_doc():
    from app.utils.ev_pass_docx import generate_promise_docx

    student, req = _sample()
    return Document(BytesIO(generate_promise_docx(student, req)))


# ---------- 模板里不写死 ----------

@pytest.mark.parametrize("name", ["电动车通行证.docx", "电动车承诺书.docx"])
def test_ev_pass_templates_have_no_hardcoded_branding(name):
    """模板 XML 里不该出现任何具体的学校 / 班级字样

    查的是整份 XML（含 run 属性），模板里凡是这些值的位置都该是 {{TOKEN}}。
    这条红了不代表功能坏了 —— 说明有人往模板里又写死了一个值，
    那处以后换学校 / 换届就得改模板。
    """
    text = _all_text(Document(str(TEMPLATES / name)))
    found = [word for word in HARDCODED if word in text]
    assert not found, f"{name} 里又写死了：{found}。该处应改成 {{{{TOKEN}}}} 并从配置取值"


# ---------- 值确实来自配置 ----------

def test_pass_fields_come_from_config(monkeypatch):
    """通行证：八个格子各就各位，值全部来自配置和学生记录"""
    v = _branded(monkeypatch)
    table = _pass_doc().tables[0]

    assert [c.text for c in table.rows[1].cells] == [
        "张三", "京A12345", "13800138000", v["college"],
        v["ev_pass_grade"], v["ev_pass_graduation"], "雅迪", v["ev_pass_address"],
    ]


def test_pass_signature_line_is_assembled_from_config(monkeypatch):
    """落款由校名 + 学院 + 班级拼出来，日期是生成当天（不是写死的年份）"""
    v = _branded(monkeypatch)
    text = _all_text(_pass_doc())

    assert f"{v['school']}{v['college']}示例班委员会" in text
    assert f"{datetime.now().year}年" in text, "落款日期该是生成当天"


def test_pass_plate_prefix_is_only_a_hint(monkeypatch):
    """车牌号那一格是标签行里的示例（前缀来自配置），值行填的是学生自己的车牌"""
    v = _branded(monkeypatch)
    table = _pass_doc().tables[0]

    assert table.rows[0].cells[1].text.strip() == f"2.车牌号：{v['ev_pass_plate_prefix']}XXXXXX"
    assert table.rows[1].cells[1].text.strip() == "京A12345"


def test_promise_text_comes_from_config(monkeypatch):
    """承诺书：抬头与正文里的校名 / 学院 / 专业班级都来自配置和学生记录"""
    v = _branded(monkeypatch)
    text = _all_text(_promise_doc())

    assert f"{v['school']}安稳部：" in text
    assert (
        f"系{v['school']}{v['college']}{v['major']}专业示例班学生" in text
    ), "正文那句该按 校名+学院+专业+班级 拼出来"


def test_promise_keeps_the_underline_under_the_name_and_no(monkeypatch):
    """姓名和学号填在一条带下划线的填空线上 —— 下划线是模板给的，填字不能把它弄丢

    这就是「每个 {{TOKEN}} 必须整个落在一个 run 里」的原因：跨 run 就得整段重写，
    那段的下划线连同字号会一起没（见 utils/docx_template.py）。
    """
    _branded(monkeypatch)
    doc = _promise_doc()

    target = next(p for p in doc.paragraphs if "现申请办理电动车校内通行证" in p.text)
    underlined = [r for r in target.runs if r.underline]
    assert underlined, "带下划线的那个 run 不见了，整句格式被重写过"
    assert underlined[0].text == "张三（学号：20202600001123）", (
        "姓名和学号该落在同一条下划线上"
    )


# ---------- 占位符替换的边界 ----------

def test_nothing_left_unfilled(monkeypatch):
    """配齐了就不该有 {{ 残留 —— 印在正式表格上很难看"""
    _branded(monkeypatch)
    for doc, who in ((_pass_doc(), "通行证"), (_promise_doc(), "承诺书")):
        assert "{{" not in _all_text(doc), f"{who}里还有没替换掉的占位符"


def test_empty_config_prints_blank_not_the_token(monkeypatch):
    """配置留空就印成空白，不能把 {{ADDRESS}} 印到要盖章的表格上

    留空是运维自己看得见的事；而没配的占位符印出来，收表的人只会当成乱码。
    """
    _branded(monkeypatch, ev_pass_address="", ev_pass_grade="")
    doc = _pass_doc()
    cells = [c.text for c in doc.tables[0].rows[1].cells]

    assert cells[4] == "" and cells[7] == ""
    assert "{{" not in _all_text(doc)


def test_unknown_token_stays_visible(monkeypatch):
    """模板写了、代码没给值的 token 要原样留着 —— 那是两边对不上，得让人看见

    和上面那条（键在、值是空串）是两种不同情况，别合并。
    """
    from app.utils.docx_template import fill

    doc = Document()
    doc.add_paragraph("已知：{{KNOWN}}，未知：{{UNKNOWN}}")
    fill(doc, {"KNOWN": "填上了"})

    assert doc.paragraphs[0].text == "已知：填上了，未知：{{UNKNOWN}}"


def test_placeholder_split_across_runs_is_not_filled():
    """跨 run 的占位符替换不了 —— 这是有意的，用模板时就得避开

    真按「跨 run 也拼起来替换」做，就得整段重写，填空下划线会消失（见
    test_promise_keeps_the_underline_...）。所以宁可替换不到，让 {{ 露在生成的文档上。
    """
    from app.utils.docx_template import fill

    doc = Document()
    p = doc.add_paragraph()
    p.add_run("{{NA")
    p.add_run("ME}}")
    fill(doc, {"NAME": "张三"})

    assert p.text == "{{NAME}}", "跨 run 的情况居然被替换了，说明改成了整段重写"
