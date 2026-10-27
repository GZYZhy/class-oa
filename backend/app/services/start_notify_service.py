"""投票 / 收集 / 签到的「开始提醒」调度器

出卷时由发起人决定要不要提醒（notify_on_start）。**创建时不发**，等 start_at 到了
才由这里巡检发一次：

- 开始时间在未开始时可以改，巡检永远看**当前**的 start_at，所以改了时间提醒就跟着走；
- 已经开始（非 pending）后 start_at 锁定，不会出现「发过之后又改时间」；
- 发完写 start_notified_at，进程重启、巡检重复跑都不会补发；
- 老投票升级时在迁移里标成已提醒，不会被补发（见 database_migrate）。

和日程提醒一样在进程内起守护线程：后端是单进程（Dockerfile 的 uvicorn 没带
--workers），不会出现多实例各发一遍。
"""

import os
import threading
import time
import traceback
from datetime import datetime

from sqlalchemy import func, or_

from ..database import SessionLocal
from ..models import (
    Checkin,
    CheckinTarget,
    Collection,
    CollectionQuestion,
    CollectionTarget,
    Poll,
    PollQuestion,
    PollTarget,
)
from . import notify_service as ns
from .collection_service import collection_share_token
from .poll_service import poll_share_token
from .share_service import share_path

TICK_SECONDS = 60

_thread: threading.Thread | None = None


def _enabled() -> bool:
    return os.environ.get("START_NOTIFY_SCHEDULER", "1") != "0"


def _tick_seconds() -> float:
    try:
        return float(os.environ.get("START_NOTIFY_TICK", TICK_SECONDS))
    except ValueError:
        return TICK_SECONDS


def _notify_poll(db, poll: Poll) -> None:
    """给一场到点的投票发开始提醒"""
    question_count = (
        db.query(func.count(PollQuestion.id))
        .filter(PollQuestion.poll_id == poll.id)
        .scalar()
        or 0
    )
    body = f"共 {question_count} 题，{poll.end_at:%m-%d %H:%M} 截止"
    if poll.anonymous:
        body += "（不记名）"
    title = f"投票开始：{poll.title}"
    page = share_path("vote", poll_share_token(poll.id))

    for (student_no,) in (
        db.query(PollTarget.student_no)
        .filter(PollTarget.poll_id == poll.id)
        .all()
    ):
        # 自己发起的投票不推给自己
        if student_no == poll.creator_no:
            continue
        targets = ns.recipients(
            db, only_no=student_no, exclude_no=poll.creator_no
        )
        ns.deliver_now(
            db, targets, title, body, level="timeSensitive", page=page
        )


def _notify_collection(db, collection: Collection) -> None:
    """给一场到点的收集发开始提醒"""
    question_count = (
        db.query(func.count(CollectionQuestion.id))
        .filter(CollectionQuestion.collection_id == collection.id)
        .scalar()
        or 0
    )
    body = f"共 {question_count} 题，每人可填 {collection.submit_quota} 份"
    if collection.max_responses is not None:
        body += f"，只收前 {collection.max_responses} 份"
    body += f"，{collection.end_at:%m-%d %H:%M} 截止"
    if collection.anonymous:
        body += "（不记名）"
    title = f"收集开始：{collection.title}"
    page = share_path("collect", collection_share_token(collection.id))

    for (student_no,) in (
        db.query(CollectionTarget.student_no)
        .filter(CollectionTarget.collection_id == collection.id)
        .all()
    ):
        if student_no == collection.creator_no:
            continue
        targets = ns.recipients(
            db, only_no=student_no, exclude_no=collection.creator_no
        )
        ns.deliver_now(
            db, targets, title, body, level="timeSensitive", page=page
        )


def _notify_checkin(db, checkin: Checkin) -> None:
    """给一场到点的签到发开始提醒

    签到的发布人很可能自己也在范围内，得一起收到 —— 和创建时立即发的那条
    口径一致，不按 creator_no 排除。
    """
    body = f"截止 {checkin.end_at:%m-%d %H:%M}，打开链接完成签到"
    if checkin.require_photo:
        body += "，需上传照片"
    if checkin.lat is not None and checkin.lng is not None:
        body += "，需在指定地点签到"
    title = f"签到开始：{checkin.title}"
    page = share_path("checkin", checkin.code)

    for (student_no,) in (
        db.query(CheckinTarget.student_no)
        .filter(CheckinTarget.checkin_id == checkin.id)
        .all()
    ):
        targets = ns.recipients(db, only_no=student_no)
        ns.deliver_now(
            db, targets, title, body, level="timeSensitive", page=page
        )


def tick(now: datetime | None = None, db=None) -> int:
    """巡检一轮，返回这一轮成功提醒的活动数

    db 参数只给测试用：测试进程拿一个指向测试库的会话传进来，
    就不用为了发一条提醒去起第二个后端。生产里传 None，自己开会话。
    """
    now = now or datetime.now()
    own_session = db is None
    if own_session:
        db = SessionLocal()

    sent = 0
    try:
        polls = (
            db.query(Poll)
            .filter(
                Poll.notify_on_start.is_(True),
                Poll.start_notified_at.is_(None),
                Poll.start_at <= now,
                # 进程停过一整场的情况：已经截止的就不补发了
                Poll.end_at >= now,
                Poll.closed_at.is_(None),
            )
            .all()
        )
        for poll in polls:
            try:
                _notify_poll(db, poll)
                poll.start_notified_at = now
                db.commit()
                sent += 1
            except Exception:
                db.rollback()
                print(
                    f"[开始提醒] 投票 {poll.id} 发送失败：\n{traceback.format_exc()}",
                    flush=True,
                )

        collections = (
            db.query(Collection)
            .filter(
                Collection.notify_on_start.is_(True),
                Collection.start_notified_at.is_(None),
                Collection.start_at <= now,
                Collection.end_at >= now,
                Collection.closed_at.is_(None),
            )
            .all()
        )
        for collection in collections:
            try:
                _notify_collection(db, collection)
                collection.start_notified_at = now
                db.commit()
                sent += 1
            except Exception:
                db.rollback()
                print(
                    f"[开始提醒] 收集 {collection.id} 发送失败：\n"
                    f"{traceback.format_exc()}",
                    flush=True,
                )

        checkins = (
            db.query(Checkin)
            .filter(
                Checkin.notify_on_start.is_(True),
                Checkin.start_notified_at.is_(None),
                # 老签到的 start_at 可能为空（发布即可签）；新签到创建时已立即
                # 发出并标记，这里主要兜住未来开始的签到
                or_(
                    Checkin.start_at.is_(None),
                    Checkin.start_at <= now,
                ),
                Checkin.end_at >= now,
                Checkin.closed_at.is_(None),
            )
            .all()
        )
        for checkin in checkins:
            try:
                _notify_checkin(db, checkin)
                checkin.start_notified_at = now
                db.commit()
                sent += 1
            except Exception:
                db.rollback()
                print(
                    f"[开始提醒] 签到 {checkin.id} 发送失败：\n"
                    f"{traceback.format_exc()}",
                    flush=True,
                )

        return sent
    finally:
        if own_session:
            db.close()


def _loop() -> None:
    """线程主体。循环绝不退出，单条失败只跳过这一条"""
    while True:
        started = time.monotonic()
        try:
            tick()
        except Exception:
            print("[开始提醒] 巡检异常：\n" + traceback.format_exc(), flush=True)
        # 睡到「本轮开始 + 一个周期」，避免发送耗时把巡检周期越拉越长
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, _tick_seconds() - elapsed))


def start() -> None:
    """启动守护线程；重复调用只启一次"""
    global _thread
    if not _enabled():
        print("[开始提醒] 已禁用（START_NOTIFY_SCHEDULER=0）", flush=True)
        return
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(
        target=_loop, name="start-notify", daemon=True
    )
    _thread.start()
    print(
        f"[开始提醒] 调度任务已启动：每 {_tick_seconds():.0f} 秒巡检一次",
        flush=True,
    )
