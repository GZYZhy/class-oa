"""成绩（测验分数）模型

一次测试 = 一张成绩表：班委传一份 Excel（必须有「学号」列，其余列当科目），
系统按学号认人，学生在「我的信息 → 我的成绩」里只看自己的各科分数。

三张表：grade_tests（一次测试）→ grade_subjects（这次考了哪几科）
→ grade_items（某人某科的成绩，一格一行）。
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from ..database import Base

# 一格成绩只允许两种形态：分数，或下面这几个标记之一。
#
# **词表只定义这一份**：service 解析 Excel 时用它判合法，接口把它回显进预览和
# 详情响应里，前端不再自己抄一遍。项目里考勤那套是反例 ——
# api/attendance.py 的 STATUS_LABELS 和 schemas/attendance.py 的 STATUS_PATTERN
# 是同一个词表散在两处，改一处就两边不一致。
MARK_VALUES = ("缺考", "免修", "缓考", "违纪")

# 分数的上界。取 1000 这种宽口径是为了**永不误挡一张 150 分 / 200 分的卷子**，
# 而不是为了卡手滑 —— 「850」这种手滑靠在预览里把它标出来解决，
# 真靠范围去拦，早晚会拦下一张合法的满分卷。
MAX_SCORE = 1000

# 成绩形态。挂在**科目**上而不是整场测试上：一场考试里完全可以语文计分、
# 体育只记通过 / 不通过。
SUBJECT_MODES = ("score", "pass_fail")

# 通过制科目的取值词表。**不并进 MARK_VALUES**：那个词表是「没参加考试」的原因，
# 两种形态的科目都能填；通过 / 不通过是成绩本身，只有通过制科目能填。
PASS_VALUES = ("通过", "不通过")

# 及格线 = 满分 × 这个比例。分数段也按满分的百分比切（见 services.grade_service）
PASS_RATIO = 0.6

# 默认满分。绝大多数科目就是 100 分制；150 / 200 分制的在界面上改一次即可。
# 通过制科目用不上它，但仍保留这个值 —— 设为可空会让统计、前端、导入三处都要判空，
# 为一个用不上的场景不值得。
DEFAULT_FULL_SCORE = 100


class GradeTest(Base):
    """一次测试（一场卷子的成绩表）

    **不存科目数、不存录入人数**：两个数都从 grade_items / grade_subjects 聚合
    （services/grade_service）。存了就要在每次增删科目、每个格子改动时同步维护，
    两份数据迟早走散 —— 同 models/attendance.py 那条。

    `tested_at` 是**日期**而不是日期时间：一次测验「哪天考的」就够用了。
    同一天两场（上午语文、下午数学）靠 name 和 remark 区分。
    """
    __tablename__ = "grade_tests"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False, comment="测试名称，如「高数期中考」")
    tested_at = Column(Date, nullable=False, index=True, comment="测试日期")
    remark = Column(Text, default="", comment="备注")

    creator_no = Column(String(20), index=True, comment="录入人学号")
    # 姓名冗余一份：与 Poll.creator_name / LeaveRequest 同一口径，录入人删档后还读得懂
    creator_name = Column(String(50), comment="录入人姓名")

    created_at = Column(DateTime, default=datetime.now, comment="录入时间")


class GradeSubject(Base):
    """一次测试里的一门科目

    科目必须是**行**，不能像投票的选项那样塞 JSON 文本 —— 班委能随时增删科目列，
    而成绩是逐格存的：科目存 JSON 的话，加一列要把整行重写一遍，也没法给
    「某人在某科的成绩」建唯一约束。

    唯一约束 (test_id, name)：同一场测试不许有两个同名科目。Excel 表头重名、
    或确认时手滑传了重复的科目名，都靠它兜底。
    """
    __tablename__ = "grade_subjects"
    __table_args__ = (
        UniqueConstraint("test_id", "name", name="uq_grade_subject"),
    )

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, index=True, nullable=False, comment="所属测试 ID")
    name = Column(String(50), nullable=False, comment="科目名（来自 Excel 表头）")
    sort = Column(Integer, comment="列序（前端写 0..n-1，排序用 (sort, id)）")

    # 成绩形态：score（记分数）或 pass_fail（只记通过 / 不通过）。
    # **改形态要挡住已有数据**（改的落点是 api/grades.py，理由写在那儿）
    mode = Column(
        String(20), nullable=False, default="score",
        comment="score=计分 / pass_fail=通过制",
    )
    # 满分：决定及格线（满分 × PASS_RATIO）和分数段的划分
    full_score = Column(
        Float, nullable=False, default=DEFAULT_FULL_SCORE, comment="满分",
    )


class GradeItem(Base):
    """某人某科的成绩（一格一行）

    `score` 与 `mark` **二选一**：数字进 score，MARK_VALUES 里的词进 mark。
    不合成一个文本列，是因为数字存文本就没法排序、没法算统计，而且
    「85」与「85.0」两种写法会一直漂。

    **判空一律 `is not None`，不能写 `if item.score`** —— 0 分是合法成绩却是假值，
    真值判断会把 0 分当成「没录」。第一号实现陷阱。

    `test_id` 冗余一份、不靠 subject_id 绕：删整次测试时按它一把删干净
    （同 models/poll.py 给 PollAnswer 加 poll_id 的理由）。
    `student_name` 冗余一份：学生改名或毕业删档（student_service.delete_student
    是物理删）之后，历史成绩还读得懂 —— 同 models/attendance.py 的 AttendanceItem。
    """
    __tablename__ = "grade_items"
    __table_args__ = (
        # 一人一科一行。单格写入走 upsert，并发双击时两个请求可能都查不到旧行，
        # 只有一个插得进去、另一个撞约束 —— 接口把它转成中文提示而不是 500
        UniqueConstraint("subject_id", "student_no", name="uq_grade_item"),
    )

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, index=True, nullable=False, comment="所属测试 ID（冗余）")
    subject_id = Column(Integer, index=True, nullable=False, comment="所属科目 ID")

    student_no = Column(String(20), index=True, nullable=False, comment="学号")
    student_name = Column(String(50), comment="姓名（快照）")

    score = Column(Float, nullable=True, comment="分数；与 mark 二选一")
    mark = Column(String(20), nullable=True, comment="缺考/免修/缓考/违纪；与 score 二选一")
