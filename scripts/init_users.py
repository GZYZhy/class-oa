"""
初始化登录账号（后端启动时也会自动执行本逻辑，此脚本用于手动补建）

规则：
- 账号 = 学号
- 默认密码 = 身份证号后 6 位；没有身份证号的退化为学号后 6 位
- 只增不改：已存在的账号不会被重置密码，可放心重复执行

用法：python3 scripts/init_users.py
"""

import sys
from pathlib import Path

# 允许直接以 scripts/init_users.py 方式运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.services import ensure_default_users  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = ensure_default_users(db)
        print(f"账号初始化完成：新建 {result['created']} 个，已存在跳过 {result['skipped']} 个")

        if result["fallback"]:
            print(f"\n以下 {len(result['fallback'])} 人没有身份证号，默认密码改用【学号后6位】，需单独告知：")
            for student_no, name, password in result["fallback"]:
                print(f"  {name}（{student_no}） 默认密码：{password}")

        # 无论是否新建，都列出无身份证号的学生，便于核对
        elif result["created"] == 0:
            print("\n提示：本次没有新建账号。如需确认哪些学生缺身份证号，可查询 students 表。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
