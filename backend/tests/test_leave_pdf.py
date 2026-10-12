"""请假审批表 PDF 里的签字：位置对、不拉伸、不压字，没图也不炸

    cd backend && python -m pytest tests/test_leave_pdf.py -q

版式契约（单页、行距、12 行都在）在 tests/test_leave_template.py，这个文件只管
**图片** —— 那是 reportlab 最危险的失效模式：图宽溢出格子时它既不报错也不换行，
会把后面的字直接画到格子外面，肉眼扫一眼很容易漏掉。

用例不起后端：生成函数只读 student / leave 的属性、不碰库，鸭子类型的假对象就够
（见 [[pydantic-model-construct-ignores-extra]]）。
"""

import io
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from PIL import Image

# 签字图绘制后允许的宽度上限（pt）。跨 5 列那一格内宽 348.5pt，签字框本身还不到 100pt；
# 给这么宽的上限就是为了抓「图按原生像素尺寸画出来了」——4000px 的图若按 1px=1pt 铺开，
# 一次就顶穿整张表
MAX_DRAWN_W = 120.0


def _sample():
    """一对鸭子类型的假学生 / 假请假条（和 test_leave_template 里那份是同一个东西）"""
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


def _sign(path: Path, px_w: int, px_h: int) -> Path:
    """造一张真图当签字，返回路径

    尺寸要真实：**宽高比就是「有没有被拉伸」的唯一依据**，1×1 的图比不出来。
    Pillow 不用另外装 —— 它是 reportlab 的硬依赖（Requires-Dist: pillow>=9.0.0）。
    """
    buf = io.BytesIO()
    Image.new("RGB", (px_w, px_h), (20, 20, 200)).save(buf, format="PNG")
    path.write_bytes(buf.getvalue())
    return path


def _page(student, leave, applicant=None, advisor=None):
    from app.utils.leave_pdf import generate_leave_pdf

    blob = generate_leave_pdf(student, leave, applicant_sign=applicant, advisor_sign=advisor)
    return pymupdf.open(stream=blob, filetype="pdf")


# ---------- 图在不在、画成了多大 ----------

def test_three_signatures_are_drawn(tmp_path):
    """申请人两处（承诺段末、销假记录）+ 班导师一处 —— 一处都不能少"""
    student, leave = _sample()
    page = _page(
        student, leave,
        applicant=_sign(tmp_path / "applicant.png", 300, 120),
        advisor=_sign(tmp_path / "advisor.png", 400, 130),
    )[0]

    # 按**原生像素**分辨哪张是哪张：PDF 里图放大缩小，像素尺寸还是原样
    by_px = {}
    for info in page.get_image_info():
        by_px.setdefault((info["width"], info["height"]), []).append(info)

    assert len(by_px.get((300, 120), [])) == 2, "申请人签字该有两处（行 8 和行 11）"
    assert len(by_px.get((400, 130), [])) == 1, "班导师签字该有一处（行 9）"


def test_signatures_keep_their_aspect_ratio(tmp_path):
    """等比缩放，不许拉伸 —— 签字图被拉扁一眼就能看出来，比排版错还显眼"""
    student, leave = _sample()
    page = _page(
        student, leave,
        applicant=_sign(tmp_path / "applicant.png", 300, 120),
        advisor=_sign(tmp_path / "advisor.png", 400, 130),
    )[0]

    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        assert (x1 - x0) / (y1 - y0) == pytest.approx(
            info["width"] / info["height"], rel=0.02
        ), f"{info['width']}×{info['height']} 的图被拉成了 {x1 - x0:.1f}×{y1 - y0:.1f}"


def test_giant_signature_is_scaled_into_its_box(tmp_path):
    """4000px 的图照样缩进格子 —— 溢出时 reportlab 不报错、不换行，只会静默画到格外"""
    student, leave = _sample()
    page = _page(student, leave, applicant=_sign(tmp_path / "huge.png", 4000, 4000))[0]

    infos = page.get_image_info()
    assert len(infos) == 2, "两处申请人签字"
    for info in infos:
        w = info["bbox"][2] - info["bbox"][0]
        assert w <= MAX_DRAWN_W, f"图宽 {w:.1f}pt，框没框住"


def test_no_signature_covers_any_text(tmp_path):
    """图和字不许压在一起

    段内 <img> 是骑在基线上**往正上方冒**的，而且冒出去那块不占本行高度 ——
    reportlab 不会替你让位，留白只能自己算（见 leave_pdf._sign_line）。
    这条就是那个留白算没算够的验收。
    """
    student, leave = _sample()
    page = _page(
        student, leave,
        applicant=_sign(tmp_path / "applicant.png", 300, 120),
        advisor=_sign(tmp_path / "advisor.png", 400, 130),
    )[0]

    texts = [
        pymupdf.Rect(span["bbox"])
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
    ]
    for info in page.get_image_info():
        box = pymupdf.Rect(info["bbox"])
        covered = [t for t in texts if box.intersects(t)]
        assert not covered, f"签字图压住了 {len(covered)} 处文字：{covered[:3]}"


def test_row11_still_keeps_its_date(tmp_path):
    """行 11 的「年 月 日」还在，而且排在签字图右边

    行 11 那一格最挤：签字图 + 21 个空格 + 日期全挤在同一条内宽 348.5pt 的格子里，
    图一宽就把日期挤出格（reportlab 静默溢出，页面上看不到任何报错）。
    """
    student, leave = _sample()
    page = _page(student, leave, applicant=_sign(tmp_path / "applicant.png", 300, 120))[0]

    date_hits = [h for h in page.search_for("年") if h.y0 > 600]
    assert date_hits, "行 11 的日期整行不见了"

    # 行 11 那处图：三张图里 y 最大的那个（页面坐标系 y 向下）
    bottom_img = max(page.get_image_info(), key=lambda i: i["bbox"][3])
    assert bottom_img["bbox"][2] < date_hits[0].x0, "图把日期挤到右边去了"


# ---------- 没图的时候 ----------

def test_without_any_signature_it_still_builds():
    """一个签字都没有照样出表 —— 少个签字不该让人下载不到表"""
    student, leave = _sample()
    doc = _page(student, leave)
    assert doc.page_count == 1
    assert "请假人(签字):" in doc[0].get_text()
    assert not doc[0].get_image_info(), "没传图就不该画图"


def test_missing_image_file_is_treated_as_no_image(tmp_path):
    """路径给了、文件却不在盘上：当没图，不抛异常

    「库里留着文件名、图早被删了」是真会发生的情况（换图 / 删图接口只改库），
    这条路上不能把整张表打死。
    """
    student, leave = _sample()
    ghost = tmp_path / "deleted.png"          # 故意不创建
    doc = _page(student, leave, applicant=ghost, advisor=ghost)
    assert doc.page_count == 1
    assert not doc[0].get_image_info()


def test_broken_image_file_is_treated_as_no_image(tmp_path):
    """文件在、但不是图：也当没图。_sign_tag 里那句 try/except 的验收"""
    student, leave = _sample()
    broken = tmp_path / "not-an-image.png"
    broken.write_bytes("这不是图片".encode("utf-8"))
    doc = _page(student, leave, applicant=broken)
    assert doc.page_count == 1
    assert not doc[0].get_image_info()


# ---------- 字体回退 ----------

def test_missing_font_falls_back_instead_of_raising(monkeypatch, tmp_path):
    """字体文件没了也不许抛，退回内置中文字体继续出表

    正常走不到这一步（assets/fonts 随镜像走），但字体是**外部二进制**，一旦
    打包时漏拷，报错位置在「学生下载请假表」这么个说不清的地方。
    """
    from app.utils import leave_pdf

    monkeypatch.setattr(leave_pdf, "FONT_PATH", tmp_path / "不存在.ttf")
    monkeypatch.setattr(leave_pdf, "_font_cache", None)
    student, leave = _sample()

    doc = _page(student, leave)
    assert doc.page_count == 1
    assert "请假人(签字):" in doc[0].get_text()
