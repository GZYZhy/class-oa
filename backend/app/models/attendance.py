"""考勤（点名）记录模型"""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint

from ..database import Base


class AttendanceRecord(Base):
    """一次点名

    点名结果原先只在操作日志里留痕（见 services/log_service.py 开头那句），
    但 log_operation 会把 detail 截断到 500 字，缺席十来人名字就写不全，
    所以改成落库。顺带让请假数据第一次能用上：点名时落在已批准请假区间内的
    人自动记成 leave。
    """
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, index=True)

    # 字段名不叫 date：类体里一旦被 Column 占住这个名字，同一个类里再写
    # default=date.today 就会解析成那个 Column 对象（真实的手滑来源）
    call_date = Column(Date, index=True, comment="点名当天")
    # 存的就是前端那个中文字符串（全班 / 男生 / 女生）原样，不另造一套枚举 ——
    # 点名弹窗和考勤页说的得是同一个词
    scope = Column(String(10), comment="点名范围：全班/男生/女生")

    called_at = Column(DateTime, default=datetime.now, comment="点名时刻")
    operator_no = Column(String(20), comment="操作人学号")
    operator_name = Column(String(50), comment="操作人姓名")


class AttendanceItem(Base):
    """一次点名里某个人的状态

    **存被点到的每一个人**，不只是缺席的：明细要能改，把「到」改成「无应答」
    得先有一行可改；只存异常的话这个方向就得凭空 INSERT 一行出来。

    **不存任何计数列**（应到/实到/请假/无应答一律从明细聚合）：存了就要在每次
    改状态时同步维护，两份数据迟早走散。
    """
    __tablename__ = "attendance_items"
    __table_args__ = (
        # 没有它，PATCH 改的是哪一行是不确定的，重复上报还会插出重复行
        UniqueConstraint("record_id", "student_no", name="uq_attendance_item"),
    )

    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, index=True, comment="所属点名记录 ID")

    student_no = Column(String(20), index=True, comment="学号")
    # 人名冗余一份：学生改名或毕业删档后，历史考勤还读得懂（与 LeaveRequest 同一口径）
    student_name = Column(String(50), comment="姓名")

    status = Column(String(10), comment="present/absent/leave")
