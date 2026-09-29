#!/usr/bin/env python3
"""
Excel 数据导入脚本
把学生信息 Excel 里的数据导入数据库，同时把内嵌照片提取到 data/photos

    python3 scripts/import_excel.py <Excel路径> [工作表名，默认「全部信息」]

Excel 是校内隐私文件，不放在项目里，由命令行指定路径。

注意：核心解析和写入逻辑在 app/services/student_import_service.py 里，
脚本和 Web 接口都调同一份，保证两边行为一致。
"""

import sys
import os

# 添加上级目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import SessionLocal, Base, engine
from app.models import User
from app.services.student_import_service import parse_excel, import_students


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    excel_path = sys.argv[1]
    sheet_name = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(excel_path):
        print(f"错误：文件不存在 - {excel_path}")
        sys.exit(1)

    # 确保数据库表存在
    Base.metadata.create_all(bind=engine)

    print(f"正在读取 Excel 文件：{excel_path}")
    with open(excel_path, "rb") as f:
        file_bytes = f.read()

    db = SessionLocal()

    try:
        # 第一步：解析
        preview = parse_excel(file_bytes, sheet_name=sheet_name, db=db)
        print(f"工作表：{preview.sheet_name}，共 {preview.total_rows} 行有效数据")
        print(f"  新增：{preview.will_create} 条")
        print(f"  覆盖：{preview.will_update} 条")
        print(f"  跳过：{preview.skip_count} 条")
        if preview.photo_count:
            print(f"  照片：{preview.photo_count} 张")
        if preview.warnings:
            print(f"  警告：{len(preview.warnings)} 条")
            for w in preview.warnings[:5]:
                print(f"    - {w}")
            if len(preview.warnings) > 5:
                print(f"    ... 还有 {len(preview.warnings) - 5} 条")

        # 第二步：真正写入（脚本是命令行，没有确认步骤，直接导入）
        # 从库里找一个 admin 角色的账号当操作人，找不到就跳过日志
        # （全新数据库第一次导入时可能还没有账号，这是正常的）
        operator = (
            db.query(User)
            .filter(User.role == "admin", User.is_external == False)  # noqa: E712
            .first()
        )
        if not operator:
            # 没有管理员就找第一个用户
            operator = db.query(User).first()

        if operator:
            result = import_students(db, preview, operator, ip="127.0.0.1")
        else:
            # 全新数据库还没有任何账号时，造一个临时操作人用于记日志。
            # log_operation 用到 user.student_no 和 display_name(db, user)，
            # 后者对 is_external=True 的账号直接取 display_name。
            class _DummyOp:
                student_no = "system"
                display_name = "系统导入"
                role = "admin"
                is_external = True
                is_active = True
            result = import_students(db, preview, _DummyOp(), ip="127.0.0.1")

        print()
        print("导入完成！")
        print(f"  新增：{result['created']} 条")
        print(f"  覆盖：{result['updated']} 条")
        print(f"  跳过：{result['skipped']} 条")
        total = result["created"] + result["updated"]
        print(f"  合计处理：{total} 条")
        if result["warnings"]:
            print(f"  警告：{len(result['warnings'])} 条")

    except Exception as e:
        db.rollback()
        print(f"导入失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
