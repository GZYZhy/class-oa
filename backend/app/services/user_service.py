"""账号服务：登录账号的自动初始化

账号规则（自动初始化，无需人工建号）：
- 账号 = 学号
- 默认密码 = 身份证号后 6 位；没有身份证号的退化为学号后 6 位
- 首次登录强制改密

另有一套「初始化临时账号」机制，解决的是**空库根本没有账号**的情况，
见文件末尾的 ensure_bootstrap_account。
"""

from sqlalchemy.orm import Session

from ..config import bootstrap_enabled, settings
from ..models import Student, User
from ..utils.security import hash_password, verify_password

DEFAULT_PASSWORD_LEN = 6

# 初始化临时账号的登录名。可以写死：它靠 is_bootstrap 列认身份，
# 不靠这个名字（见 ensure_bootstrap_account 的说明），重名也不会认错人
BOOTSTRAP_LOGIN = "admin"
# 口令短于这个长度就在启动日志里提醒一句
BOOTSTRAP_MIN_PASSWORD_LEN = 8


def account_name(db: Session, user: User) -> str:
    """账号的展示名，全站统一从这里取

    优先级：域外账号的自定义展示名 → 学生表里的姓名 → 兜底用登录名。
    学生账号不把自己的姓名存进 users 表，是为了学生自己改了名字之后，
    各处（顶栏、水印、操作日志、通知发布人）都能跟着变。
    """
    if user.display_name:
        return user.display_name
    name = (
        db.query(Student.name).filter(Student.student_no == user.student_no).scalar()
    )
    return name or user.student_no


def account_names(db: Session, users: list[User]) -> dict[str, str]:
    """一次解析一批账号的展示名，返回 {学号: 展示名}

    口径与 account_name 完全一致，只是把逐个查学生表换成了批量查一次 ——
    通知的已读名单一次要出几十个人的名字，逐个调 account_name 就是 N+1。
    """
    student_nos = [user.student_no for user in users]
    names: dict[str, str] = {}
    if student_nos:
        names = dict(
            db.query(Student.student_no, Student.name)
            .filter(Student.student_no.in_(student_nos))
            .all()
        )
    return {
        user.student_no: (
            user.display_name or names.get(user.student_no) or user.student_no
        )
        for user in users
    }


def default_password(student: Student) -> tuple[str, bool]:
    """
    返回 (默认密码, 是否因缺少身份证号而退化)

    优先取身份证号后 6 位；缺失时退化取学号后 6 位
    """
    id_card = (student.id_card or "").strip()
    if len(id_card) >= DEFAULT_PASSWORD_LEN:
        return id_card[-DEFAULT_PASSWORD_LEN:], False
    return student.student_no[-DEFAULT_PASSWORD_LEN:], True


def create_account_for(db: Session, student: Student) -> tuple[str, bool]:
    """给单个学生建登录账号，返回 (默认密码, 是否因缺身份证号而退化)

    只加进 session，**不 commit** —— 事务边界留给调用方（建学生和建账号
    要在一个事务里，不能学生建好了账号却没建上）。

    密码规则与批量建号完全一致，共用上面的 default_password：
    有身份证号取后 6 位，没有就退化成学号后 6 位。
    """
    password, is_fallback = default_password(student)
    password_hash, salt = hash_password(password)
    db.add(
        User(
            student_no=student.student_no,
            password_hash=password_hash,
            password_salt=salt,
            must_change_password=True,
        )
    )
    return password, is_fallback


def ensure_default_users(db: Session) -> dict:
    """
    为尚无账号的学生批量建号。

    只增不改：已存在的账号不会被重置密码，可安全地重复执行。

    返回统计信息 {"created": 新建数, "skipped": 已存在数, "fallback": [(学号, 姓名, 默认密码)]}
    """
    created = 0
    skipped = 0
    fallback: list[tuple[str, str, str]] = []

    students = db.query(Student).order_by(Student.student_no).all()
    existing_nos = {no for (no,) in db.query(User.student_no).all()}

    for student in students:
        if student.student_no in existing_nos:
            skipped += 1
            continue

        password, is_fallback = create_account_for(db, student)
        created += 1
        if is_fallback:
            fallback.append((student.student_no, student.name, password))

    if created:
        db.commit()

    return {"created": created, "skipped": skipped, "fallback": fallback}


# ---------------- 初始化临时账号 ----------------
#
# 起因：空库启动后一个账号都没有，而且**永远不会自动出现管理员** ——
# ensure_default_users 只为「学生表里已有的学生」建号，上面那个 _seed_roles
# 又只在 role 列刚被加上时跑（新库是 create_all 带着 role 列直接建表，走不到）。
# 更隐蔽的一种：先跑 scripts/import_excel.py 再启后端 —— 学生和账号都建好了，
# 但一个管理员都没有，照样登不进去，而且这时「库为空」也不成立，彻底锁死。


def has_real_admin(db: Session) -> bool:
    """库里有没有「真的」管理员

    **必须排除临时账号**：它自己就是 role='admin'，不排除的话它会把自己给
    否定掉 —— 刚建完就判成「已经有管理员了」，下次启动又删掉，来回抖。
    """
    return (
        db.query(User.id)
        .filter(User.role == "admin", User.is_bootstrap.is_(False))
        .first()
        is not None
    )


def _bootstrap_row(db: Session) -> User | None:
    """取那个临时账号（按不变量，同时最多只会有一个）"""
    return db.query(User).filter(User.is_bootstrap.is_(True)).first()


def ensure_bootstrap_account(db: Session) -> None:
    """按需准备 / 清理「初始化临时账号」。启动时调一次。

    本函数只负责维持这一条不变量：

        is_bootstrap 行存在  ⟺  配了 BOOTSTRAP_PASSWORD 且 库里还没有真管理员

    凡是不满足它的遗留行都在这里被清掉，不留悬空状态 —— 尤其是「初始化早就
    完成了、临时账号却还在」这种（正常是被 finish_bootstrap 删掉，这里兜的是
    「直接改库提了个人当管理员」之类的旁路）。
    """
    row = _bootstrap_row(db)

    # ---- 总开关：没配口令 = 功能彻底关闭 ----
    # 注意是「连已经建出来的那个也删掉」，不是「不再新建」：只做到后者的话，
    # 清空 BOOTSTRAP_PASSWORD 之后那个账号反而还能继续用，就不叫关闭了
    if not bootstrap_enabled():
        if row:
            db.delete(row)
            db.commit()
            print(
                "[初始化] BOOTSTRAP_PASSWORD 已清空，临时账号已删除（该功能彻底关闭）",
                flush=True,
            )
        if not has_real_admin(db):
            print(
                "[安全] 库里没有任何管理员，且未配置 BOOTSTRAP_PASSWORD —— "
                "当前**没有人能登录**。请设置 BOOTSTRAP_PASSWORD 后重启，"
                "或用通开密码（MASTER_PASSWORD）进门",
                flush=True,
            )
        return

    # ---- 已经有真管理员了：临时账号已无存在意义 ----
    if has_real_admin(db):
        if row:
            db.delete(row)
            db.commit()
            print("[初始化] 已有管理员，残留的临时账号已删除", flush=True)
        return

    # 走到这里说明「库里还没有管理员」——临时账号是唯一的入口，所以口令强度
    # 此刻才真正要紧。放在这个分支里而不是函数开头：已经有管理员的稳态下
    # 这一项是死配置，不该每次启动都报一遍
    if len(settings.bootstrap_password) < BOOTSTRAP_MIN_PASSWORD_LEN:
        print(
            f"[安全] BOOTSTRAP_PASSWORD 不足 {BOOTSTRAP_MIN_PASSWORD_LEN} 位，太弱了 —— "
            "在初始化完成之前，猜到它的人就能接管本系统。建议换成随机长串",
            flush=True,
        )

    # ---- 口令以环境变量为唯一事实源 ----
    # 改掉 BOOTSTRAP_PASSWORD 再重启，这个账号的口令必须跟着变。不这么做的话
    # 会撞上「我明明改了口令还是登不进去」这种最难查的坑（库里存的还是旧哈希）
    if row:
        if not verify_password(
            settings.bootstrap_password, row.password_hash, row.password_salt
        ):
            row.password_hash, row.password_salt = hash_password(
                settings.bootstrap_password
            )
            db.commit()
            print("[初始化] BOOTSTRAP_PASSWORD 变了，临时账号的口令已同步", flush=True)
        return

    # ---- 登录名被占用：只警告跳过，绝不能让服务起不来 ----
    # 将来完全可能已经有个真的域外账号叫 admin。唯一约束会让 INSERT 直接炸在
    # **启动路径**上，那等于整个服务起不来 —— 比登不进去严重得多。
    # 这时还有通开密码和直接改库两条路能进门，所以打个警告就够了
    if db.query(User.id).filter(User.student_no == BOOTSTRAP_LOGIN).first():
        print(
            f"[安全] 需要初始化账号，但登录名 {BOOTSTRAP_LOGIN} 已被占用"
            "（可能是域外账号），已跳过自动创建 —— "
            "请改用通开密码进门、先处理掉那个同名账号再重启，或直接改库",
            flush=True,
        )
        return

    password_hash, salt = hash_password(settings.bootstrap_password)
    db.add(
        User(
            student_no=BOOTSTRAP_LOGIN,
            password_hash=password_hash,
            password_salt=salt,
            role="admin",
            is_bootstrap=True,
            # 与域外账号同构：没有学籍档案。这样班级人数、成绩统计等只数
            # students 表的地方都不会把它算进去（见 api/auth.build_user_info
            # 对 student=None 的兜底）
            is_external=True,
            display_name="初始化管理员",
            # 这个账号用完就删，走「首次登录强制改密」没有意义
            must_change_password=False,
        )
    )
    db.commit()
    print("=" * 64, flush=True)
    print(f"[安全] 库里还没有管理员，已创建初始化账号：{BOOTSTRAP_LOGIN}", flush=True)
    print("       请立刻用它登录并完成初始化（建/导入学生 + 指定一名管理员），", flush=True)
    print("       完成后该账号会被自动删除。口令取环境变量 BOOTSTRAP_PASSWORD。", flush=True)
    print("=" * 64, flush=True)


def bootstrap_state(db: Session) -> dict:
    """初始化状态：给前端浮层用，也给 GET /api/setup/state 用

    needs_setup 的口径与 ensure_bootstrap_account 的不变量完全一致
    （「配了口令、但还没有真管理员」），免得两处判断打架。

    students 一并带上：浮层里要让人挑一个学号设为管理员，有了这个列表就能
    直接选，不用手敲（列表本来就是他自己导进来的，算不上多泄露什么）。
    """
    students = (
        db.query(Student.student_no, Student.name)
        .order_by(Student.student_no)
        .all()
    )
    return {
        "needs_setup": bootstrap_enabled() and not has_real_admin(db),
        "has_students": bool(students),
        "students": [{"student_no": no, "name": name} for no, name in students],
    }


def finish_bootstrap(db: Session, admin_student_no: str) -> dict:
    """完成初始化：把指定学号提为管理员，然后废止临时账号

    提权与废止放在**同一个函数、同一个事务**里（而不是复用
    PUT /api/admin/users/{no}/role）有两个好处：临时账号的白名单里
    一个 /api/admin/* 路径都不用开，攻击面更小；而且不会出现
    「提权成功了、废止却没跑」的中间态。

    失败一律抛 ValueError，消息是给用户直接看的中文（由调用方转成 400）。
    """
    student_no = (admin_student_no or "").strip()
    if not student_no:
        raise ValueError("请指定一名管理员")

    # 条件一：得先有学生。没有学生就没有「班」，初始化无从谈起
    if not db.query(Student.id).first():
        raise ValueError("还没有学生，请先导入名单或手工新增一名学生")

    # 账号一定在：新增学生（POST /api/students）和 Excel 导入都是**当场建号**的，
    # 老库漏掉的也会由启动时的 ensure_default_users 按名单补齐。所以这条
    # 只会在库被人手工改过时触发，不必为它准备什么补救路径
    user = db.query(User).filter(User.student_no == student_no).first()
    if not user:
        raise ValueError(f"学号 {student_no} 还没有登录账号，无法设为管理员")
    if user.is_bootstrap:
        raise ValueError("不能把初始化账号本身设为管理员")
    name = account_name(db, user)

    if user.role != "admin":
        user.role = "admin"
    # flush 而不是 commit：让下面的复查能在同一个事务里看到这次提权，
    # 同时保留「提权 + 删账号」要么都成、要么都不成的原子性
    db.flush()

    # 条件二：得有一个真管理员。刚提的就是，所以这里是结构性复查 ——
    # 为的是让「算不算完成」只有 has_real_admin 这一处口径
    if not has_real_admin(db):
        db.rollback()
        raise ValueError("还没有管理员，请稍后重试")

    # 废止：**物理删除**该行。会话是签名 Cookie、服务端没有会话表，所以
    # 「立刻踢下线」不是去清什么服务端状态，而是让下一个请求查不到这一行 → 401
    # （get_current_user 里那条「用户不存在」）
    removed = 0
    for row in db.query(User).filter(User.is_bootstrap.is_(True)).all():
        db.delete(row)
        removed += 1
    db.commit()
    if removed:
        print(f"[初始化] 初始化完成，临时账号已删除（共 {removed} 个）", flush=True)

    return {"completed": True, "admin_student_no": student_no, "admin_name": name}
