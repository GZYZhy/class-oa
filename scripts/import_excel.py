#!/usr/bin/env python3
"""
Excel 数据导入脚本
把学生信息 Excel 里的数据导入数据库，同时把内嵌照片提取到 data/photos

    python3 scripts/import_excel.py <Excel路径> [工作表名，默认「全部信息」]

Excel 是校内隐私文件，不放在项目里，由命令行指定路径。
"""

import sys
import os
from collections import defaultdict

# 添加上级目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from datetime import datetime, date

import openpyxl
from sqlalchemy.orm import Session

from app.database import engine, Base, SessionLocal
from app.models import Student
from app.services import get_student_by_no

# 照片保存目录（相对于 backend 目录）
PHOTO_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "photos")


def parse_date(value):
    """解析日期"""
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date)):
        return value.date() if isinstance(value, datetime) else value
    return None


def parse_datetime(value):
    """解析日期时间"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return None


def parse_int(value):
    """解析整数"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def parse_str(value):
    """解析字符串，处理 None 和空值"""
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s == "None":
        return None
    return s


def _normalize_position(value):
    """归一化职务字段：'否'、空值统一为'无'，正常值原样返回"""
    s = parse_str(value)
    if not s or s == "否":
        return "无"
    return s


def extract_photos(ws, header_map, student_no_col):
    """
    从工作表中提取照片，按行号关联学号

    返回：{学号: {'gaokao': 路径, 'on_site': 路径}}
    """
    os.makedirs(PHOTO_DIR, exist_ok=True)

    # 高考照片和实地采集列的索引
    gaokao_col_idx = header_map.get("高考照片")
    shidi_col_idx = header_map.get("实地采集")

    if gaokao_col_idx is None and shidi_col_idx is None:
        print("  未找到照片列")
        return {}

    # 先建立行号到学号的映射
    row_to_student_no = {}
    for row_idx in range(2, ws.max_row + 1):
        row = [cell.value for cell in ws[row_idx]]
        if student_no_col < len(row):
            sno = parse_str(row[student_no_col])
            if sno:
                row_to_student_no[row_idx - 1] = sno  # 0-based row index

    # 遍历所有图片
    photo_map = defaultdict(dict)
    photo_count = 0

    for img in ws._images:
        anchor = img.anchor
        from_row = anchor._from.row  # 0-based
        from_col = anchor._from.col

        student_no = row_to_student_no.get(from_row)
        if not student_no:
            continue

        # 确定照片类型
        photo_type = None
        if gaokao_col_idx is not None and from_col == gaokao_col_idx:
            photo_type = "gaokao"
        elif shidi_col_idx is not None and from_col == shidi_col_idx:
            photo_type = "on_site"

        if not photo_type:
            continue

        # 保存图片文件
        ext = "jpg" if img.format == "jpeg" else (img.format or "jpg").lower()
        filename = f"{student_no}_{photo_type}.{ext}"
        filepath = os.path.join(PHOTO_DIR, filename)

        # 读取图片数据（必须先回到流起始位置，
        # openpyxl 解析图片时会移动内部读取位置，否则拿到的数据文件头丢失、图片损坏）
        img.ref.seek(0)
        img_data = img.ref.read()

        with open(filepath, "wb") as f:
            f.write(img_data)

        # 只存文件名：照片经带鉴权的 /api/students/{id}/photo 下发，
        # 前端自己按学生 id 拼地址，这里存的只是个"有没有照片"的标记
        photo_map[student_no][photo_type] = filename
        photo_count += 1

    print(f"  提取照片：{photo_count}张")
    return photo_map


def import_from_excel(excel_path: str, sheet_name: str = "全部信息", extract_photo: bool = True):
    """从 Excel 文件导入学生数据"""
    if not os.path.exists(excel_path):
        print(f"错误：文件不存在 - {excel_path}")
        return

    print(f"正在读取 Excel 文件：{excel_path}")
    wb = openpyxl.load_workbook(excel_path)
    if sheet_name not in wb.sheetnames:
        print(f"错误：工作表 {sheet_name} 不存在")
        print(f"可用工作表：{wb.sheetnames}")
        return

    ws = wb[sheet_name]
    print(f"工作表：{sheet_name}，共 {ws.max_row - 1} 行数据")

    # 读取表头
    headers = [cell.value for cell in ws[1]]
    print(f"列数：{len(headers)}")

    # 建立列名到索引的映射
    header_map = {}
    for idx, header in enumerate(headers):
        if header:
            header_map[str(header).strip()] = idx

    # 确保数据库表存在
    Base.metadata.create_all(bind=engine)

    # 提取照片
    photo_map = {}
    if extract_photo:
        print("正在提取照片...")
        student_no_col = header_map.get("学号", 3)
        photo_map = extract_photos(ws, header_map, student_no_col)

    db = SessionLocal()
    success_count = 0
    update_count = 0
    skip_count = 0

    try:
        for row_idx in range(2, ws.max_row + 1):
            row = [cell.value for cell in ws[row_idx]]

            def get_val(name):
                idx = header_map.get(name)
                if idx is None or idx >= len(row):
                    return None
                return row[idx]

            student_no = parse_str(get_val("学号"))
            name = parse_str(get_val("姓名"))

            if not student_no or not name:
                skip_count += 1
                continue

            # 获取照片路径
            photos = photo_map.get(student_no, {})

            # 检查是否已存在
            existing = get_student_by_no(db, student_no)

            student_data = {
                "student_no": student_no,
                "name": name,
                "gender": parse_str(get_val("性别")),
                "major": parse_str(get_val("专业")),
                "class_name": parse_str(get_val("班级")),
                "birth_date": parse_date(get_val("出生日期")),
                "ethnicity": parse_str(get_val("民族")),
                "political_status": parse_str(get_val("政治面貌")),
                "hometown": parse_str(get_val("生源地")),
                "id_card": parse_str(get_val("身份证号")),
                "exam_no": parse_str(get_val("考生号")),
                "exam_category": parse_str(get_val("考生类别")),
                "subject_type": parse_str(get_val("科类")),
                "exam_type": parse_str(get_val("考试类型")),
                "admission_batch": parse_str(get_val("录取批次")),
                "gaokao_score": parse_int(get_val("高考总分")),
                "high_school": parse_str(get_val("毕业中学")),
                "registration_status": parse_str(get_val("报到状态")) or "已报到",
                "registration_time": parse_datetime(get_val("报到时间")),
                "school_status": parse_str(get_val("在校状态")) or "正常",
                "phone": parse_str(get_val("本人电话")),
                "family_phone": parse_str(get_val("家庭电话")),
                "qq": parse_str(get_val("QQ号码")),
                "email": parse_str(get_val("本人电子邮箱")),
                "family_address": parse_str(get_val("家庭通信地址")),
                "postal_code": parse_str(get_val("邮政编码")),
                "dormitory": parse_str(get_val("宿舍")),
                "bed": parse_str(get_val("床位")),
                # 班委/团学会职务：脏值"否"统一归为"无"
                "class_position": _normalize_position(get_val("班委")),
                "league_position": _normalize_position(get_val("团学会职务")),
                # 贫困生：脏值"无"统一归为"否"
                "is_poor": "是" if parse_str(get_val("贫困生")) == "是" else "否",
                "remark": parse_str(get_val("备注")),
                "gaokao_photo": photos.get("gaokao"),
                "on_site_photo": photos.get("on_site"),
            }

            if existing:
                # 更新已有记录
                for key, value in student_data.items():
                    if key != "student_no":
                        setattr(existing, key, value)
                update_count += 1
            else:
                # 新增记录
                student = Student(**student_data)
                db.add(student)
                success_count += 1

            # 每 10 条 commit 一次
            if (success_count + update_count) % 10 == 0:
                db.commit()

        db.commit()
        print(f"\n导入完成！")
        print(f"  新增：{success_count} 条")
        print(f"  更新：{update_count} 条")
        print(f"  跳过：{skip_count} 条")
        total = success_count + update_count
        print(f"  合计处理：{total} 条")

    except Exception as e:
        db.rollback()
        print(f"导入失败：{e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)
    import_from_excel(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "全部信息")
