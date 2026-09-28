"""资料下载的数据库操作

之前的版本用代码里的 RESOURCE_CATALOG 数组维护清单，
这里提供同样的「按分类分组的列表」接口，只是数据源换成数据库。
对外的返回格式和之前一致，前端 Downloads 页面不用改。
"""

import os
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..models.resource import Resource

# 资料文件放在 data/downloads/ 下，和旧版一致
RESOURCE_DIR = BASE_DIR / "data" / "downloads"
RESOURCE_DIR.mkdir(parents=True, exist_ok=True)

# 下载接口 URL 前缀，旧版是 /api/resources/file，保持不变
URL_PREFIX = "/api/resources/file"


def download_name(row: Resource) -> str:
    """下载/预览时用的文件名：列表里显示什么名，存下来就叫什么名

    取展示名（name）而不是上传时的原始文件名：管理员在后台改名的目的就是让
    下载下来的文件叫这个名字。扩展名从磁盘文件名上取（存盘名是 UUID + 原扩展名），
    这样改名不会把文件类型改掉。

    name 可能已经被管理员连扩展名一起写了（「电动车承诺书.docx」），
    这时不再重复追加，否则会变成 x.docx.docx。
    """
    ext = Path(row.file_name).suffix
    if ext and row.name.lower().endswith(ext.lower()):
        return row.name
    return f"{row.name}{ext}"


def list_resources(db: Session) -> list[dict]:
    """按分类分组返回资料列表（旧版 RESOURCE_CATALOG 的形状）

    返回：[{"category": "徽章标志", "items": [{name, file, size, url}, ...]}, ...]
    前端 Downloads.vue 直接用。
    """
    rows = db.query(Resource).order_by(Resource.sort_order, Resource.id).all()
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for r in rows:
        if r.category not in groups:
            groups[r.category] = []
            order.append(r.category)
        file_path = RESOURCE_DIR / r.file_name
        size = file_path.stat().st_size if file_path.exists() else 0
        url = f"{URL_PREFIX}/{r.file_name}" if file_path.exists() else None
        groups[r.category].append({
            "id": r.id,
            "name": r.name,
            "file": r.file_name,
            # 前端存盘用的名字。file 是磁盘上的 UUID 名，直接拿它存盘就是
            # 一串乱码似的文件名 —— 别让前端自己拼，就这一处口径
            "download_name": download_name(r),
            "original_name": r.original_name,
            "size": size,
            "url": url,
            "category": r.category,
            "sort_order": r.sort_order,
        })
    return [{"category": cat, "items": groups[cat]} for cat in order]


def list_all(db: Session) -> list[Resource]:
    """管理员用的全量列表，不分组，按分类 + 排序"""
    return db.query(Resource).order_by(Resource.category, Resource.sort_order, Resource.id).all()


def get_resource(db: Session, resource_id: int) -> Resource | None:
    return db.query(Resource).filter(Resource.id == resource_id).first()


def get_by_file_name(db: Session, file_name: str) -> Resource | None:
    """按磁盘文件名查，用于下载接口的白名单校验"""
    safe_name = os.path.basename(file_name)
    return db.query(Resource).filter(Resource.file_name == safe_name).first()


def add_resource(
    db: Session,
    name: str,
    category: str,
    file_bytes: bytes,
    original_name: str,
) -> Resource:
    """新增资料：保存文件到磁盘 + 插一条数据库记录

    文件名用 UUID 前缀，防止路径穿越和重名覆盖。
    扩展名保留原始的，方便识别。
    """
    # 取原始扩展名，没有就留空
    ext = Path(original_name).suffix.lower()
    safe_disk_name = f"{uuid.uuid4().hex}{ext}"

    (RESOURCE_DIR / safe_disk_name).write_bytes(file_bytes)

    # 同一分类下新条目排最后
    max_sort = db.query(Resource).filter(Resource.category == category).count()

    row = Resource(
        name=name.strip(),
        file_name=safe_disk_name,
        original_name=original_name,
        category=category.strip(),
        sort_order=max_sort,
    )
    db.add(row)
    db.flush()
    return row


def update_resource(
    db: Session,
    resource_id: int,
    name: str | None = None,
    category: str | None = None,
) -> Resource | None:
    """修改资料的名称或分类"""
    row = get_resource(db, resource_id)
    if not row:
        return None
    if name is not None:
        row.name = name.strip()
    if category is not None:
        row.category = category.strip()
        # 换了分类，排到新分类的最后
        max_sort = db.query(Resource).filter(Resource.category == row.category).count()
        row.sort_order = max_sort
    db.flush()
    return row


def reorder_category(db: Session, category: str, id_order: list[int]) -> None:
    """重排某个分类内的条目顺序

    id_order 是按新顺序排列的资源 ID 列表。列表里没有的 ID 不动，
    排到最后（这是防御性的，正常不会出现）。
    """
    rows = db.query(Resource).filter(Resource.category == category).all()
    by_id = {r.id: r for r in rows}
    for idx, rid in enumerate(id_order):
        if rid in by_id:
            by_id[rid].sort_order = idx
            del by_id[rid]
    # 不在列表里的，塞到最后
    start = len(id_order)
    for i, row in enumerate(by_id.values()):
        row.sort_order = start + i


def delete_resource(db: Session, resource_id: int) -> bool:
    """删除资料：同时删磁盘文件和数据库记录

    顺序：先删文件、再删行。反过来的话，行删了文件还在就成了孤儿。
    """
    row = get_resource(db, resource_id)
    if not row:
        return False

    file_path = RESOURCE_DIR / row.file_name
    if file_path.exists():
        file_path.unlink()

    db.delete(row)
    db.flush()
    return True


def seed_from_catalog(db: Session, catalog: list[dict]) -> int:
    """从旧版 RESOURCE_CATALOG 导入初始数据

    只有当 resources 表完全为空时才导入，保证幂等。
    返回导入的条目数。
    """
    if db.query(Resource).count() > 0:
        return 0

    count = 0
    for group in catalog:
        category = group["category"]
        for idx, item in enumerate(group["items"]):
            # 旧版没有 original_name，就用显示名顶替
            db.add(Resource(
                name=item["name"],
                file_name=item["file"],
                original_name=item["name"] + Path(item["file"]).suffix,
                category=category,
                sort_order=idx,
            ))
            count += 1
    db.flush()
    return count
