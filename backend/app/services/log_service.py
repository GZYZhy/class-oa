"""操作日志服务

只记「内容变更」类操作（发布/修改/删除文件与通知、改学生信息、审核、重置密码、
改角色、冻结账号）以及考勤类动作（点名）—— 后者虽然不改数据，
但它是有人主动做出的动作、且有留痕价值。

不记查询，也不记登录：免得日志被浏览量和高频事件淹没。
**登录和「本人自行改密」记在另一张表 account_events**（见 models/account_event.py），
由「按账号查日志」按 7 天窗口单独展示。两张表各管一类，不合并。
"""

from sqlalchemy.orm import Session

from ..models import OperationLog, User
from .user_service import account_name


def display_name(db: Session, user: User) -> str:
    """取当前用户的展示名（域外账号用自定义展示名，学生账号查学生表），取不到就退回登录名"""
    return account_name(db, user)


def log_operation(
    db: Session, user: User, action: str, target: str = "", detail: str = "",
    ip: str | None = None,
    target_student_nos: list[str] | None = None,
) -> None:
    """记一条操作日志

    只 add 不 commit：调用方把日志和业务改动一起提交，避免出现「记了日志但数据没改」。

    操作对象是**某个账号**时（重置密码、改角色、冻结、改学生信息、审批申请……），
    target 一律写成 f"{学号} {姓名}"，两者之间一个空格。账号日志里的「被操作记录」
    就是按这个格式反查的（见 api/admin.py 的 user_logs），少写学号或漏掉那个空格，
    这条记录在对方的「被操作记录」里就查不到。此处不代拼，因为「姓名」各调用点
    的取法不同（学生查学生表、域外账号取 display_name）。

    批量操作时（如导出学生信息，一次涉及 N 人），通过 target_student_nos 传入
    全部学号列表，写入 target_student_nos 字段（JSON 数组）。被操作记录反查时
    会同时匹配 target 和 target_student_nos 两个字段。
    """
    import json

    nos_json = ""
    if target_student_nos:
        nos_json = json.dumps(target_student_nos, ensure_ascii=False)

    db.add(
        OperationLog(
            operator_no=user.student_no,
            operator_name=display_name(db, user),
            action=action,
            target=target[:200] if target else None,
            # 截断避免超长内容把日志列表撑坏（如整段备注）
            detail=detail[:500] if detail else None,
            ip=ip,
            target_student_nos=nos_json,
        )
    )
