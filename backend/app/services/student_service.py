from datetime import date
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Student
from ..schemas import StudentCreate, StudentUpdate


def get_student(db: Session, student_id: int) -> Optional[Student]:
    """根据ID获取学生信息"""
    return db.query(Student).filter(Student.id == student_id).first()


def get_student_by_no(db: Session, student_no: str) -> Optional[Student]:
    """根据学号获取学生信息"""
    return db.query(Student).filter(Student.student_no == student_no).first()


def get_students(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    keyword: Optional[str] = None,
    gender: Optional[str] = None,
    ethnicity: Optional[str] = None,
    political_status: Optional[str] = None,
    hometown: Optional[str] = None,
    dormitory: Optional[str] = None,
    class_position: Optional[str] = None,
    league_position: Optional[str] = None,
    is_poor: Optional[str] = None,
    school_status: Optional[str] = None,
    birthday_days: Optional[int] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "asc",
) -> tuple[list[Student], int]:
    """
    分页查询学生列表，支持多条件筛选和排序

    返回：(学生列表, 总数)
    """
    query = db.query(Student)

    # 关键词搜索（姓名、学号、班级、宿舍）
    if keyword:
        keyword_pattern = f"%{keyword}%"
        query = query.filter(
            (Student.name.like(keyword_pattern))
            | (Student.student_no.like(keyword_pattern))
            | (Student.class_name.like(keyword_pattern))
            | (Student.dormitory.like(keyword_pattern))
            | (Student.hometown.like(keyword_pattern))
            | (Student.league_position.like(keyword_pattern))
        )

    # 分类筛选
    if gender:
        query = query.filter(Student.gender == gender)
    if ethnicity:
        query = query.filter(Student.ethnicity == ethnicity)
    if political_status:
        query = query.filter(Student.political_status == political_status)
    if hometown:
        query = query.filter(Student.hometown.like(f"%{hometown}%"))
    if dormitory:
        query = query.filter(Student.dormitory.like(f"%{dormitory}%"))
    if class_position and class_position != "无":
        query = query.filter(Student.class_position != "无")
    elif class_position == "无":
        query = query.filter((Student.class_position == "无") | (Student.class_position.is_(None)))
    if league_position and league_position != "无":
        query = query.filter(Student.league_position != "无")
    elif league_position == "无":
        query = query.filter((Student.league_position == "无") | (Student.league_position.is_(None)))
    if is_poor:
        query = query.filter(Student.is_poor == is_poor)
    if school_status:
        query = query.filter(Student.school_status == school_status)

    # 未来 N 天内过生日（只比较月-日，自动跨年）
    if birthday_days is not None:
        from datetime import timedelta
        today = date.today()
        target_dates = {(today + timedelta(days=i)).strftime("%m-%d") for i in range(birthday_days + 1)}
        # SQLite strftime 提取月日，与候选集合匹配
        query = query.filter(
            func.strftime("%m-%d", Student.birth_date).in_(target_dates)
        )

    # 总数
    total = query.count()

    # 排序
    if sort_by:
        # 允许排序的字段映射，防止注入
        sort_columns = {
            "name": Student.name,
            "student_no": Student.student_no,
            "birth_date": Student.birth_date,
            "gaokao_score": Student.gaokao_score,
            "dormitory": Student.dormitory,
            "registration_time": Student.registration_time,
        }
        col = sort_columns.get(sort_by, Student.student_no)
        if sort_order == "desc":
            query = query.order_by(col.desc())
        else:
            query = query.order_by(col.asc())
    else:
        query = query.order_by(Student.student_no.asc())

    # 分页
    items = query.offset(skip).limit(limit).all()

    return items, total


def get_statistics(db: Session) -> dict:
    """获取各类统计数据"""
    total = db.query(func.count(Student.id)).scalar()

    # 性别统计
    gender_stats = dict(
        db.query(Student.gender, func.count(Student.id))
        .group_by(Student.gender)
        .all()
    )

    # 民族统计
    ethnicity_stats = dict(
        db.query(Student.ethnicity, func.count(Student.id))
        .group_by(Student.ethnicity)
        .order_by(func.count(Student.id).desc())
        .all()
    )

    # 政治面貌统计
    political_stats = dict(
        db.query(Student.political_status, func.count(Student.id))
        .group_by(Student.political_status)
        .all()
    )

    # 宿舍统计
    dormitory_stats = dict(
        db.query(Student.dormitory, func.count(Student.id))
        .group_by(Student.dormitory)
        .order_by(Student.dormitory.asc())
        .all()
    )

    # 贫困生统计
    poor_stats = dict(
        db.query(Student.is_poor, func.count(Student.id))
        .group_by(Student.is_poor)
        .all()
    )

    # 班委统计（非"无"且非空）
    class_committee_count = (
        db.query(func.count(Student.id))
        .filter(Student.class_position.notin_(["无", ""]))
        .filter(Student.class_position.isnot(None))
        .scalar()
    )

    # 团学会统计
    league_count = (
        db.query(func.count(Student.id))
        .filter(Student.league_position.notin_(["无", ""]))
        .filter(Student.league_position.isnot(None))
        .scalar()
    )

    # 高考分数区间统计
    score_ranges = [
        ("600分以上", 600, 999),
        ("550-599分", 550, 599),
        ("500-549分", 500, 549),
        ("450-499分", 450, 499),
        ("450分以下", 0, 449),
    ]
    score_stats = {}
    for label, low, high in score_ranges:
        count = (
            db.query(func.count(Student.id))
            .filter(Student.gaokao_score >= low)
            .filter(Student.gaokao_score <= high)
            .scalar()
        )
        if count:
            score_stats[label] = count

    # 在校状态统计
    status_stats = dict(
        db.query(Student.school_status, func.count(Student.id))
        .group_by(Student.school_status)
        .all()
    )

    # 考生类别统计
    exam_category_stats = dict(
        db.query(Student.exam_category, func.count(Student.id))
        .group_by(Student.exam_category)
        .order_by(func.count(Student.id).desc())
        .all()
    )
    # 过滤掉 None
    exam_category_stats = {k: v for k, v in exam_category_stats.items() if k}

    # 科类统计
    subject_type_stats = dict(
        db.query(Student.subject_type, func.count(Student.id))
        .group_by(Student.subject_type)
        .order_by(func.count(Student.id).desc())
        .all()
    )
    subject_type_stats = {k: v for k, v in subject_type_stats.items() if k}

    # 录取批次统计
    admission_stats = dict(
        db.query(Student.admission_batch, func.count(Student.id))
        .group_by(Student.admission_batch)
        .order_by(func.count(Student.id).desc())
        .all()
    )
    admission_stats = {k: v for k, v in admission_stats.items() if k}

    # 考试类型统计
    exam_type_stats = dict(
        db.query(Student.exam_type, func.count(Student.id))
        .group_by(Student.exam_type)
        .order_by(func.count(Student.id).desc())
        .all()
    )
    exam_type_stats = {k: v for k, v in exam_type_stats.items() if k}

    # 班委职务明细统计
    class_position_stats = dict(
        db.query(Student.class_position, func.count(Student.id))
        .filter(Student.class_position.notin_(["无", ""]))
        .filter(Student.class_position.isnot(None))
        .group_by(Student.class_position)
        .order_by(func.count(Student.id).desc())
        .all()
    )

    # 团学会职务明细统计
    league_position_stats = dict(
        db.query(Student.league_position, func.count(Student.id))
        .filter(Student.league_position.notin_(["无", ""]))
        .filter(Student.league_position.isnot(None))
        .group_by(Student.league_position)
        .order_by(func.count(Student.id).desc())
        .all()
    )

    # 生源地省份统计（取省/直辖市/自治区级别）
    # 从生源地字段提取省份信息
    all_hometowns = [row[0] for row in db.query(Student.hometown).all() if row[0]]
    province_stats = {}
    for ht in all_hometowns:
        # 简单提取：取第一个省/市/区级别的关键字
        province = ht[:2] if len(ht) >= 2 else ht
        if "省" in ht:
            province = ht.split("省")[0] + "省"
        elif "市" in ht and ("北京" in ht or "上海" in ht or "天津" in ht or "重庆" in ht):
            province = ht[:3] if "市" not in ht[:3] else ht[:ht.index("市")+1]
        elif "自治区" in ht:
            # 取到自治区
            idx = ht.find("自治区")
            province = ht[:idx+3]
        else:
            province = ht[:4] if len(ht) >= 4 else ht
        province_stats[province] = province_stats.get(province, 0) + 1

    # 按数量降序排序
    province_stats = dict(sorted(province_stats.items(), key=lambda x: x[1], reverse=True))

    # 年龄统计（根据出生日期计算年龄）
    from datetime import date
    today = date.today()
    age_stats = {}
    for row in db.query(Student.birth_date).all():
        bd = row[0]
        if bd:
            age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
            age_stats[age] = age_stats.get(age, 0) + 1
    age_stats = dict(sorted(age_stats.items()))

    # 出生月份统计
    birth_month_stats = {}
    for row in db.query(Student.birth_date).all():
        bd = row[0]
        if bd:
            month = f"{bd.month}月"
            birth_month_stats[month] = birth_month_stats.get(month, 0) + 1
    # 按月份顺序排
    month_order = [f"{i}月" for i in range(1, 13)]
    birth_month_stats = {k: birth_month_stats[k] for k in month_order if k in birth_month_stats}

    # 毕业中学统计
    high_school_stats = dict(
        db.query(Student.high_school, func.count(Student.id))
        .group_by(Student.high_school)
        .order_by(func.count(Student.id).desc())
        .all()
    )
    high_school_stats = {k: v for k, v in high_school_stats.items() if k}

    # 单元统计（宿舍格式为"单元-房间号"，如 3-701 表示三单元）
    unit_name_map = {"2": "二单元", "3": "三单元"}
    building_stats = {}
    for dorm, count in dormitory_stats.items():
        if dorm and '-' in dorm:
            unit_key = dorm.split('-')[0]
            unit_name = unit_name_map.get(unit_key, f"{unit_key}单元")
            building_stats[unit_name] = building_stats.get(unit_name, 0) + count
        elif dorm:
            building_stats[dorm] = building_stats.get(dorm, 0) + count

    # 高考分数统计（平均分、最高分、最低分）
    score_query = db.query(
        func.avg(Student.gaokao_score),
        func.max(Student.gaokao_score),
        func.min(Student.gaokao_score),
    ).filter(Student.gaokao_score.isnot(None)).first()

    score_summary = {
        "avg": round(score_query[0], 1) if score_query[0] else 0,
        "max": score_query[1] or 0,
        "min": score_query[2] or 0,
    }

    return {
        "total": total,
        "gender": gender_stats,
        "ethnicity": ethnicity_stats,
        "political_status": political_stats,
        "dormitory": dormitory_stats,
        "poor_student": poor_stats,
        "class_committee_count": class_committee_count,
        "league_count": league_count,
        "score_ranges": score_stats,
        "school_status": status_stats,
        # 新增统计
        "exam_category": exam_category_stats,
        "subject_type": subject_type_stats,
        "admission_batch": admission_stats,
        "exam_type": exam_type_stats,
        "class_positions": class_position_stats,
        "league_positions": league_position_stats,
        "provinces": province_stats,
        "ages": age_stats,
        "birth_months": birth_month_stats,
        "high_schools": high_school_stats,
        "buildings": building_stats,
        "score_summary": score_summary,
    }


def get_filter_options(db: Session) -> dict:
    """获取筛选下拉选项（各字段去重值）"""
    def _distinct_values(column):
        return [
            row[0] for row in db.query(column).distinct().order_by(column.asc()).all()
            if row[0] is not None and row[0] != ""
        ]

    return {
        "genders": _distinct_values(Student.gender),
        "ethnicities": _distinct_values(Student.ethnicity),
        "political_statuses": _distinct_values(Student.political_status),
        "dormitories": _distinct_values(Student.dormitory),
        "classes": _distinct_values(Student.class_name),
        "school_statuses": _distinct_values(Student.school_status),
    }


def create_student(db: Session, student: StudentCreate, commit: bool = True) -> Student:
    """创建学生信息

    commit=False 时只加进 session，事务边界交给调用方 —— 新增学生要连同他的
    登录账号一起提交，不能出现「学生建好了、账号没建上」这种半截状态。
    那种情况下对象还没有主键，调用方 commit 之后再用。
    """
    db_student = Student(**student.model_dump())
    db.add(db_student)
    if commit:
        db.commit()
        db.refresh(db_student)
    return db_student


def update_student(
    db: Session,
    student_id: int,
    student: StudentUpdate,
    allowed_fields: Optional[set[str]] = None,
) -> Optional[Student]:
    """更新学生信息

    allowed_fields 为 None 表示不限字段（管理员）；给了集合就只改集合里的字段，
    其余字段**静默忽略**（班委只能改备注），不再像以前那样无脑 setattr 全表。

    注意：前端传了白名单外的字段不会报错，只是不生效，调用方想记日志请自行对照白名单。
    """
    db_student = get_student(db, student_id)
    if not db_student:
        return None
    update_data = student.model_dump(exclude_unset=True)
    if allowed_fields is not None:
        update_data = {k: v for k, v in update_data.items() if k in allowed_fields}
    for key, value in update_data.items():
        setattr(db_student, key, value)
    db.commit()
    db.refresh(db_student)
    return db_student


def delete_student(db: Session, student_id: int, commit: bool = True) -> bool:
    """删除学生信息

    commit=False 的含义同 create_student：删学生要连同他的登录账号、推送订阅
    一起提交，交给调用方一次做完。
    """
    db_student = get_student(db, student_id)
    if not db_student:
        return False
    db.delete(db_student)
    if commit:
        db.commit()
    return True
