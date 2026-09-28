"""轻量建表补丁

SQLAlchemy 的 `Base.metadata.create_all` 只建「不存在的表」，**不会给已存在的表补列**。
所以直接往模型里加字段，老库启动后会报 `no such column`
（本项目踩过一次：notices.updated_at 是靠手工 ALTER TABLE 补的）。

本模块在 create_all 之后、任何查询之前运行：查出实际列，缺什么补什么。
只用 SQLite 语法（PRAGMA），换别的数据库时请手工补列。
"""

from datetime import datetime

from sqlalchemy import insert, text

from .database import SessionLocal, engine

# 需要补的列：(表名, 列名, 列定义)。新库由 create_all 直接建全，这里只服务老库
NEW_COLUMNS = [
    ("users", "role", "VARCHAR(20) NOT NULL DEFAULT 'student'"),
    ("announcements", "publisher", "VARCHAR(50) DEFAULT ''"),
    # 默认 1：补列时老文件一律视为「已公开」，维持原有可见范围
    ("announcements", "is_public", "BOOLEAN NOT NULL DEFAULT 1"),
    # 可空：补列前没人登录过，前端显示「从未登录」
    ("users", "last_login_at", "DATETIME"),
    # 最近登录 IP
    ("users", "last_login_ip", "VARCHAR(45)"),
    # 操作日志里的客户端 IP
    ("operation_logs", "ip", "VARCHAR(45)"),
    # Bark 推送设备 key，可空：补列前没人开过推送
    ("users", "bark_key", "VARCHAR(128)"),
    # ---------- 域外账号 ----------
    # 以下三列可空 / 默认 0：补列后老账号一律视为「学生账号」，
    # 姓名头像仍走学生表，行为与补列前完全一致
    ("users", "display_name", "VARCHAR(50)"),
    ("users", "avatar", "VARCHAR(200)"),
    ("users", "is_external", "BOOLEAN NOT NULL DEFAULT 0"),
    # 意见反馈附件，JSON 数组串。老行补成空串，出参按空列表处理
    ("feedbacks", "attachments", "TEXT DEFAULT ''"),
    # 通知公告附件，JSON 数组串。老行补成空串，出参按空列表处理
    ("notices", "attachments", "TEXT DEFAULT ''"),
    # 通知公告编辑人列表，JSON 数组串。老行补成空串，出参用 publisher 兜底显示
    ("notices", "editors", "TEXT DEFAULT ''"),
    # 是否冻结账号。默认 0：补列时老账号一律视为未冻结，行为与补列前一致
    ("users", "is_frozen", "BOOLEAN NOT NULL DEFAULT 0"),
    # 会话代次。默认 0：补列前签发的会话 cookie 里没有这个字段，校验时按 0 处理，
    # 正好和这里的默认值对上，所以升级不会把已登录的人集体踢下线
    ("users", "session_epoch", "INTEGER NOT NULL DEFAULT 0"),
]

# 首次加 role 列时播种的管理员学号：张邗语（班长）、赵梦婷（团支书）
ADMIN_STUDENT_NOS = ("26102030128", "26102030131")


def _existing_columns(conn, table: str) -> set:
    """取某张表的现有列名；表不存在时是空集合（正常不会发生，防手滑写错表名）"""
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _seed_roles(conn) -> None:
    """按现有名单播种一次角色

    只在 role 列「刚被加上」时调用，所以管理员日后把谁降权，不会重启又变回来。
    """
    for student_no in ADMIN_STUDENT_NOS:
        conn.execute(
            text("UPDATE users SET role = 'admin' WHERE student_no = :no"),
            {"no": student_no},
        )
    # 班委：学生表里填了班委职务的人（导入 Excel 时脏值「否」已归一为「无」）
    conn.execute(text(
        "UPDATE users SET role = 'committee' "
        "WHERE role = 'student' AND student_no IN ("
        "  SELECT student_no FROM students "
        "  WHERE class_position IS NOT NULL AND class_position NOT IN ('', '无')"
        ")"
    ))
    counts = dict(conn.execute(text("SELECT role, COUNT(*) FROM users GROUP BY role")).fetchall())
    print(f"[迁移] 角色已初始化：管理员 {counts.get('admin', 0)} 人、"
          f"班委 {counts.get('committee', 0)} 人、学生 {counts.get('student', 0)} 人", flush=True)


def _rebuild_leave_table(conn) -> None:
    """请假表：旧版起止只到「日」，新版精确到「时」

    该功能尚未正式上线、表里没有数据，所以直接弃掉旧表按新结构重建
    （SQLite 改不了已有列的类型，只能换新列名）。
    建表语句直接取模型定义，避免在这里再抄一遍字段。
    """
    columns = _existing_columns(conn, "leave_requests")
    # 没有旧列、或已经是新结构，都不用管
    if "start_at" in columns or "start_date" not in columns:
        return
    from .models import LeaveRequest

    conn.execute(text("DROP TABLE leave_requests"))
    LeaveRequest.__table__.create(bind=conn)
    print("[迁移] 已按「精确到小时」的新结构重建 leave_requests", flush=True)


def backfill_notice_reads() -> None:
    """把升级前就已存在的通知，一次性补成「全员已读」

    调用条件由 main.py 把关：只在 notice_reads 表**刚被建出来**的那一次启动时跑，
    所以这里不用做幂等判断，也不会把将来新发的通知误标成已读。

    为什么必须补：老版本没有已读这个概念，升级后一条记录都没有的话，
    每个人一登录就会看到红点上写着「未读 30 条」，而那些通知他们早就看过了；
    班委打开「已读情况」也会看到一份全是不准的名单。补完之后，
    红点只反映升级之后新发的通知。
    """
    # 在函数内 import：models 会反过来用到 database，放到模块顶部容易绕成循环导入
    from .models import Notice, NoticeRead, User

    with SessionLocal() as db:
        notice_ids = [row[0] for row in db.query(Notice.id).all()]
        student_nos = [row[0] for row in db.query(User.student_no).all()]
        if not notice_ids or not student_nos:
            # 全新部署（没有老通知）或还没有任何账号，无事可做
            return

        now = datetime.now()
        db.execute(
            insert(NoticeRead),
            [
                {"notice_id": notice_id, "student_no": student_no, "read_at": now}
                for notice_id in notice_ids
                for student_no in student_nos
            ],
        )
        db.commit()
        print(
            f"[迁移] 已把 {len(notice_ids)} 条既有通知补为「全员已读」"
            f"（{len(notice_ids) * len(student_nos)} 行）",
            flush=True,
        )


def run_migrations() -> None:
    """补齐老库缺失的列；新库上什么都不做"""
    if engine.dialect.name != "sqlite":
        print(f"[迁移] 跳过：当前数据库是 {engine.dialect.name}，请手工补列", flush=True)
        return

    seed_needed = False
    with engine.begin() as conn:
        for table, column, ddl in NEW_COLUMNS:
            columns = _existing_columns(conn, table)
            if not columns or column in columns:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            print(f"[迁移] 已补列 {table}.{column}", flush=True)
            if table == "users" and column == "role":
                seed_needed = True

        if seed_needed:
            _seed_roles(conn)

        _rebuild_leave_table(conn)
