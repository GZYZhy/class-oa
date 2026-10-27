"""资料下载接口

历史说明：
- v1：资料清单写死在代码里的 RESOURCE_CATALOG 数组里，加资料要改代码
- v2（现在）：清单存在 resources 表里，管理员在系统管理页面就能上传、改名、换分类

向后兼容：
- /api/resources（GET）的返回格式完全不变，前端 Downloads 页面一行都不用改
- /api/resources/file/{name} 的行为不变
- 旧数据：首次启动时自动从旧的 RESOURCE_CATALOG 导入到数据库（见 main.py）
"""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import ResourceShareCreate, ResourceShareCreated, ResourceShareInfo
from ..services import (
    SHARE_DAY_CHOICES,
    SHARE_DAY_LABELS,
    SHARE_STATUS_MISSING,
    SHARE_STATUS_VALID,
    create_share_link,
    display_name,
    download_name,
    get_by_file_name,
    get_share_link,
    list_resources,
    log_operation,
    record_share_download,
    share_link_status,
)
from ..utils.links import full_url
from ..utils.media_type import guess_media_type
from .deps import get_client_ip, get_current_user

router = APIRouter(prefix="/api/resources", tags=["资料下载"])

# 文件经带鉴权的接口下发，不走公开静态目录
# RESOURCE_DIR 在 resource_service 里定义，下载接口也要用
from ..services.resource_service import RESOURCE_DIR, get_resource  # noqa: E402
from ..services.share_service import share_path  # noqa: E402


@router.get("", summary="可下载资料清单（需登录）")
def list_resources_api(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按分类分组返回资料列表

    返回格式与旧版完全一致，前端 Downloads 页面零改动。
    """
    return list_resources(db)


@router.get("/file/{file_name}", summary="下载资料文件（需登录）")
def serve_resource(
    file_name: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    download: bool = Query(True, description="true=作为附件下载，false=浏览器内预览"),
):
    """按文件名下发资料；只取文件名，且必须命中数据库，杜绝越权取任意文件

    白名单从数据库读，而不是旧版的 RESOURCE_CATALOG 集合，
    这样管理员新加的资料立刻就能下，不用改代码。
    """
    safe_name = os.path.basename(file_name)

    row = get_by_file_name(db, safe_name)
    if not row:
        raise HTTPException(status_code=404, detail="资料不存在")

    file_path = RESOURCE_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="资料文件丢失")

    # 计一次下载。只看 download=true：预览（inline）不算下载次数，
    # 否则管理员在后台点开看一眼也会让数字往上涨
    if download:
        row.download_count = (row.download_count or 0) + 1
        db.commit()

    # 文件名含中文，HTTP 头只允许 latin-1，交给 FileResponse 按 RFC 5987 处理：
    # 名字里有非 ASCII 时它只发 filename*=utf-8''中文百分号编码，
    # 纯 ASCII 时才发 filename="..."。两种都合法，浏览器也都认。
    #
    # 别改回手拼那个头：把百分号编码串塞进普通 filename= 是错的 ——
    # 认这个参数而不认 filename* 的客户端会把
    # %E8%B5%84%E6%96%99.docx 原样存成文件名
    return FileResponse(
        str(file_path),
        # media_type 必须显式给：浏览器认这个头，猜错成 text/plain 时
        # 下载下来的 .docx 会被存成 .txt（见 utils/media_type.py 的说明）
        media_type=guess_media_type(row.file_name, row.original_name),
        filename=download_name(row),
        content_disposition_type="attachment" if download else "inline",
    )


# ==================== 分享外链 ====================
# 外链落地在 /share/resource/{token}（前端分享页），这里只提供数据和文件。
# 下载接口**不需要登录** —— 外链的本意就是「拿到链接的人都能下」，
# 可用性完全由链接自身（有效期 / 是否吊销）决定。


@router.post(
    "/{resource_id}/share",
    summary="创建资料外链",
    response_model=ResourceShareCreated,
)
def create_resource_share(
    resource_id: int,
    payload: ResourceShareCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """给一份资料生成外链，有效期由分享人选（1 天 / 7 天 / 30 天 / 永久）

    登录用户都能分享：资料清单本来就对所有登录用户开放，分享只是把
    「登录才能下」换成「拿到链接就能下」。谁创建、什么时候创建、用的哪个
    有效期、经链接下了几次，都在管理员的「资料分享外链」里可查、可吊销。
    """
    resource = get_resource(db, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="资料不存在")
    if not (RESOURCE_DIR / resource.file_name).exists():
        raise HTTPException(status_code=404, detail="资料文件丢失")
    if payload.days not in SHARE_DAY_CHOICES:
        raise HTTPException(status_code=400, detail="有效期只能是 1 天、7 天、30 天或永久")

    link = create_share_link(
        db,
        resource,
        created_by_no=user.student_no,
        created_by_name=display_name(db, user),
        days=payload.days,
    )
    path = share_path("resource", link.token)
    log_operation(
        db, user, "分享资料",
        target=f"{resource.category}/{resource.name}",
        detail=f"有效期 {SHARE_DAY_LABELS[payload.days]}，外链 {path}",
        ip=ip,
    )
    # 先把要返回的值取出来：commit 之后对象会被标记过期，再访问就是一次新查询
    token, expires_at, created_at = link.token, link.expires_at, link.created_at
    db.commit()
    return ResourceShareCreated(
        token=token,
        path=path,
        url=full_url(request, path),
        expires_at=expires_at,
        created_at=created_at,
    )


@router.get(
    "/share/{token}/info",
    summary="资料外链信息（公开，免登录）",
    response_model=ResourceShareInfo,
)
def resource_share_info(token: str, db: Session = Depends(get_db)):
    """外链落地页的数据源

    token 不存在 → 404（链接被改动过）。存在但过期 / 已吊销 → 200 且
    valid=false，由页面说明具体原因：游客看到「已过期」比统一一句
    「链接失效」有用得多。
    """
    link = get_share_link(db, token)
    if not link:
        raise HTTPException(status_code=404, detail="分享链接无效")
    resource = get_resource(db, link.resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="分享链接无效")

    status = share_link_status(link)
    file_path = RESOURCE_DIR / resource.file_name
    if status == SHARE_STATUS_VALID and not file_path.exists():
        status = SHARE_STATUS_MISSING

    info = ResourceShareInfo(
        valid=status == SHARE_STATUS_VALID,
        reason="" if status == SHARE_STATUS_VALID else status,
        resource_name=resource.name,
        category=resource.category,
        expires_at=link.expires_at,
        created_at=link.created_at,
    )
    if info.valid:
        info.file_ext = Path(download_name(resource)).suffix.lower()
        info.size = file_path.stat().st_size
        info.download_name = download_name(resource)
        info.download_url = f"/api/resources/share/{link.token}/file"
    return info


@router.get("/share/{token}/file", summary="经外链下载资料（公开，免登录）")
def resource_share_download(token: str, db: Session = Depends(get_db)):
    """外链下载。每次下载给这条链接记一次数，同时给资料的总下载次数 +1"""
    link = get_share_link(db, token)
    if not link or share_link_status(link) != SHARE_STATUS_VALID:
        raise HTTPException(status_code=404, detail="分享链接已失效")

    resource = get_resource(db, link.resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="分享链接已失效")

    file_path = RESOURCE_DIR / resource.file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="资料文件丢失")

    record_share_download(db, link)
    db.commit()

    # 和站内下载同一套口径：文件名交给 FileResponse 按 RFC 5987 编码，
    # media_type 显式给（见上面 serve_resource 的说明）
    return FileResponse(
        str(file_path),
        media_type=guess_media_type(resource.file_name, resource.original_name),
        filename=download_name(resource),
        content_disposition_type="attachment",
    )
