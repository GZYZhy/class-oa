"""文件体检：库里有盘上没有、盘上有库里没有

数据体检原来只看学生表那几列。照片、资料、附件这些是「数据库记名字、磁盘存内容」，
两边一旦对不上，页面上只表现为一张裂图或一个 404，从库里完全看不出来：

  * **登记了但文件丢了**：删记录时漏删文件、手工清理过目录、换过盘；
  * **孤儿文件**：文件在，但没有任何记录指向它 —— 换资料时先传后删旧记录、
    上传中途失败，都会留下这种占空间又没人认领的文件。

第三条「孤儿文件」可以一键清理（只删文件，绝不删数据库记录）。
清理前会重新算一遍、并跳过太新的文件，避免把「刚写盘还没入库」的文件误删。

目录常量在各自的接口模块里也有同样一份（都吃同名环境变量）。这里不 import
那些 api 模块：services → api 会绕成循环导入（api 在导入时又会把 services 拉起来）。
"""

import json
import os
import time
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..models import (
    Announcement,
    CertificateRequest,
    CheckinTarget,
    Collection,
    Checkin,
    CollectionAnswer,
    CollectionSubmission,
    EvPassRequest,
    ExportRequest,
    Feedback,
    LeaveRequest,
    Notice,
    Resource,
    Student,
    User,
)
from ..utils.human_size import human_size

PHOTO_DIR = Path(os.environ.get("PHOTO_DIR") or (BASE_DIR / "data" / "photos"))
AVATAR_DIR = Path(os.environ.get("AVATAR_DIR") or (BASE_DIR / "data" / "avatars"))
ANNOUNCEMENT_DIR = Path(
    os.environ.get("ANNOUNCEMENT_DIR") or BASE_DIR / "data" / "announcements"
)
RESOURCE_DIR = Path(os.environ.get("RESOURCE_DIR") or (BASE_DIR / "data" / "downloads"))
LEAVE_DIR = Path(os.environ.get("LEAVE_DIR") or BASE_DIR / "data" / "leaves")
EV_PASS_DIR = Path(os.environ.get("EV_PASS_DIR") or BASE_DIR / "data" / "ev_passes")
CERT_ATTACH_DIR = Path(
    os.environ.get("CERT_ATTACH_DIR")
    or BASE_DIR / "data" / "certificates" / "attachments"
)
CERT_RESULT_DIR = Path(
    os.environ.get("CERT_RESULT_DIR") or BASE_DIR / "data" / "certificates" / "results"
)
CHECKIN_DIR = Path(os.environ.get("CHECKIN_DIR") or BASE_DIR / "data" / "checkins")
NOTICE_ATTACH_DIR = Path(
    os.environ.get("NOTICE_ATTACH_DIR") or (BASE_DIR / "data" / "notices")
)
# 收集的图片按「收集 ID」分子目录：collection_files/{collection_id}/{存盘名}
COLLECTION_FILE_DIR = Path(
    os.environ.get("COLLECTION_FILE_DIR") or (BASE_DIR / "data" / "collection_files")
)
FEEDBACK_DIR = Path(os.environ.get("FEEDBACK_DIR") or (BASE_DIR / "data" / "feedbacks"))
REMARK_ATTACH_DIR = Path(
    os.environ.get("REMARK_ATTACH_DIR") or (BASE_DIR / "data" / "remark_attachments")
)
EXPORT_DIR = Path(os.environ.get("EXPORT_DIR") or (BASE_DIR / "data" / "exports"))

# 文件刚写完到入库之间有个毫秒级空档。小于这个年龄的文件不报孤儿、也不清理，
# 否则体检正好撞上「正在上传」就会把人家刚传的文件删掉。
ORPHAN_MIN_AGE_SECONDS = 3600
_CLEANUP_LOCK = threading.Lock()


@dataclass(frozen=True)
class Domain:
    """一类文件：一个目录 + 一句人话说明

    recursive=True 的目录下还有按业务分子目录（目前只有收集），
    文件名带相对路径参与比对，同名文件不会互相顶掉。
    """

    key: str
    label: str
    directory: Path
    recursive: bool = False


DOMAINS: tuple[Domain, ...] = (
    Domain("photos", "学生照片与签字图", PHOTO_DIR),
    Domain("avatars", "域外账号头像", AVATAR_DIR),
    Domain("announcements", "文件公告 PDF", ANNOUNCEMENT_DIR),
    Domain("resources", "资料下载文件", RESOURCE_DIR),
    Domain("leaves", "请假证明材料", LEAVE_DIR),
    Domain("ev_passes", "电动车行驶证与签字图", EV_PASS_DIR),
    Domain("cert_attachments", "证明申请附件", CERT_ATTACH_DIR),
    Domain("cert_results", "证明成品 PDF", CERT_RESULT_DIR),
    Domain("checkins", "签到照片", CHECKIN_DIR),
    Domain("notices", "通知公告附件", NOTICE_ATTACH_DIR),
    # 收集的图片按收集 ID 分子目录
    Domain("collection_files", "收集附件", COLLECTION_FILE_DIR, recursive=True),
    Domain("feedbacks", "意见反馈附件", FEEDBACK_DIR),
    Domain("remark_attachments", "学生备注附件", REMARK_ATTACH_DIR),
    Domain("exports", "导出产物", EXPORT_DIR),
)

DOMAIN_BY_KEY = {domain.key: domain for domain in DOMAINS}

# 学生三个照片字段（不含签字图）：它们的「缺失」由 data_health 的「照片」卡片报，
# 这里只把它们算进「被引用」，避免同一件事报两遍、也避免被当成孤儿
_STUDENT_PHOTO_PROPS = (
    ("gaokao_photo", "高考照片"),
    ("on_site_photo", "实地采集照片"),
    ("id_photo", "自备证件照"),
)

_SIGN_PHOTO = "sign_photo"
_FILE_MISSING = "file_missing"
_FILE_ORPHAN = "file_orphan"
_FILE_REFERENCE_INVALID = "file_reference_invalid"

_GROUP_LABELS = {
    _SIGN_PHOTO: "签字图",
    _FILE_MISSING: "文件丢失",
    _FILE_ORPHAN: "孤儿文件",
    _FILE_REFERENCE_INVALID: "文件引用异常",
}


def _json_files(raw: str | None, key: str = "file") -> list[str] | None:
    """附件 JSON（[{"file": "...", "name": "..."}]）→ 文件名列表

    收集答卷的图片用的是 `name` 键（见 CollectionAnswer.files），所以键名可传。
    解析失败返回 None，调用方保护整个目录并报告引用异常
    """
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(items, list):
        return None
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get(key), str)
        or not item[key].strip()
        for item in items
    ):
        return None
    return [item[key] for item in items]


def _base_name(name: str | None) -> str:
    """库里存的可能是裸文件名，也可能带目录/URL 前缀，统一取最后一段

    公告的 file_path 存的是 `/api/announcements/file/xxx.pdf`，
    老数据的照片有存成 `/static/photos/xxx.jpg` 的 —— 两边口径都在这里归一。
    """
    return os.path.basename(str(name or "").strip())


def _user_label(user: User) -> str:
    return (user.display_name or user.student_no or "").strip()


def _collect(
    db: Session, *, lock: bool = False
) -> tuple[dict[str, set[str]], list[dict], list[dict]]:
    """扫一遍数据库，返回（各目录被引用的文件名, 登记项清单, 引用异常）

    登记项用于「文件丢了」检查，字段：
      category      sign_photo / file_missing
      domain        属于哪个目录
      file          文件名
      subject       给人看的对象说明
      label         这是什么东西（高考照片 / 辅助证明 / 成品 PDF）
      report        False 表示缺失由别的卡片负责（学生三照由「照片」卡片报）
    """

    def query(*entities):
        rows = db.query(*entities)
        return rows.with_for_update() if lock else rows

    refs: dict[str, set[str]] = {domain.key: set() for domain in DOMAINS}
    registry: list[dict] = []
    invalid: list[dict] = []

    def add_json(
        domain: str,
        raw: str | None,
        subject: str,
        label: str,
        *,
        key="file",
        collection_id=None,
    ):
        names = _json_files(raw, key)
        if names is None:
            invalid.append(
                {
                    "domain": domain,
                    "subject": subject,
                    "reason": "附件引用记录无法完整解析，已跳过该目录的孤儿检查与清理",
                }
            )
            return
        for name in names:
            rel = (
                f"{collection_id}/{_base_name(name)}"
                if collection_id is not None
                else None
            )
            add(domain, name, subject, label, rel=rel)

    def add(
        domain: str,
        name: str | None,
        subject: str,
        label: str,
        *,
        rel: str | None = None,
        category: str = _FILE_MISSING,
        report: bool = True,
    ) -> None:
        """登记一处「库里的文件名 → 该在哪个目录」

        rel 用于分子目录的域（收集）：传 `{collection_id}/{文件名}`，
        不传就按裸文件名（单层目录）。
        """
        text = str(name or "").strip()
        if not text:
            return
        relative = rel or _base_name(text)
        refs[domain].add(relative)
        registry.append(
            {
                "category": category,
                "domain": domain,
                "file": relative,
                "subject": subject,
                "label": label,
                "report": report,
            }
        )

    for student in query(Student).order_by(Student.student_no).all():
        subject = f"{student.name}（{student.student_no}）"
        for prop, label in _STUDENT_PHOTO_PROPS:
            add(
                "photos",
                getattr(student, prop, None),
                subject,
                label,
                report=False,  # 由「照片」卡片负责，避免重复
            )
        add(
            "photos",
            student.sign_photo,
            subject,
            "签字图",
            category=_SIGN_PHOTO,
        )
        add_json("remark_attachments", student.remark_attachments, subject, "备注附件")

    # 域外账号：头像和签字图各在一个目录
    for user in query(User).all():
        if not (user.avatar or user.sign_photo):
            continue
        subject = f"账号 {_user_label(user)}"
        add("avatars", user.avatar, subject, "头像")
        add(
            "photos",
            user.sign_photo,
            subject,
            "签字图",
            category=_SIGN_PHOTO,
        )

    for row in query(Announcement).all():
        add("announcements", row.file_path, f"公告「{row.title}」", "PDF")

    for row in query(Resource).all():
        add("resources", row.file_name, f"资料「{row.name}」", "文件")

    for row in query(LeaveRequest).all():
        subject = f"请假申请 #{row.id}"
        add("leaves", row.proof_file, subject, "辅助证明")
        add("leaves", row.advisor_sign_file, subject, "班导师签字图")

    for row in query(EvPassRequest).all():
        subject = f"电动车通行证 #{row.id}"
        add("ev_passes", row.license_file, subject, "行驶证")
        add("ev_passes", row.sign_file, subject, "经办班委签字图")

    for row in query(CertificateRequest).all():
        subject = f"证明开具 #{row.id}"
        add_json("cert_attachments", row.attachments, subject, "申请附件")
        add("cert_results", row.result_file, subject, "成品 PDF")

    for row in query(CheckinTarget).all():
        add("checkins", row.photo_file, f"签到 #{row.checkin_id}", "签到照片")

    for row in query(Notice).all():
        subject = f"通知「{row.title}」"
        add_json("notices", row.attachments, subject, "附件")

    for row in query(Feedback).all():
        add_json("feedbacks", row.attachments, f"意见反馈 #{row.id}", "附件")

    for row in query(ExportRequest).all():
        add("exports", row.file_name, f"导出申请 #{row.id}", "导出文件")

    # 收集的答卷图片：目录是 collection_files/{collection_id}/，
    # 所以要顺着 answer → submission 拿到收集 ID，按相对路径比对
    collection_of_submission = {
        row.id: row.collection_id for row in query(CollectionSubmission).all()
    }
    for answer in query(CollectionAnswer).all():
        collection_id = collection_of_submission.get(answer.submission_id)
        if collection_id is None:
            if _json_files(answer.files, "name") != []:
                invalid.append(
                    {
                        "domain": "collection_files",
                        "subject": f"答卷附件 #{answer.id}",
                        "reason": "附件所属答卷无法确定，已跳过收集目录的孤儿检查与清理",
                    }
                )
            continue
        add_json(
            "collection_files",
            answer.files,
            f"收集 #{collection_id}",
            "答卷附件",
            key="name",
            collection_id=collection_id,
        )

    # 上传凭证可一直等到活动结束。保护这些目录，覆盖先上传后提交和旧临时文件改名的窗口。
    cutoff = datetime.now() - timedelta(seconds=ORPHAN_MIN_AGE_SECONDS)
    active_collections = (
        query(Collection.id)
        .filter(
            Collection.closed_at.is_(None),
            Collection.end_at >= cutoff,
        )
        .all()
    )
    for (collection_id,) in active_collections:
        directory = COLLECTION_FILE_DIR / str(collection_id)
        if directory.is_dir() and not directory.is_symlink():
            refs["collection_files"].update(
                f"{collection_id}/{path.name}"
                for path in directory.iterdir()
                if path.is_file()
            )
    # 签到临时照片的文件名没有场次信息，活动上传窗口内保护整个签到目录。
    active_checkin = query(Checkin.id).filter(Checkin.end_at >= cutoff).first()
    if active_checkin and CHECKIN_DIR.is_dir():
        refs["checkins"].update(
            path.name for path in CHECKIN_DIR.iterdir() if path.is_file()
        )

    return refs, registry, invalid


def _protected_paths(refs: dict[str, set[str]]) -> set[Path]:
    # 配置中若有共用目录，任何业务的引用都要保护同一物理文件。
    return {
        (DOMAIN_BY_KEY[key].directory / name).resolve()
        for key, names in refs.items()
        for name in names
    }


def _blocked_domains(invalid: list[dict]) -> set[str]:
    roots = [DOMAIN_BY_KEY[item["domain"]].directory.resolve() for item in invalid]
    return {
        domain.key
        for domain in DOMAINS
        if any(
            domain.directory.resolve().is_relative_to(root)
            or root.is_relative_to(domain.directory.resolve())
            for root in roots
        )
    }


def _orphan_paths(domain: Domain, referenced: set[str], protected: set[Path]):
    """这个目录里没人认领的文件，返回 (路径, 相对路径, 扫描时的文件状态)

    recursive 的域（收集附件）会往下扫子目录，相对路径形如 `12/x.jpg`；
    单层目录的相对路径就是文件名。跳过隐藏文件和太新的（可能正在上传）。
    """
    if not domain.directory.exists():
        return
    cutoff = time.time() - ORPHAN_MIN_AGE_SECONDS
    iterator = (
        domain.directory.rglob("*") if domain.recursive else domain.directory.iterdir()
    )
    for path in sorted(iterator):
        if path.is_symlink() or not path.is_file() or path.name.startswith("."):
            continue
        if not path.resolve().is_relative_to(domain.directory.resolve()):
            continue
        rel = path.relative_to(domain.directory).as_posix()
        if any(
            part.startswith(".") for part in path.relative_to(domain.directory).parts
        ):
            continue
        if rel in referenced or path.resolve() in protected:
            continue
        try:
            # 刚写盘的文件先不动：可能正处在上传 → 入库之间的空档
            snapshot = path.stat()
            if snapshot.st_mtime > cutoff:
                continue
        except OSError:
            continue
        yield path, rel, snapshot


def _prune_empty_dirs(domain: Domain) -> None:
    """递归域里删完文件后，把空子目录顺手删掉

    只删**空**目录（rmdir 对非空会抛错，正好当保护），不会碰任何文件；
    目录本身留着，下次上传还要用。
    """
    if not domain.recursive or not domain.directory.exists():
        return
    for child in sorted(
        (
            p
            for p in domain.directory.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ),
        reverse=True,
    ):
        try:
            child.rmdir()
        except OSError:
            pass  # 还有别的文件 / 没权限：跳过


def check_files(db: Session) -> list[dict]:
    """文件类体检，返回与 data_health 同形状的卡片列表"""
    refs, registry, invalid = _collect(db)
    blocked = _blocked_domains(invalid)
    protected = _protected_paths(refs)
    groups = {
        key: {
            "key": key,
            "label": label,
            "level": "warn",
            "items": [],
            "can_cleanup": key == _FILE_ORPHAN,
        }
        for key, label in _GROUP_LABELS.items()
    }

    for issue in invalid:
        groups[_FILE_REFERENCE_INVALID]["items"].append(
            {
                "id": None,
                "student_no": None,
                "name": None,
                "file": None,
                "size": None,
                **issue,
            }
        )

    for item in registry:
        if not item["report"]:
            continue
        domain = DOMAIN_BY_KEY[item["domain"]]
        target = domain.directory / item["file"]
        if target.exists():
            continue
        groups[item["category"]]["items"].append(
            {
                "id": None,
                "student_no": None,
                "name": None,
                "subject": item["subject"],
                "reason": f"{item['label']}在服务器上找不到（{item['file']}）",
                "domain": item["domain"],
                "file": item["file"],
                "size": None,
            }
        )

    for domain in DOMAINS:
        if domain.key in blocked:
            continue
        for path, rel, _snapshot in _orphan_paths(domain, refs[domain.key], protected):
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            groups[_FILE_ORPHAN]["items"].append(
                {
                    "id": None,
                    "student_no": None,
                    "name": None,
                    "subject": f"{domain.label}：{rel}",
                    "reason": f"磁盘上有这个文件，但没有任何记录指向它（{human_size(size)}）",
                    "domain": domain.key,
                    "file": rel,
                    "size": size,
                }
            )

    groups[_SIGN_PHOTO]["items"].sort(key=lambda item: item["subject"] or "")
    groups[_FILE_MISSING]["items"].sort(key=lambda item: item["subject"] or "")
    groups[_FILE_ORPHAN]["items"].sort(
        key=lambda item: (item["domain"] or "", item["file"] or "")
    )
    return [group for group in groups.values() if group["items"]]


def cleanup_orphans(db: Session, domains: list[str] | None = None) -> dict:
    # 手动与自动回收共用锁和判定，使用独立会话读取当前引用，避免请求会话的旧缓存。
    with _CLEANUP_LOCK, Session(bind=db.get_bind()) as scan:
        if scan.get_bind().dialect.name == "sqlite":
            # 清理期间阻止新增或修改引用，消除扫描与删除之间的数据库竞态。
            scan.connection().exec_driver_sql("BEGIN IMMEDIATE")
        return _cleanup_orphans(scan, domains)


def _cleanup_orphans(db: Session, domains: list[str] | None = None) -> dict:
    """删掉孤儿文件，返回 {deleted, freed_bytes, failed, by_domain}

    **只删文件，不碰数据库。** 删之前重新算一遍引用：从体检到点「清理」之间
    可能刚有人上传并入库，拿前端的旧结果去删就是删活文件。
    domains 为空 = 所有目录；传了只处理名单里的（白名单之外的一律忽略）。
    """
    refs, _, invalid = _collect(db, lock=True)
    blocked = _blocked_domains(invalid)
    protected = _protected_paths(refs)
    wanted = set(domains) if domains else {domain.key for domain in DOMAINS}

    deleted = 0
    freed = 0
    failed = 0
    by_domain: list[dict] = []

    for domain in DOMAINS:
        if domain.key not in wanted or domain.key in blocked:
            continue
        count = 0
        bytes_freed = 0
        for path, _rel, snapshot in _orphan_paths(domain, refs[domain.key], protected):
            try:
                # 扫描后被替换、重新上传或移出目录的路径不参与删除。
                if path.is_symlink() or not path.resolve().is_relative_to(
                    domain.directory.resolve()
                ):
                    continue
                stat = path.stat()
                if (
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                    stat.st_size,
                ) != (
                    snapshot.st_dev,
                    snapshot.st_ino,
                    snapshot.st_mtime_ns,
                    snapshot.st_ctime_ns,
                    snapshot.st_size,
                ):
                    continue
                if stat.st_mtime > time.time() - ORPHAN_MIN_AGE_SECONDS:
                    continue
                size = stat.st_size
                path.unlink()
            except OSError:
                failed += 1
                continue
            count += 1
            bytes_freed += size
        _prune_empty_dirs(domain)
        if count:
            by_domain.append(
                {
                    "domain": domain.key,
                    "label": domain.label,
                    "deleted": count,
                    "freed_bytes": bytes_freed,
                }
            )
        deleted += count
        freed += bytes_freed

    return {
        "deleted": deleted,
        "freed_bytes": freed,
        "failed": failed,
        "by_domain": by_domain,
        "skipped_domains": sorted(blocked & wanted),
    }
