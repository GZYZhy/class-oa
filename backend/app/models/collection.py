"""投票收集模型

和「投票表决」是两个独立的东西，刻意不共用 polls / poll_answers：

- 投票是**一人一卷、不许改票**，`poll_answers` 上有 `UNIQUE(question_id, student_no)`，
  数据库层面就只允许一份；
- 收集允许**每人多份**、有提交单、要按提交时间排序/删除/导出，还需要文本、图片、评分。

把两者塞进同一张表就得重建 `poll_answers` 并迁移老数据，风险远大于多写几张表。
所以收集从 `Collection` 开始另起一套，投票原样不动。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from ..database import Base


class Collection(Base):
    """一次收集活动

    状态不落库：未开始 / 进行中 / 已暂停 / 已结束由 start_at、end_at、paused_at、
    closed_at 现算（services/collection_service.collection_status）。

    `response_count` 是**竞争名额的原子计数器**：只收前 X 份时，提交用
    `UPDATE ... WHERE response_count < max_responses` 抢占名额，删除时同事务减一。
    不能用「先 COUNT 再 INSERT」，并发下会超收。
    """
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(200), nullable=False, comment="标题")
    description = Column(Text, default="", comment="详细说明（Markdown）")

    # 和投票一样：库里照存学号（配额、催办要用），匿名只在接口层保证
    anonymous = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否不记名",
    )
    # 由出卷人指定；仅进行中/暂停中可撤回，结束后答卷定稿不可撤
    allow_withdraw = Column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="是否允许答题人撤回自己的答卷",
    )

    start_at = Column(DateTime, nullable=False, comment="开始时间")
    end_at = Column(DateTime, nullable=False, comment="截止时间")
    closed_at = Column(DateTime, nullable=True, comment="手动结束的时刻，空=没手动结束")
    # 暂停不是结束：只暂时不收答卷，恢复后还能继续填；到点仍照常自动结束。
    # 只有进行中的收集能暂停（和投票的 locked_at 同一口径）
    paused_at = Column(DateTime, nullable=True, comment="暂停的时刻，空=没暂停")

    creator_no = Column(String(20), index=True, comment="发起人学号")
    creator_name = Column(String(50), comment="发起人姓名（冗余，删档后仍可读）")
    created_at = Column(DateTime, default=datetime.now, comment="发起时间")

    # 开始时提醒：出卷人指定；由 services/start_notify_service.py 在 start_at 到达时
    # 发一次，创建时不发。老投票升级时不会补发（见 database_migrate）。
    notify_on_start = Column(
        Boolean, nullable=False, default=True, server_default=text("1"),
        comment="到开始时间是否提醒范围内的人",
    )
    start_notified_at = Column(
        DateTime, nullable=True, comment="开始提醒已发送的时刻，空=还没发",
    )

    submit_quota = Column(
        Integer, nullable=False, default=1, server_default=text("1"),
        comment="每人最多可填几份",
    )
    # 空 = 不限；非空 = 只收前 N 份（竞争性填写）
    max_responses = Column(Integer, nullable=True, comment="全局最多收几份，空=不限")
    response_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="已收答卷份数（竞争名额的原子计数器）",
    )


class CollectionTarget(Base):
    """可填写的人员范围（一人一行）

    和 PollTarget 同构：范围来源、完成率分母、催填名单都靠它。姓名冗余一份，
    学生删档后「谁还没填」仍然读得懂。
    """
    __tablename__ = "collection_targets"
    __table_args__ = (
        UniqueConstraint("collection_id", "student_no", name="uq_collection_target"),
    )

    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(Integer, index=True, comment="所属收集 ID")
    student_no = Column(String(20), index=True, comment="学号")
    student_name = Column(String(50), comment="姓名")


class CollectionQuestion(Base):
    """收集里的一道题

    题型（qtype）：
      single / multiple        选择题，options 存 JSON 数组，作答存下标
      short_text / long_text   文本，长度上限是常量（200 / 2000）
      image                    图片，每题最多 3 张、单张 10MB
      rating                   评分，固定 1–5

    有答卷之后题目结构锁定（api/collections.py 的 update_collection），
    理由同投票：作答存的是选项下标，改选项会让历史答卷错位。
    """
    __tablename__ = "collection_questions"

    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(Integer, index=True, comment="所属收集 ID")
    sort = Column(Integer, comment="题号（前端写 0..n-1，排序用 (sort, id)）")

    title = Column(String(500), comment="题干")
    qtype = Column(
        String(20), nullable=False, default="single", server_default=text("'single'"),
        comment="single/multiple/short_text/long_text/image/rating",
    )
    required = Column(
        Boolean, nullable=False, default=True, server_default=text("1"),
        comment="是否必答",
    )
    # 仅选择题使用；文本/图片/评分题为空
    options = Column(Text, default="", comment="选项文案（JSON 数组）")
    max_choices = Column(Integer, nullable=True, comment="多选题最多选几项")


class CollectionSubmission(Base):
    """一份答卷（一次提交）

    这是收集和投票最根本的区别：投票没有「提交单」，一次作答散成每题一行；
    收集以提交单为单位，删除、排序、导出、配额计数都围绕它。

    `seq_no` 是**这个人在这场收集里的第几份**，和 (collection_id, student_no)
    一起唯一：并发连点两下时，数据库会挡住第二份相同的 seq。
    """
    __tablename__ = "collection_submissions"
    __table_args__ = (
        UniqueConstraint(
            "collection_id", "student_no", "seq_no", name="uq_collection_submission_seq"
        ),
        Index("ix_collection_submissions_poll_time", "collection_id", "submitted_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(Integer, index=True, comment="所属收集 ID")
    student_no = Column(String(20), index=True, comment="学号（匿名只在接口层隐藏）")
    seq_no = Column(Integer, nullable=False, comment="这个人的第几份，从 1 开始")
    submitted_at = Column(DateTime, default=datetime.now, index=True, comment="提交时间")


class CollectionAnswer(Base):
    """一份答卷里的一道题

    一份提交会写多条：答过的题各一条。选答题没答就不写行，
    「至少答一道题」由接口保证。
    """
    __tablename__ = "collection_answers"
    __table_args__ = (
        UniqueConstraint("submission_id", "question_id", name="uq_collection_answer"),
    )

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, index=True, comment="所属提交单 ID")
    question_id = Column(Integer, index=True, comment="所属题目 ID")

    # 选择题：选项下标 JSON；文本：原文；评分：1–5；图片：文件元信息 JSON
    choices = Column(Text, default="", comment="选中选项的下标（JSON 数组）")
    text_value = Column(Text, default="", comment="短文本/长文本的原文")
    rating = Column(Integer, nullable=True, comment="评分 1–5")
    files = Column(Text, default="", comment="图片列表 JSON [{name, original, size}]")
