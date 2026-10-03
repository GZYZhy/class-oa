import os
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote

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
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import Announcement, FileAccessLog, User
from ..schemas import AnnouncementResponse
from ..services import (
    account_name,
    add_invisible_watermark,
    make_watermark_token,
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
    ip: str = Depends(get_client_ip),
):
    """按文件名下发 PDF；只取文件名，杜绝路径穿越"""
    safe_name = os.path.basename(file_name)
    file_path = ANNOUNCEMENT_DIR / safe_name
    if not file_path.exists() or file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="文件不存在")

    # 查出公告行（班委也要查：为了记访问日志的 file_id / 标题，以及下载打水印）
    announcement = (
        db.query(Announcement)
        .filter(Announcement.file_path == f"{URL_PREFIX}/{safe_name}")
        .first()
    )

    # 「仅班委可见」的文件，对普通学生一律按不存在处理
    # （列表里本来就查不到，这里拦住的是手敲/猜 URL 直连；回 404 而不回 403，
    #  免得泄露「这个文件存在」）
    if not is_committee(user):
        if not announcement or not announcement.is_public:
            raise HTTPException(status_code=404, detail="文件不存在")
        # 普通学生只能在线预览，不能下载——防止绕过前端按钮直接调接口
        if download:
            raise HTTPException(status_code=403, detail="无下载权限")

    # 记访问日志（查看、下载都记）
    _log_file_access(
        db, user, announcement,
        action="download" if download else "view",
        ip=ip,
    )

    # 一律打水印，不再分成「查看不打、下载才打」——
    # 分着打的话，把 URL 里的 download 参数去掉就能拿到无水印原文件
    # （这个 URL 就在列表接口的 file_path 里，连猜都不用猜），
    # 浏览器内嵌的 PDF 查看器自带下载按钮，一存就是无标记副本；
    # 真出了外泄，没有水印反而不指向任何人，溯源等于白做。
    return _watermarked_pdf_response(file_path, announcement, user, download)


def _watermarked_pdf_response(
    file_path: Path,
    announcement: Announcement | None,
    user: User,
    download: bool,
) -> Response:
    """读取原 PDF、打上不可见水印后返回

    水印内容：OA-WM:<file_id>:<user_no>:<timestamp>
    """
    with open(file_path, "rb") as f:
        pdf_bytes = f.read()

    # 正常都能查到公告行（普通学生那档已经按 is_public 拦过了），
    # 但班委能取到「磁盘上有、库里没登记」的孤儿文件（删公告不删文件），
    # 那种情况拿 0 当 file_id —— 照样打水印，不留一条拿原文件的路
    file_id = announcement.id if announcement else 0
    token = make_watermark_token(file_id, user.student_no)
    watermarked = add_invisible_watermark(pdf_bytes, token)

    # 优先用上传时的原始文件名（用户上传的中文名字），UUID 名只用于磁盘存储
    display_name = (
        announcement.file_name if announcement and announcement.file_name else file_path.name
    )
    # 这里是自己造 Response（内容是打过水印的字节），FileResponse 那套用不上，
    # 只能手写头 —— 那就必须写成 RFC 5987 的 filename*=utf-8''百分号编码形式：
    # 普通 filename= 只认 latin-1，中文名会当场 UnicodeEncodeError
    return Response(
        content=watermarked,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                ("attachment" if download else "inline")
                + "; filename*=utf-8''"
                + quote(display_name)
            ),
            "Content-Length": str(len(watermarked)),
        },
    )


def _log_file_access(
    db: Session, user: User, announcement: Announcement | None,
    action: str, ip: str | None,
) -> None:
    """记一条文件访问日志（查看/下载）

    直接 add + commit：文件下发是只读操作，没有别的业务改动一起提交，
    也不能等下次 commit —— 请求结束后 session 就关了。
    """
    if not announcement:
        # 查不到公告行的话就不记了（理论上前面已经 404 了，这里只是兜底）
        return
    # 查看次数只加在「在线查看」上。列表里那列就叫「查看次数」，
    # 把下载也加进去的话，数出来的东西和名字对不上
    if action == "view":
        announcement.view_count = (announcement.view_count or 0) + 1
    db.add(FileAccessLog(
        user_no=user.student_no,
        user_name=account_name(db, user),
        file_id=announcement.id,
        file_title=announcement.title,
        action=action,
        ip=ip,
    ))
    db.commit()


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

    # 发布人一律取当前登录账号的展示名，前端无法伪造。
    # 用 account_name 而不是学生表：域外账号（老师）也可能有班委权限。
    # 先取成变量：下面那条推送文案也要用，而且它是个普通字符串，不受 commit 过期影响
    publisher = account_name(db, user)
    created = create_announcement(
        db,
        title=title,
        doc_number=doc_number.strip() or None,
        publish_date=publish_date,
        file_path=f"{URL_PREFIX}/{safe_name}",
        file_name=filename,
        publisher=publisher,
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
        f"{publisher} 上传了一份文件" + ("" if is_public else "（仅班委可见）"),
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
