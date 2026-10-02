"""访问令牌的调用限流（进程内）

**为什么要限**：令牌天然是给脚本、定时任务、MCP 这类东西用的。Cookie 那条路被
「人点鼠标的速度」天然限住了，令牌没有这个约束 —— 一个写错的循环、一个失控的
定时任务就能把接口打满，而本站是 SQLite + 小机器，全班会跟着一起变慢。

**按令牌 id 计数，不按 IP**：同一把令牌可能从多个地址调（换网络、挂代理）；
反过来同一个出口 IP（同一间机房、同一个宿舍路由）下可能有好几把正常令牌，
按 IP 会把它们连坐。

用内存字典，和登录失败计数（login_guard）同一套理由：量级很小、重启清空无所谓、
窗口过了自己就失效。

字典**只增不删**，所以条目数不是按「生效中的令牌」封顶的，而是按「累计创建过的
令牌」—— 一次没再被用过的令牌，它的条目会一直留着。这是有意为之：每个条目只有
几十字节，而令牌创建一个要输一次密码、每个账号还限 10 个生效中，一个班的全部
历史令牌加起来也就几十上百条，为它写清理逻辑不划算。
（令牌行不会被物理删除，所以 id 不会复用，也就不存在「旧计数算到新令牌头上」。）
"""

from datetime import datetime, timedelta

# 每分钟允许多少次。2 次/秒是给「一次拉一批数据」留的余量：
# 正常脚本远到不了，而失控的死循环会被立刻挡住
MAX_PER_MINUTE = 120

_WINDOW = timedelta(minutes=1)

# 结构：{ token_id: {"count": n, "window_start": datetime} }
_hits: dict[int, dict] = {}


def hit(token_id: int) -> int | None:
    """记一次令牌调用

    没超限返回 None；超限返回**还要等多少秒**才能再试，调用方据此返回 429。

    用固定窗口而不是滑动窗口：实现简单，代价是窗口边界上可能短时到 2 倍，
    对这个场景无所谓。
    """
    now = datetime.now()
    rec = _hits.get(token_id)
    if rec is None or (now - rec["window_start"]) >= _WINDOW:
        _hits[token_id] = {"count": 1, "window_start": now}
        return None
    rec["count"] += 1
    if rec["count"] > MAX_PER_MINUTE:
        # 至少 1 秒：算出来 0 的话提示会变成「请 0 秒后再试」
        return max(1, int((rec["window_start"] + _WINDOW - now).total_seconds()))
    return None
