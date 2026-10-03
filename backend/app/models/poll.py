"""投票（表决）模型

一次投票 = 一张含多道题的卷子。班委出卷时定题目、选项、参与范围、起止时间，
以及记名还是不记名；范围内的人在截止前整卷作答一次。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from ..database import Base


class Poll(Base):
    """一次投票（一张卷子）

    **状态不落库**：未开始 / 进行中 / 已结束由 start_at、end_at、closed_at
    三个时刻现算（services/poll_service.poll_status）。存一个 status 列就要在
    到点时有人去改它，而本项目没有为投票转的调度线程 —— 算出来的状态永远不会过期。

    `closed_at` 是「立即结束」按下的时刻，单独一列而不直接改写 end_at：
    改了就再也看不出这场原本打算什么时候截止。
    """
    __tablename__ = "polls"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(200), nullable=False, comment="标题")
    description = Column(Text, default="", comment="描述")

    # 不记名。库里的作答**照存学号** —— 匿名只在接口层保证（见 api/polls.py），
    # 这一列管的是「接口要不要把谁投了什么返回出去」
    anonymous = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否不记名",
    )

    start_at = Column(DateTime, nullable=False, comment="开始时间")
    end_at = Column(DateTime, nullable=False, comment="截止时间")
    closed_at = Column(DateTime, nullable=True, comment="手动结束的时刻，空=没手动结束")

    creator_no = Column(String(20), index=True, comment="发起人学号")
    # 姓名冗余一份：与 LeaveRequest / AttendanceItem 同一口径，发起人删档后投票还读得懂
    creator_name = Column(String(50), comment="发起人姓名")

    created_at = Column(DateTime, default=datetime.now, comment="发起时间")


class PollTarget(Base):
    """谁有权表决（一人一行）

    单开一张表而不是把学号数组塞进 polls 的一列：投票列表要按「我在不在范围内」
    过滤**并分页**，必须能在 SQL 里查（api/polls.py 的列表接口用 IN 子查询）。
    它同时是投票率的分母和催票的名单来源。

    姓名冗余一份是**必须的**，不是可选：还没投的人在其他表里根本没有行，
    「谁还没投」这份名单只能从这张表出；而学生毕业删档时账号和学生行都会被物理
    删掉（services/student_service.py 的 delete_student），不冗余姓名就只剩一串学号。
    """
    __tablename__ = "poll_targets"
    __table_args__ = (
        UniqueConstraint("poll_id", "student_no", name="uq_poll_target"),
    )

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, index=True, comment="所属投票 ID")

    student_no = Column(String(20), index=True, comment="学号")
    student_name = Column(String(50), comment="姓名")


class PollQuestion(Base):
    """投票里的一道题

    选项存 JSON 文本而不单开一张表，理由同 Feedback.attachments：选项只在展示时
    用，不需要单独查询、不需要外键，同一行自带还能让详情接口零额外查询。
    代价是票数没法在 SQL 里按选项 GROUP BY，只能在 Python 侧聚合
    （services/poll_service.tally）—— 班级几十人，这个量级无所谓。

    **发起之后不提供编辑**（api/polls.py 没有编辑接口）：作答存的是选项**下标**，
    能改题目的话，删掉一个选项会让历史作答的下标整体错位。
    """
    __tablename__ = "poll_questions"

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, index=True, comment="所属投票 ID")
    sort = Column(Integer, comment="题号（前端写 0..n-1，排序用 (sort, id)）")

    title = Column(String(500), comment="题干")
    multiple = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="单选还是多选",
    )
    max_choices = Column(Integer, comment="多选时最多选几项；单选恒为 1")
    options = Column(Text, default="", comment="选项文案（JSON 数组）")


class PollAnswer(Base):
    """一个人对一道题的作答

    一人一卷**整卷一次提交**：一次请求把这张卷子上每道题的行一起写进来，
    **投过就不能再投**（api/polls.py 的 vote 直接 400）。于是「已投」= 这张表里
    有没有我的行，不需要另开一张「投票凭证」表。前提是**每题必答**：
    允许空选的话，全弃权的人一行都没有，看起来就像没投过。

    `poll_id` 单独存一份、不靠 question_id 绕：删投票时按它一把删干净。
    """
    __tablename__ = "poll_answers"
    __table_args__ = (
        # 一人一题一行。既然不许改票，这条约束就是防重复提交的最后一道闸 ——
        # 同一人并发点两次，或者前端在提交中又点了一次，都靠它挡下
        UniqueConstraint("question_id", "student_no", name="uq_poll_answer"),
    )

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, index=True, comment="所属投票 ID")
    question_id = Column(Integer, index=True, comment="所属题目 ID")
    # 库里存了学号、join 得出身份，接口层才是不记名的（api/polls.py 的说明）
    student_no = Column(String(20), index=True, comment="学号")

    choices = Column(Text, default="", comment="选中选项的下标（JSON 数组）")
    answered_at = Column(DateTime, default=datetime.now, comment="提交时间")
