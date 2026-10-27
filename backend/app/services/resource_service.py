"""资料下载的数据库操作

之前的版本用代码里的 RESOURCE_CATALOG 数组维护清单，
这里提供同样的「按分类分组的列表」接口，只是数据源换成数据库。
对外的返回格式和之前一致，前端 Downloads 页面不用改。
"""

import os
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..models.resource import Resource, ResourceCategory
from ..models.resource_share import ResourceShareLink

# 资料文件放在 data/downloads/ 下，和旧版一致。
# 吃环境变量是为了测试能指到临时目录去 —— 不吃的话用例一上传资料就写进
# 真实数据目录，而且事后没人清得掉（照 PHOTO_DIR / LEAVE_DIR / 公告目录的先例）
RESOURCE_DIR = Path(os.environ.get("RESOURCE_DIR") or (BASE_DIR / "data" / "downloads"))
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

    扩展名优先从磁盘名取；磁盘名没有（上传时浏览器没给原始文件名，存成了光秃秃的
    UUID）就退回上传时的原始名。再取不到就只能是个没有后缀的名字，
    客户端会按 Content-Type 自己补一个 —— 那种情况下 media_type 更不能给错。
    """
    ext = Path(row.file_name).suffix or Path(row.original_name or "").suffix
    if ext and row.name.lower().endswith(ext.lower()):
        return row.name
    return f"{row.name}{ext}"


def _ordered_categories(db: Session, categories: list[str]) -> list[str]:
    """按管理员设置的顺序排列分类

    categories 是「默认顺序」（按分类里最靠前那条资料的 sort_order / id 撞出来的）。
    没设置过顺序的分类排在已设置的后面，彼此之间保持默认顺序 —— 新出现的分类
    自然落到末尾，管理员再决定往哪挪。
    """
    rank = {
        row.name: row.sort_order
        for row in db.query(ResourceCategory)
        .filter(ResourceCategory.name.in_(categories))
        .all()
    }
    return sorted(categories, key=lambda name: rank.get(name, float("inf")))


def list_resources(db: Session) -> list[dict]:
    """按分类分组返回资料列表（旧版 RESOURCE_CATALOG 的形状）

    返回：[{"category": "徽章标志", "items": [{name, file, size, url}, ...]}, ...]
    分类之间的先后由管理员设置（resource_categories），分类内部按 sort_order。
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
            "download_count": r.download_count or 0,
        })
    return [{"category": cat, "items": groups[cat]}
            for cat in _ordered_categories(db, order)]


def list_all(db: Session) -> list[Resource]:
    """管理员用的全量列表，不分组，按分类展示顺序 + 分类内排序

    后台是按这个顺序分组的，所以这里也得跟 Downloads 页面一个口径 ——
    否则管理员在后台调了分类顺序，前台变了、后台没变，看着像没保存。
    """
    rows = db.query(Resource).order_by(Resource.sort_order, Resource.id).all()
    categories: list[str] = []
    for row in rows:
        if row.category not in categories:
            categories.append(row.category)
    index = {name: i for i, name in enumerate(_ordered_categories(db, categories))}
    return sorted(rows, key=lambda row: (index[row.category], row.sort_order, row.id))


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


def reorder_categories(db: Session, order: list[str]) -> None:
    """按给定顺序记录分类的展示顺序

    order 是分类名列表，顺序即显示顺序。没列出来的分类排到后面（正常不会发生：
    前端每次都会把当前所有分类整个发上来）。
    """
    existing = {row.name: row for row in db.query(ResourceCategory).all()}
    for idx, name in enumerate(order):
        row = existing.get(name)
        if row is None:
            db.add(ResourceCategory(name=name, sort_order=idx))
        else:
            row.sort_order = idx
    # 已有记录里没被本次列表覆盖的，按原顺序接在后面
    rest = sorted(
        (row for name, row in existing.items() if name not in order),
        key=lambda row: (row.sort_order, row.id),
    )
    for i, row in enumerate(rest, start=len(order)):
        row.sort_order = i
    db.flush()


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

    # 资料没了，指向它的外链自然也该消失：留着只会变成一个点开就失效的死链，
    # 还会在管理员的「分享外链」列表里占一行
    db.query(ResourceShareLink).filter(
        ResourceShareLink.resource_id == row.id
    ).delete(synchronize_session=False)

    db.delete(row)
    db.flush()
    return True


# ==================== 分享外链 ====================

# 有效期四档（天）。0 = 永久，前端的单选项和这里一一对应
SHARE_DAY_CHOICES = (1, 7, 30, 0)
SHARE_DAY_LABELS = {1: "1 天", 7: "7 天", 30: "30 天", 0: "永久"}

SHARE_STATUS_VALID = "valid"
SHARE_STATUS_EXPIRED = "expired"
SHARE_STATUS_REVOKED = "revoked"
SHARE_STATUS_MISSING = "missing"  # 链接不存在，或资料/文件已被删掉


def new_share_token(db: Session) -> str:
    """12 位 URL 安全随机串。够长，猜不到；撞了换一个，最多试 5 次

    不用投票/收集那套「id + HMAC 签名」：签名串没法按条吊销 ——
    换密钥等于把所有链接一起作废。资料外链既要能单独吊销，又要按条统计
    下载次数，所以令牌必须落库（见 ResourceShareLink 的说明）。
    """
    for _ in range(5):
        token = secrets.token_urlsafe(12)
        if not db.query(ResourceShareLink.id).filter(
            ResourceShareLink.token == token
        ).first():
            return token
    raise RuntimeError("生成资料分享链接失败，请重试")


def create_share_link(
    db: Session,
    resource: Resource,
    *,
    created_by_no: str,
    created_by_name: str,
    days: int,
) -> ResourceShareLink:
    """为一份资料建一条外链

    days 只接四档：1 / 7 / 30 / 0（永久）。不在这里做「最小 1 天」之类的
    自动纠正 —— 传了别的值说明调用方算错了，直接报错比悄悄改成 7 天好。
    """
    if days not in SHARE_DAY_CHOICES:
        raise ValueError("有效期只能是 1 天、7 天、30 天或永久")

    now = datetime.now()
    row = ResourceShareLink(
        resource_id=resource.id,
        token=new_share_token(db),
        created_by_no=created_by_no,
        created_by_name=created_by_name or "",
        expires_at=None if days == 0 else now + timedelta(days=days),
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row


def get_share_link(db: Session, token: str) -> ResourceShareLink | None:
    if not token:
        return None
    return db.query(ResourceShareLink).filter(ResourceShareLink.token == token).first()


def share_link_status(link: ResourceShareLink | None, now: datetime | None = None) -> str:
    """一条外链现在是什么状态

    吊销优先于过期：管理员主动停掉的链接，哪怕时间也早就到了，
    列表里也显示「已吊销」—— 那是他能理解的那件事。
    """
    if link is None:
        return SHARE_STATUS_MISSING
    if link.revoked_at is not None:
        return SHARE_STATUS_REVOKED
    now = now or datetime.now()
    if link.expires_at is not None and link.expires_at <= now:
        return SHARE_STATUS_EXPIRED
    return SHARE_STATUS_VALID


def share_link_status_label(link: ResourceShareLink | None, now: datetime | None = None) -> str:
    return {
        SHARE_STATUS_VALID: "有效",
        SHARE_STATUS_EXPIRED: "已过期",
        SHARE_STATUS_REVOKED: "已吊销",
        SHARE_STATUS_MISSING: "资料不存在",
    }.get(share_link_status(link, now), "有效")


def list_share_links(db: Session) -> list[dict]:
    """管理员看的全部外链，按创建时间倒序（新的在最上面）

    一次把资料表捞出来做映射，避免每行都去查一次资料名。
    """
    rows = (
        db.query(ResourceShareLink)
        .order_by(ResourceShareLink.created_at.desc(), ResourceShareLink.id.desc())
        .all()
    )
    resources = {r.id: r for r in db.query(Resource).all()}
    now = datetime.now()
    result: list[dict] = []
    for row in rows:
        resource = resources.get(row.resource_id)
        result.append({
            "id": row.id,
            "resource_id": row.resource_id,
            # 资料被删时外链会一起删掉，这里只是兜底，正常不会出现
            "resource_name": resource.name if resource else "（资料已删除）",
            "created_by_no": row.created_by_no,
            "created_by_name": row.created_by_name,
            "token": row.token,
            "expires_at": row.expires_at,
            "revoked_at": row.revoked_at,
            "status": share_link_status(row, now),
            "status_label": share_link_status_label(row, now),
            "download_count": row.download_count or 0,
            "last_download_at": row.last_download_at,
            "created_at": row.created_at,
        })
    return result


def revoke_share_link(db: Session, link_id: int) -> ResourceShareLink | None:
    """吊销一条外链。已经吊销过的不报错，原样返回（重复点不该是失败）"""
    row = db.query(ResourceShareLink).filter(ResourceShareLink.id == link_id).first()
    if not row:
        return None
    if row.revoked_at is None:
        row.revoked_at = datetime.now()
        db.flush()
    return row


def record_share_download(db: Session, link: ResourceShareLink) -> None:
    """经外链下载一次：链接自己的计数 + 资料的总下载次数一起涨"""
    now = datetime.now()
    link.download_count = (link.download_count or 0) + 1
    link.last_download_at = now
    resource = db.query(Resource).filter(Resource.id == link.resource_id).first()
    if resource:
        resource.download_count = (resource.download_count or 0) + 1
    db.flush()


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
