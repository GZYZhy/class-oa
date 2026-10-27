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
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..models import (
    Announcement,
    CertificateRequest,
    CheckinTarget,
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

_GROUP_LABELS = {
    _SIGN_PHOTO: "签字图",
    _FILE_MISSING: "文件丢失",
    _FILE_ORPHAN: "孤儿文件",
}


def _json_files(raw: str | None, key: str = "file") -> list[str]:
    """附件 JSON（[{"file": "...", "name": "..."}]）→ 文件名列表

    收集答卷的图片用的是 `name` 键（见 CollectionAnswer.files），所以键名可传。
    解析不了就当没有附件：体检不该因为一条历史脏 JSON 整页 500
    """
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    return [
        str(item.get(key) or "")
        for item in items
        if isinstance(item, dict) and item.get(key)
    ]


def _base_name(name: str | None) -> str:
    """库里存的可能是裸文件名，也可能带目录/URL 前缀，统一取最后一段

    公告的 file_path 存的是 `/api/announcements/file/xxx.pdf`，
    老数据的照片有存成 `/static/photos/xxx.jpg` 的 —— 两边口径都在这里归一。
    """
    return os.path.basename(str(name or "").strip())


def _user_label(user: User) -> str:
    return (user.display_name or user.student_no or "").strip()


def _collect(db: Session) -> tuple[dict[str, set[str]], list[dict]]:
    """扫一遍数据库，返回（各目录被引用的文件名, 登记项清单）

    登记项用于「文件丢了」检查，字段：
      category      sign_photo / file_missing
      domain        属于哪个目录
      file          文件名
      subject       给人看的对象说明
      label         这是什么东西（高考照片 / 辅助证明 / 成品 PDF）
      report        False 表示缺失由别的卡片负责（学生三照由「照片」卡片报）
    """
    refs: dict[str, set[str]] = {domain.key: set() for domain in DOMAINS}
    registry: list[dict] = []

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
        registry.append({
            "category": category,
            "domain": domain,
            "file": relative,
            "subject": subject,
            "label": label,
            "report": report,
        })

    for student in db.query(Student).order_by(Student.student_no).all():
        subject = f"{student.name}（{student.student_no}）"
        for prop, label in _STUDENT_PHOTO_PROPS:
            add(
                "photos", getattr(student, prop, None), subject, label,
                report=False,  # 由「照片」卡片负责，避免重复
            )
        add(
            "photos", student.sign_photo, subject, "签字图",
            category=_SIGN_PHOTO,
        )
        for name in _json_files(student.remark_attachments):
            add("remark_attachments", name, subject, "备注附件")

    # 域外账号：头像和签字图各在一个目录
    for user in db.query(User).all():
        if not (user.avatar or user.sign_photo):
            continue
        subject = f"账号 {_user_label(user)}"
        add("avatars", user.avatar, subject, "头像")
        add(
            "photos", user.sign_photo, subject, "签字图",
            category=_SIGN_PHOTO,
        )

    for row in db.query(Announcement).all():
        add("announcements", row.file_path, f"公告「{row.title}」", "PDF")

    for row in db.query(Resource).all():
        add("resources", row.file_name, f"资料「{row.name}」", "文件")

    for row in db.query(LeaveRequest).all():
        subject = f"请假申请 #{row.id}"
        add("leaves", row.proof_file, subject, "辅助证明")
        add("leaves", row.advisor_sign_file, subject, "班导师签字图")

    for row in db.query(EvPassRequest).all():
        subject = f"电动车通行证 #{row.id}"
        add("ev_passes", row.license_file, subject, "行驶证")
        add("ev_passes", row.sign_file, subject, "经办班委签字图")

    for row in db.query(CertificateRequest).all():
        subject = f"证明开具 #{row.id}"
        for name in _json_files(row.attachments):
            add("cert_attachments", name, subject, "申请附件")
        add("cert_results", row.result_file, subject, "成品 PDF")

    for row in db.query(CheckinTarget).all():
        add("checkins", row.photo_file, f"签到 #{row.checkin_id}", "签到照片")

    for row in db.query(Notice).all():
        subject = f"通知「{row.title}」"
        for name in _json_files(row.attachments):
            add("notices", name, subject, "附件")

    for row in db.query(Feedback).all():
        for name in _json_files(row.attachments):
            add("feedbacks", name, f"意见反馈 #{row.id}", "附件")

    for row in db.query(ExportRequest).all():
        add("exports", row.file_name, f"导出申请 #{row.id}", "导出文件")

    # 收集的答卷图片：目录是 collection_files/{collection_id}/，
    # 所以要顺着 answer → submission 拿到收集 ID，按相对路径比对
    collection_of_submission = {
        row.id: row.collection_id for row in db.query(CollectionSubmission).all()
    }
    for answer in db.query(CollectionAnswer).all():
        collection_id = collection_of_submission.get(answer.submission_id)
        if collection_id is None:
            continue
        for name in _json_files(answer.files, "name"):
            add(
                "collection_files", name, f"收集 #{collection_id}", "答卷图片",
                rel=f"{collection_id}/{_base_name(name)}",
            )

    return refs, registry


def _orphan_paths(domain: Domain, referenced: set[str]):
    """这个目录里没人认领的文件，返回 (路径, 相对路径)

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
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = path.relative_to(domain.directory).as_posix()
        if rel in referenced:
            continue
        try:
            # 刚写盘的文件先不动：可能正处在上传 → 入库之间的空档
            if path.stat().st_mtime > cutoff:
                continue
        except OSError:
            continue
        yield path, rel


def _prune_empty_dirs(domain: Domain) -> None:
    """递归域里删完文件后，把空子目录顺手删掉

    只删**空**目录（rmdir 对非空会抛错，正好当保护），不会碰任何文件；
    目录本身留着，下次上传还要用。
    """
    if not domain.recursive or not domain.directory.exists():
        return
    for child in sorted(
        (p for p in domain.directory.iterdir() if p.is_dir() and not p.name.startswith(".")),
        reverse=True,
    ):
        try:
            child.rmdir()
        except OSError:
            pass  # 还有别的文件 / 没权限：跳过


def check_files(db: Session) -> list[dict]:
    """文件类体检，返回与 data_health 同形状的卡片列表"""
    refs, registry = _collect(db)
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

    for item in registry:
        if not item["report"]:
            continue
        domain = DOMAIN_BY_KEY[item["domain"]]
        target = domain.directory / item["file"]
        if target.exists():
            continue
        groups[item["category"]]["items"].append({
            "id": None,
            "student_no": None,
            "name": None,
            "subject": item["subject"],
            "reason": f"{item['label']}在服务器上找不到（{item['file']}）",
            "domain": item["domain"],
            "file": item["file"],
            "size": None,
        })

    for domain in DOMAINS:
        for path, rel in _orphan_paths(domain, refs[domain.key]):
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            groups[_FILE_ORPHAN]["items"].append({
                "id": None,
                "student_no": None,
                "name": None,
                "subject": f"{domain.label}：{rel}",
                "reason": f"磁盘上有这个文件，但没有任何记录指向它（{human_size(size)}）",
                "domain": domain.key,
                "file": rel,
                "size": size,
            })

    groups[_SIGN_PHOTO]["items"].sort(key=lambda item: item["subject"] or "")
    groups[_FILE_MISSING]["items"].sort(key=lambda item: item["subject"] or "")
    groups[_FILE_ORPHAN]["items"].sort(
        key=lambda item: (item["domain"] or "", item["file"] or "")
    )
    return [group for group in groups.values() if group["items"]]


def cleanup_orphans(db: Session, domains: list[str] | None = None) -> dict:
    """删掉孤儿文件，返回 {deleted, freed_bytes, failed, by_domain}

    **只删文件，不碰数据库。** 删之前重新算一遍引用：从体检到点「清理」之间
    可能刚有人上传并入库，拿前端的旧结果去删就是删活文件。
    domains 为空 = 所有目录；传了只处理名单里的（白名单之外的一律忽略）。
    """
    refs, _ = _collect(db)
    wanted = set(domains) if domains else {domain.key for domain in DOMAINS}

    deleted = 0
    freed = 0
    failed = 0
    by_domain: list[dict] = []

    for domain in DOMAINS:
        if domain.key not in wanted:
            continue
        count = 0
        bytes_freed = 0
        for path, _rel in _orphan_paths(domain, refs[domain.key]):
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError:
                failed += 1
                continue
            count += 1
            bytes_freed += size
        _prune_empty_dirs(domain)
        if count:
            by_domain.append({
                "domain": domain.key,
                "label": domain.label,
                "deleted": count,
                "freed_bytes": bytes_freed,
            })
        deleted += count
        freed += bytes_freed

    return {
        "deleted": deleted,
        "freed_bytes": freed,
        "failed": failed,
        "by_domain": by_domain,
    }
