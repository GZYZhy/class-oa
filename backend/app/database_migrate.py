"""轻量建表补丁

SQLAlchemy 的 `Base.metadata.create_all` 只建「不存在的表」，**不会给已存在的表补列**。
所以直接往模型里加字段，老库启动后会报 `no such column`
（本项目踩过一次：notices.updated_at 是靠手工 ALTER TABLE 补的）。

本模块在 create_all 之后、任何查询之前运行：查出实际列，缺什么补什么。
只用 SQLite 语法（PRAGMA），**补列这条路只服务 SQLite 老库**；其它数据库上
只支持全新安装（新库由 create_all 一次建全，没有老库可补），见 run_migrations。
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
    # 是否初始化临时账号。默认 0：补列时已有的账号全是正常账号，
    # 不会有人被突然当成临时账号（那种会被限制权限、并在初始化完成后删除）
    ("users", "is_bootstrap", "BOOLEAN NOT NULL DEFAULT 0"),
    # 会话代次。默认 0：补列前签发的会话 cookie 里没有这个字段，校验时按 0 处理，
    # 正好和这里的默认值对上，所以升级不会把已登录的人集体踢下线
    ("users", "session_epoch", "INTEGER NOT NULL DEFAULT 0"),
    # 文件公开的查看次数。补完列要从 file_access_logs 回填，否则升级后
    # 之前看过的文件会显示 0 次，看着像从来没人看过（见 _backfill_view_counts）
    ("announcements", "view_count", "INTEGER NOT NULL DEFAULT 0"),
    # 资料下载的下载次数。资料功能上线时就没有访问日志，没有历史可回填
    ("resources", "download_count", "INTEGER NOT NULL DEFAULT 0"),
    # 批量操作涉及的多个学号（JSON 数组）。用于被操作记录反查：
    # 一次导出涉及几十人，每个人查被操作记录时都能找到这条
    ("operation_logs", "target_student_nos", "TEXT DEFAULT ''"),
    # ---------- 自定义 webhook 渠道 ----------
    # 一律默认空串 = 没配东西。补列后老账号行为和补列前完全一致
    # （不会突然有人开始往某个地址发 POST）
    ("users", "webhook_url", "VARCHAR(500) NOT NULL DEFAULT ''"),
    ("users", "webhook_template", "TEXT NOT NULL DEFAULT ''"),
    # webhook 开关：这一列是后加的（一开始只有「地址空不空」这一个判据）。
    # DEFAULT 0 是给新账号的默认值，但**补列时必须按「有没有地址」回填一次** ——
    # 不然升级时会给已经配好地址的人一律盖上「关」，渠道当场静默停摆，
    # 而他那边只是发现收不到通知了、没有任何提示。见 _backfill_webhook_enabled
    ("users", "webhook_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    # ---------- 电子邮件渠道 ----------
    # notify_email 默认空串 = 回退用学生档案里的邮箱；开关默认 0 = 不开启。
    # 全班 36 人都有邮箱，默认打开等于上线当天给所有人发信，所以必须默认关
    ("users", "notify_email", "VARCHAR(100) NOT NULL DEFAULT ''"),
    ("users", "notify_email_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    # ---------- 生日关怀的运行状态 ----------
    # 三列都可空 = 「从没跑过」，与「跑过、但当天没人过生日」区分开（那种是 0）。
    # 只用于页面上显示运行状态、不参与任何判断，所以老库补成 NULL 完全安全
    ("birthday_settings", "last_run_at", "DATETIME"),
    ("birthday_settings", "last_run_birthdays", "INTEGER"),
    ("birthday_settings", "last_run_notices", "INTEGER"),
    # ---------- 学生备注附件 ----------
    # 备注从纯文本升级成 Markdown + 附件。附件元信息以 JSON 串存在这一列，
    # 老行补成空串 = 没有附件，与 noticies.attachments 的模式一致
    ("students", "remark_attachments", "TEXT DEFAULT ''"),
    # ---------- 自备证件照 ----------
    # 第三种照片：学生自己上传的证件照，与高考照片、实地采集照片并列
    ("students", "id_photo", "VARCHAR(200)"),
    # ---------- 手写签字图 ----------
    # 第四张图，但**不进 PHOTO_FIELDS**：照片那条链路是「班委看得见这个学生就能看
    # 他的照片」，签字要凭管理员审批，混进去等于开一条绕过审批的直通车。
    # 打包导入认它（admin_required），取图走 api/sign_photos.py
    ("students", "sign_photo", "VARCHAR(200)"),
    # ---------- 成绩科目形态与满分 ----------
    # 默认值就是「补列前的行为」：老成绩一律当计分科目、按 100 分制看。
    # 若某场真是 150 分制，班委在科目设置里改一次满分即可
    ("grade_subjects", "mode", "VARCHAR(20) NOT NULL DEFAULT 'score'"),
    ("grade_subjects", "full_score", "FLOAT NOT NULL DEFAULT 100"),
    # ---------- 我的日程：事件类型 ----------
    # schedules 表在早期版本已创建，后来才加 event_type。默认空串 = 旧日程没有类型，
    # 与补列前行为一致（create_all 不会给已存在的表补列，只能走这里 ALTER）
    ("schedules", "event_type", "VARCHAR(20) NOT NULL DEFAULT ''"),
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


def _backfill_view_counts(conn) -> None:
    """用已有的访问日志回填 announcements.view_count

    只在 view_count 列**刚被加上**时调用，所以不用做幂等判断。
    不回填的话，升级前学生看过的文件查看次数会显示 0，看着像从来没人看过。
    只数 action='view'：下载在日志里是另一条记录，不算「查看」。
    """
    # 没有访问日志表就没什么可回填的（正常不会发生：本表由 create_all 先建出来）
    if not _existing_columns(conn, "file_access_logs"):
        return

    # WHERE 上再判一次「确实有人看过」：不然日志里会按「被 UPDATE 命中的行数」
    # 报出「回填 N 条」，而实际全是 0，看着像回填出了问题
    view_count_sql = (
        "SELECT COUNT(*) FROM file_access_logs"
        " WHERE file_access_logs.file_id = announcements.id"
        "   AND file_access_logs.action = 'view'"
    )
    result = conn.execute(text(
        f"UPDATE announcements SET view_count = ({view_count_sql})"
        f" WHERE ({view_count_sql}) > 0"
    ))
    if result.rowcount:
        print(f"[迁移] 已按访问日志回填 {result.rowcount} 条文件的查看次数", flush=True)


def _backfill_webhook_enabled(conn) -> None:
    """按「有没有填地址」回填 users.webhook_enabled

    只在 webhook_enabled 列**刚被加上**时调用，所以不用做幂等判断。

    加这一列之前，「发不发」的唯一判据就是「地址是不是空的」—— 填了地址的用户
    本来就一直在收通知。新列的 DEFAULT 0 要是直接生效，这批人会在升级后集体
    静默停摆（他们看不到任何变化，只是再也收不到了）。所以补完列立刻按老口径
    回填：有地址 = 当时是开着的 = 1。

    从更老的版本升上来的情况（webhook_url 和 webhook_enabled 同一趟补出来）：
    那时所有行的 url 都是空串，这条 UPDATE 一行都命中不了，正好是想要的结果。
    """
    result = conn.execute(text(
        "UPDATE users SET webhook_enabled = 1 WHERE webhook_url IS NOT NULL AND webhook_url != ''"
    ))
    if result.rowcount:
        print(
            f"[迁移] 已按已填地址回填 {result.rowcount} 个账号的 webhook 开关（保持升级前就在发的继续发）",
            flush=True,
        )


def run_migrations() -> None:
    """补齐老库缺失的列；新库上什么都不做"""
    if engine.dialect.name != "sqlite":
        # 全新安装时这里**正常就该跳过**：库是 create_all 刚建的，列一个不缺。
        # 所以不能说成「请手工补列」——那会让运维以为哪里做错了。
        # 真正的例外只有一种：把别处的老 SQLite 库搬进 MySQL，那才需要自己补
        print(
            f"[迁移] 跳过补列检查：{engine.dialect.name} 上只支持全新安装"
            "（新库由 create_all 一次建全，没有老库要补列）",
            flush=True,
        )
        return

    seed_needed = False
    view_count_added = False
    webhook_enabled_added = False
    with engine.begin() as conn:
        for table, column, ddl in NEW_COLUMNS:
            columns = _existing_columns(conn, table)
            if not columns or column in columns:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            print(f"[迁移] 已补列 {table}.{column}", flush=True)
            if table == "users" and column == "role":
                seed_needed = True
            if table == "announcements" and column == "view_count":
                view_count_added = True
            if table == "users" and column == "webhook_enabled":
                webhook_enabled_added = True

        if seed_needed:
            _seed_roles(conn)

        if view_count_added:
            _backfill_view_counts(conn)

        if webhook_enabled_added:
            _backfill_webhook_enabled(conn)

        _rebuild_leave_table(conn)
