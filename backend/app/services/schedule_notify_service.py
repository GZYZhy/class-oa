"""日程提醒调度器

分钟级巡检，找出接下来 1 分钟内需要触发的日程提醒，调用 notify_service 推送。

沿用生日调度器的模式（线程 + 巡检），但粒度更细（每 60 秒一次）。
后端是单进程，所以不会出现「多个实例各发一遍」的问题。

**严格遵守：未开启通知的日程一律不推送，绝不默认通知。**
只有 schedule.notify_enabled == True 且 开始时间 - 当前时间 <= 提前量 的日程才会被触发。
"""

import os
import threading
import time
import traceback
from datetime import datetime, timedelta

from ..database import SessionLocal
from .schedule_service import list_upcoming_notifications
from . import notify_service as ns
from ..models.schedule import SOURCE_BATCH

# 巡检间隔（秒）。1 分钟一次，最多有 1 分钟延迟，可接受。
TICK_SECONDS = 60

# 已发送记录（内存，进程重启丢失也没关系——同一天内的重复触发不会超过 1 次，
# 因为巡检窗口是「下一分钟」，发过的下一轮就不在窗口里了）
_sent_keys: set[tuple[int, str]] = set()

_thread: threading.Thread | None = None


def _enabled() -> bool:
    return os.environ.get("SCHEDULE_NOTIFY_SCHEDULER", "1") != "0"


def _tick_seconds() -> float:
    try:
        return float(os.environ.get("SCHEDULE_NOTIFY_TICK", TICK_SECONDS))
    except ValueError:
        return TICK_SECONDS


def tick(now: datetime | None = None) -> int:
    """到点就发送；返回本轮发送的条数

    now 只为测试能伪造时间。
    巡检窗口：[now, now + 1 tick_interval]，找出这个窗口内要触发的提醒。
    """
    now = now or datetime.now()
    window_end = now + timedelta(seconds=_tick_seconds())

    db = SessionLocal()
    try:
        upcoming = list_upcoming_notifications(db, now, window_end)
        count = 0
        for tpl, student, notify_time in upcoming:
            # 去重：同一天同一日程只发一次
            key = (tpl.id, notify_time.strftime("%Y%m%d%H%M"))
            if key in _sent_keys:
                continue
            _sent_keys.add(key)

            # 一条发失败不能带走这一轮剩下的：窗口是「下一分钟」，这轮跳过的人
            # 下一轮的窗口已经不覆盖他了，等于这条提醒永远发不出去（还不报错）
            try:
                _send_notification(db, tpl, student, notify_time)
            except Exception:
                print(
                    f"[日程提醒] 发送失败（日程 {tpl.id}）：\n{traceback.format_exc()}",
                    flush=True,
                )
                continue
            count += 1

        # 清理已发送记录（只留最近 24 小时的）
        _cleanup_sent(now)

        return count
    finally:
        db.close()


def _send_notification(db, tpl, student, notify_time: datetime) -> None:
    """发送一条日程提醒

    用 notify_service.deliver_now 同步发送（调度线程里没有 BackgroundTasks）。
    只推给这一个学生。
    """
    from .inbox_service import recipient_nos
    from .bark_service import bark_keys
    from .webpush_service import web_subscriptions
    from .webhook_service import webhook_targets
    from .email_service import email_recipients, email_enabled
    from ..config import smtp_enabled

    # 组装收件人 —— 只给这一个学生
    targets = ns.Recipients(
        bark=bark_keys(db, only_no=student.student_no),
        web=web_subscriptions(db, only_no=student.student_no),
        webhook=webhook_targets(db, only_no=student.student_no),
        email=(
            email_recipients(db, only_no=student.student_no)
            if smtp_enabled()
            else []
        ),
        inbox=recipient_nos(db, only_no=student.student_no),
    )

    title = f"日程提醒：{tpl.title}"
    # 组装内容
    start_str = tpl.start_time.strftime("%H:%M")
    end_str = tpl.end_time.strftime("%H:%M")
    lines = [
        f"时间：{start_str} - {end_str}",
    ]
    if tpl.location:
        lines.append(f"地点：{tpl.location}")
    if tpl.description:
        lines.append(f"备注：{tpl.description}")
    if tpl.source_type == SOURCE_BATCH:
        lines.append("（班委分配日程）")
    body = "\n".join(lines)

    # 用 deliver_now 同步发送
    ns.deliver_now(db, targets, title, body, level="active", page="/schedule")


def _cleanup_sent(now: datetime) -> None:
    """清理 24 小时之前的已发送记录，避免内存无限增长"""
    cutoff = (now - timedelta(hours=24)).strftime("%Y%m%d%H%M")
    to_remove = [key for key in _sent_keys if key[1] < cutoff]
    for key in to_remove:
        _sent_keys.discard(key)


def _loop() -> None:
    """线程主体。循环绝不允许退出。

    睡到「这一轮开始 + 一个周期」，不是固定睡满一个周期：窗口是
    [本轮开始, 本轮开始 + 周期]，tick 自己花掉的时间（发邮件、写站内信）
    若被固定 sleep 再叠加一次，两个窗口之间就裂出一条缝，落在缝里的提醒
    两头都不沾，再也不会被捡起来（生日那边没这个问题，它的语义是「过了点就补」）。
    """
    while True:
        started = time.monotonic()
        try:
            tick()
        except Exception:
            print("[日程提醒] 巡检异常：\n" + traceback.format_exc(), flush=True)
        time.sleep(max(0.0, _tick_seconds() - (time.monotonic() - started)))


def state() -> str:
    """调度器状态：running / off / dead"""
    if not _enabled():
        return "off"
    if _thread is not None and _thread.is_alive():
        return "running"
    return "dead"


def start() -> None:
    """启动日程提醒调度线程（幂等）"""
    global _thread
    if not _enabled():
        print("[日程提醒] 定时任务已通过 SCHEDULE_NOTIFY_SCHEDULER=0 关闭", flush=True)
        return
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(
        target=_loop, name="schedule-notify-scheduler", daemon=True,
    )
    _thread.start()
    print(f"[日程提醒] 定时任务已启动：每 {_tick_seconds()} 秒巡检一次", flush=True)
