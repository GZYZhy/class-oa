"""公开接口：仅供首页使用，只暴露最小必要字段，不含任何敏感信息"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Student
from sqlalchemy import func

router = APIRouter(prefix="/api/public", tags=["公开信息"])


@router.get("/summary", summary="首页公开摘要")
def summary(db: Session = Depends(get_db)):
    total = db.query(func.count(Student.id)).scalar()

    gender = dict(
        db.query(Student.gender, func.count(Student.id)).group_by(Student.gender).all()
    )
    political = dict(
        db.query(Student.political_status, func.count(Student.id))
        .group_by(Student.political_status)
        .all()
    )
    # 班委人数（职务非"无"）
    committee = (
        db.query(func.count(Student.id))
        .filter(Student.class_position.notin_(["无", ""]))
        .filter(Student.class_position.isnot(None))
        .scalar()
    )

    return {
        "total": total,
        "gender": gender,
        "political_status": political,
        "class_committee_count": committee,
    }
