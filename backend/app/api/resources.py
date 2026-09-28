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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services import download_name, get_by_file_name, list_resources
from ..utils.media_type import guess_media_type
from .deps import get_current_user

router = APIRouter(prefix="/api/resources", tags=["资料下载"])

# 文件经带鉴权的接口下发，不走公开静态目录
# RESOURCE_DIR 在 resource_service 里定义，下载接口也要用
from ..services.resource_service import RESOURCE_DIR  # noqa: E402


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
