"""关于班级：登录即可查看（普通学生也能打开这一页）

原来这一页是拉 /api/students 全量（500 条）在前端筛班委、再拉 /api/students/statistics
取人数，那两个接口收口到班委后普通学生就 403 了，所以单开一个只吐必要字段的接口。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Student, User
from ..schemas import AboutResponse, CommitteeMember
from .deps import get_current_user

router = APIRouter(prefix="/api/about", tags=["关于班级"])


@router.get("", response_model=AboutResponse, summary="班级概况（人数、性别分布、班委名单）")
def about(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total = db.query(func.count(Student.id)).scalar()
    gender = dict(
        db.query(Student.gender, func.count(Student.id)).group_by(Student.gender).all()
    )

    # 只返回姓名和职务，不带手机号等任何联系方式
    members = (
        db.query(Student)
        .filter(Student.class_position.isnot(None), Student.class_position.notin_(["", "无"]))
        .order_by(Student.student_no)
        .all()
    )

    return AboutResponse(
        total=total,
        gender=gender,
        committee=[CommitteeMember(name=m.name, position=m.class_position) for m in members],
    )
