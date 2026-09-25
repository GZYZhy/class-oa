"""操作日志服务

只记「内容变更」类操作（发布/修改/删除文件与通知、改学生信息、审核、重置密码、改角色）
以及考勤类动作（点名）—— 后者虽然不改数据，但它是有人主动做出的动作、且有留痕价值。

不记登录和查询，免得日志被浏览量淹没。
"""

from sqlalchemy.orm import Session

from ..models import OperationLog, Student, User


def display_name(db: Session, user: User) -> str:
    """取当前用户的姓名（users 表不存姓名，从学生表关联），取不到就退回学号"""
    name = db.query(Student.name).filter(Student.student_no == user.student_no).scalar()
    return name or user.student_no


def log_operation(
    db: Session, user: User, action: str, target: str = "", detail: str = "",
    ip: str | None = None,
) -> None:
    """记一条操作日志

    只 add 不 commit：调用方把日志和业务改动一起提交，避免出现「记了日志但数据没改」。
    """
    db.add(
        OperationLog(
            operator_no=user.student_no,
            operator_name=display_name(db, user),
            action=action,
            target=target[:200] if target else None,
            # 截断避免超长内容把日志列表撑坏（如整段备注）
            detail=detail[:500] if detail else None,
            ip=ip,
        )
    )
