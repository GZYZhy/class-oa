"""账号服务：登录账号的自动初始化

账号规则（自动初始化，无需人工建号）：
- 账号 = 学号
- 默认密码 = 身份证号后 6 位；没有身份证号的退化为学号后 6 位
- 首次登录强制改密
"""

from sqlalchemy.orm import Session

from ..models import Student, User
from ..utils.security import hash_password

DEFAULT_PASSWORD_LEN = 6


def default_password(student: Student) -> tuple[str, bool]:
    """
    返回 (默认密码, 是否因缺少身份证号而退化)

    优先取身份证号后 6 位；缺失时退化取学号后 6 位
    """
    id_card = (student.id_card or "").strip()
    if len(id_card) >= DEFAULT_PASSWORD_LEN:
        return id_card[-DEFAULT_PASSWORD_LEN:], False
    return student.student_no[-DEFAULT_PASSWORD_LEN:], True


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
        created += 1
        if is_fallback:
            fallback.append((student.student_no, student.name, password))

    if created:
        db.commit()

    return {"created": created, "skipped": skipped, "fallback": fallback}
