"""站内信：所有推送的存档

登录的人各看各的。写入不在这里 —— 那是 notify_service 的事（所有推送顺手存一份），
本模块只有「看」「标记已读」和「删除已读」。菜单红点用的未读数另有 /api/badges 一处，
不在这里重复开接口。
"""

import html as html_lib

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User
from ..schemas.inbox import InboxListResponse
from ..services import inbox_service
from .deps import get_current_user

router = APIRouter(prefix="/api/inbox", tags=["站内信"])

# 每页条数上限。前端固定传 20，这个上限只是防手工构造请求一次拉全表
MAX_PAGE_SIZE = 100
# 邮件已读链接里最多认多少个令牌（共用邮箱时一个人可能带好几条，留足余量）
MAX_EMAIL_TOKENS = 100
# public_base_url 没配时追踪接口也得返回一张图，不能给邮箱客户端一个 404
_TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


@router.get("", response_model=InboxListResponse, summary="我的站内信")
def list_inbox(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按时间倒序分页；unread 是全量未读数（见 schema 里的说明）"""
    rows, total = inbox_service.list_messages(db, user.student_no, page, page_size)
    return InboxListResponse(
        total=total,
        page=page,
        page_size=page_size,
        unread=inbox_service.unread_count(db, user.student_no),
        items=rows,
    )


@router.get("/read-email", response_class=HTMLResponse, summary="邮件里一键标记已读")
def read_email(
    tokens: str = Query("", max_length=8000),
    db: Session = Depends(get_db),
):
    """邮件里的「标记为已读」按钮点进来这里，**不要求登录**

    每条令牌由 inbox_service 用站点密钥签名，绑定了消息 id 和学号，
    改一个字符就验不过，所以不需要账号也不会误标别人的消息。
    一个邮箱被多人共用时链接里会带多个令牌，这里逐个处理。

    返回一页极简结果，不跳转 SPA —— 用户点邮件里的按钮只是清红点，
    不该被带进整个站点。
    """
    pairs = _parse_email_tokens(tokens)
    if not pairs:
        return _result_page("链接无效或已过期", "请回到站内信查看这条通知。", 400)

    found = _mark_email_tokens(db, pairs)
    if not found:
        return _result_page("通知不存在或已删除", "它可能已经被清理掉了。", 404)
    return _result_page("已标记为已读", f"这次通知（共 {found} 条）不会再显示未读。")


def _parse_email_tokens(tokens: str) -> list[tuple[int, str]]:
    """解析逗号分隔的令牌，非法的直接丢掉"""
    pairs = []
    for raw in tokens.split(",")[:MAX_EMAIL_TOKENS]:
        pair = inbox_service.parse_read_token(raw.strip())
        if pair:
            pairs.append(pair)
    return pairs


def _mark_email_tokens(db: Session, pairs: list[tuple[int, str]]) -> int:
    """把令牌对应的消息标为已读，返回找到的条数（已读的也算找到）"""
    return sum(
        1 for message_id, student_no in pairs
        if inbox_service.mark_read(db, student_no, message_id)
    )


@router.get(
    "/email-open",
    summary="邮件校徽加载追踪（非重要通知自动已读）",
    include_in_schema=False,
)
def email_open(
    tokens: str = Query("", max_length=8000),
    db: Session = Depends(get_db),
):
    """非重要通知的校徽唯一地址：图片被加载时顺手标记已读

    **只用于非重要通知**：发送侧不会把重要通知的校徽换成这个地址。
    开关关掉后，已经发出去的旧邮件再被加载也不会标记 —— 这里每次都重新读配置。
    无效令牌、消息已删都不报错，照样返回校徽，避免邮箱里出现破图。
    """
    if settings.email_open_auto_read:
        _mark_email_tokens(db, _parse_email_tokens(tokens))

    base = settings.public_base_url.rstrip("/")
    if base:
        # 302 到真正的静态校徽：图片内容不经过后端，也避免在仓库里再存一份
        return RedirectResponse(
            f"{base}/logo.png?v=1",
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=_TRANSPARENT_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store"},
    )


def _result_page(title: str, message: str, status_code: int = 200) -> HTMLResponse:
    """结果页：和邮件同一套配色，单个卡片，不需要任何前端资源"""
    site = html_lib.escape(settings.site_name.strip() or settings.app_name)
    base = settings.public_base_url.rstrip("/")
    back = ""
    if base:
        back = (
            f'<p style="margin:18px 0 0;"><a href="{html_lib.escape(base, quote=True)}" '
            'style="color:#5b5bd6;font-size:13px;text-decoration:none;">'
            "返回站点</a></p>"
        )
    body = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_lib.escape(title)} - {site}</title></head>
<body style="margin:0;background:#eef0f7;font-family:-apple-system,BlinkMacSystemFont,
'Segoe UI','PingFang SC','Microsoft YaHei',Arial,sans-serif;">
<div style="max-width:420px;margin:12vh auto 0;padding:0 16px;">
<div style="background:#ffffff;border:1px solid #e2e4f2;border-radius:16px;
padding:30px 30px 26px;text-align:center;">
<div style="font-size:12px;letter-spacing:.12em;color:#8a90a5;margin-bottom:14px;">{site}</div>
<div style="font-size:20px;font-weight:700;color:#343a66;line-height:1.5;">{html_lib.escape(title)}</div>
<p style="margin:12px 0 0;color:#5f657b;font-size:14px;line-height:1.8;">{html_lib.escape(message)}</p>
{back}
</div></div></body></html>"""
    return HTMLResponse(
        body, status_code=status_code, headers={"Cache-Control": "no-store"}
    )


@router.post("/{message_id}/read", summary="标记一条为已读")
def read_message(
    message_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重复调用无副作用（前端点开就调，刷新后再点一次也不报错）

    不是自己的消息按「不存在」处理，不泄露「这个 id 存在但不归你」。
    """
    if not inbox_service.mark_read(db, user.student_no, message_id):
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"ok": True}


@router.post("/read-all", summary="全部标为已读")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"updated": inbox_service.mark_all_read(db, user.student_no)}


@router.delete("/read", summary="删除全部已读消息")
def delete_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """只删自己、只删已读的；未读消息一条不动。重复调用返回 0，无副作用。"""
    return {"deleted": inbox_service.delete_read(db, user.student_no)}
