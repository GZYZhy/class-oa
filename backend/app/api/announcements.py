import os
import uuid
from datetime import date
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import Announcement, User
from ..schemas import AnnouncementResponse
from ..services import (
    account_name,
    list_announcements,
    create_announcement,
    delete_announcement,
    get_announcement,
    log_operation,
    notify,
    recipients,
)
from .deps import (
    get_current_user,
    committee_required,
    is_committee,
    get_client_ip,
)

router = APIRouter(prefix="/api/announcements", tags=["文件公开"])

# 公告 PDF 存放目录
ANNOUNCEMENT_DIR = BASE_DIR / "data" / "announcements"
ANNOUNCEMENT_DIR.mkdir(parents=True, exist_ok=True)
# 文件经带鉴权的接口下发，不再走公开静态目录
URL_PREFIX = "/api/announcements/file"


@router.get("", response_model=list[AnnouncementResponse], summary="文件列表（按发布时间降序）")
def get_list(
    user: User = Depends(get_current_user),
    title: str | None = Query(None, description="按标题搜索（模糊）"),
    start_date: str | None = Query(None, description="发布时间起始（YYYY-MM-DD）"),
    end_date: str | None = Query(None, description="发布时间截止（YYYY-MM-DD）"),
    db: Session = Depends(get_db),
):
    # 普通学生只看得到「向班委以外公开」的文件；班委及以上看全部
    return list_announcements(
        db,
        title=title,
        start_date=start_date,
        end_date=end_date,
        public_only=not is_committee(user),
    )


@router.get("/file/{file_name}", summary="查看/下载公告文件（需登录）")
def serve_file(
    file_name: str,
    user: User = Depends(get_current_user),
    download: bool = Query(False, description="true=作为附件下载，false=浏览器内预览"),
    db: Session = Depends(get_db),
):
    """按文件名下发 PDF；只取文件名，杜绝路径穿越"""
    safe_name = os.path.basename(file_name)
    file_path = ANNOUNCEMENT_DIR / safe_name
    if not file_path.exists() or file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="文件不存在")

    # 「仅班委可见」的文件，对普通学生一律按不存在处理
    # （列表里本来就查不到，这里拦住的是手敲/猜 URL 直连；回 404 而不回 403，
    #  免得泄露「这个文件存在」）
    if not is_committee(user):
        row = (
            db.query(Announcement)
            .filter(Announcement.file_path == f"{URL_PREFIX}/{safe_name}")
            .first()
        )
        if not row or not row.is_public:
            raise HTTPException(status_code=404, detail="文件不存在")

    return _pdf_response(file_path, download)


def _pdf_response(file_path: Path, download: bool) -> FileResponse:
    """返回 PDF；download=True 时带上原始文件名作为下载名"""
    headers = {"Content-Disposition": f'inline; filename="{file_path.name}"'}
    if download:
        headers = {"Content-Disposition": f'attachment; filename="{file_path.name}"'}
    return FileResponse(str(file_path), media_type="application/pdf", headers=headers)


@router.post("", response_model=AnnouncementResponse, summary="上传PDF并发布公告（班委及以上）")
async def upload_announcement(
    # BackgroundTasks 必须放在最前：它没有默认值，排在下面那些带默认值的参数后面会语法报错
    background: BackgroundTasks,
    title: str = Form(..., description="文件标题"),
    doc_number: str = Form("", description="文号"),
    publish_date: date = Form(..., description="发布时间"),
    is_public: bool = Form(True, description="是否向班委以外公开"),
    file: UploadFile = File(..., description="PDF 文件"),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    # 校验文件类型必须为 PDF
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只允许上传 PDF 文件")

    # 读取文件并校验大小（50MB，与 nginx 的 client_max_body_size 一致）
    MAX_SIZE = 50 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过 50MB")

    # 用 UUID 前缀防止重名和路径穿越
    safe_name = f"{uuid.uuid4().hex}.pdf"
    save_path = ANNOUNCEMENT_DIR / safe_name

    with open(save_path, "wb") as f:
        f.write(content)

    created = create_announcement(
        db,
        title=title,
        doc_number=doc_number.strip() or None,
        publish_date=publish_date,
        file_path=f"{URL_PREFIX}/{safe_name}",
        file_name=filename,
        # 发布人一律取当前登录账号的展示名，前端无法伪造。
        # 用 account_name 而不是学生表：域外账号（老师）也可能有班委权限
        publisher=account_name(db, user),
        is_public=is_public,
    )
    log_operation(
        db, user, "上传文件", target=created.title,
        detail="" if is_public else "仅班委可见",
        ip=ip,
    )
    # 「仅班委可见」的文件如果推给全体，等于把不该看到的人也叫来了，
    # 所以收件人必须和列表接口的可见范围保持一致（见上面的 get_list）
    targets = recipients(
        db,
        roles=None if is_public else ["admin", "committee"],
        exclude_no=user.student_no,
    )
    # commit 会让对象过期，之后访问属性要再查一次库，所以先把标题取出来
    title = created.title
    db.commit()

    notify(
        background, targets, f"新公告：{title}",
        f"{student.name} 上传了一份文件" + ("" if is_public else "（仅班委可见）"),
        level="active", page="/announcements",
    )
    return created


@router.delete("/{announcement_id}", summary="删除公告（班委及以上）")
def remove_announcement(
    announcement_id: int,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    announcement = get_announcement(db, announcement_id)
    if not announcement:
        raise HTTPException(status_code=404, detail="公告不存在")

    # 先删除物理文件（不存在不影响）
    safe_name = os.path.basename(announcement.file_path)
    title = announcement.title  # 删除后不能再访问属性，先取出来
    file_full_path = ANNOUNCEMENT_DIR / safe_name
    if file_full_path.exists():
        file_full_path.unlink()

    delete_announcement(db, announcement_id)
    log_operation(db, user, "删除文件", target=title, ip=ip)
    db.commit()
    return {"message": "删除成功"}
