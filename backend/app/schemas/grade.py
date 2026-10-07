"""成绩接口的出入参

**这里只放字段形状和长度上限，业务校验一律在 api/grades.py 里做**：schema 的
field_validator 抛异常会变成 422，而 detail 是个数组，前端 request.js 的
errText 遇到非字符串只会退回兜底文案（`typeof detail === 'string'` 那行），
所以「分数越没越界」「科目名在不在上传的表里」都得在接口里判，
好回一句能直接显示给用户的中文 —— 同 schemas/poll.py 顶部那条注释。
"""

from datetime import date, datetime

from pydantic import BaseModel, Field


# ---------- 上传预览 ----------

class GradeColumnPreview(BaseModel):
    """识别出来的一列

    keep_default 是服务端给的「这列看着像不像科目」的预判：序号 / 班级 / 总分
    这类常客默认不勾（界面上仍可勾回来）。它只是默认值，真正生效的是确认时
    传回来的 subjects。

    suggest_pass_fail 同理：整列的取值全是「通过 / 不通过」时预选通过制，
    班委在确认页上可改回来。
    """
    name: str
    keep_default: bool = True
    suggest_pass_fail: bool = False
    sample: list[str] = Field(default_factory=list, description="前几个非空值，帮班委判断该不该勾")


class GradeProblemRow(BaseModel):
    """一格没能解析出来的成绩

    原文 raw 一并返回：班委要照着它回 Excel 里改。
    """
    row: int
    student_no: str = ""
    column: str = ""
    raw: str = ""
    reason: str


class GradeUnmatchedRow(BaseModel):
    """学号在班级名单里查不到 —— 这一行不入库"""
    row: int
    student_no: str = ""
    student_name: str = ""
    reason: str


class GradeNameMismatchRow(BaseModel):
    """学号对得上、姓名对不上 —— 只提示，照样入库（学号才是身份）"""
    row: int
    student_no: str
    excel_name: str
    db_name: str


class GradeDuplicateRow(BaseModel):
    """同一个学号在表里出现了不止一次 —— 只有第一行生效"""
    row: int
    student_no: str


class GradePreviewResponse(BaseModel):
    """上传后的识别结果

    token 交给确认接口；10 分钟过期。**这里不写库**。
    """
    token: str
    sheet_name: str
    available_sheets: list[str]
    columns: list[GradeColumnPreview]
    sample_rows: list[dict] = Field(
        default_factory=list,
        description="前几行的原样回显：{学号, 姓名, 列名: 原值}",
    )
    student_count: int = Field(0, description="学号非空、能解析的行数")
    matched_count: int = Field(0, description="其中学号能在名单里找到的")
    unmatched: list[GradeUnmatchedRow] = Field(default_factory=list)
    name_mismatch: list[GradeNameMismatchRow] = Field(default_factory=list)
    duplicates: list[GradeDuplicateRow] = Field(default_factory=list)
    problems: list[GradeProblemRow] = Field(default_factory=list)
    mark_values: list[str] = Field(
        default_factory=list,
        description="允许的标记词表。服务端是唯一口径，前端照它显示、不再自己抄一份",
    )
    warnings: list[str] = Field(default_factory=list)


class GradeImportConfirm(BaseModel):
    """确认录入

    subjects 是**保留**的科目名（顺序即列序），必须是预览里 columns 的子集 ——
    班委在确认页勾掉「序号」这类列，靠的就是它。
    """
    token: str = Field(..., description="预览令牌")
    name: str = Field(..., max_length=100, description="测试名称")
    tested_at: date = Field(..., description="测试日期（YYYY-MM-DD）")
    remark: str = Field("", max_length=2000, description="备注")
    subjects: list[str] = Field(..., min_length=1, description="要录入的科目名，顺序即列序")
    subject_modes: dict[str, str] = Field(
        default_factory=dict,
        description="科目名 → score / pass_fail，没给的按计分",
    )
    subject_full_scores: dict[str, float] = Field(
        default_factory=dict,
        description="科目名 → 满分，没给的按 100（只对计分科目有意义）",
    )
    notify: bool = Field(True, description="录入后要不要给这些学生发通知")


class GradeImportResultResponse(BaseModel):
    test_id: int
    name: str
    subject_count: int
    student_count: int
    cell_count: int
    skipped: int = Field(0, description="没入库的行数（学号对不上 + 表内重复）")
    message: str
    warnings: list[str] = Field(default_factory=list)


# ---------- 列表 ----------

class GradeListItem(BaseModel):
    """列表里的一次测试

    两个计数是聚合算出来的，不是表里的列。
    """
    id: int
    name: str
    tested_at: date
    remark: str = ""
    creator_no: str = ""
    creator_name: str = ""
    created_at: datetime | None = None
    subject_count: int = 0
    student_count: int = 0


class GradeListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[GradeListItem]


# ---------- 学生看自己的 ----------

class MyGradeEntry(BaseModel):
    """我的某一科 + 它在这一科的位次

    **只给自己的位次**：平均分、最高最低、分数段、及格率属于班级层面的统计，
    一律班委及以上才看得到（用户口径）。

    rank_percent 是「排在班级前百分之几」= 名次 ÷ 有成绩人数 × 100，
    并列同分按最好名次算。只有计分科目、且我这一格确实是分数时才有值；
    通过制科目和缺考之类的标记词都是 None。
    scored_count 是那个分母（这一科实际有分数的人数），前端显示成「N 人有成绩」。
    """
    subject: str
    value: str = Field("", description="数字，或缺考/免修/缓考/违纪；空串 = 没录")
    mode: str = Field("score", description="score=计分 / pass_fail=通过制")
    rank_percent: float | None = Field(None, description="排在班级前百分之几；算不出来就是 null")
    scored_count: int = Field(0, description="这一科有成绩的人数")


class MyGradeItem(BaseModel):
    """我参加的一次测试"""
    test_id: int
    name: str
    tested_at: date
    remark: str = ""
    scores: list[MyGradeEntry] = Field(default_factory=list)


# ---------- 明细 ----------

class GradeSubjectResponse(BaseModel):
    id: int
    name: str
    sort: int = 0
    mode: str = Field("score", description="score=计分 / pass_fail=通过制")
    full_score: float = Field(100, description="满分；决定及格线与分数段划分")


class GradeDetailRow(BaseModel):
    """明细表里的一个学生"""
    student_no: str
    student_name: str = ""
    in_roster: bool = Field(True, description="还在学生表里；false = 只剩成绩里的快照（已删档）")
    school_status: str = ""
    values: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "键是 str(subject_id)，值是归一化后的成绩文本；空串 = 这格没录。"
            "**每行每科都给键**（不省略），前端 `row.values[String(s.id)]` 才不会踩到 undefined"
        ),
    )


class GradeDetailResponse(BaseModel):
    id: int
    name: str
    tested_at: date
    remark: str = ""
    creator_no: str = ""
    creator_name: str = ""
    created_at: datetime | None = None
    subjects: list[GradeSubjectResponse] = Field(default_factory=list)
    rows: list[GradeDetailRow] = Field(default_factory=list)
    mark_values: list[str] = Field(default_factory=list)
    subject_count: int = 0
    student_count: int = 0


# ---------- 编辑 ----------

class GradeTestUpdate(BaseModel):
    """改测试信息。三个字段都可选，只改传了的那些"""
    name: str | None = Field(None, max_length=100)
    tested_at: date | None = None
    remark: str | None = Field(None, max_length=2000)


class GradeSubjectCreate(BaseModel):
    name: str = Field(..., max_length=50, description="科目名")
    mode: str = Field("score", description="score=计分 / pass_fail=通过制")
    full_score: float = Field(100, gt=0, description="满分（只对计分科目有意义）")


class GradeSubjectUpdate(BaseModel):
    """改一科的形态 / 满分。两个都可选，只改传了的那些

    改形态会被接口挡住的事：那一科已有的数据和目标形态对不上（有分数却要改成
    通过制、有通过/不通过却要改成计分）。接口回 400 说清原因，不做静默清空。
    """
    mode: str | None = Field(None, description="score=计分 / pass_fail=通过制")
    full_score: float | None = Field(None, gt=0, description="满分")


# ---------- 统计（班委及以上） ----------

class GradeRangeBucket(BaseModel):
    """一个分数段。标签是**满分的百分比**，与满分具体是多少无关"""
    label: str
    count: int = 0


class GradeSubjectStat(BaseModel):
    """单科的统计条。**只有单科，没有总分**（模块里不存在这个概念）

    格子按三类分着数，加起来正好是统计范围里的人：
    有成绩的（scored_count，各种比例的分母）、有标记词的（marked_count，
    缺考/免修/缓考/违纪）、没录的（blank_count）。

    scored_count 按形态含义不同：计分科目是**有分数的**人数，通过制科目是
    **记了通过 / 不通过的**人数 —— 通过制没有分数，但两种情况下它都正好是
    pass_rate 的分母，前端也只显示这一个数。
    """
    subject_id: int
    name: str
    mode: str = "score"
    full_score: float = 100
    scored_count: int = 0
    marked_count: int = 0
    blank_count: int = 0
    # 计分科目才有
    avg: float | None = None
    max: float | None = None
    min: float | None = None
    pass_count: int = 0
    ranges: list[GradeRangeBucket] = Field(default_factory=list)
    # 通过制科目才有
    passed_count: int = 0
    failed_count: int = 0
    # 计分是及格率、通过制是通过率 —— 都是「达标比例」，前端按 mode 决定标题
    pass_rate: float | None = Field(None, description="百分比，0~100")


class GradeStatsResponse(BaseModel):
    test_id: int
    name: str
    tested_at: date
    subjects: list[GradeSubjectStat] = Field(default_factory=list)
    roster_count: int = Field(0, description="统计范围内的人数（名单上的 + 已删档但有成绩的）")


class GradeScoreIn(BaseModel):
    """写一个格子

    value **故意不设 max_length**：太长或内容不合法时，要由接口回一句
    「只能填 0~1000 之间的数字，或 缺考/免修/缓考/违纪」，而不是 422 让前端
    只能弹兜底文案 —— 这是班里最常出错的一格，文案必须具体。
    """
    student_no: str = Field(..., description="学号")
    subject_id: int = Field(..., description="科目 ID")
    value: str = Field("", description="空串 = 清空；分数；或标记词")


class GradeScoreResponse(BaseModel):
    student_no: str
    subject_id: int
    value: str
