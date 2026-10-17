"""意见反馈：学生提交，班委查看/标记已读/回复"""

import json
import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import get_db
from ..models import Feedback, Student, User
from ..schemas import FeedbackReply, FeedbackResponse
from ..services import display_name
from ..services.list_filters import created_between, keyword_like
from ..utils.media_type import guess_media_type
from .deps import (
    committee_required,
    get_current_student,
    get_current_user,
    is_committee,
)

router = APIRouter(prefix="/api/feedback", tags=["意见反馈"])

# 状态：unread 未读 / read 已读 / replied 已回复
VALID_STATUSES = {"unread", "read", "replied"}

# 反馈附件存放目录
FEEDBACK_DIR = BASE_DIR / "data" / "feedbacks"
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

# 允许的附件类型：图片 / 视频 / 音频 / 文档。
# 不收压缩包（内容不可见，容易被用来投递可执行文件）、不收 svg/html/js
# （能被浏览器当页面渲染）、不收带宏的 docm/xlsm/pptm。
# 前端 Feedback.vue 里的 accept 是另一份清单，改这里时两边要一起改。
ALLOWED_ATTACHMENT_EXTENSIONS = {
    # 图片（heic/heif 是 iPhone 拍照的默认格式）
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif",
    # 视频
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm",
    # 音频
    ".mp3", ".m4a", ".wav",
    # 文档（wps/et/dps 是 WPS 的文字/表格/演示）
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".pdf", ".txt", ".md", ".wps", ".et", ".dps",
}

# 单个附件大小上限（不是 3 个合计），和请假证明取同一个值
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024

# 一条反馈最多带几个附件
MAX_ATTACHMENTS = 3


def _attachment_name(original: str) -> str:
    """提取后缀，生成安全的存储文件名（同 leaves.py 的 _safe_name）"""
    ext = Path(original).suffix.lower() if original else ""
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的附件类型：{ext or '（无后缀）'}，仅支持图片 / 视频 / 音频 / 文档",
        )
    return f"{uuid.uuid4().hex}{ext}"


def _load_attachments(fb: Feedback) -> list:
    """把库里存的 JSON 串读成列表；读不出来就当没有附件"""
    if not fb.attachments:
        return []
    try:
        items = json.loads(fb.attachments or "")
    except (ValueError, TypeError):
        return []
    return items if isinstance(items, list) else []


def _to_response(fb: Feedback) -> FeedbackResponse:
    return FeedbackResponse.model_validate(fb)


# ---------- 学生端 ----------

@router.get("/my", response_model=list[FeedbackResponse], summary="我的反馈")
def my_feedback(
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """当前登录学生自己的反馈列表，按时间倒序"""
    rows = (
        db.query(Feedback)
        .filter(Feedback.student_id == student.id)
        .order_by(desc(Feedback.id))
        .all()
    )
    return [_to_response(r) for r in rows]


@router.post("", response_model=FeedbackResponse, summary="提交意见反馈")
async def submit_feedback(
    title: str = Form(..., min_length=1, max_length=100, description="标题"),
    content: str = Form(..., min_length=1, max_length=5000, description="正文"),
    # 必须带 File(...)：写成裸的 = [] 会被当成 query 参数，收不到文件
    attachments: list[UploadFile] = File(default=[], description="附件，最多 3 个"),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """提交反馈（multipart：正文和附件一起发）

    附件条数上限没用注解表达，因为超限时 FastAPI 抛的是 422、detail 是
    list of dict，前端弹出来是 [object Object]。手写 400 + 中文原因更好排查。

    另一个会抛 422 的地方：multipart 里 filename 为空串的 part 会被 FastAPI
    当成普通字段（Expected UploadFile, received: str），而且是在进这个函数
    之前就整单拒掉，这里接不住。el-upload 只会送用户真实选中的 File
    （一定有名字），正常路径碰不到，所以不为此加防御。
    """
    # min_length 放得过全是空格的标题，这里再拦一道（同 leaves.py 查 reason）
    if not title.strip():
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not content.strip():
        raise HTTPException(status_code=400, detail="正文不能为空")

    if len(attachments) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"附件最多 {MAX_ATTACHMENTS} 个")

    # 先把所有附件校验完再落盘。反过来的话，第 2 个附件不合法时
    # 第 1 个已经写进磁盘，成了一份没人认领的孤儿文件
    pending = []  # [(存盘名, 原始名, 内容)]
    for f in attachments:
        store_name = _attachment_name(f.filename)
        blob = await f.read()
        if not blob:
            raise HTTPException(status_code=400, detail=f"附件「{f.filename}」是空文件")
        if len(blob) > MAX_ATTACHMENT_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"附件「{f.filename}」超过 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB",
            )
        pending.append((store_name, f.filename, blob))

    written = []
    try:
        for store_name, _, blob in pending:
            path = FEEDBACK_DIR / store_name
            with open(path, "wb") as fp:
                fp.write(blob)
            written.append(path)

        fb = Feedback(
            student_id=student.id,
            student_no=student.student_no,
            student_name=student.name,
            title=title.strip(),
            content=content.strip(),
            status="unread",
            attachments=json.dumps(
                [
                    {"file": name, "name": original, "size": len(blob)}
                    for name, original, blob in pending
                ],
                ensure_ascii=False,
            ),
        )
        db.add(fb)
        db.commit()
        db.refresh(fb)
    except Exception:
        # 文件已落盘但入库失败：把刚写的删掉，别留孤儿。
        # （进程直接被 kill 这一档无解，请假那边也没做清理任务，不额外加）
        db.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        raise

    return _to_response(fb)


@router.get("/{feedback_id}", response_model=FeedbackResponse, summary="查看我的反馈详情")
def my_feedback_detail(
    feedback_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """学生只能看自己的"""
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb or fb.student_id != student.id:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return _to_response(fb)


# ---------- 附件下载（学生看自己的，班委及以上看全部） ----------

@router.get("/{feedback_id}/attachments/{index}", summary="下载反馈附件")
def download_attachment(
    feedback_id: int,
    index: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """班委及以上能下任意反馈的附件，普通学生只能下自己那条

    越权时用 404 而不是 403：不泄露「这条反馈存在，只是不属于你」
    （同 my_feedback_detail 的处理）。
    """
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")
    if not is_committee(user) and fb.student_no != user.student_no:
        raise HTTPException(status_code=404, detail="反馈不存在")

    items = _load_attachments(fb)
    # 负号必须显式拦掉：index 是 int，-1 会被 Python 当成「最后一个」
    # 返回，而不是当成非法下标
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail="附件不存在")

    item = items[index]
    store_name = item.get("file") if isinstance(item, dict) else None
    if not store_name:
        raise HTTPException(status_code=404, detail="附件不存在")

    # 存盘名是我们自己生成的一串 hex + 后缀，这里再 .name 一下挡路径穿越
    file_path = FEEDBACK_DIR / Path(store_name).name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="附件文件不存在")

    # 交给 FileResponse 处理文件名：它会按 RFC 5987 编码，中文名才不会炸
    # （别手拼 Content-Disposition，announcements.py 那个写法在这个项目踩过坑）
    return FileResponse(
        str(file_path),
        # 显式给类型，别让 Starlette 去猜：猜不出来时它兜底成 text/plain，
        # 附件里的 Word 会被浏览器存成 .txt（见 utils/media_type.py）
        media_type=guess_media_type(item.get("name"), store_name),
        filename=item.get("name") or store_name,
    )


# ---------- 班委端 ----------

@router.get("", response_model=list[FeedbackResponse], summary="反馈列表（班委及以上）")
def list_feedback(
    status: str | None = Query(None, description="unread/read/replied，不传为全部"),
    keyword: str | None = Query(None, description="按提交人姓名或学号模糊搜索"),
    start: date | None = Query(None, description="提交日期起始，含当天"),
    end: date | None = Query(None, description="提交日期结束，含当天"),
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    query = db.query(Feedback)
    if status and status in VALID_STATUSES:
        query = query.filter(Feedback.status == status)
    person_match = keyword_like(keyword, Feedback.student_name, Feedback.student_no)
    if person_match is not None:
        query = query.filter(person_match)
    query = created_between(query, Feedback.created_at, start, end)
    rows = query.order_by(desc(Feedback.id)).all()
    return [_to_response(r) for r in rows]


@router.get("/{feedback_id}/detail", response_model=FeedbackResponse, summary="反馈详情（班委）")
def feedback_detail(
    feedback_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    """班委查看详情。如果状态是 unread，自动标记为已读。"""
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")

    # 查看即标为已读（但不覆盖 replied 状态）
    if fb.status == "unread":
        fb.status = "read"
        db.commit()
        db.refresh(fb)

    return _to_response(fb)


@router.post("/{feedback_id}/mark-read", response_model=FeedbackResponse, summary="标记已读（班委）")
def mark_read(
    feedback_id: int,
    _: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")
    if fb.status == "unread":
        fb.status = "read"
        db.commit()
        db.refresh(fb)
    return _to_response(fb)


@router.post("/{feedback_id}/reply", response_model=FeedbackResponse, summary="回复反馈（班委）")
def reply_feedback(
    feedback_id: int,
    data: FeedbackReply,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
):
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")

    fb.reply_content = data.content.strip()
    fb.reply_name = display_name(db, user)
    fb.reply_no = user.student_no
    fb.reply_at = datetime.now()
    fb.status = "replied"
    db.commit()
    db.refresh(fb)
    return _to_response(fb)
