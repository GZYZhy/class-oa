"""签字人的公共逻辑：谁能签、把选中那张图快照一份下来

请假（api/leaves.py）与电动车（api/ev_passes.py）共用这一份。

**只到这一步为止**：再往上（「把签字写进哪三列」）就带着各自单据的字段语义了，
提成通用函数得传一堆参数名，反而更难懂 —— 那部分各写各的那五行。
"""

import shutil
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Student, User
from .log_service import display_name
from .student_photo_service import sign_photo_path, user_sign_photo_path


def signer_photo(db: Session, student_no: str) -> tuple[Path, User] | None:
    """某登录名能不能当签字人：返回 (签字图路径, 账号)，不能就返回 None

    域外账号的签字图存 users.sign_photo、在册学生存 students.sign_photo，
    按 is_external 分流 —— 两边「同等权限」的账号在签字这件事上也同等
    （用户口径：可以用包含域外同等权限在内的某个管理员的签字）。

    **图必须在盘上**：库里留着文件名、文件却被删掉的情况是有的，
    候选人列表里就不该出现一个选了却插不进表的空签字。
    """
    user = db.query(User).filter(User.student_no == student_no).first()
    if not user:
        return None
    if user.is_external:
        path = user_sign_photo_path(user)
    else:
        student = db.query(Student).filter(Student.student_no == student_no).first()
        path = sign_photo_path(student) if student else None
    if not path or not path.exists():
        return None
    return path, user


def signer_candidates(db: Session) -> list[User]:
    """能当签字人的账号：管理员，且签字图确实在盘上

    **不复用** GET /api/admin/users 的 has_sign_photo：那一列的语义是
    「域外账号有没有签字图，学生账号恒 False」，拿它筛会把学生管理员整批漏掉。

    候选人一共没几个，逐个查图的 N+1 无所谓，好读优先。
    """
    rows = db.query(User).filter(User.role == "admin").order_by(User.student_no).all()
    return [row for row in rows if signer_photo(db, row.student_no)]


def signer_options(db: Session) -> list[dict]:
    """候选人列表，直接当接口的响应体（域外与在册同权，用 is_external 标出来给前端区分）"""
    return [
        {"student_no": row.student_no, "name": display_name(db, row),
         "is_external": bool(row.is_external)}
        for row in signer_candidates(db)
    ]


def copy_signature(db: Session, sign_no: str, dest_dir: Path, stem: str) -> tuple[Path, str]:
    """把选中的签字图复制一份进 dest_dir，返回 (副本路径, 签字人姓名)

    存副本而不是只记原图名，是为了让「用批准当时那张」这句承诺站得住：
    原图被换掉或删掉时（换图 / 删图接口都有），历史单据不能静默掉签字。

    *dest_dir* 必须由调用方给：请假的落 LEAVE_DIR、电动车的落 EV_PASS_DIR ——
    写死一个，另一边的副本就会存进别人家的目录（这是从 leaves.py 提出来时才发现的坑）。
    *stem* 也由调用方按单据 id 起；补签不允许覆盖已签过的记录，所以不会撞名。
    """
    found = signer_photo(db, sign_no)
    if not found:
        raise HTTPException(status_code=400, detail="该账号没有可用的签字图，请重新选择")
    src, user = found
    dest = dest_dir / f"{stem}{src.suffix.lower()}"
    shutil.copyfile(src, dest)
    return dest, display_name(db, user)
