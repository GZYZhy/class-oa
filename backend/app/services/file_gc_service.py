"""每天凌晨 2 点回收孤儿文件，开关由后台运维配置持久化。"""

import threading
import time
import traceback
from datetime import datetime

from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import OperationLog, RuntimeSetting
from ..utils.human_size import human_size
from .file_health_service import cleanup_orphans

LAST_RUN_KEY = "orphan_cleanup_last_date"
_thread: threading.Thread | None = None
_RUN_LOCK = threading.Lock()


def run_due(db: Session, now: datetime | None = None) -> dict | None:
    """凌晨 2 点时段的首次巡检执行，同一天成功运行后持久化去重。"""
    now = now or datetime.now()
    if now.hour != 2:
        return None
    with _RUN_LOCK:
        enabled = db.get(RuntimeSetting, "orphan_cleanup_enabled")
        active = (
            enabled.value.lower() == "true"
            if enabled
            else settings.orphan_cleanup_enabled
        )
        if not active:
            return None
        last = db.get(RuntimeSetting, LAST_RUN_KEY)
        today = now.date().isoformat()
        if last and last.value == today:
            return None
        result = cleanup_orphans(db)
        db.merge(RuntimeSetting(key=LAST_RUN_KEY, value=today))
        db.add(
            OperationLog(
                operator_no="system",
                operator_name="系统",
                action="自动清理孤儿文件",
                target="文件体检",
                created_at=now,
                detail=(
                    f"删除 {result['deleted']} 个文件，释放 {human_size(result['freed_bytes'])}，"
                    f"{result['failed']} 个删除失败，{len(result['skipped_domains'])} 个目录因引用异常跳过"
                ),
            )
        )
        db.commit()
        return result


def _loop() -> None:
    while True:
        db = SessionLocal()
        try:
            run_due(db)
        except Exception:
            db.rollback()
            print("[文件回收] 巡检异常：\n" + traceback.format_exc(), flush=True)
        finally:
            db.close()
        time.sleep(60)


def start() -> None:
    """后台开关随时可改，巡检线程常驻，默认关闭自动删除。"""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="file-gc-scheduler", daemon=True)
    _thread.start()
