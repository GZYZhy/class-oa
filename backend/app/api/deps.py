"""通用鉴权依赖"""

from datetime import datetime
from typing import NamedTuple, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import AccessToken, User, Student
from ..services import token_guard
from ..utils.ip import ip_in_cidrs, normalize_ip, parse_cidrs, pick_client_ip
from ..utils.security import TOKEN_PREFIX, hash_token


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


# 令牌的 last_used_at 不每次请求都更新：那会让**每一个 GET 都变成一次写事务**，
# 而 SQLite 是单写者，高频的只读脚本能把写锁一直占住。一小时刷一次，
# 用来回答「这把令牌还在用吗」已经够了
_LAST_USED_REFRESH_SECONDS = 3600


def _user_from_pat(request: Request, db: Session) -> Optional[User]:
    """尝试用 Authorization: Bearer 头里的访问令牌认证

    没有 Bearer 头、或带的不是本站格式的令牌 → 返回 None，由调用方走 Cookie 逻辑。
    **只有「格式是我们的、但校验没过」才抛 401** —— 不然别的服务用自己的 Bearer
    令牌来打公开接口时会被我们误伤。

    校验通过返回的 User **角色已经被降级成 student**，细节见函数内的注释。
    """
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    raw = auth[7:].strip()
    if not raw.startswith(TOKEN_PREFIX):
        return None

    row = (
        db.query(AccessToken)
        .filter(AccessToken.token_hash == hash_token(raw))
        .first()
    )
    now = datetime.now()
    if not row or row.revoked_at is not None:
        request.state.pat_rejected = True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问令牌无效或已被吊销",
        )
    if row.expires_at is not None and row.expires_at < now:
        request.state.pat_rejected = True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问令牌已过期，请重新创建",
        )

    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        request.state.pat_rejected = True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在"
        )
    # 冻结的令牌当场失效。令牌是长期凭据，Cookie 那套踢不掉它，
    # 所以这里必须自己判一次（管理员「吊销会话 / 重置密码」也会连带吊销，见 admin.py）
    if user.is_frozen:
        request.state.pat_rejected = True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号已被冻结",
        )

    # 限流。放在所有校验之后：只限**成功**的调用，坏令牌本来就 401，不用占额度。
    # 429 也要置 pat_rejected —— 否则脚本打公开接口时会被 get_optional_user
    # 吞成「游客 200」，它根本不知道自己被限流了
    wait = token_guard.hit(row.id)
    if wait is not None:
        request.state.pat_rejected = True
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"访问令牌调用过于频繁，请 {wait} 秒后再试",
        )

    # ---------------- 降级：令牌一律按「学生身份」看待 ----------------
    #
    # 全班委 / 管理员权限最终都落在 user.role 这一个属性上
    # （require_role、is_committee、以及几处手写的 role == "admin"），
    # 所以把它改成 student，班委级接口自动 403、行级过滤自动收窄到本人 ——
    # 不用改任何一处权限判断，也就不可能漏项。
    #
    # ⚠ 以下三行的**顺序不能动**，另外两种写法都会出事：
    #
    # 1) 不能不 expunge 就直接改。这时 user 还挂在 session 上，而路由里几乎每个
    #    写接口都有 db.commit()，那一下会把 role="student" flush 进库 ——
    #    **把真管理员永久降级**。expunge 之后对象脱离 session，谁 commit 都不碰它。
    #
    # 2) 不能先 commit 再 expunge。sessionmaker 没写 expire_on_commit，即默认 True，
    #    commit 会把 session 里的对象 expire；紧接着 expunge，路由再读
    #    user.student_no 就会因为没法 refresh 而 DetachedInstanceError。
    #    先 expunge 的话，commit 的 expire 只看 identity map、碰不到它，
    #    而属性在 query 那一刻就全加载好了，脱离后照样读得到。
    #
    # ⚠ 这个对象是**脱离 session** 的，两条禁忌写在这里：
    #    - 在令牌能到达的路由里不要写 `db.query(User).filter(User.id == user.id)`
    #      这类按 id 重查，那会拿回真实角色、让降级静默失效
    #    - 也别拿它做 `user.xxx = ...` 的赋值再 commit，脱离对象的改动会**静默丢失**。
    #      要写 users 行的接口都在 auth.py 里挂了 require_cookie_auth 挡掉令牌
    db.expunge(user)
    user.role = "student"
    # 纯内存标记，不是数据库列：让 log_operation 知道这条操作是「令牌代做的」。
    # 不用 request.state 传是因为 log_operation 手上没有 request。
    # 只在令牌这条路径上设，Cookie 那边走 getattr 默认 False
    user.via_pat = True

    # 节流更新最后使用时间。务必放在 expunge 之后 commit，理由见上面第 2 条
    if (
        row.last_used_at is None
        or (now - row.last_used_at).total_seconds() > _LAST_USED_REFRESH_SECONDS
    ):
        row.last_used_at = now
        db.commit()

    request.state.auth_via = "pat"
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """从签名会话（或访问令牌）中获取当前登录用户，未登录返回 401"""
    # 令牌优先：同时带了 Cookie 和 Bearer 时按令牌算 —— 让更严格的一侧胜出，
    # 免得出现「明明用的是令牌、却拿到全权管理员身份」这种意外
    pat_user = _user_from_pat(request, db)
    if pat_user is not None:
        return pat_user

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
    # 所以升级本身不会把已登录的人集体踢下线；只有真的点过吊销，代次才会对不上。
    #
    # 注意这一条**不适用于访问令牌**：令牌有自己的吊销机制，改密码、吊销会话
    # 不该连坐它（令牌本来就该在改密后继续能用，否则脚本天天要重配）。
    # 真要让令牌当场失效，靠管理员那边的吊销接口和冻结开关
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
        # 令牌是我们自己认的格式、但没过（过期 / 被吊销 / 账号冻结 / 被限流）：
        # 这个错误必须透出去。吞掉的话脚本会拿到 200 + 游客数据，
        # 根本不知道自己已经掉线或被限流了 —— 静默降级比报错危险得多
        if getattr(request.state, "pat_rejected", False):
            raise
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


def require_cookie_auth(
    request: Request, user: User = Depends(get_current_user)
) -> User:
    """只允许浏览器会话（签名 Cookie）调用，带访问令牌一律 403

    两类接口要用它：

    1. **令牌自身的管理**（列出 / 创建 / 吊销）。不挡的话，一把泄露的令牌能自己
       再铸一把长期令牌，那原令牌吊销了也白搭 —— 等于永久后门。
    2. **写 users 行的接口**：改密码、设初始密码、bark / webhook / 邮件设置。
       - 改密码 / 设初始密码是**实打实的提权路径**：令牌 → 设一个自己知道的密码 →
         用浏览器正常登录 → 这账号要是管理员就全拿到了。（设初始密码那条尤其危险：
         它本来就不校验原密码。）
       - 另外三个纯粹是技术原因：令牌请求里的 user 对象已经被 expunge 出 session，
         对它赋值再 commit 会**静默丢改动** —— 接口返回「已保存」而库里纹丝不动。
         与其假成功，不如直接拒掉说得清楚。

    这个判断集中在 deps 里，而不是在每个 handler 里手写 request.state ——
    散着写迟早漏一个。

    get_current_user 是它的子依赖，会先求值并设好 request.state.auth_via
    """
    if getattr(request.state, "auth_via", None) == "pat":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作不支持使用访问令牌，请用网页登录后再操作",
        )
    return user


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


def is_admin(user: User) -> bool:
    """是否管理员，口径同 is_committee（角色只有 ROLE_RANK 这一处定义）"""
    return ROLE_RANK.get(user.role or "student", 0) >= ROLE_RANK["admin"]
