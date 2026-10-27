"""外链分享的服务端 meta 片段（给 nginx SSI 用）

nginx 对 `/share/{kind}/{token}` 返回 SPA 的 index.html，并在同一次响应里用
`<!--# include virtual="/api/share-meta${request_uri}" -->` 把这个片段插进
`<head>`。微信爬虫不执行 JS，但会读这里渲染好的 title / description / og。

两条硬约束：
1. **任何输入都必须返回 200**。SSI 的 include 会把非 200 的错误页正文原样
   插进 head，卡片上就会出现一段 nginx/FastAPI 的报错。所以未知 kind、
   伪造签名、乱路径、数据库异常一律走统一失效片段。
2. 只输出 head 内的标签，不输出 html/body/style；所有动态值都要转义。

新增外链类型：在 _RESOLVERS 里加一个 `resolver(db, token) -> ShareMeta | None`。
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Checkin,
    CheckinTarget,
    Collection,
    CollectionQuestion,
    Notice,
    Poll,
    PollQuestion,
    PollTarget,
    Resource,
)
from ..services import clip
from ..services.checkin_service import (
    CHECKIN_ENDED,
    CHECKIN_ONGOING,
    CHECKIN_PAUSED,
    CHECKIN_PENDING,
    checkin_status,
)
from ..services.collection_service import (
    STATUS_CLOSED as COLLECTION_CLOSED,
    STATUS_OPEN as COLLECTION_OPEN,
    STATUS_PAUSED as COLLECTION_PAUSED,
    STATUS_PENDING as COLLECTION_PENDING,
    collection_status,
    parse_collection_share_token,
    scope_label as collection_scope_label,
)
from ..services.poll_service import (
    STATUS_CLOSED,
    STATUS_LOCKED,
    STATUS_OPEN,
    STATUS_PENDING,
    parse_poll_share_token,
    poll_status,
    scope_label,
)
from ..services.resource_service import (
    RESOURCE_DIR,
    SHARE_STATUS_VALID,
    get_share_link,
    share_link_status,
)
from ..services.share_service import ShareMeta, render_meta_html
from ..utils.notify_text import markdown_to_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/share-meta", tags=["外链分享"])

POLL_STATE_LABELS = {
    STATUS_PENDING: "未开始",
    STATUS_OPEN: "进行中",
    STATUS_LOCKED: "已暂停",
    STATUS_CLOSED: "已结束",
}
CHECKIN_STATE_LABELS = {
    CHECKIN_PENDING: "未开始",
    CHECKIN_ONGOING: "进行中",
    CHECKIN_PAUSED: "已暂停",
    CHECKIN_ENDED: "已结束",
}
COLLECTION_STATE_LABELS = {
    COLLECTION_PENDING: "未开始",
    COLLECTION_OPEN: "进行中",
    COLLECTION_PAUSED: "已暂停",
    COLLECTION_CLOSED: "已结束",
}


def _vote_meta(db: Session, token: str) -> ShareMeta | None:
    """投票卡片：状态、范围、记名方式、人数、题数、截止时间"""
    poll_id = parse_poll_share_token(token)
    poll = db.query(Poll).filter(Poll.id == poll_id).first() if poll_id else None
    if not poll:
        return None

    target_count = (
        db.query(PollTarget).filter(PollTarget.poll_id == poll.id).count()
    )
    question_count = (
        db.query(PollQuestion).filter(PollQuestion.poll_id == poll.id).count()
    )
    state = POLL_STATE_LABELS.get(poll_status(poll), "进行中")
    desc = (
        f"{state} · {scope_label(db, poll.id)}"
        f" · {'不记名' if poll.anonymous else '记名'}"
        f" · 应投 {target_count} 人 · {question_count} 道题"
        f" · 截止 {poll.end_at:%m月%d日 %H:%M}"
    )
    if poll.description:
        desc = f"{clip(markdown_to_text(poll.description), 60)}｜{desc}"

    title = (poll.title or "投票表决").strip() or "投票表决"
    if not title.startswith("投票："):
        title = f"投票：{title}"
    return ShareMeta(kind="vote", token=token, title=title, description=desc)


def _checkin_meta(db: Session, code: str) -> ShareMeta | None:
    """签到卡片：状态、应到人数、截止时间"""
    checkin = db.query(Checkin).filter(Checkin.code == code).first()
    if not checkin:
        return None

    target_count = (
        db.query(CheckinTarget).filter(CheckinTarget.checkin_id == checkin.id).count()
    )
    state = CHECKIN_STATE_LABELS.get(checkin_status(checkin), "进行中")
    desc = f"{state} · 应到 {target_count} 人 · 截止 {checkin.end_at:%m月%d日 %H:%M}"
    if checkin.remark:
        desc = f"{clip(markdown_to_text(checkin.remark), 60)}｜{desc}"

    title = (checkin.title or "签到").strip() or "签到"
    if not title.startswith("签到："):
        title = f"签到：{title}"
    return ShareMeta(kind="checkin", token=code, title=title, description=desc)


def _collection_meta(db: Session, token: str) -> ShareMeta | None:
    """收集卡片：状态、范围、记名、每人份数、竞争份数、题数、截止时间"""
    collection_id = parse_collection_share_token(token)
    collection = (
        db.query(Collection).filter(Collection.id == collection_id).first()
        if collection_id
        else None
    )
    if not collection:
        return None

    question_count = (
        db.query(CollectionQuestion)
        .filter(CollectionQuestion.collection_id == collection.id)
        .count()
    )
    state = COLLECTION_STATE_LABELS.get(collection_status(collection), "进行中")
    desc = (
        f"{state} · {collection_scope_label(db, collection.id)}"
        f" · {'不记名' if collection.anonymous else '记名'}"
        f" · 每人可填 {collection.submit_quota} 份"
    )
    if collection.max_responses is not None:
        desc += f" · 限收 {collection.max_responses} 份"
    desc += (
        f" · {question_count} 道题"
        f" · 截止 {collection.end_at:%m月%d日 %H:%M}"
    )
    if collection.description:
        desc = f"{clip(markdown_to_text(collection.description), 60)}｜{desc}"

    title = (collection.title or "收集").strip() or "收集"
    if not title.startswith("收集："):
        title = f"收集：{title}"
    return ShareMeta(
        kind="collect", token=token, title=title, description=desc
    )


def _notice_meta(db: Session, token: str) -> ShareMeta | None:
    """公告卡片：标题 + 正文纯文本摘要 + 发布日期

    通知公告本身就是公开内容（列表接口无需登录），所以分享路径直接用自增 id，
    不需要签名：`/share/notice/12` 就是一个稳定、可被爬取的真实地址。
    """
    try:
        notice_id = int(token)
    except (TypeError, ValueError):
        return None
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        return None

    preview = clip(markdown_to_text(notice.content or ""), 60)
    desc = f"发布于 {notice.publish_date:%Y-%m-%d}"
    if preview:
        desc = f"{preview}｜{desc}"
    if notice.updated_at:
        desc = f"{desc} · 已更新"
    return ShareMeta(
        kind="notice",
        token=token,
        title=f"公告：{notice.title}",
        description=desc,
    )


def _size_text(size: int) -> str:
    """文件大小的人类可读写法，口径与前端资料卡片一致"""
    if not size:
        return "文件缺失"
    if size < 1024:
        return f"{size} B"
    kb = size / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.1f} GB"


def _resource_meta(db: Session, token: str) -> ShareMeta | None:
    """资料外链卡片：材料名 + 分类、大小、有效期

    资料外链是可以单独吊销的，token 由数据库里那条记录决定；
    过期或已吊销时给失效卡片（robots 也会跟着变成 noindex）——
    微信里转发出去之后失效的链接，不该继续被搜索引擎收录。
    """
    link = get_share_link(db, token)
    if not link:
        return None
    resource = db.query(Resource).filter(Resource.id == link.resource_id).first()
    if not resource:
        return None

    title = f"资料：{resource.name}"
    if share_link_status(link) != SHARE_STATUS_VALID:
        return ShareMeta(
            kind="resource",
            token=token,
            title=title,
            description="这个分享链接已过期或被发布人收回",
            valid=False,
        )

    file_path = RESOURCE_DIR / resource.file_name
    if not file_path.exists():
        # 链接本身还有效但文件没了：落地页会显示「文件暂不可用」，
        # 卡片也不能继续让搜索引擎收录这个死链
        return ShareMeta(
            kind="resource",
            token=token,
            title=title,
            description="资料文件已不在服务器上，请联系管理员",
            valid=False,
        )
    size = file_path.stat().st_size
    desc = f"{resource.category} · {_size_text(size)}"
    if link.expires_at:
        desc += f" · 有效期至 {link.expires_at:%Y-%m-%d %H:%M}"
    else:
        desc += " · 永久有效"
    return ShareMeta(kind="resource", token=token, title=title, description=desc)


# 类型注册表。新增外链类型只加一行，不需要动 nginx 和 index.html
_RESOLVERS = {
    "vote": _vote_meta,
    "checkin": _checkin_meta,
    "notice": _notice_meta,
    "collect": _collection_meta,
    "resource": _resource_meta,
}


@router.get(
    "/{rest:path}",
    response_class=HTMLResponse,
    summary="外链分享的 head 片段（SSI 子请求，公开）",
    include_in_schema=False,
)
def share_meta(
    rest: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """`/api/share-meta/share/vote/{token}` → 一段可插入 <head> 的 HTML

    路径固定是 `share/{kind}/{token}` 三段。解析不了、查不到、签名不对、
    查询异常，全部返回 200 的失效卡片 —— 见模块开头的说明。
    """
    meta = None
    try:
        parts = [part for part in rest.split("/") if part]
        if len(parts) == 3 and parts[0] == "share":
            resolver = _RESOLVERS.get(parts[1])
            if resolver is not None:
                meta = resolver(db, parts[2])
    except Exception:  # noqa: BLE001 - 这里就是要兜住一切，保证 SSI 拿到 200
        logger.exception("生成分享卡片失败：%s", rest)
        meta = None

    return HTMLResponse(
        render_meta_html(request, meta),
        headers={"Cache-Control": "no-store"},
    )
