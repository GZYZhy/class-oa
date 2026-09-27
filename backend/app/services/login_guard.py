"""登录失败计数（进程内）

按 IP 记「最近失败了几次」，两个用途：
- 失败 1 次就要求人机验证（验证码 / Turnstile）
- 失败到 login_ban_threshold 次就自动封禁这个 IP（见 ban_service）

**用内存字典，不落库**：量级很小（一个班），重启就清空也无所谓 ——
反正窗口过了自己就失效。真正需要持久化的是封禁结果本身，那个在 ip_bans 表里。

之所以从 api/auth.py 搬到这里，是因为 admin.py 手动解封时也要清计数，
不能跨模块去摸 auth 的私有变量。
"""

from datetime import datetime, timedelta

from ..config import fail_window_minutes

# 结构：{ "1.2.3.4": {"count": 2, "first_fail": datetime} }
_login_failures: dict[str, dict] = {}

# 失败几次后开始要求人机验证（题目说第一次输错后就要，所以 = 1）
_CAPTCHA_THRESHOLD = 1


def _window() -> timedelta:
    """统计窗口。

    和自动封禁**共用** config.fail_window_minutes()：各配一个的话，
    计数会在较短的那个窗口先被清零，长窗口的封禁阈值永远达不到。
    """
    return timedelta(minutes=fail_window_minutes())


def needs_captcha(ip: str) -> bool:
    """这个 IP 是否需要先过人机验证才能登录"""
    record = _login_failures.get(ip)
    if not record:
        return False
    # 超过窗口，清掉这条记录
    if datetime.now() - record["first_fail"] > _window():
        del _login_failures[ip]
        return False
    return record["count"] >= _CAPTCHA_THRESHOLD


def record_failure(ip: str) -> int:
    """记一次登录失败，返回**新的**失败次数（调用方靠它判断该不该封禁）"""
    now = datetime.now()
    record = _login_failures.get(ip)
    if record and (now - record["first_fail"]) <= _window():
        record["count"] += 1
    else:
        _login_failures[ip] = {"count": 1, "first_fail": now}
    return _login_failures[ip]["count"]


def clear_failures(ip: str) -> None:
    """清掉这个 IP 的失败计数

    两处要调：登录成功之后，以及管理员解封之后 ——
    后者不清的话，解封后第一次输错立刻又会被封（计数还停在阈值上），
    管理员会以为解封没生效。
    """
    _login_failures.pop(ip, None)
