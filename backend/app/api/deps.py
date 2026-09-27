"""通用鉴权依赖"""

from typing import NamedTuple, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User, Student
from ..utils.ip import ip_in_cidrs, normalize_ip, parse_cidrs, pick_client_ip


class ClientInfo(NamedTuple):
    """一次请求的来源判定结果

    - ip：用于记录和封禁的地址（已归一化）
    - peer：直连来源（TCP 层看到的那个地址）
    - is_proxy：True 表示解析出来的其实是代理自己，不是真实客户端 ——
      这种地址**绝不能拿去封**，封了等于把全班挡在门外
    """

    ip: str
    peer: str
    is_proxy: bool


def resolve_client(request: Request) -> ClientInfo:
    """判断这个请求到底是哪个 IP 发来的。

    规则只有一条：**只信自己人的 X-Forwarded-For**。

    直连来源不在可信网段里（也就是说，这个请求不是从我们的反向代理转过来的），
    那么它带的 XFF 全是它自己写的，一律不作数，直接按直连地址算。
    只有直连来源可信时，才从 XFF 里从右往左找出真实客户端（见 utils.ip.pick_client_ip）。

    为什么不认 X-Real-IP：多认一个头就多一个可以伪造的面，
    而 XFF 在本项目的两种 nginx 配置下都必然存在。
    """
    peer = request.client.host if request.client else ""
    nets = parse_cidrs(settings.trusted_proxies)
    norm = normalize_ip(peer)

    if norm is None:
        # 直连来源不是 IP（TestClient 的 "testclient"、异常情况下的空值）。
        # is_proxy=True：这种地址不能封，封了就是所有人共用一行
        return ClientInfo(peer or "unknown", peer, True)

    if not ip_in_cidrs(norm, nets):
        # 直连来源不可信 → 忽略它带来的 XFF
        return ClientInfo(norm, norm, False)

    real = pick_client_ip(request.headers.get("x-forwarded-for", ""), nets)
    if real:
        return ClientInfo(real, norm, False)

    # 可信代理，但拿不到可用的转发头（自定义 nginx 配置、NGINX_TRUST_PROXY=off）。
    # 这时解析出来的只能是代理自己，同样不能拿去封
    return ClientInfo(norm, norm, True)


def get_client_ip(request: Request) -> str:
    """取真实客户端 IP（40 多处调用点用的都是这个）

    只是 resolve_client 的一层薄包装。需要区分「直连来源」和「是否代理」的地方
    请直接用 resolve_client。
    """
    return resolve_client(request).ip


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
    # 冻结的账号当场踢下线。会话是签名 Cookie，服务端没有会话表，
    # 所以「立即终止现有会话」不是去清什么服务端状态，而是让下一个请求就 401 ——
    # 放在这里，全部需要登录的接口一次性全覆盖，不用逐个接口加判断
    if user.is_frozen:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号已被冻结",
        )
    # 会话代次：管理员「吊销所有会话」会把这一列 +1，此前签发的 cookie 全部作废。
    # 老 cookie（本列上线前签发的）里没有 epoch，按 0 处理 —— 与补列时的默认值一致，
    # 所以升级本身不会把已登录的人集体踢下线；只有真的点过吊销，代次才会对不上
    if request.session.get("epoch", 0) != (user.session_epoch or 0):
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="会话已被吊销，请重新登录",
        )
    return user


def get_optional_user(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    """可选登录：登录了就返回用户，没登录返回 None，**不抛 401**

    给公开接口用 —— 通知列表游客也能看，登录的人额外拿一个 is_read。

    直接复用 get_current_user 再吞掉 401，是为了让「什么算登录着」只有一处口径。
    会话失效 / 账号冻结 / 会话被吊销在这里都当作游客，顺带把无效 cookie 清掉
    （get_current_user 里的 session.clear()）也没关系 —— 反正这个请求不依赖它。
    """
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


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
