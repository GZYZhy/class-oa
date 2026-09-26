import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Notice, User
from ..schemas import NoticeCreate, NoticeResponse
from ..services import (
    account_name,
    clip,
    list_notices,
    create_notice,
    update_notice,
    delete_notice,
    log_operation,
    notify,
    recipients,
)
from .deps import committee_required, get_client_ip

router = APIRouter(prefix="/api/notices", tags=["通知公告"])


def _preview(markdown: str) -> str:
    """从 Markdown 正文里摘一句纯净文本做通知正文

    正文是 Markdown，原样推过去手机上会看到「##」「![]()」这些符号，
    通知栏又没地方渲染。只取第一段有内容的文字，并去掉链接/图片的语法。
    """
    for line in markdown.splitlines():
        text = line.strip().lstrip("#>*+- \t").strip()
        text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text).strip()
        if text:
            return clip(text, 80)
    return "点击查看详情"


# 通知列表公开（首页性质，无需登录）
@router.get("", response_model=list[NoticeResponse], summary="通知列表")
def get_list(
    title: str | None = Query(None, description="按标题搜索（模糊）"),
    start_date: str | None = Query(None, description="发布时间起始"),
    end_date: str | None = Query(None, description="发布时间截止"),
    db: Session = Depends(get_db),
):
    return list_notices(db, title=title, start_date=start_date, end_date=end_date)


# 以下管理操作需要班委及以上
@router.post("", response_model=NoticeResponse, summary="发布通知（班委及以上）")
def publish(
    notice: NoticeCreate,
    background: BackgroundTasks,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    data = notice.model_dump()
    # 发布人一律取当前登录账号的展示名，前端即便传了 publisher 也不作数。
    # 用 account_name 而不是学生表：域外账号（老师）也可能有班委权限
    data["publisher"] = account_name(db, user)
    created = create_notice(db, data)
    log_operation(db, user, "发布通知", target=created.title, ip=ip)
    # 先取收件人：下面 commit 之后才算真的发出去了
    targets = recipients(db, exclude_no=user.student_no)
    db.commit()

    # 通知人人可见，所以推给全体（发布者自己不用收）。只是知会，active 就够
    notify(
        background, targets, f"新通知：{created.title}",
        _preview(created.content or ""), level="active", page="/notices",
    )
    return created


@router.put("/{notice_id}", response_model=NoticeResponse, summary="编辑通知（班委及以上）")
def edit(
    notice_id: int,
    notice: NoticeCreate,
    user: User = Depends(committee_required),
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    updated = update_notice(db, notice_id, notice.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="通知不存在")
    log_operation(db, user, "编辑通知", target=updated.title, detail=f"原发布人：{updated.publisher}", ip=ip)
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
    title = notice.title  # 先取出来：删除并 commit 后再访问属性会报 ObjectDeletedError
    delete_notice(db, notice_id)
    log_operation(db, user, "删除通知", target=title, ip=ip)
    db.commit()
    return {"message": "删除成功"}
