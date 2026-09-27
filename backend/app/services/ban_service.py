"""IP 封禁的读写

约定和 log_operation 一样：**只 add / delete 不 commit**，由调用方在同一个事务里提交。
唯一的例外是 purge_expired —— 它由 main.py 在启动时单独调，自己提交。
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..config import settings
from ..models import IpBan, User
from ..utils.ip import ip_in_cidrs, normalize_ip, parse_cidrs, target_matches


def is_ban_candidate(ip: str) -> bool:
    """这个地址能不能封？自动封禁和手动封禁共用这一个判据。

    三种 False，每一种都对应一次真实事故：
    - 不是合法 IP（"unknown" / "testclient"）→ 唯一约束下它们会挤成同一行，
      封了等于把所有人一起封
    - 落在可信代理网段里 → 那是我们自己的 nginx，封了全班都进不来
    - 没配可信网段 → 分不清代理和客户端，谁都可能是代理，那就一个都不封
    """
    norm = normalize_ip(ip)
    if norm is None:
        return False
    nets = parse_cidrs(settings.trusted_proxies)
    if not nets:
        return False
    return not ip_in_cidrs(norm, nets)


# 判定「这次封禁和已有的相比算不算变化」时的容差（秒）。
# 存在的理由：每次请求都按 now 重新算解封时间，同一分钟内连点两次「1 小时」，
# 第二次算出来的结束时间会比第一次晚几十秒。那点差别不该被当成「延长」——
# 否则管理员每次手滑重复点一下都会多一条日志。
_CHANGE_TOLERANCE_SECONDS = 60


def get_active_ban(db: Session, ip: str) -> IpBan | None:
    """这个 IP 当前是否被封；被封则返回那条封禁记录。

    做成「一行 SQL 取出全部生效行 + Python 里逐个比」而不是把判定写进 SQL：
    用 SQL 表达「一个网段是否包含某个 IP」对 IPv6 很难写对，
    而这张表一个班最多几十行，循环一下更简单也更不容易出错。

    **不做内存缓存**：手动解封必须立刻生效，加缓存就要等 TTL，
    管理员点了「解封」却发现还能进去，会以为接口坏了。

    多条同时命中时（比如既有 10.0.0.0/8 又有 10.0.0.1）取**解封最晚**的那条 ——
    否则页面上显示的解封时间会比实际生效的早，用户以为到点就能进，结果还是进不去。
    """
    if not ip:
        return None
    now = datetime.now()
    rows = (
        db.query(IpBan)
        .filter((IpBan.expires_at.is_(None)) | (IpBan.expires_at > now))
        .all()
    )
    hit = [row for row in rows if target_matches(row.target, ip)]
    if not hit:
        return None
    # expires_at 为 None（永久）的排在最前
    return sorted(hit, key=lambda r: (r.expires_at is not None, r.expires_at))[-1]


def ban_ip(
    db: Session,
    target: str,
    minutes: int | None,
    reason: str = "",
    operator: User | None = None,
) -> IpBan | None:
    """封禁一个 IP 或网段（target 必须是已经归一化过的字符串）。

    返回写入的那条记录；**如果没能让封禁变得更严格（结束时间没变），返回 None**，
    此时调用方应当认为「什么也没发生」（不写日志、不改数据）——
    对应 freeze_user 那套「重复操作不报错、也不留痕」的口径。

    - minutes=None 表示永久
    - 已经封着的话**只延长不缩短**：永久不会被限时降级，长封不会被短封覆盖。
      这是最容易写错的一处：管理员手滑再点一次「1 小时」，
      不该把正在生效的 7 天封禁改成 1 小时提前放人进来
    - 管理员插手过（不管是新封还是延长）都置 is_manual=True
    """
    now = datetime.now()
    expiry = None if minutes is None else now + timedelta(minutes=minutes)

    existing = db.query(IpBan).filter(IpBan.target == target).first()
    if existing is not None:
        # 「不能降级」：已有的解封时间更晚（或者是永久）就沿用它。
        # 注意这要放在判断「有没有变化」之前算，否则「拿 1 小时去覆盖 7 天」
        # 会被当成一次变化，白写一条日志
        if existing.expires_at is None:
            expiry = None
        elif expiry is not None and existing.expires_at > expiry:
            expiry = existing.expires_at

        if not _is_change(existing.expires_at, expiry):
            # 结果没有变化（重复点了同一个时长）→ 不写库也不记日志
            return None

        # 先删旧行再插新行。
        # **必须用批量 delete**（它立即执行），不能 db.delete(obj) + db.add(new)：
        # SQLAlchemy 的 unit of work 会先 INSERT 后 DELETE，flush 时撞唯一约束。
        # 顺带解决「已过期的行占着唯一键」的问题。
        db.query(IpBan).filter(IpBan.target == target).delete(synchronize_session=False)
        db.flush()

    record = IpBan(
        target=target,
        reason=reason,
        # 被管理员插手过的（含延长过的自动封禁）就是「手动」，这条记录从此不算系统自动封的
        is_manual=bool(operator is not None or (existing is not None and existing.is_manual)),
        expires_at=expiry,
        operator_no=operator.student_no if operator else (existing.operator_no if existing else None),
        operator_name=_operator_name(db, operator) or (existing.operator_name if existing else None),
    )
    db.add(record)
    db.flush()
    return record


def _is_change(old: datetime | None, new: datetime | None) -> bool:
    """最终的结束时间和原来那条相比，算不算「真的变了」。

    None（永久）两边相等也算没变 —— 所以「永久再封一次限时」和
    「永久再封一次永久」都是空操作，符合「不能降级」。
    """
    if old == new:
        return False
    if old is None or new is None:
        return True
    return abs((new - old).total_seconds()) > _CHANGE_TOLERANCE_SECONDS


def _operator_name(db: Session, operator: User | None) -> str | None:
    """操作人姓名。延迟 import 避免 services 内部循环引用"""
    if operator is None:
        return None
    from .user_service import account_name

    return account_name(db, operator)


def unban_ip(db: Session, ban_id: int) -> IpBan | None:
    """按主键解封，返回被删掉的那条记录（不存在则返回 None）。

    用 id 而不是 target 做参数：网段和 IPv6 里的 / : % 在 URL 路径里都要转义，
    转完还可能被中间层还原错，踩一次很难查。前端列表里本来就有 id。

    调用方记得同时 clear_failures(ip)，否则解封后第一次输错立刻又被封。
    """
    record = db.query(IpBan).filter(IpBan.id == ban_id).first()
    if record is None:
        return None
    db.delete(record)
    db.flush()
    return record


def purge_expired(db: Session) -> int:
    """删掉所有已过期的封禁行，返回删掉的条数。

    **只在启动时调一次**。不要放进 GET /ip-bans 里：在 GET 里写库、
    又忘了 commit 的话是静默无效，没人会注意到；列表接口只要在 SQL 里
    过滤掉过期行就够了（过期行留着最多占一行，不影响判定）。
    """
    now = datetime.now()
    return (
        db.query(IpBan)
        .filter(IpBan.expires_at.isnot(None), IpBan.expires_at <= now)
        .delete(synchronize_session=False)
    )
