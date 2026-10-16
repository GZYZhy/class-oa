import json
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
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import BASE_DIR, settings
from ..database import get_db
from ..models import Notice, Student, User
from ..schemas import (
    ICalTokenResponse,
    NoticeResponse,
    NoticeReadStatus,
)
from ..services import (
    account_name,
    clip,
    list_notices,
    create_notice,
    update_notice,
    delete_notice,
    mark_read,
    read_notice_ids,
    read_status,
    log_operation,
    notify,
    notice_attachments,
    recipients,
)
from ..services import notice_rss_service as nrs
from ..services import schedule_service as ss
from ..utils.links import full_url
from ..utils.media_type import guess_media_type
from ..utils.notify_text import markdown_to_text
from .deps import (
    committee_required,
    get_client_ip,
    get_current_student,
    get_current_user,
    get_optional_user,
)

router = APIRouter(prefix="/api/notices", tags=["通知公告"])

# 通知附件存放目录
NOTICE_ATTACH_DIR = BASE_DIR / "data" / "notices"
NOTICE_ATTACH_DIR.mkdir(parents=True, exist_ok=True)

# 允许的附件类型：复用反馈附件的白名单（图片 / 视频 / 音频 / 文档）+ 压缩包
# 不收 svg/html/js、不收带宏的 docm/xlsm/pptm。
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif",
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm",
    ".mp3", ".m4a", ".wav",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".pdf", ".txt", ".md", ".wps", ".et", ".dps",
    ".zip", ".rar", ".7z",
}

MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 单文件 20MB
MAX_ATTACHMENTS = 3  # 一条通知最多带几个附件


def _safe_attach_name(original: str) -> str:
    """校验后缀并生成安全存盘名（UUID + 后缀）；不合法抛 400"""
    ext = Path(original).suffix.lower() if original else ""
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的附件类型：{ext or '（无后缀）'}，仅支持图片 / 视频 / 音频 / 文档 / 压缩包",
        )
    return f"{uuid.uuid4().hex}{ext}"


def _preview(markdown: str) -> str:
    """从 Markdown 正文里摘一句纯净文本做通知正文

    正文是 Markdown，原样推过去手机上会看到「##」「![]()」这些符号，
    通知栏又没地方渲染，所以先摘成纯文本再截断。
    """
    return clip(markdown_to_text(markdown), 80) or "点击查看详情"


# 通知列表公开（首页性质，无需登录）
@router.get("", response_model=list[NoticeResponse], summary="通知列表")
def get_list(
    title: str | None = Query(None, description="按标题搜索（模糊）"),
    start_date: str | None = Query(None, description="发布时间起始"),
    end_date: str | None = Query(None, description="发布时间截止"),
    limit: int | None = Query(None, ge=1, le=100, description="只返回最新 N 条（首页用）"),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    notices = list_notices(
        db, title=title, start_date=start_date, end_date=end_date, limit=limit
    )

    # 给每条通知挂上 is_read（NoticeResponse 按属性读这个名字）。
    # 直接挂在 ORM 对象上的确有点取巧，但省掉了把整个响应体复制一遍；
    # 这些对象本来就是这次请求里现查出来、用完就丢的。
    read_ids = read_notice_ids(db, user.student_no) if user else set()
    for notice in notices:
        notice.is_read = notice.id in read_ids
    return notices


@router.post("/{notice_id}/read", summary="标记为已读")
def mark_notice_read(
    notice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """展开通知时前端调它。重复调用无副作用（唯一约束兜底）"""
    if not db.query(Notice.id).filter(Notice.id == notice_id).first():
        raise HTTPException(status_code=404, detail="通知不存在")
    mark_read(db, notice_id, user.student_no)
    return {"message": "已标记为已读"}


@router.get(
    "/{notice_id}/reads",
    response_model=NoticeReadStatus,
    summary="通知已读情况（班委及以上）",
)
def get_reads(
    notice_id: int,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    if not db.query(Notice.id).filter(Notice.id == notice_id).first():
        raise HTTPException(status_code=404, detail="通知不存在")
    return read_status(db, notice_id)


@router.post("/{notice_id}/remind", summary="提醒未读的人（班委及以上）")
def remind_unread(
    # BackgroundTasks 没有默认值，必须排在那些带默认值的参数前面（见 leaves.py 的注释）
    notice_id: int,
    background: BackgroundTasks,
    request: Request,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """给「还没读这条通知」的人各推一条提醒

    名单直接用已读清单那份（read_status 的分母是 users 全表）。三条口径：
    - **冻结账号跳过**：他们本来就读不了通知（读接口会拒），推了也白推
    - **操作人自己跳过**：他正对着这条通知点「提醒未读」，再给自己推一条纯属噪音
      （发布通知那条链路也是这么排除自己的，口径一致）
    - 域外账号照推：名单里有他们，说明这条通知本来就发给了他们

    前两条都要在前端算按钮上的「未读 N 人」时同样排除，否则按钮说 3 人、
    提示说「已提醒 1 人」，班委会以为漏推了。

    逐个人调 recipients(only_no=...)，不给 recipients 加「批量学号」参数 —— 那要
    同时改 bark / webpush / email / webhook 四个渠道服务，而班级规模几十人、未读
    通常十几人，循环几个查询在这个量级上更简单也更不容易改错。**别改成批量查询**。

    recipients 必须在请求处理过程中调用（响应发出去之后 get_db 会把会话关掉，
    见 notify_service.recipients 的注释），所以循环和 commit 都留在请求里。

    不写操作日志的话，「我为什么收到这条提醒」事后查不到任何记录 ——
    一次给几十人推送是对他们可见的动作，值得留痕。

    返回值从前还有一个 unreachable（没读、但四个渠道一个都没订阅、因此什么都
    收不到的人）。**加站内信之后这类人不存在了**：提醒一定落进对方的收件箱，
    所以「已提醒 N 人」就是 N 个人真收到了，不用再分两类说。
    """
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="通知不存在")

    unread = [
        row
        for row in read_status(db, notice_id)["rows"]
        if row["read_at"] is None
        and not row["frozen"]
        and row["student_no"] != user.student_no
    ]
    # 没人可提醒就直接返回：按钮在 0 人时是禁用的，走到这里说明名单是刚变的
    # （比如别人抢先读了）。这时写一条「已提醒 0 人」的日志只会让后来查日志的人困惑
    if not unread:
        return {"reminded": 0}

    for row in unread:
        # recipients 这里必然非空：站内信不看任何开关，每个人至少有一份存档。
        # 从前那个「四个渠道都没订阅、所以什么都没发出去」的分支不用再判了 ——
        # 站内信解决的正是那件事
        notify(
            db, background, recipients(db, only_no=row["student_no"]),
            f"提醒：{notice.title}",
            _preview(notice.content or ""), level="active", page="/notices",
        )

    log_operation(
        db,
        user,
        action="提醒未读",
        target=notice.title,
        detail=f"已提醒 {len(unread)} 人",
        ip=get_client_ip(request),
    )
    db.commit()
    return {"reminded": len(unread)}


# ---------- 附件下载（无需登录即可下载，通知是公开的） ----------
@router.get("/{notice_id}/attachments/{index}", summary="下载通知附件")
def download_attachment(
    notice_id: int,
    index: int,
    db: Session = Depends(get_db),
):
    """按通知 id 和附件下标下载；通知是公开的，所有人（含未登录）都能下载"""
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="通知不存在")

    items = notice_attachments(notice)
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail="附件不存在")

    item = items[index]
    store_name = item.get("file", "")
    # 防路径穿越：只取文件名部分
    safe_name = Path(store_name).name
    file_path = NOTICE_ATTACH_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="附件文件不存在")

    display_name = item.get("name", safe_name)
    # 文件名交给 FileResponse 按 RFC 5987 编码，别手拼 Content-Disposition：
    # HTTP 头只装得下 latin-1，中文名塞进 filename="..." 会当场 UnicodeEncodeError，
    # 整个接口 500 —— feedback.py 里那句「别手拼」说的就是这个坑。
    # 类型也显式给（它认识白名单里的全部后缀），原先写死 octet-stream，
    # 图片 / PDF 附件在新标签页预览时会变成下载。
    return FileResponse(
        str(file_path),
        media_type=guess_media_type(display_name, safe_name),
        filename=display_name,
        content_disposition_type="attachment",
    )


# ---------- RSS 订阅 ----------
# 「需要登录」就落在这里：token 只能通过上面那个带登录的接口拿到，拿不到 token
# 就拼不出订阅地址；而 feed 端点没有有效 token 一律 404。
# 注意列表接口本身是公开的（首页性质），所以走订阅与否只差这一道门。


@router.get("/rss/token", response_model=ICalTokenResponse, summary="获取通知订阅链接")
def get_rss_token(
    request: Request,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """获取通知公告的 RSS 订阅链接（需登录）

    用的是「我的日程」那**同一个**订阅令牌（ical_tokens 表）—— 不用新建表、
    不用迁移。代价是在日程页重置令牌会让这条 RSS 链接一起失效，前端文案里写明了。
    """
    token, _ = ss.get_or_create_ical_token(db, student.id)
    db.commit()  # 首次访问时新建的 token 必须落库，否则返回的链接当场 404
    url = full_url(request, f"/api/notices/rss/{token}.xml")
    token_row = ss.get_student_by_ical_token(db, token)
    last_accessed = token_row[1].last_accessed_at if token_row else None
    return {"token": token, "url": url, "last_accessed_at": last_accessed}


# 和 ical_feed 一样：不走登录会话，纯 token 鉴权
@router.get("/rss/{token}.xml", summary="通知公告 RSS 订阅")
def rss_feed(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """RSS 订阅端点（通过 URL 里的 token 鉴权，无效一律 404）

    这里**故意不设** Cache-Control：nginx 的 `location ^~ /api/` 里有一句
    `add_header Cache-Control "no-store"`，而 add_header 是**追加**不是覆盖 ——
    写了会变成两个 Cache-Control 头、no-store 生效，等于在代码里留一句假承诺。
    刷新节奏交给 feed 里的 <ttl>。
    """
    if not ss.get_student_by_ical_token(db, token):
        # 不区分「不存在」和「已失效」：不泄露这个 token 曾经存在
        raise HTTPException(status_code=404, detail="Not found")
    db.commit()  # 提交 last_accessed_at 的更新

    content = nrs.generate_rss(
        list_notices(db)[: nrs.MAX_ITEMS],
        site_url=full_url(request, ""),
        feed_url=full_url(request, f"/api/notices/rss/{token}.xml"),
        site_name=settings.site_name or settings.app_name,
    )
    return Response(content=content, media_type="application/rss+xml; charset=utf-8")


# ---------- 以下管理操作需要班委及以上 ----------
@router.post("", response_model=NoticeResponse, summary="发布通知（班委及以上）")
async def publish(
    background: BackgroundTasks,
    title: str = Form(..., min_length=1, max_length=200, description="标题"),
    publish_date: date = Form(..., description="发布时间"),
    content: str = Form(..., description="正文（Markdown）"),
    attachments: list[UploadFile] = File(default=[], description="附件，最多 3 个"),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """发布通知（multipart form：正文 + 附件一起发）"""
    if not title.strip():
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not content.strip():
        raise HTTPException(status_code=400, detail="正文不能为空")
    if len(attachments) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"附件最多 {MAX_ATTACHMENTS} 个")

    # 先校验并保存所有附件（全部校验通过再落盘，避免半截文件）
    attach_meta = []
    saved_files = []  # 已经存了的，失败时回滚用
    for f in attachments:
        if not f.filename:
            raise HTTPException(status_code=400, detail="附件文件名不能为空")
        safe_name = _safe_attach_name(f.filename)
        file_content = await f.read()
        if len(file_content) > MAX_ATTACHMENT_SIZE:
            # 回滚已经存了的
            for p in saved_files:
                try:
                    p.unlink()
                except OSError:
                    pass
            raise HTTPException(
                status_code=400,
                detail=f"附件「{f.filename}」超过 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB",
            )
        save_path = NOTICE_ATTACH_DIR / safe_name
        with open(save_path, "wb") as fp:
            fp.write(file_content)
        saved_files.append(save_path)
        attach_meta.append({
            "file": safe_name,
            "name": f.filename,
            "size": len(file_content),
        })

    data = {
        "title": title.strip(),
        "publish_date": publish_date,
        "content": content,
        "publisher": account_name(db, user),
        "attachments": json.dumps(attach_meta, ensure_ascii=False) if attach_meta else "",
    }
    created = create_notice(db, data, user=user)
    log_operation(
        db, user, "发布通知", target=created.title,
        detail=f"带 {len(attach_meta)} 个附件" if attach_meta else "",
        ip=ip,
    )
    targets = recipients(db, exclude_no=user.student_no)
    db.commit()

    notify(
        db, background, targets, f"新通知：{created.title}",
        _preview(created.content or ""), level="active", page="/notices",
    )
    return created


@router.put("/{notice_id}", response_model=NoticeResponse, summary="编辑通知（班委及以上）")
async def edit(
    notice_id: int,
    title: str = Form(..., min_length=1, max_length=200, description="标题"),
    publish_date: date = Form(..., description="发布时间"),
    content: str = Form(..., description="正文（Markdown）"),
    attachments: list[UploadFile] = File(default=[], description="新增附件，最多 3 个（含原有）"),
    # 原有附件的下标列表（JSON 串），前端把要保留的原附件下标传过来
    keep_attachments: str = Form("", description="保留的原附件下标（JSON 数组，如 [0,2]）"),
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """编辑通知：正文和附件都能改。

    附件处理逻辑：
    - keep_attachments: 要保留的原附件下标（JSON 数组字符串），不传或为空表示全部保留
    - attachments: 新上传的附件
    - 最终附件列表 = 保留的原附件 + 新上传的附件，总数不超过 MAX_ATTACHMENTS
    - 被去掉的原附件文件会被删除
    """
    if not title.strip():
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not content.strip():
        raise HTTPException(status_code=400, detail="正文不能为空")

    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="通知不存在")

    # 解析要保留的原附件下标
    old_items = notice_attachments(notice)
    keep_indices = set()
    if keep_attachments.strip():
        try:
            keep_indices = set(int(x) for x in json.loads(keep_attachments))
        except (ValueError, TypeError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="keep_attachments 格式错误")

    # 保留的原附件
    kept = [old_items[i] for i in sorted(keep_indices) if 0 <= i < len(old_items)]

    # 校验总数（保留的 + 新增的）
    if len(kept) + len(attachments) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"附件最多 {MAX_ATTACHMENTS} 个")

    # 保存新附件
    new_meta = []
    saved_files = []
    for f in attachments:
        if not f.filename:
            raise HTTPException(status_code=400, detail="附件文件名不能为空")
        safe_name = _safe_attach_name(f.filename)
        file_content = await f.read()
        if len(file_content) > MAX_ATTACHMENT_SIZE:
            for p in saved_files:
                try:
                    p.unlink()
                except OSError:
                    pass
            raise HTTPException(
                status_code=400,
                detail=f"附件「{f.filename}」超过 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB",
            )
        save_path = NOTICE_ATTACH_DIR / safe_name
        with open(save_path, "wb") as fp:
            fp.write(file_content)
        saved_files.append(save_path)
        new_meta.append({
            "file": safe_name,
            "name": f.filename,
            "size": len(file_content),
        })

    # 最终附件列表
    final_attachments = kept + new_meta

    # 删掉被移除的旧附件文件
    removed_indices = set(range(len(old_items))) - keep_indices
    for i in removed_indices:
        store_name = old_items[i].get("file", "")
        if store_name:
            p = NOTICE_ATTACH_DIR / Path(store_name).name
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

    data = {
        "title": title.strip(),
        "publish_date": publish_date,
        "content": content,
        "attachments": json.dumps(final_attachments, ensure_ascii=False) if final_attachments else "",
    }
    updated = update_notice(db, notice_id, data, user=user)
    if not updated:
        raise HTTPException(status_code=404, detail="通知不存在")

    log_operation(
        db, user, "编辑通知", target=updated.title,
        detail=f"原发布人：{updated.publisher}；附件 {len(final_attachments)} 个",
        ip=ip,
    )
    db.commit()
    return updated


@router.delete("/{notice_id}", summary="删除通知（班委及以上）")
def remove(
    notice_id: int,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="通知不存在")
    title = notice.title

    # 先删附件文件（删不掉也不影响主流程）
    items = notice_attachments(notice)
    for item in items:
        store_name = item.get("file", "")
        if store_name:
            p = NOTICE_ATTACH_DIR / Path(store_name).name
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

    delete_notice(db, notice_id)
    log_operation(db, user, "删除通知", target=title, ip=ip)
    db.commit()
    return {"message": "删除成功"}
