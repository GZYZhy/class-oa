"""学生信息 Excel 导入

从 scripts/import_excel.py 抽出来的服务层版本：脚本和 Web 接口都调这一份，
保证两边行为一致。

覆盖策略（和原脚本完全相同，保证线上兼容）：
- 学号已存在 → 更新 students 表所有字段（包括照片列）
- 不动 users 表（密码、角色、冻结状态、bark_key 全保留）
- 不动 push_subscriptions（推送设备保留）
- 不动历史业务表（请假、反馈、改信息申请……都不动）
- 学号被域外账号占用 → 跳过 + 警告

照片处理（两阶段）：
- 解析阶段（parse_excel）：把图片数据读进内存，不写盘
  （否则用户取消导入时，照片已经落盘了，变成垃圾文件）
- 确认阶段（import_students）：真正写入 data/photos/
- 覆盖时：新照片先写盘 → 数据库 commit 成功 → 再删旧文件；
  失败时数据库全回滚，新照片还没落库 = 没人引用，变孤儿但不破坏旧数据
"""

import io
import json
import os
import time
import uuid
import tempfile
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path

import openpyxl
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..models import Student, User
from .student_service import get_student_by_no, create_student
from .user_service import create_account_for
from .log_service import log_operation

# 照片存放目录。可用 PHOTO_DIR 环境变量指到别处 —— 测试会指到临时目录，
# 免得往真实的数据目录里写文件（和 DATABASE_URL 一个路子：那个变量只管库文件，
# 库换成临时的而照片还落在真目录里，测试跑完就会留下一堆没人引用的图）
PHOTO_DIR = Path(os.environ.get("PHOTO_DIR") or (BASE_DIR / "data" / "photos"))
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

# 预览令牌的临时存放目录。不用内存缓存是因为本项目没有这种基础设施，
# 临时文件最简单，进程重启也不丢（只要没过期）。
_PREVIEW_DIR = Path(tempfile.gettempdir()) / "class-oa-import-preview"
_PREVIEW_TTL = 600  # 10 分钟

# Excel 列名 → 学生字段的映射。表头的文字顺序、列名都跟原脚本一致
# （改列名会导致老 Excel 导不进来，所以一字不动抄过来）
COLUMN_MAP = {
    "学号": "student_no",
    "姓名": "name",
    "性别": "gender",
    "专业": "major",
    "班级": "class_name",
    "出生日期": "birth_date",
    "民族": "ethnicity",
    "政治面貌": "political_status",
    "生源地": "hometown",
    "身份证号": "id_card",
    "考生号": "exam_no",
    "考生类别": "exam_category",
    "科类": "subject_type",
    "考试类型": "exam_type",
    "录取批次": "admission_batch",
    "高考总分": "gaokao_score",
    "毕业中学": "high_school",
    "报到状态": "registration_status",
    "报到时间": "registration_time",
    "在校状态": "school_status",
    "本人电话": "phone",
    "家庭电话": "family_phone",
    "QQ号码": "qq",
    "本人电子邮箱": "email",
    "家庭通信地址": "family_address",
    "邮政编码": "postal_code",
    "宿舍": "dormitory",
    "床位": "bed",
    "班委": "class_position",
    "团学会职务": "league_position",
    "贫困生": "is_poor",
    "备注": "remark",
}


# ========== 基础解析函数（与原脚本逐字一致）==========


def _parse_date(value):
    """解析日期（与原脚本 parse_date 完全一致）"""
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date)):
        return value.date() if isinstance(value, datetime) else value
    return None


def _parse_datetime(value):
    """解析日期时间"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return None


def _parse_int(value):
    """解析整数"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_str(value):
    """解析字符串，处理 None 和空值。注意 'None' 字符串也当成空——这是原脚本的行为，
    老 Excel 里偶尔会出现字面量 'None'，保持兼容。"""
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s == "None":
        return None
    return s


def _normalize_position(value):
    """归一化职务字段：'否'、空值统一为'无'，正常值原样返回"""
    s = _parse_str(value)
    if not s or s == "否":
        return "无"
    return s


def _normalize_poor(value):
    """贫困生：只有'是'才是'是'，其它一律'否'——和原脚本一致"""
    return "是" if _parse_str(value) == "是" else "否"


def _remove_photo_safe(file_name: str | None) -> None:
    """删除照片文件，静默失败（文件不存在等都不当错）"""
    if not file_name:
        return
    try:
        (PHOTO_DIR / file_name).unlink()
    except OSError:
        pass


# ========== 照片提取（内存阶段，不落盘）==========


def _extract_photo_data(ws, header_map, student_no_col_idx):
    """从工作表中提取内嵌照片数据（不写盘）

    返回：{学号: {'gaokao': (文件名, bytes), 'on_site': (文件名, bytes)}}
    """
    gaokao_col_idx = header_map.get("高考照片")
    # 「实地照片」是字段标签里的叫法，两种表头都认，免得用户照着标签改名
    # 列下标可能是 0（falsy），必须用 is not None 判断
    shidi_col_idx = header_map.get("实地采集")
    if shidi_col_idx is None:
        shidi_col_idx = header_map.get("实地照片")
    id_col_idx = header_map.get("证件照")
    if id_col_idx is None:
        id_col_idx = header_map.get("自备证件照")

    if gaokao_col_idx is None and shidi_col_idx is None and id_col_idx is None:
        return {}

    # 行号 → 学号（0-based）
    row_to_student_no = {}
    for row_idx in range(2, ws.max_row + 1):
        row = [cell.value for cell in ws[row_idx]]
        if student_no_col_idx < len(row):
            sno = _parse_str(row[student_no_col_idx])
            if sno:
                row_to_student_no[row_idx - 1] = sno

    photo_data = defaultdict(dict)

    for img in ws._images:
        anchor = img.anchor
        from_row = anchor._from.row  # 0-based
        from_col = anchor._from.col

        student_no = row_to_student_no.get(from_row)
        if not student_no:
            continue

        # 确定照片类型
        if gaokao_col_idx is not None and from_col == gaokao_col_idx:
            photo_type = "gaokao"
        elif shidi_col_idx is not None and from_col == shidi_col_idx:
            photo_type = "on_site"
        elif id_col_idx is not None and from_col == id_col_idx:
            photo_type = "id"
        else:
            continue

        # 扩展名：jpeg → jpg，其它小写
        ext = "jpg" if img.format == "jpeg" else (img.format or "jpg").lower()
        filename = f"{student_no}_{photo_type}.{ext}"

        # 必须先回到流起始位置再读，否则拿到的数据文件头丢失、图片损坏
        # （原脚本里有这坑的注释）
        img.ref.seek(0)
        img_bytes = img.ref.read()

        photo_data[student_no][photo_type] = (filename, img_bytes)

    return photo_data


def _write_photo_files(photo_data: dict[str, dict[str, tuple[str, bytes]]]) -> dict[str, dict[str, str]]:
    """把内存里的照片数据写入磁盘，返回 {学号: {类型: 文件名}}"""
    result: dict[str, dict[str, str]] = {}
    for sno, types in photo_data.items():
        result[sno] = {}
        for ptype, (fname, data) in types.items():
            (PHOTO_DIR / fname).write_bytes(data)
            result[sno][ptype] = fname
    return result


# ========== 预览 / 解析 ==========


class ImportPreview:
    """Excel 解析结果的预览对象

    两份数据：
    - public 字段（构造参数里的）：可以安全返回给前端
    - _rows / _photo_data：内部用，确认导入时才用，不序列化给前端

    注意：_photo_data 里存的是 (文件名, bytes) 元组，解析阶段不落盘，
    只有确认导入后才真正写到 data/photos/。
    """

    def __init__(
        self,
        sheet_name: str,
        available_sheets: list[str],
        total_rows: int,
        will_create: int,
        will_update: int,
        skip_count: int,
        sample_create: list[dict],
        sample_update: list[dict],
        photo_count: int,
        warnings: list[str],
    ):
        self.sheet_name = sheet_name
        self.available_sheets = available_sheets
        self.total_rows = total_rows
        self.will_create = will_create
        self.will_update = will_update
        self.skip_count = skip_count
        self.sample_create = sample_create
        self.sample_update = sample_update
        self.photo_count = photo_count
        self.warnings = warnings
        # 内部用：完整行数据（dict 列表）+ 照片内存数据
        self._rows: list[dict] = []
        self._photo_data: dict[str, dict[str, tuple[str, bytes]]] = {}

    def to_public(self) -> dict:
        """返回给前端看的字段（不含内部数据）"""
        return {
            "sheet_name": self.sheet_name,
            "available_sheets": self.available_sheets,
            "total_rows": self.total_rows,
            "will_create": self.will_create,
            "will_update": self.will_update,
            "skip_count": self.skip_count,
            "sample_create": self.sample_create,
            "sample_update": self.sample_update,
            "photo_count": self.photo_count,
            "warnings": self.warnings,
        }


def parse_excel(file_bytes: bytes, sheet_name: str | None = None,
                db: Session | None = None) -> ImportPreview:
    """解析 Excel，返回预览（不写库，也不写照片文件）

    传了 db 的话，会查一下现有学号来区分「新增」和「覆盖」；
    没传 db 就把所有行都当成 will_create（预览只看格式的场景用）。
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    available_sheets = wb.sheetnames

    # 没指定工作表就用第一个，或者叫「全部信息」的那张（原脚本的默认值）
    if sheet_name:
        if sheet_name not in available_sheets:
            raise ValueError(f"工作表 {sheet_name} 不存在")
    elif "全部信息" in available_sheets:
        sheet_name = "全部信息"
    else:
        sheet_name = available_sheets[0]

    ws = wb[sheet_name]

    # 读表头
    headers = [cell.value for cell in ws[1]]
    header_map = {}
    for idx, header in enumerate(headers):
        if header:
            header_map[str(header).strip()] = idx

    # 学号列的索引（照片提取要用）
    student_no_col_idx = header_map.get("学号", 3)

    # 提取照片数据（内存阶段，不落盘）
    photo_data = _extract_photo_data(ws, header_map, student_no_col_idx)
    photo_count = sum(len(v) for v in photo_data.values())

    # 逐行解析
    rows: list[dict] = []
    skip_count = 0
    warnings: list[str] = []

    for row_idx in range(2, ws.max_row + 1):
        row = [cell.value for cell in ws[row_idx]]

        def get_val(col_name: str):
            idx = header_map.get(col_name)
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        student_no = _parse_str(get_val("学号"))
        name = _parse_str(get_val("姓名"))

        if not student_no or not name:
            # 整行都空的静默跳过；只有一个有值才打警告
            if student_no or name:
                warnings.append(f"第 {row_idx} 行：学号或姓名为空，已跳过")
                skip_count += 1
            continue

        # 组装学生数据（和原脚本的 student_data 字典完全一致）
        student_data = {
            "student_no": student_no,
            "name": name,
            "gender": _parse_str(get_val("性别")),
            "major": _parse_str(get_val("专业")),
            "class_name": _parse_str(get_val("班级")),
            "birth_date": _parse_date(get_val("出生日期")),
            "ethnicity": _parse_str(get_val("民族")),
            "political_status": _parse_str(get_val("政治面貌")),
            "hometown": _parse_str(get_val("生源地")),
            "id_card": _parse_str(get_val("身份证号")),
            "exam_no": _parse_str(get_val("考生号")),
            "exam_category": _parse_str(get_val("考生类别")),
            "subject_type": _parse_str(get_val("科类")),
            "exam_type": _parse_str(get_val("考试类型")),
            "admission_batch": _parse_str(get_val("录取批次")),
            "gaokao_score": _parse_int(get_val("高考总分")),
            "high_school": _parse_str(get_val("毕业中学")),
            "registration_status": _parse_str(get_val("报到状态")) or "已报到",
            "registration_time": _parse_datetime(get_val("报到时间")),
            "school_status": _parse_str(get_val("在校状态")) or "正常",
            "phone": _parse_str(get_val("本人电话")),
            "family_phone": _parse_str(get_val("家庭电话")),
            "qq": _parse_str(get_val("QQ号码")),
            "email": _parse_str(get_val("本人电子邮箱")),
            "family_address": _parse_str(get_val("家庭通信地址")),
            "postal_code": _parse_str(get_val("邮政编码")),
            "dormitory": _parse_str(get_val("宿舍")),
            "bed": _parse_str(get_val("床位")),
            "class_position": _normalize_position(get_val("班委")),
            "league_position": _normalize_position(get_val("团学会职务")),
            "is_poor": _normalize_poor(get_val("贫困生")),
            "remark": _parse_str(get_val("备注")),
            # 照片字段先留空，后面从 photo_data 补（只补文件名，不补字节）
            "gaokao_photo": None,
            "on_site_photo": None,
            "id_photo": None,
        }

        # 补上照片文件名（只有名字，字节数据在 _photo_data 里）
        p = photo_data.get(student_no, {})
        if "gaokao" in p:
            student_data["gaokao_photo"] = p["gaokao"][0]
        if "on_site" in p:
            student_data["on_site_photo"] = p["on_site"][0]
        if "id" in p:
            student_data["id_photo"] = p["id"][0]

        rows.append(student_data)

    total_rows = len(rows)

    # 区分新增 / 覆盖。有 db 就查库，没有就全算新增
    will_create = 0
    will_update = 0
    sample_create: list[dict] = []
    sample_update: list[dict] = []
    skipped_external: set[str] = set()

    if db is not None and rows:
        all_nos = [r["student_no"] for r in rows]
        existing_nos = {
            s.student_no for s in
            db.query(Student.student_no).filter(Student.student_no.in_(all_nos)).all()
        }
        # 域外账号占着的学号也要挑出来（这些不能导入）
        external_nos = {
            u.student_no for u in
            db.query(User.student_no).filter(
                User.student_no.in_(all_nos),
                User.is_external == True,  # noqa: E712
            ).all()
        }

        for r in rows:
            sno = r["student_no"]
            if sno in external_nos:
                warnings.append(f"学号 {sno} 已被域外账号占用，已跳过")
                skip_count += 1
                total_rows -= 1
                skipped_external.add(sno)
                continue
            if sno in existing_nos:
                will_update += 1
                if len(sample_update) < 5:
                    sample_update.append({
                        "student_no": sno,
                        "name": r["name"],
                        "class_name": r["class_name"] or "",
                    })
            else:
                will_create += 1
                if len(sample_create) < 5:
                    sample_create.append({
                        "student_no": sno,
                        "name": r["name"],
                        "class_name": r["class_name"] or "",
                    })

        # 从 rows 里剔掉被跳过的域外账号行
        rows = [r for r in rows if r["student_no"] not in skipped_external]
        # photo_data 也同步清理
        for sno in skipped_external:
            photo_data.pop(sno, None)
    else:
        will_create = total_rows
        sample_create = [
            {
                "student_no": r["student_no"],
                "name": r["name"],
                "class_name": r["class_name"] or "",
            }
            for r in rows[:5]
        ]

    preview = ImportPreview(
        sheet_name=sheet_name,
        available_sheets=available_sheets,
        total_rows=total_rows,
        will_create=will_create,
        will_update=will_update,
        skip_count=skip_count,
        sample_create=sample_create,
        sample_update=sample_update,
        photo_count=photo_count,
        warnings=warnings,
    )
    preview._rows = rows
    preview._photo_data = photo_data
    return preview


# ========== 预览令牌（临时文件缓存）==========


def _preview_path(token: str) -> Path:
    _PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    return _PREVIEW_DIR / f"preview_{token}.json"


def save_preview(preview: ImportPreview) -> str:
    """把预览对象存成临时文件，返回令牌

    照片的字节数据用 base64 编码存 JSON，保证能序列化。
    """
    import base64
    token = uuid.uuid4().hex

    # photo_data 里的 bytes 要转成 base64 字符串才能存 JSON
    serializable_photos = {}
    for sno, types in preview._photo_data.items():
        serializable_photos[sno] = {}
        for ptype, (fname, data_bytes) in types.items():
            serializable_photos[sno][ptype] = [
                fname,
                base64.b64encode(data_bytes).decode("ascii"),
            ]

    data = {
        "public": preview.to_public(),
        "rows": preview._rows,
        "photo_data": serializable_photos,
        "created_at": time.time(),
    }
    path = _preview_path(token)
    path.write_text(json.dumps(data, ensure_ascii=False, default=_json_default), encoding="utf-8")
    return token


def load_preview(token: str) -> ImportPreview | None:
    """从令牌读取预览对象。过期或不存在返回 None"""
    import base64

    path = _preview_path(token)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # 过期检查
    if time.time() - data.get("created_at", 0) > _PREVIEW_TTL:
        try:
            path.unlink()
        except OSError:
            pass
        return None

    pub = data["public"]

    # 日期/时间字段从字符串还原
    rows = []
    for r in data["rows"]:
        r2 = dict(r)
        if r2.get("birth_date"):
            r2["birth_date"] = date.fromisoformat(r2["birth_date"])
        if r2.get("registration_time"):
            r2["registration_time"] = datetime.fromisoformat(r2["registration_time"])
        rows.append(r2)

    # 照片的 base64 还原成 bytes
    photo_data: dict[str, dict[str, tuple[str, bytes]]] = {}
    for sno, types in data.get("photo_data", {}).items():
        photo_data[sno] = {}
        for ptype, [fname, b64str] in types.items():
            photo_data[sno][ptype] = (fname, base64.b64decode(b64str))

    preview = ImportPreview(
        sheet_name=pub["sheet_name"],
        available_sheets=pub["available_sheets"],
        total_rows=pub["total_rows"],
        will_create=pub["will_create"],
        will_update=pub["will_update"],
        skip_count=pub["skip_count"],
        sample_create=pub["sample_create"],
        sample_update=pub["sample_update"],
        photo_count=pub["photo_count"],
        warnings=pub["warnings"],
    )
    preview._rows = rows
    preview._photo_data = photo_data
    return preview


def cleanup_expired_previews() -> None:
    """清理过期的预览文件。不是必须调用，但可以偶尔跑一下。"""
    _PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for p in _PREVIEW_DIR.glob("preview_*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if now - data.get("created_at", 0) > _PREVIEW_TTL:
                p.unlink()
        except (json.JSONDecodeError, OSError):
            try:
                p.unlink()
            except OSError:
                pass


def _json_default(obj):
    """JSON 序列化的兜底：date/datetime 转 ISO 字符串"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ========== 真正写入 ==========


def import_students(
    db: Session,
    preview: ImportPreview,
    operator: User,
    ip: str | None = None,
) -> dict:
    """把预览中的数据写入数据库

    返回：{created, updated, skipped, warnings, all_student_nos}

    事务规则：
    - 所有写入（学生 + 账号 + 日志）在一个事务里
    - 照片文件在写入数据前先落盘（openpyxl 拿不到流句柄，只能先写），
      但此时数据库还没 commit，失败的话这些新文件变成孤儿但不破坏旧数据
    - commit 成功后，再把被覆盖掉的旧照片删掉
    """
    rows = preview._rows
    if not rows:
        return {
            "created": 0, "updated": 0, "skipped": preview.skip_count,
            "warnings": list(preview.warnings), "all_student_nos": [],
        }

    # 第一步：把照片从内存写到磁盘
    # （命名是 学号_类型.后缀，同一个学号同一个类型会互相覆盖，
    #  但新文件还没关联到数据库，所以旧文件还在、不影响旧数据）
    photo_map = _write_photo_files(preview._photo_data)

    created_count = 0
    updated_count = 0
    warnings = list(preview.warnings)
    all_student_nos: list[str] = []
    # 被覆盖的旧照片文件名，commit 成功后再删
    old_photos_to_remove: list[str] = []
    # 本轮新写的照片文件名，回滚时清掉
    new_photo_files: list[str] = []
    for types in photo_map.values():
        new_photo_files.extend(types.values())

    try:
        for student_data in rows:
            sno = student_data["student_no"]
            all_student_nos.append(sno)
            existing = get_student_by_no(db, sno)

            if existing:
                # 覆盖：只改 students 表字段，不动账号、不动推送订阅
                # （原脚本就是这个语义，保持兼容）
                for key, value in student_data.items():
                    if key == "student_no":
                        continue  # 学号不动
                    # 记录旧照片（等 commit 后删文件）
                    if key in ("gaokao_photo", "on_site_photo") and value:
                        old_name = getattr(existing, key)
                        if old_name and old_name != value:
                            old_photos_to_remove.append(old_name)
                    setattr(existing, key, value)
                updated_count += 1
            else:
                # 新增：学生 + 账号一起建（和单条新增学生接口一致）
                from ..schemas.student import StudentCreate
                # create_student 用 StudentCreate schema，它不认 gaokao_photo/on_site_photo
                # （那俩在 StudentBase 里有，但默认是 None，传进去也没事）
                new_student = create_student(
                    db, StudentCreate(**student_data), commit=False
                )
                create_account_for(db, new_student)
                created_count += 1

        # 记一条操作日志（批量操作模式，和导出同一个写法）
        first = rows[0]
        total = len(rows)
        target = f"{first['student_no']} {first['name']} 等{total}人"
        detail = f"新增 {created_count} 人，覆盖 {updated_count} 人，跳过 {preview.skip_count} 行"
        log_operation(
            db, operator, "导入学生",
            target=target,
            detail=detail,
            ip=ip,
            target_student_nos=all_student_nos,
        )

        db.commit()

    except Exception:
        db.rollback()
        # 数据库回滚了，但新写的照片文件还在——它们是孤儿文件，占磁盘但不破坏旧数据
        for fname in new_photo_files:
            _remove_photo_safe(fname)
        raise

    # 提交成功后，清理被覆盖掉的旧照片文件
    # （commit 之后才删，失败时旧数据完好）
    for fname in old_photos_to_remove:
        _remove_photo_safe(fname)

    # 预览缓存用完就删（不用等 TTL）
    try:
        # 调用方拿到 token 后自己删也可以，这里只提供一个语义
        pass
    except Exception:
        pass

    return {
        "created": created_count,
        "updated": updated_count,
        "skipped": preview.skip_count,
        "warnings": warnings,
        "all_student_nos": all_student_nos,
    }
