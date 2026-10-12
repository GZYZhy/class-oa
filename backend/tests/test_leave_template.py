"""请假审批表模板的排版：别一填字就溢到第二页

    cd backend && python -m pytest tests/test_leave_template.py -q

模板是一张 12 行 × 6 列的表，A4、上下边距各 2.54cm，可用高度 24.62cm。
表格声明的行高（hRule 没写 = auto，意思是「至少这么高」）合计 17.04cm，
表外的标题 / 学院 / 三段备注再占约 3.6cm，剩下约 4cm 才是「请假事由」能长的余量。

改之前前 8 行是按 1.2~1.34cm 声明的，其中 6 行白占掉 2.3cm，余量不到 1.5cm ——
手写两行事由就顶出去了，这就是「写一点东西就变两页」。那 6 行放的都是单行短文本
（姓名、学号、电话、邮箱…），0.75cm 足够，所以压到 425 twips。手签区 4 行和事由
那一行要留出写字的地方，不能动。

模板还得放在仓库的 templates/ 下：data/downloads 是挂载进来的数据卷，跑一次
scripts/setup_resources.py 就会被素材目录里的同名文件盖回去。而「资料下载」里那份
请假审批表是给学生下载手填的空白表，跟这份生成模板是两份东西，各管各的。

这些用例不需要起后端：模板是仓库里的文件，生成函数只读 student / leave 的属性、
不碰库（所以用鸭子类型的假对象就够，见 [[pydantic-model-construct-ignores-extra]]）。
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from docx.oxml.ns import qn

BACKEND = Path(__file__).resolve().parent.parent
TEMPLATES = (BACKEND / "templates").resolve()

TWIPS_PER_CM = 567
# 学生填写区的那几行：单行短文本，0.75cm 就够
SLIM_TWIPS = 425
SLIM_ROWS = (0, 1, 2, 3, 6, 7)
# 表格外面那几行固定内容（标题 15pt + 学院 12pt + 三段备注），实测约 3.6cm
OUTSIDE_CM = 3.6
# 给事由留的余量下限。事由那行声明了 1.54cm，超出部分才吃这个余量，
# 所以 2.5cm 够它再长六七行 —— 一页 A4 写满都未必超
MIN_ROOM_CM = 2.5


def _row_height(row) -> int:
    """这一行声明的行高（twips），没声明返回 0

    hRule 没写就是 auto，即「至少这么高」：内容多了自己会长，所以声明值看着像
    建议，其实照样吃页面预算 —— 这也是它容易被人忽略的原因。
    """
    trPr = row._tr.trPr
    h = trPr.find(qn("w:trHeight")) if trPr is not None else None
    return int(h.get(qn("w:val"))) if h is not None else 0


def _usable_height_cm(doc) -> float:
    """页面可用高度（去掉上下边距）"""
    section = doc.sections[0]
    return section.page_height.cm - section.top_margin.cm - section.bottom_margin.cm


def _template() -> Document:
    from app.utils import leave_docx

    return Document(str(leave_docx.TEMPLATE_PATH))


def _sample():
    """一对鸭子类型的假学生 / 假请假条 —— 生成函数只读属性，够用了"""
    student = SimpleNamespace(
        name="张三", gender="男", class_name="统26-1", student_no="2024000001",
        phone="13800138000", email="zhangsan@example.com", id_card="110101200601011234",
        qq="123456789", family_address="北京市石景山区晋元庄路5号北方工业大学",
        family_phone="13900139000",
    )
    leave = SimpleNamespace(
        start_at=datetime(2026, 10, 15, 8), end_at=datetime(2026, 10, 17, 18),
        leave_type="事假", reason="家里有事需要回去一趟", travel_mode="高铁",
        travel_detail="G123 次", destination="山东省济南市历下区解放路1号",
        destination_phone="13700137000",
    )
    return student, leave


# ---------- 模板放哪儿 ----------

def test_template_lives_in_the_repo():
    """生成模板必须在仓库的 templates/ 下，不能放数据卷里

    data/downloads 是挂载进来的数据卷：.gitignore 不跟踪它，setup_resources.py
    还会拿素材目录里的同名文件把它盖回去 —— 改在里面的排版会无声丢失。
    """
    from app.utils import leave_docx

    path = leave_docx.TEMPLATE_PATH.resolve()
    assert path.exists(), f"模板不见了：{path}"
    assert path.parent == TEMPLATES, f"模板该在 {TEMPLATES}，实际在 {path.parent}"


def test_ev_pass_templates_live_in_the_repo():
    """电动车那两份是纯生成模板（不在「资料下载」清单里），同样得在 templates/ 下"""
    from app.utils import ev_pass_docx

    for path in (ev_pass_docx.PASS_TEMPLATE, ev_pass_docx.PROMISE_TEMPLATE):
        assert path.exists(), f"模板不见了：{path}"
        assert path.resolve().parent == TEMPLATES, f"该在 {TEMPLATES}，实际在 {path.parent}"


# ---------- 排版：留了多少余地 ----------

def test_student_rows_are_slim():
    """学生填写区那几行不能声明得太高 —— 这是「写一点就两页」的根"""
    rows = _template().tables[0].rows
    fat = {i: _row_height(rows[i]) for i in SLIM_ROWS if _row_height(rows[i]) > SLIM_TWIPS}
    assert not fat, (
        f"这几行又变高了（twips）：{fat}，上限 {SLIM_TWIPS}。"
        f"每高出 142 twips（0.25cm）就少一行事由的位置"
    )


def test_table_leaves_room_on_the_page():
    """表格 + 表外固定内容之后，得给请假事由留出够用的余量"""
    doc = _template()
    table_cm = sum(_row_height(r) for r in doc.tables[0].rows) / TWIPS_PER_CM
    usable_cm = _usable_height_cm(doc)
    room_cm = usable_cm - OUTSIDE_CM - table_cm
    assert room_cm > MIN_ROOM_CM, (
        f"表格声明 {table_cm:.2f}cm + 表外 {OUTSIDE_CM}cm，可用高才 {usable_cm:.2f}cm，"
        f"余量只剩 {room_cm:.2f}cm（要留 {MIN_ROOM_CM}cm 以上）"
    )


# ---------- 生成出来的文档 ----------

def test_generated_doc_keeps_the_layout_and_fills_the_right_cells():
    """填好之后排版沿用模板（行高不被生成过程改动），字段也落在正确的格子里"""
    from app.utils.leave_docx import generate_leave_docx

    student, leave = _sample()
    doc = Document(BytesIO(generate_leave_docx(student, leave)))
    table = doc.tables[0]

    rows = table.rows
    assert len(rows) == 12 and len(rows[0].cells) == 6, "模板结构变了（12 行 × 6 列）"
    assert all(_row_height(rows[i]) <= SLIM_TWIPS for i in SLIM_ROWS), \
        "生成时把学生填写区的行高又改回去了"

    # 抽查几个格子：表头对、值填在右边的格子里（错一列就会串行）
    assert rows[0].cells[0].text.strip().startswith("学生姓名")
    assert rows[0].cells[1].text.strip() == "张三"
    assert rows[1].cells[1].text.strip() == "2024000001"
    assert rows[2].cells[1].text.strip() == "110101200601011234"
    assert "2026年10月15日 8时" in rows[4].cells[1].text
    assert "共 3 天" in rows[4].cells[1].text
    assert rows[5].cells[1].text.strip() == "[事假] 家里有事需要回去一趟"
    assert rows[6].cells[1].text.strip() == "高铁"

    # 手签区那三块系统不填，得原样留着
    assert "本人承诺" in rows[8].cells[0].text
    assert "班导师" in rows[9].cells[0].text
    assert "销假记录" in rows[11].cells[0].text
