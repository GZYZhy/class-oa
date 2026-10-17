"""办件的受理环节：待受理 → 已受理，以及撤回受理与退回补正

三个办件（请假 / 电动车通行证 / 证明开具）共用这一份。它们的审核流程逐字同构，
各写一遍的话 `"accepted"` 这个字面量会散在六七个文件里，写错一个字母不报错、
只会静默算成 0，红点上就少一个数。

**只放状态转移这一层**：状态常量、四个动作、一个守卫。日志怎么写、通知发不发、
接口长什么样，都留在各自的 api 文件里 —— 那部分带着各自单据的语义，
提到这里得传一堆参数名，反而更难懂（和 signer_service 那条界线一致）。
"""

from typing import Any

from fastapi import HTTPException

# 提交 → 受理 → 办结，三种处境的五个状态
STATUS_PENDING = "pending"        # 待受理
STATUS_ACCEPTED = "accepted"      # 已受理，等审批
STATUS_CORRECTING = "correcting"  # 已受理但材料要补，等申请人重交
STATUS_APPROVED = "approved"      # 已通过（终态）
STATUS_REJECTED = "rejected"      # 已驳回（终态）
STATUS_REVOKED = "revoked"        # 已撤销：管理员把已通过的单子撤了（终态，不可恢复）

# 管理端还得动手的：列表的「待处理」那一档、菜单红点，都用这一份口径
ADMIN_TODO = (STATUS_PENDING, STATUS_ACCEPTED)

# 还没办结的。比 ADMIN_TODO 多一个 correcting —— 那种单子在等申请人改、管理端不催它，
# 但学生也不能就这么撒手：留一份挂在半路上的办件去删学生，班委回头就收不了尾了
UNFINISHED = (STATUS_PENDING, STATUS_ACCEPTED, STATUS_CORRECTING)

# 已办结的：三个终态合起来，就是列表里「已办结」那一档。
# 和 UNFINISHED 刚好互补（六个状态一分为二），这也是列表筛选器那四档的来源：
# 待处理 / 待补正 / 已办结 / 全部 —— 前两档分开是因为它们要办的人不同
CLOSED = (STATUS_APPROVED, STATUS_REJECTED, STATUS_REVOKED)


def accept(row: Any) -> bool:
    """受理：待受理 → 已受理。已经受理过就原样不动，返回是否真的变了

    受理的判据只有一条：**审批者看过这份材料**。所以申请人一改材料，这次受理就作废
    （改完把状态置回 pending），得重新看一遍。
    """
    if row.status != STATUS_PENDING:
        return False
    row.status = STATUS_ACCEPTED
    return True


def unaccept(row: Any) -> bool:
    """撤回受理：已受理 → 待受理（受理点错了的回头路）

    只退受理，不动审批结果：审批一旦发出（通知已推送、PDF 已生成、签字图已快照），
    静默改写等于篡改一份已经发出去的正式单据 —— 和「补签字不重审」是同一条口径。
    """
    if row.status != STATUS_ACCEPTED:
        return False
    row.status = STATUS_PENDING
    return True


def correct(row: Any, reason: str) -> bool:
    """退回补正：已受理 → 待补正，并把理由写进记录（申请人在学生端看得见）

    和 unaccept 的区别是**带理由**：撤回受理是「我看错了，退回来」，学生多半不用动；
    退回补正是「材料不对，补齐了还能批」，学生必须动，所以理由得留下来。
    """
    if row.status != STATUS_ACCEPTED:
        return False
    row.status = STATUS_CORRECTING
    row.correction_reason = reason.strip()
    return True


def resubmit(row: Any) -> None:
    """申请人改完重交：待补正的**回到已受理**，待受理的原地不动，两者都清掉补正理由

    待补正也算「已受理」（用户口径）—— 受理没被撤销，只是材料要补齐，所以补完退回
    已受理，不必让班委再看一遍。而待受理的单子本来就还没人看过，改完仍然等着受理。
    """
    if row.status == STATUS_CORRECTING:
        row.status = STATUS_ACCEPTED
    row.correction_reason = ""


def require_accepted(row: Any) -> None:
    """现在能不能批：得先受理过，而且还没办结

    三种不能批的处境合成一条守卫——它们回答的是同一个问题（「能不能点通过/驳回」）。
    分开写的话六个审批接口各要写一遍终态判断，而证明那两个接口原本就漏了
    （approve 只挡「已通过」、reject 一句检查都没有，能在通过之后再驳回一次）。
    """
    if row.status in CLOSED:
        raise HTTPException(status_code=400, detail="该申请已处理过")
    if row.status == STATUS_CORRECTING:
        # 刚说了「材料不对、补齐再来」，此刻批它就是自相矛盾；等学生补齐（回到已受理）再批
        raise HTTPException(status_code=400, detail="该申请已退回补正，待申请人补齐材料")
    if row.status != STATUS_ACCEPTED:
        # 「先受理后审批」是硬性的（用户口径）：没看过材料就能批的话，这个环节等于没设
        raise HTTPException(status_code=400, detail="该申请需先受理后才能审批")
