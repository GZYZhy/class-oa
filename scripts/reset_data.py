"""
把数据库恢复成初始化状态：只保留学生个人信息

清空所有业务数据（通知、公告、请假、反馈、修改申请、操作日志、浏览器推送订阅），
删掉请假证明和公告附件的物理文件，并把所有账号恢复成初始密码 + 首次登录强制改密。

⚠️ 不可逆。执行前请先备份 backend/data/。默认密码的算法与
user_service.ensure_default_users 共用同一个函数，不在这里另写一份，
避免两处规则漂移。

刻意**不动**的东西（都是有意保留的，不是漏掉了）：
- data/photos/               学生照片，属于个人信息，不是业务数据
- data/downloads/            静态资料，由 RESOURCE_CATALOG 白名单引用，跟数据库无关
- data/.session_secret       删了全体登录态立刻失效，那是另一个动作
- data/.vapid_private.pem    删了这台服务器上所有浏览器推送订阅立刻失效
- users.bark_key             账号级的设备绑定，跟着账号走，不是业务数据

用法：python3 scripts/reset_data.py
"""

import os
import sys
from pathlib import Path

# 允许直接以 scripts/reset_data.py 方式运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import delete, func, select  # noqa: E402

# 上传目录从各自的接口模块里取，不在这里另写一份路径 —— 万一目录改了，
# 脚本会跟着一起改；自己写死的话只会静默地留下满地孤儿文件
from app.api.announcements import ANNOUNCEMENT_DIR  # noqa: E402
from app.api.leaves import LEAVE_DIR  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Announcement,
    ChangeRequest,
    Feedback,
    LeaveRequest,
    Notice,
    OperationLog,
    PushSubscription,
    Student,
    User,
)
from app.services import default_password  # noqa: E402
from app.utils.security import hash_password  # noqa: E402

# 要清空的业务表。顺序无所谓（表之间没有强外键约束）
CLEAR_MODELS = [
    OperationLog,
    LeaveRequest,
    Feedback,
    ChangeRequest,
    Announcement,
    Notice,
    PushSubscription,
]


def remove_files(names, directory, label: str) -> None:
    """删掉一批上传文件并报告个数

    文件名一律过一遍 os.path.basename 再拼路径：库里的字符串带目录前缀
    （公告存的是 `/api/resources/file/xxx.pdf` 这种），不过这道就可能删到
    data/ 外面去。路径穿越的防线，和 announcements.py 删除公告时一致。
    """
    removed = 0
    for name in names:
        if not name:
            continue
        path = directory / os.path.basename(name)
        if path.exists():
            path.unlink()
            removed += 1
    print(f"  {label:<22} 删掉 {removed} 个文件", flush=True)


def main() -> None:
    db = SessionLocal()
    try:
        print("=== 1. 清空业务数据 ===", flush=True)

        # 先把文件名捞出来 —— 行删掉之后就再也查不到这些名字了
        proof_files = [r[0] for r in db.execute(select(LeaveRequest.proof_file)).all()]
        announcement_files = [r[0] for r in db.execute(select(Announcement.file_path)).all()]

        for model in CLEAR_MODELS:
            removed = db.execute(delete(model)).rowcount
            print(f"  {model.__tablename__:<22} 清掉 {removed} 行", flush=True)

        print("\n=== 2. 账号恢复初始状态（角色保持不变）===", flush=True)
        students = {s.student_no: s for s in db.query(Student).all()}
        reset = 0
        skipped: list[str] = []
        for user in db.query(User).all():
            student = students.get(user.student_no)
            if student is None:
                # 学生表里没有对应的人，保留原样，交给人来判断
                skipped.append(user.student_no)
                continue
            # 默认密码只用于算哈希，绝不打印
            password, _ = default_password(student)
            user.password_hash, user.password_salt = hash_password(password)
            user.must_change_password = True
            user.last_login_at = None
            user.last_login_ip = None
            reset += 1

        db.commit()
        print(f"  users                  重置 {reset} 个账号", flush=True)
        if skipped:
            print(f"  没有对应学生的账号（未动）：{skipped}", flush=True)

        # 先提交数据库、再删文件：万一这中间挂了，留下的是没人引用的孤儿文件
        # （不可见、无害），而不是指向空文件的数据行
        print("\n=== 3. 删除上传的物理文件 ===", flush=True)
        remove_files(proof_files, LEAVE_DIR, "请假证明")
        remove_files(announcement_files, ANNOUNCEMENT_DIR, "公告附件")

        print("\n=== 4. 重置后核对 ===", flush=True)
        for model in CLEAR_MODELS:
            count = db.execute(select(func.count()).select_from(model)).scalar()
            print(f"  {model.__tablename__:<22} {count} 行", flush=True)
        print(f"  students               {db.execute(select(func.count()).select_from(Student)).scalar()} 行", flush=True)
        print(f"  users                  {db.execute(select(func.count()).select_from(User)).scalar()} 行", flush=True)

        roles = db.execute(select(User.role, func.count()).group_by(User.role)).all()
        print("  角色分布：" + "、".join(f"{r} {c} 人" for r, c in roles), flush=True)

        pending = db.execute(
            select(func.count()).select_from(User).where(User.must_change_password.is_(False))
        ).scalar()
        print(f"  仍处于「已改密」状态的账号：{pending} 个（应为 0）", flush=True)

        # 保留项也报一下数，让运维一眼看到这些是**有意**留下的
        print("\n=== 5. 刻意保留 ===", flush=True)
        bark = db.execute(
            select(func.count()).select_from(User).where(User.bark_key.isnot(None), User.bark_key != "")
        ).scalar()
        print(f"  users.bark_key         保留 {bark} 条设备绑定", flush=True)
        print("  data/photos/、data/downloads/、.session_secret、.vapid_private.pem 均未改动", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
