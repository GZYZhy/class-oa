"""每日文件回收的开关、时点、持久化去重与失败重试。"""

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import OperationLog, RuntimeSetting
from app.services import file_gc_service as gc


def test_daily_cleanup_switch_time_and_restart(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'gc.db'}")
    Base.metadata.create_all(engine)
    calls = []
    result = {
        "deleted": 2,
        "freed_bytes": 100,
        "failed": 0,
        "by_domain": [],
        "skipped_domains": [],
    }
    monkeypatch.setattr(gc, "cleanup_orphans", lambda db: calls.append(True) or result)
    monkeypatch.setattr(gc.settings, "orphan_cleanup_enabled", False)
    with Session(engine) as db:
        assert gc.run_due(db, datetime(2026, 11, 13, 2)) is None
        db.add(RuntimeSetting(key="orphan_cleanup_enabled", value="true"))
        db.commit()
        assert gc.run_due(db, datetime(2026, 11, 13, 1, 59)) is None
        assert gc.run_due(db, datetime(2026, 11, 13, 2)) == result
        assert gc.run_due(db, datetime(2026, 11, 13, 2, 1)) is None
        assert db.query(OperationLog).count() == 1
    with Session(engine) as db:
        assert gc.run_due(db, datetime(2026, 11, 13, 2, 30)) is None
        assert gc.run_due(db, datetime(2026, 11, 14, 2)) == result
        db.get(RuntimeSetting, "orphan_cleanup_enabled").value = "false"
        db.commit()
        assert gc.run_due(db, datetime(2026, 11, 15, 2)) is None
    assert len(calls) == 2
    engine.dispose()


def test_cleanup_failure_can_retry(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'gc-retry.db'}")
    Base.metadata.create_all(engine)

    def fail(db):
        raise OSError("测试磁盘不可用")

    monkeypatch.setattr(gc, "cleanup_orphans", fail)
    with Session(engine) as db:
        db.add(RuntimeSetting(key="orphan_cleanup_enabled", value="true"))
        db.commit()
        import pytest

        with pytest.raises(OSError):
            gc.run_due(db, datetime(2026, 11, 13, 2))
        db.rollback()
        assert db.get(RuntimeSetting, gc.LAST_RUN_KEY) is None
    engine.dispose()


def test_real_cleanup_preserves_cross_domain_references(tmp_path, monkeypatch):
    import os
    import time
    from app.models import Student
    from app.services import file_health_service as files

    folder = tmp_path / "shared-files"
    folder.mkdir()
    live = folder / "live.png"
    orphan = folder / "orphan.png"
    for path in (live, orphan):
        path.write_bytes(b"file")
        os.utime(path, (time.time() - 7200, time.time() - 7200))
    domains = (
        files.Domain("photos", "照片", folder),
        files.Domain("avatars", "头像", folder),
    )
    monkeypatch.setattr(files, "DOMAINS", domains)
    monkeypatch.setattr(
        files, "DOMAIN_BY_KEY", {domain.key: domain for domain in domains}
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'gc-real.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Student(student_no="test", name="测试同学", gaokao_photo=live.name))
        db.add(RuntimeSetting(key="orphan_cleanup_enabled", value="true"))
        db.commit()
        result = gc.run_due(db, datetime(2026, 11, 13, 2))
        assert result["deleted"] == 1
        assert live.exists()
        assert not orphan.exists()
    engine.dispose()


def test_changed_candidate_is_preserved(tmp_path, monkeypatch):
    import os
    import time
    from app.services import file_health_service as files

    candidate = tmp_path / "old.png"
    candidate.write_bytes(b"old")
    os.utime(candidate, (time.time() - 7200, time.time() - 7200))
    domain = files.Domain("photos", "照片", tmp_path)
    monkeypatch.setattr(files, "DOMAINS", (domain,))
    monkeypatch.setattr(files, "DOMAIN_BY_KEY", {"photos": domain})
    scan = files._orphan_paths

    def replace_after_scan(*args):
        for item in scan(*args):
            item[0].write_bytes(b"newly-uploaded")
            yield item

    monkeypatch.setattr(files, "_orphan_paths", replace_after_scan)
    engine = create_engine(f"sqlite:///{tmp_path / 'gc-changed.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = files.cleanup_orphans(db, ["photos"])
        assert result["deleted"] == 0
        assert candidate.read_bytes() == b"newly-uploaded"
    engine.dispose()
