"""可答范围的中文标签

投票和收集都只存「目标学号」，不存「当时点的是全班还是仅团员」。
这个反推逻辑必须只有一份，否则两个模块的「全班 / 班委 / 团员 / 定向 N 人」
迟早会给出不同答案。
"""

from sqlalchemy.orm import Session

from ..models import Student, User
from ..utils.roles import ROLE_RANK


def scope_context(db: Session) -> dict:
    """一次查清反推范围要用的三批人，供列表批量使用

    列表一页 20 条，逐条重查「全体学生 / 角色 / 团员」就是 60 次查询；
    先取好上下文，每条只做集合比较。
    """
    students = (
        db.query(Student.student_no, Student.political_status)
        .filter(Student.school_status == "正常")
        .all()
    )
    all_nos = {student_no for student_no, _ in students}
    roles = dict(db.query(User.student_no, User.role).all())
    return {
        "all": all_nos,
        "committee": {
            student_no
            for student_no in all_nos
            if ROLE_RANK.get(roles.get(student_no) or "student", 0)
            >= ROLE_RANK["committee"]
        },
        "league": {
            student_no
            for student_no, political_status in students
            if political_status == "共青团员"
        },
    }


def label_for_targets(target_nos, context: dict) -> str:
    """用已经查好的上下文比较，口径见 target_scope_label"""
    targets = set(target_nos)
    if not targets:
        return "定向 0 人"
    if targets == context["all"]:
        return "全班"
    if targets == context["committee"]:
        return "班委"
    if targets == context["league"]:
        return "团员"
    return f"定向 {len(targets)} 人"


def target_scope_label(db: Session, target_nos) -> str:
    """把目标学号集合反推成公开的中文范围

    - 目标集合 == 全体正常在校生 → 全班
    - == 全体班委（角色口径同 api/polls.py 的 get_roster）→ 班委
    - == 全体共青团员（political_status == '共青团员'）→ 团员
    - 其余 → 定向 N 人

    优先级按上面顺序：小班里全体学生也都是班委时，先说「全班」。
    名单在活动创建后变动时标签会跟着变 —— 对外只需要回答「现在这批人等于
    哪个范围」，不需要还原当时点的是哪个快捷键。
    """
    return label_for_targets(target_nos, scope_context(db))


def target_scope_labels(db: Session, targets_by_id: dict) -> dict:
    """批量版：targets_by_id = {活动 id: 目标学号集合}"""
    context = scope_context(db)
    return {
        key: label_for_targets(target_nos, context)
        for key, target_nos in targets_by_id.items()
    }
