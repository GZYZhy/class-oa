"""操作日志服务

只记「内容变更」类操作（发布/修改/删除文件与通知、改学生信息、审核、重置密码、
改角色、冻结账号）以及考勤类动作（点名）—— 后者虽然不改数据，
但它是有人主动做出的动作、且有留痕价值。

不记查询，也不记登录：免得日志被浏览量和高频事件淹没。
**登录和「本人自行改密」记在另一张表 account_events**（见 models/account_event.py），
由「按账号查日志」按 7 天窗口单独展示。两张表各管一类，不合并。
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import AccountEvent, OperationLog, User
from .user_service import account_name

# 「按账号查日志」里登录/改密事件的展示窗口，以及 account_events() 的默认页大小。
# 窗口是查的时候限的，不是往里写的时候限的（account_events 只增不删）。
#
# LIMIT 这名字是历史遗留：加分页之前它是「最多展示 200 条」的硬上限，现在是默认
# page_size —— 管理员那边（api/admin.py）不传分页参数，拿到的仍是「窗口内最多
# 200 条」；「我的日志」（api/auth.py）显式传 20 并翻页。改这个值会同时影响两边。
ACCOUNT_EVENT_DAYS = 7
ACCOUNT_EVENT_LIMIT = 200


def display_name(db: Session, user: User) -> str:
    """取当前用户的展示名（域外账号用自定义展示名，学生账号查学生表），取不到就退回登录名"""
    return account_name(db, user)


def account_operations(db: Session, student_no: str, page: int = 1, page_size: int = 20):
    """某个账号**作为操作人**留下的操作日志，分页。返回 (总数, 当前页条目)。

    operator_no 是精确匹配。admin 的 /logs?operator= 走的是 LIKE %x%，
    拿 2026012 去查会把 20260123、20260124 一起带出来，那种模糊匹配
    不能用来「看某个账号」。
    """
    query = db.query(OperationLog).filter(OperationLog.operator_no == student_no)
    total = query.count()
    items = (
        query.order_by(OperationLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items


def account_events(
    db: Session,
    student_no: str,
    page: int = 1,
    page_size: int = ACCOUNT_EVENT_LIMIT,
):
    """某个账号最近 ACCOUNT_EVENT_DAYS 天的登录 / 自行改密事件，分页。

    返回 (窗口内总数, 当前页条目, 窗口左端)。总数是**窗口内的**总数，
    可能大于本页条数，调用方据此决定分页器或「只列了最近 N 条」的提示。

    page_size 的默认值特地取 ACCOUNT_EVENT_LIMIT 而不是 20：admin.py 的
    「账号管理 → 查日志」不传分页参数，靠这个默认值拿到的仍是「窗口内最多
    200 条」，与加分页之前**逐字一致**；只有「我的日志」（api/auth.py）
    显式传 page_size，才走真正的翻页。
    """
    since = datetime.now() - timedelta(days=ACCOUNT_EVENT_DAYS)
    query = db.query(AccountEvent).filter(
        AccountEvent.student_no == student_no,
        # created_at 是 Python 端写入的北京时间，这里也用 datetime.now()，
        # 两边同源才比得了（SQLite 的 CURRENT_TIMESTAMP 是 UTC，混用就会错 8 小时）
        AccountEvent.created_at >= since,
    )
    total = query.count()
    items = (
        # 按 created_at 倒序而不是 id 倒序：窗口本来就是拿 created_at 划的，
        # 排序用同一个字段才自洽。id 倒序只在「写入顺序 = 时间顺序」时等价
        query.order_by(AccountEvent.created_at.desc(), AccountEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items, since


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

    用访问令牌（PAT）发起的那次调用，操作人照样是这个账号（student_no 一样、
    一样出现在他本人的「我的日志」里），只在 detail 前面多一句
    「（经由访问令牌）」，好让管理员把「本人点出来的」和「脚本干的」分开看。
    """
    import json

    # 令牌代做的操作打个标记。标记加在这里而不是散到各个调用点，是为了让
    # 「谁调的都记一条」这件事保持只有一处实现 —— 调用方一行都不用改。
    # 放**前缀**而不是后缀：detail 下面会被截断到 500 字，追加在后面可能正好被切掉
    if getattr(user, "via_pat", False):
        detail = "（经由访问令牌）" + (detail or "")

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
