"""通用鉴权依赖"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Student


def get_client_ip(request: Request) -> str:
    """取真实客户端 IP。

    有 X-Forwarded-For 时取最左边那个（那才是用户，后面的都是代理）。
    部署时如果前面挂了反向代理（Nginx/Caddy/Cloudflare），
    记得在代理层配置把用户 IP 写到这个头里。
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """从签名会话中获取当前登录用户，未登录返回 401"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或会话已过期",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        # 用户不存在（理论上不会发生），清除无效会话
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    return user


def get_current_student(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Student:
    """获取当前用户对应的学生信息

    依赖本函数的接口都是「绑定学生身份」的（我的信息、请假、反馈、信息变更……），
    域外账号没有学生记录，一律 403 说清楚原因 —— 不用 404，免得以为是页面不存在。
    """
    if user.is_external:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="域外账号不支持该功能",
        )
    student = (
        db.query(Student).filter(Student.student_no == user.student_no).first()
    )
    if not student:
        raise HTTPException(status_code=404, detail="未找到对应学生信息")
    return student


# ---------- 角色权限 ----------

# 角色等级：数值越大权限越高，等级 >= 要求即放行
ROLE_RANK = {"student": 0, "committee": 1, "admin": 2}


def require_role(minimum: str):
    """依赖工厂：校验当前用户的角色等级，不足返回 403

    用法：`user: User = Depends(require_role("committee"))`；
    常用的两档已备好，直接用 committee_required / admin_required 即可。

    注意：必须定义在 get_current_user 之后 —— 下面 Depends(get_current_user)
    在 require_role 被调用时就要能解析到。
    """

    def _check_role(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role or "student", 0) < ROLE_RANK[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return user

    return _check_role


# 班委及以上（含管理员）
committee_required = require_role("committee")
# 仅管理员
admin_required = require_role("admin")


def is_committee(user: User) -> bool:
    """是否班委及以上，用于需要按角色分支而非直接拦截的场景"""
    return ROLE_RANK.get(user.role or "student", 0) >= ROLE_RANK["committee"]
