"""每日生日任务的守护线程

项目没有定时任务框架，也不打算为这一件事引入 APScheduler（依赖全部钉死），
用标准库 thread 就够。后端是**单进程**（backend/Dockerfile 的 uvicorn 没带
--workers），所以进程内起一个线程不会出现「多个实例各发一遍」。

线程里**必须自己开会话**：get_db 是请求级依赖，响应发出之后就关了，
后台线程借不到（notify_service.recipients 那条注释说的就是这件事）。
"""

import os
import threading
import time
import traceback
from datetime import date, datetime, timedelta

from ..database import SessionLocal
from .birthday_service import get_settings, run_daily

# 巡检间隔。不是为了掐准 8:00 —— 定点只需「到点后的第一次巡检把它捡起来」，
# 几分钟的误差对一天一次的事完全可以接受
TICK_SECONDS = 300
RUN_HOUR = 8

_thread: threading.Thread | None = None


def _enabled() -> bool:
    # 下面三个都是运维 / 测试旋钮，不是管理员设置（管理员只要那三个开关）
    return os.environ.get("BIRTHDAY_SCHEDULER", "1") != "0"


def _tick_seconds() -> float:
    try:
        return float(os.environ.get("BIRTHDAY_TICK_SECONDS", TICK_SECONDS))
    except ValueError:
        return TICK_SECONDS


def _run_hour() -> int:
    try:
        return int(os.environ.get("BIRTHDAY_RUN_HOUR", RUN_HOUR))
    except ValueError:
        return RUN_HOUR


def tick(now: datetime | None = None) -> bool:
    """到点就跑一次；返回这轮是否真的执行了

    now 只为测试能伪造时间。生产一律 datetime.now()（naive，北京时间靠容器的
    TZ=Asia/Shanghai）—— 别用 func.now() / CURRENT_TIMESTAMP，SQLite 那个是 UTC，
    差 8 小时。

    catch-up 语义：只要「过了 8 点」且今天还没跑过就发。所以容器 08:00 没运行、
    10:00 才起来，照样补发当天的 —— 数据是「今天的寿星」，10:00 时它依然正确；
    不补发的话「容器昨晚重启过」就等于当天功能消失。代价是 23:50 启动也会补一条，
    接受（不引入「22 点后不补」这类额外规则，简单优先）。
    """
    now = now or datetime.now()
    if now.hour < _run_hour():
        return False
    db = SessionLocal()
    try:
        # 今天跑没跑过由 run_daily 自己判（它拥有 last_run_date 这一个写入点）
        return run_daily(db, today=now.date())
    finally:
        # 一定要关：连接不还回池里的话，SQLite 那把单写者锁会一直挂在这次连接上
        db.close()


def _loop() -> None:
    """线程主体。**这个循环绝不允许退出**

    线程一死，此后所有日期的生日通知都会静默消失，没有报错、没有痕迹 ——
    这是本功能最难发现的一种故障。所以单次巡检的异常在这里就地吞掉、打全栈，
    循环继续。也不用 logging（项目全程 print）。

    顺带一个好处：查库撞上「database is locked」（SQLite 单写者被长请求占着）时
    会被吞掉，下一个巡检周期自动重试，当天仍在窗口内。
    """
    while True:
        try:
            tick()
        except Exception:
            print("[生日] 巡检异常：\n" + traceback.format_exc(), flush=True)
        time.sleep(_tick_seconds())


def status_line() -> str:
    """一句话说清「今天跑过没有」

    刚重启完的容器，日志里只有一行「已启动」是不够的 —— 运维真正想知道的是
    「今天的检查到底跑了没、功能还是活的吗」。查一次库把答案直接写进日志里，
    比让人对着 last_run_date 猜要省事。启动只查这一次，不产生每轮巡检的噪音。
    """
    db = SessionLocal()
    try:
        last = get_settings(db).last_run_date
    except Exception:
        # 库还没建好或连不上：启动会另打别的日志，这里不能因为一行状态就崩掉
        return "读取今日检查状态失败，请留意后面的日志"
    finally:
        db.close()
    today = date.today()
    if last == today:
        return f"今天（{today}）的检查已经跑过，不会重复发送"
    if last is None:
        return f"从没跑过任何一天，今天（{today}）会在 {_run_hour()}:00 后执行第一次"
    return f"最近一次是 {last}，今天（{today}）还没跑"


def state() -> str:
    """调度器现在的状态，给页面显示用：running / off / dead

    三种分开说，因为对管理员的意义完全不同：
      running —— 正常，等着它干活就行
      off     —— 有人用 BIRTHDAY_SCHEDULER=0 关掉了（本地开发、或专门停掉）
      dead    —— 没被关，但线程没起来或已退出，**这是真故障**：此后的生日通知
                 会全部静默消失，必须去看日志

    把 off 和 dead 合并显示成「没在跑」是不行的：前者是预期内的，后者意味着
    功能已经坏了 —— 那正是这行状态存在的意义。
    """
    if not _enabled():
        return "off"
    if _thread is not None and _thread.is_alive():
        return "running"
    return "dead"


def next_run_at(now: datetime | None = None) -> datetime | None:
    """预计下次执行检查的时刻。None = 就在接下来的某轮巡检里，给不出准确时刻

    判断依据是「今天跑过没有」，不能光看几点钟 —— 要和 tick() 的 catch-up 语义
    对齐：容器 10:00 才起来时，8:00 那个点早过了，但当天仍要补发。
    """
    # 线程不在跑（被关掉、或已经退出）就谈不上「下次」。后者尤其要说清楚：
    # 否则页面会一本正经地显示一个永远不会发生的「预计下次 08:00」
    if state() != "running":
        return None
    now = now or datetime.now()
    db = SessionLocal()
    try:
        last = get_settings(db).last_run_date
    except Exception:
        # 库连不上。状态行不值得为此报错，交给启动日志去说
        return None
    finally:
        db.close()
    run_hour = _run_hour()
    if last == now.date():
        return datetime(now.year, now.month, now.day, run_hour) + timedelta(days=1)
    if now.hour < run_hour:
        return datetime(now.year, now.month, now.day, run_hour)
    # 过了点、今天又还没跑：等下一轮巡检把它捡起来（≤ TICK_SECONDS 之后）
    return None


def start() -> None:
    """启动守护线程（幂等：重复调用只起一个）

    daemon=True：容器停的时候不用等它跑完当前这轮，进程直接退。
    """
    global _thread
    if not _enabled():
        print("[生日] 定时任务已通过 BIRTHDAY_SCHEDULER=0 关闭", flush=True)
        return
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="birthday-scheduler", daemon=True)
    _thread.start()
    print(f"[生日] 定时任务已启动：每天 {_run_hour()}:00 后的第一次巡检发送", flush=True)
    print(f"[生日] {status_line()}", flush=True)
