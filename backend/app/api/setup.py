"""初始化接口：空库引导的收尾

只有临时管理员（users.is_bootstrap）用得上这两个接口，而且那个账号
**用完就被删掉** —— 所以这是「一次部署只来一趟」的东西。

为什么单开一条 /api/setup，而不是复用现成接口：

- 若复用 PUT /api/admin/users/{no}/role 来提权，临时账号的白名单里就得开一条
  /api/admin/* 的路，攻击面白白变大（那个前缀下还有「建域外账号」这类接口）；
- 更要紧的是「提权」和「废止」必须是同一个动作。拆成两步就会出现
  「提权成功了、废止没跑」的中间态：那时初始化看着已经完成，临时账号却还活着。
  代码见 services.finish_bootstrap，两件事在同一个事务里。
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas.setup import SetupFinishRequest, SetupStateResponse
from ..services import bootstrap_state, finish_bootstrap
from .deps import get_current_user

router = APIRouter(prefix="/api/setup", tags=["初始化"])


@router.get("/state", response_model=SetupStateResponse, summary="初始化状态")
def get_state(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """还差不差东西

    只读，任何登录用户都能问（完成后前端偶尔还会问一次，返回 needs_setup=false）。
    """
    return bootstrap_state(db)


@router.post("/finish", summary="完成初始化：指定管理员并废止临时账号")
def post_finish(
    data: SetupFinishRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把指定学号设为管理员；条件满足则当场删掉临时账号

    只允许**临时账号自己**调：不然这就成了管理员改角色的一个侧门，
    绕过了系统管理页那套操作日志。真实的提权走 PUT /api/admin/users/{no}/role。
    """
    if not user.is_bootstrap:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该接口只用于首次初始化，请到「系统管理 → 账号管理」调整角色",
        )

    try:
        result = finish_bootstrap(db, data.admin_student_no)
    except ValueError as e:
        # 服务里的 ValueError 消息都是写给用户看的中文（缺学生 / 学号不存在…）
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # 临时账号那一行已经被删了，手里这个会话指向的行也不存在了。
    # 就地清掉，前端随即回登录页、用刚指定的管理员账号重新登录
    request.session.clear()
    return result
