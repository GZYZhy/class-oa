"""生日关怀：首页条幅（公开）+ 设置与测试（仅管理员）

放一个模块、导出两个 router，是因为它们共用同一份 service 和同一套文案函数；
也避免往已经 1000+ 行的 admin.py 里再塞东西。注册在 api/__init__.py 一次即可。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import BirthdaySettingsUpdate
from ..services import scheduler
from ..services.birthday_service import (
    DEFAULT_GREET_TEMPLATE,
    build_summary,
    check_template,
    get_settings,
    parse_notify_nos,
    put_settings,
    today_birthdays,
)
from ..services.notify_service import deliver_now, recipients
from .deps import admin_required, get_optional_user

# 首页条幅：公开（匿名可访问，但只给人数）
public_router = APIRouter(prefix="/api/birthday", tags=["生日关怀"])
# 设置与测试：仅管理员
admin_router = APIRouter(prefix="/api/admin/birthday", tags=["生日关怀"])


@public_router.get("/today", summary="今日生日（首页条幅）")
def today_banner(
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """首页条幅数据源

    **匿名只给人数，姓名只给登录用户**。关键在返回体本身：匿名分支里 names 恒为
    空数组 —— 不是「前端拿到再藏起来」，而是这个接口对未登录的人根本不吐姓名，
    直接 curl 也拿不到。年龄也不在这里给（年龄只进功能 3 的通知正文）。

    返回体形状恒定（四个字段永远都在），前端不用处理字段缺失。
    """
    cfg = get_settings(db)
    empty = {
        "enabled": bool(cfg.banner_enabled),
        "count": 0,
        "show_names": False,
        "names": [],
    }
    if not cfg.banner_enabled:
        return empty

    people = today_birthdays(db)
    if not people:
        return empty

    # 两个条件同时成立才给姓名：已登录 且 管理员开了「显示姓名」。
    # 匿名时 user 是 None，短路在前 —— 下面的开关读不读都碰不到姓名
    show_names = user is not None and bool(cfg.banner_show_names)
    return {
        "enabled": True,
        "count": len(people),
        "show_names": show_names,
        "names": [p["name"] for p in people] if show_names else [],
    }


@admin_router.get("/settings", summary="读取生日关怀设置")
def get_birthday_settings(_: User = Depends(admin_required), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    # 先算一次：next_run_at() 内部要查库，在 return 的字典里调两遍就白查一遍
    next_at = scheduler.next_run_at()
    return {
        "banner_enabled": bool(cfg.banner_enabled),
        "banner_show_names": bool(cfg.banner_show_names),
        "greet_enabled": bool(cfg.greet_enabled),
        "greet_template": cfg.greet_template or "",
        # 给前端当 placeholder，和真正发出去的那份必须是同一个常量
        "default_greet_template": DEFAULT_GREET_TEMPLATE,
        "notify_enabled": bool(cfg.notify_enabled),
        "notify_student_nos": parse_notify_nos(cfg.notify_student_nos),
        # ---------- 运行状态（只读，保存时不提交）----------
        # 让管理员看得见「上次什么时候自动跑过、跑出什么结果」，比只显示三个开关有用
        "last_run_date": cfg.last_run_date.isoformat() if cfg.last_run_date else None,
        "last_run_at": cfg.last_run_at.isoformat() if cfg.last_run_at else None,
        "last_run_birthdays": cfg.last_run_birthdays,
        "last_run_notices": cfg.last_run_notices,
        # 定时线程是不是活着。三种状态分开给，前端的文案也不同
        "scheduler_state": scheduler.state(),
        # None = 就在下一轮巡检里（今天已过点但还没跑），前端据此换一种说法
        "next_run_at": next_at.isoformat() if next_at else None,
    }


@admin_router.put("/settings", summary="保存生日关怀设置")
def update_birthday_settings(
    data: BirthdaySettingsUpdate,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    # 模板校验放在接口层、不放 schema：schema 里 import services 是反的依赖方向
    # （和 set_webhook 的写法一致）
    reason = check_template(data.greet_template)
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    cfg = put_settings(db, data)
    return {
        "message": "已保存",
        "last_run_date": cfg.last_run_date.isoformat() if cfg.last_run_date else None,
    }


@admin_router.post("/test", summary="给当前管理员自己发一条生日汇总测试消息")
def test_birthday_notify(user: User = Depends(admin_required), db: Session = Depends(get_db)):
    """手动触发一次功能 3 的汇总通知

    三个刻意的约束：

    1. **只发给当前管理员自己**，绝不发给 notify_student_nos 里勾选的那些账号 ——
       测试不该打扰别人。同 Bark / Webhook / 邮件测试端点「只发当前账号」的做法。
    2. **不写 last_run_date**：否则管理员早上 7:59 手点一下，08:00 真该发的那一轮
       就被幂等标记吃掉，而且不留任何痕迹。测试完全绕开标记，只调「组装 + 投递」。
    3. 文案调用的是和每日任务**同一个** build_summary()，所以测的就是真发的那段。

    数据用今天的真实寿星；今天没人过生日就用示例数据（否则一年 364 天没法验证格式），
    并在正文里标明是示例。
    """
    people = today_birthdays(db)
    if people:
        title, body = build_summary(people)
        prefix = "【测试】以下是今天的真实生日数据，正式通知不会带这个前缀。\n"
    else:
        title, body = build_summary([
            {"student_no": "", "name": "张三", "class_name": "", "age": 20},
            {"student_no": "", "name": "李四", "class_name": "", "age": 21},
        ])
        prefix = "【测试】今天没有人过生日，以下是示例数据，正式通知不会带这个前缀。\n"

    targets = recipients(db, only_no=user.student_no)
    if not targets:
        # 前端把 400 的 detail 直接弹给管理员（同 Bark 测试端点的「请先保存设备 ID」）
        raise HTTPException(
            status_code=400,
            detail="你还没有开启任何通知渠道，收不到测试消息。请先到「账户设置」里"
                   "开启 Bark、浏览器通知、Webhook 或邮件中的任意一个",
        )

    ok = deliver_now(targets, f"【测试】{title}", prefix + body, page="/dashboard")
    if not ok:
        # 同各渠道测试端点的口径：失败原因只有后端日志知道，不能把话说死成
        # 「你没配好」，否则用户会反复改一个本来没错的配置
        raise HTTPException(
            status_code=400,
            detail="测试消息没能发出去。请先确认你在「账户设置」里开启的渠道配置是否正确；"
                   "若确认无误仍失败，多半是服务器网络问题，请联系管理员",
        )
    return {"message": "已发送，请查看接收端（按你在「账户设置」里开启的渠道）"}


# 两个 router 并成一个导出，api/__init__.py 只需 include 一次
router = APIRouter()
router.include_router(public_router)
router.include_router(admin_router)
