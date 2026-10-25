"""关于班级：公开页，不登录也能查看

原来这一页是拉 /api/students 全量（500 条）在前端筛班委、再拉 /api/students/statistics
取人数，那两个接口收口到班委后普通学生就 403 了，所以单开一个只吐必要字段的接口。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Student, User
from ..schemas import AboutIntro, AboutResponse, CommitteeMember
from ..services.about_service import committee_members, get_settings, parse_order
from .deps import get_optional_user

router = APIRouter(prefix="/api/about", tags=["关于班级"])


@router.get(
    "",
    response_model=AboutResponse,
    summary="班级概况（公开：人数、性别分布、班委名单、简介）",
)
def about(_: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """公开页：返回的人数统计与班委名单不含任何联系方式或学号"""
    total = db.query(func.count(Student.id)).scalar()
    # 没填性别的学生（手工导入的旧数据可能有）不能带进响应：
    # schema 是 dict[str, int]，None 键会让整页 500。前端只读「男 / 女」两项
    gender = {
        value: count
        for value, count in db.query(
            Student.gender, func.count(Student.id)
        ).group_by(Student.gender).all()
        if value
    }

    cfg = get_settings(db)
    # 顺序是管理员在系统管理里排的；没排过就按学号
    members = committee_members(db, parse_order(cfg.roster_order))

    return AboutResponse(
        total=total,
        gender=gender,
        # 只返回姓名和职务，不带手机号等任何联系方式
        committee=[CommitteeMember(name=m.name, position=m.class_position) for m in members],
        # 顺手带出版本号，省得这一页再单独请求一次 /api/health
        version=settings.app_version,
        intro=AboutIntro(enabled=bool(cfg.intro_enabled), markdown=cfg.intro_markdown or ""),
        roster_enabled=bool(cfg.roster_enabled),
    )
