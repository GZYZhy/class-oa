"""学生照片批量导入（zip）

班委收照片的真实形态是：学生各自交一张，文件名五花八门，打包成一个 zip 发过来。
Excel 那条导入链路也支持照片，但它要求照片嵌在单元格里，套不上这个场景。

三条约定：

- **zip 只读字节，绝不 extractall**：路径穿越（`a/../../evil.jpg`）因此天然不存在，
  zip 里的子目录也不影响匹配（只看文件名）
- 预览不落盘也不读字节：只看 zip 清单里的文件名和声明大小，够下结论了；
  真正读字节是确认那一步
- 覆盖时：新文件先写盘 → commit 成功 → 再删旧文件。失败时数据库全回滚，
  新文件还没落库 = 没人引用（最多是个孤儿），旧数据完好
"""

import os
import re
import tempfile
import time
import uuid
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..models import Student
from ..utils.media_type import guess_media_type
from .log_service import log_operation
from .student_import_service import PHOTO_DIR, _remove_photo_safe

# 照片域的三条规则（后缀白名单 / 大小上限 / 类型→列名）放在这一份里，
# 单张上传（api/students.py）和批量导入共用 —— 各写一份的话，加个 .heic
# 很容易只改了其中一边
ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB，手机拍的实地采集照片也不会更大
# 随学生一起下发的三种照片。api/students.py 的通用照片接口（GET /{id}/photo）
# 只认这三种，权限是「能看这个学生就能看他的照片」
PHOTO_FIELDS = {
    "gaokao": "gaokao_photo",
    "on_site": "on_site_photo",
    "id": "id_photo",
}
# 打包导入（zip）认的四种。签字图也在其中 —— 导入是管理员的动作，跟照片没有区别，
# 都是往 students 的某个列里写一个文件名。但**取图**不能走通用照片接口：
# 签字要凭管理员审批（见 api/sign_photos.py），所以它不在上面的 PHOTO_FIELDS 里，
# 于是 GET /{id}/photo?type=sign 天然报「未知的照片类型」
IMPORT_PHOTO_FIELDS = {**PHOTO_FIELDS, "sign": "sign_photo"}
PHOTO_TYPE_LABELS = {
    "gaokao": "高考照片",
    "on_site": "实地采集照片",
    "id": "自备证件照",
    "sign": "签字图",
}


# ========== 单张：落盘 / 删除 / 取回 ==========
# 单张上传（改学生信息、提交修改申请）、取图、清理三处共用这几个工具。
# 各写一份的话，「防路径穿越」这种必须处处都对的判断迟早会漏掉一处


def save_photo(file: UploadFile) -> str:
    """把上传的照片写到磁盘，返回裸文件名（库里只存文件名，不存路径）

    抛 ValueError，文案是直接给用户看的，调用方原样转成 400（和 preview 一个路子）。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        raise ValueError(f"照片只支持 {_allowed_text()} 格式")

    content = file.file.read()
    if not content:
        raise ValueError("上传的文件是空的")
    if len(content) > MAX_PHOTO_SIZE:
        raise ValueError(f"照片不能超过 {MAX_PHOTO_SIZE // 1024 // 1024}MB")

    # 随机文件名：库里只认这个名字，于是别人就算知道学号也拼不出这个文件名
    safe_name = f"{uuid.uuid4().hex}{ext}"
    (PHOTO_DIR / safe_name).write_bytes(content)
    return safe_name


def remove_photo(file_name: str | None) -> None:
    """删照片文件。文件已经不在了也不报错（手工清理过、换过盘都可能）"""
    if not file_name:
        return
    try:
        (PHOTO_DIR / os.path.basename(file_name)).unlink(missing_ok=True)
    except OSError:
        pass


def photo_path(file_name: str) -> Path:
    """文件名 → 磁盘路径。**只取文件名部分**，于是拼进路径也穿越不出去"""
    return PHOTO_DIR / os.path.basename(file_name)


def photo_response(file_name: str, cache: str = "private, max-age=31536000") -> FileResponse:
    """文件名 → FileResponse；存在性由调用方先判（它才知道该报哪种 404）

    照片是在 <img> 里内联显示的（StudentList.vue），类型会真的被用上。
    统一交给 guess_media_type —— 它认识白名单里的全部后缀，而原先那句
    「非 png 一律当 jpeg」会把白名单里的 gif / bmp / webp 也标成 image/jpeg。

    cache 由调用方给：地址里带文件名做版本号时可以缓存一年（换照片后文件名变、
    地址跟着变）；而地址不变、图会变的那种（待审照片的「原图」）必须 no-store。
    """
    path = photo_path(file_name)
    return FileResponse(
        str(path),
        media_type=guess_media_type(path.name),
        headers={"Cache-Control": cache},
    )


def sign_photo_path(student: Student) -> Path | None:
    """某学生的签字图磁盘路径；没传过签字返回 None

    **办件将来要往 Word 里插签字时调这个**（python-docx 的 add_picture 收路径），
    别自己去拼 PHOTO_DIR —— 这个函数顺带复用了 photo_path 的防路径穿越。
    文件在不在由调用方判（exists），这里只管「库里那条记录指向哪个文件」。
    """
    return photo_path(student.sign_photo) if student.sign_photo else None


# 待确认的 zip 放临时目录，10 分钟过期。文件名带 photos_ 前缀，于是客户端
# 回传的 token 就算写成「../../x」也只会落在这一层里（"photos_.." 是个普通
# 目录名，不是上一级）；下面的正则再兜一道，免得以后有人改了命名规则
_ZIP_DIR = Path(tempfile.gettempdir()) / "class-oa-photo-preview"
_ZIP_TTL = 600
_TOKEN_RE = re.compile(r"[0-9a-f]{32}")

# zip 炸弹防护：先看清单里声明的大小，超了连读都不读
_MAX_ENTRIES = 500
_MAX_TOTAL_SIZE = 500 * 1024 * 1024


def _allowed_text() -> str:
    return " / ".join(sorted(e.lstrip(".") for e in ALLOWED_PHOTO_EXTENSIONS))


def _is_junk(name: str) -> bool:
    """zip 里的系统垃圾：macOS 的 __MACOSX/._xx 资源分叉、Windows 的 Thumbs.db"""
    base = Path(name).name
    return name.startswith("__MACOSX/") or base.startswith("._") or base in (".DS_Store", "Thumbs.db")


def _index(students: list[Student]) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """建匹配用的索引：学号（长的在前）、唯一的姓名→学号、学号→姓名"""
    by_no = sorted((s.student_no for s in students), key=len, reverse=True)
    name_count = Counter(s.name for s in students)
    by_name = {s.name: s.student_no for s in students if name_count[s.name] == 1}
    names = {s.student_no: s.name for s in students}
    return by_no, by_name, names


def _match_student(stem: str, by_no: list[str], by_name: dict[str, str]) -> str | None:
    """从文件名猜这是谁的照片，猜不出返回 None

    两条规则，命中即止：
    1. 文件名里含某个学号 —— 按学号**从长到短**比，「2023」这种短学号
       抢不走本来属于 20230001 的照片
    2. 去掉扩展名后与学生姓名一模一样，且这个姓名在班里唯一；重名的一律不猜
       （宁可让人工指认，也不能把张伟的照片安到另一个张伟头上）
    """
    for no in by_no:
        if no in stem:
            return no
    return by_name.get(stem.strip())


def _verdicts(infos: list[zipfile.ZipInfo], students: list[Student], photo_type: str) -> list[dict]:
    """给 zip 里的每个成员一个结论（不读字节）"""
    by_no, by_name, names = _index(students)
    field = IMPORT_PHOTO_FIELDS[photo_type]
    existing = {s.student_no: bool(getattr(s, field)) for s in students}

    items = []
    for info in infos:
        raw, base = info.filename, Path(info.filename).name
        item = {
            "raw_name": raw,          # 前端手工指认时按这个回传（basename 可能在子目录里重名）
            "filename": base,
            "size": info.file_size,
            "student_no": None,
            "student_name": None,
            "has_photo": False,
            "status": "ok",
            "reason": "",
        }
        items.append(item)

        if info.is_dir() or _is_junk(raw):
            item["status"], item["reason"] = "ignored", "系统隐藏文件"
            continue

        ext = Path(base).suffix.lower()
        if ext not in ALLOWED_PHOTO_EXTENSIONS:
            item["status"] = "unsupported"
            item["reason"] = (
                "iPhone 拍的 HEIC 要先转成 JPG" if ext == ".heic" else f"只支持 {_allowed_text()} 格式"
            )
            continue

        if info.file_size > MAX_PHOTO_SIZE:
            item["status"] = "too_large"
            item["reason"] = f"超过 {MAX_PHOTO_SIZE // 1024 // 1024}MB"
            continue

        no = _match_student(Path(base).stem, by_no, by_name)
        if not no:
            item["status"] = "unmatched"
            item["reason"] = "文件名里既没有学号，也不是学生姓名"
            continue

        item["student_no"] = no
        item["student_name"] = names.get(no)
        item["has_photo"] = existing.get(no, False)

    # 一个学生在这个类型上有多张：无法判断用哪张，全标成冲突交给人工
    same = Counter(i["student_no"] for i in items if i["status"] == "ok")
    for item in items:
        if item["status"] == "ok" and same[item["student_no"]] > 1:
            item["status"] = "conflict"
            item["reason"] = f"这个学生有 {same[item['student_no']]} 张，请改名后重传"
    return items


def preview(content: bytes, students: list[Student], photo_type: str) -> dict:
    """解析 zip 并逐张给结论；不写库、不写文件

    不合法（不是 zip、太大、太多）抛 ValueError，由接口层转成 400。
    """
    infos = _open_zip(content)
    items = _verdicts(infos, students, photo_type)
    counts = Counter(item["status"] for item in items)
    return {
        "total": len(items),
        "counts": dict(counts),
        "will_overwrite": sum(1 for i in items if i["status"] == "ok" and i["has_photo"]),
        "items": items,
    }


def _open_zip(content: bytes) -> list[zipfile.ZipInfo]:
    """打开 zip 只取清单，并做数量 / 体积两道闸"""
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile:
        raise ValueError("这不是一个有效的 zip 文件")

    if not infos:
        raise ValueError("zip 里没有文件")
    if len(infos) > _MAX_ENTRIES:
        raise ValueError(f"zip 里文件太多（{len(infos)} 个），一次最多 {_MAX_ENTRIES} 个")
    # 声明大小是可以造假的，所以这只是前置闸门；真读出来的字节在下面还会再量一次
    if sum(i.file_size for i in infos) > _MAX_TOTAL_SIZE:
        raise ValueError("zip 解压后体积过大，请分几次上传")
    return infos


def apply(
    db: Session, content: bytes, students: list[Student], photo_type: str,
    overwrite: bool, manual: dict[str, str], operator, ip: str | None = None,
) -> dict:
    """真正落盘并写库

    不信任前端带回来的预览结论，只认 zip：进来先按同一套规则重算一遍。
    预览到确认之间名单可能变了（有人被删档），重算自然跟着变，
    不会把照片写到已经不存在的学生身上。
    """
    infos = _open_zip(content)
    items = _verdicts(infos, students, photo_type)
    by_no = {s.student_no: s for s in students}
    field = IMPORT_PHOTO_FIELDS[photo_type]

    # 人工指认覆盖自动结论。不支持的格式和超大的那条改不了 —— 那不是「认错了人」，
    # 是这张图根本用不了
    by_raw = {i["raw_name"]: i for i in items}
    for raw, no in (manual or {}).items():
        item, student = by_raw.get(raw), by_no.get(no)
        if not item or not student:
            continue
        if item["status"] in ("unsupported", "too_large", "ignored"):
            continue
        item.update(
            status="ok", student_no=no, student_name=student.name,
            has_photo=bool(getattr(student, field)), reason="",
        )

    # 指认之后可能又撞车（两个文件被指给同一个人），按同一套规则再判一次
    same = Counter(i["student_no"] for i in items if i["status"] == "ok")
    for item in items:
        if item["status"] == "ok" and same[item["student_no"]] > 1:
            item["status"] = "conflict"
            item["reason"] = f"这个学生有 {same[item['student_no']]} 张，请改名后重传"

    saved, overwritten, skipped, failed = 0, 0, 0, []
    written: list[str] = []      # 这次新写的文件名，commit 失败要删掉
    old_files: list[str] = []    # commit 成功后才删的旧文件
    changed_nos: list[str] = []

    # 按 ZipInfo 读而不是按文件名读：zip 里同名成员是合法的，按名字读会读错那张
    with zipfile.ZipFile(BytesIO(content)) as zf:
        for info, item in zip(infos, items):
            if item["status"] != "ok":
                continue
            if item["has_photo"] and not overwrite:
                skipped += 1
                continue

            try:
                data = zf.read(info)
            except Exception as e:  # 加密条目、压缩数据损坏等
                failed.append(f"{item['filename']}：读取失败（{e}）")
                continue
            # 清单里声明的大小可以造假，这里量真字节
            if len(data) > MAX_PHOTO_SIZE:
                failed.append(f"{item['filename']}：超过 {MAX_PHOTO_SIZE // 1024 // 1024}MB")
                continue

            student = by_no[item["student_no"]]
            # 命名与 Excel 导入保持一致：{学号}_{类型}.{后缀}
            # 同一个学生同一个类型再导一次就是同一个名字，等于原地覆盖 ——
            # 此时旧文件就是它自己，不用（也不能）事后去删
            fname = f"{student.student_no}_{photo_type}{Path(item['filename']).suffix.lower()}"
            (PHOTO_DIR / fname).write_bytes(data)

            old = getattr(student, field)
            if old and old != fname:
                old_files.append(old)
                overwritten += 1
            setattr(student, field, fname)
            written.append(fname)
            changed_nos.append(student.student_no)
            saved += 1

    log_operation(
        db, operator, "批量导入照片",
        target=PHOTO_TYPE_LABELS[photo_type],
        detail=(
            f"写入 {saved} 张（覆盖 {overwritten} 张），"
            f"跳过 {skipped} 张（已有照片），失败 {len(failed)} 张"
        ),
        ip=ip,
        target_student_nos=changed_nos,
    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        # 数据库回滚了，新写的文件成了孤儿：占磁盘但没人引用，删掉即可
        for name in written:
            _remove_photo_safe(name)
        raise

    # 提交成功之后才删旧文件（失败时旧数据完好）
    for name in old_files:
        _remove_photo_safe(name)

    return {
        "saved": saved,
        "overwritten": overwritten,
        "skipped_exists": skipped,
        "failed": failed,
        "message": f"已写入 {saved} 张照片" + (f"，其中覆盖 {overwritten} 张" if overwritten else ""),
    }


# ========== 预览令牌（临时 zip 文件）==========


def _zip_path(token: str, photo_type: str) -> Path:
    """token + 类型 → 临时 zip 路径；不是我们发的那种就返回一个不存在的路径

    类型也进文件名，于是拿高考照片的 token 去导实地采集时会找不到文件 ——
    比默默按另一个类型导进去要好。
    """
    if not _TOKEN_RE.fullmatch(token or "") or photo_type not in IMPORT_PHOTO_FIELDS:
        return _ZIP_DIR / "invalid"
    return _ZIP_DIR / f"photos_{photo_type}_{token}.zip"


def save_zip(content: bytes, photo_type: str) -> str:
    """把上传的 zip 存进临时目录，返回 token

    照片体积大，不像 Excel 那套把文件塞成 base64 存 JSON —— 原样落盘更简单，
    确认时读回来直接就是 zip 字节。
    """
    _cleanup()
    _ZIP_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    _zip_path(token, photo_type).write_bytes(content)
    return token


def load_zip(token: str, photo_type: str) -> bytes | None:
    """按 token 取回 zip 字节；不存在或过期返回 None"""
    _cleanup()
    path = _zip_path(token, photo_type)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > _ZIP_TTL:
        _unlink(path)
        return None
    return path.read_bytes()


def drop_zip(token: str, photo_type: str) -> None:
    """用完就删，不用等 TTL"""
    _unlink(_zip_path(token, photo_type))


def _cleanup() -> None:
    """顺手清掉过期的临时 zip

    按修改时间判过期，不去解析内容 —— 这里躺的是二进制，按 JSON 那套读进来
    会当场抛 UnicodeDecodeError，把清理函数整个打崩。
    """
    if not _ZIP_DIR.exists():
        return
    now = time.time()
    for p in _ZIP_DIR.glob("photos_*.zip"):
        try:
            if now - p.stat().st_mtime > _ZIP_TTL:
                _unlink(p)
        except OSError:
            pass


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
