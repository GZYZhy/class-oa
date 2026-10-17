"""签到式点名模型

和「考勤记录」是两回事：这里存的是**签到会话本身**（谁发的、截止到什么时候、
要求什么），结算之后才生成一条普通的 `AttendanceRecord` + `AttendanceItem`。
学生端的签到结果挂在 `CheckinTarget` 上，一人一行。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)

from ..database import Base


class Checkin(Base):
    """一次签到

    `code` 是链接里的随机串，公开信息页只认它 —— 不知道 code 就打不开，
    也就不需要把签到做成「登录后按 id 猜」的接口。
    """
    __tablename__ = "checkins"

    id = Column(Integer, primary_key=True, index=True)

    # 12 位 URL 安全随机串。唯一索引兜底：理论上撞了也插不进去
    code = Column(String(32), unique=True, index=True, comment="链接里的随机码")

    title = Column(String(100), comment="标题")
    remark = Column(String(500), default="", comment="备注，空串 = 没写")

    created_by_no = Column(String(20), comment="发布人学号")
    created_by_name = Column(String(50), comment="发布人姓名（快照）")
    created_at = Column(DateTime, default=datetime.now, comment="发布时间")

    end_at = Column(DateTime, index=True, comment="截止时间")
    closed_at = Column(DateTime, comment="提前结束的时刻，可空")

    require_photo = Column(Boolean, default=False, comment="是否要求上传一张照片")

    # 地点四件套：有坐标才算要求定位，只填地点名不算
    lat = Column(Float, comment="签到地点纬度（GCJ-02）")
    lng = Column(Float, comment="签到地点经度（GCJ-02）")
    radius_m = Column(Integer, comment="允许的偏移范围（米）")
    location_name = Column(String(200), default="", comment="地点名称（可手填）")

    finalized_at = Column(DateTime, index=True, comment="结算时刻，可空")
    # 结算生成的考勤记录。删除考勤时要靠它拦住「删了记录、签到还指着它」的情况
    attendance_record_id = Column(Integer, index=True, comment="结算生成的考勤记录 ID")


class CheckinTarget(Base):
    """某次签到里被点名到的一个人

    `student_name` 冗余存一份：学生改名或毕业删档后，历史签到还读得懂
    （与 AttendanceItem / LeaveRequest 同一口径）。
    """
    __tablename__ = "checkin_targets"
    __table_args__ = (
        # 同一场签到里一个人只能有一行：否则重复签到会插出第二条
        UniqueConstraint("checkin_id", "student_no", name="uq_checkin_target"),
    )

    id = Column(Integer, primary_key=True, index=True)
    checkin_id = Column(Integer, index=True, comment="所属签到 ID")

    student_no = Column(String(20), index=True, comment="学号")
    student_name = Column(String(50), comment="姓名（快照）")

    signed_at = Column(DateTime, comment="签到时刻，空 = 还没签")
    lat = Column(Float, comment="签到时的纬度（GCJ-02）")
    lng = Column(Float, comment="签到时的经度（GCJ-02）")
    distance_m = Column(Integer, comment="离签到地点的距离（米）")
    photo_file = Column(String(100), comment="签到照片文件名（data/checkins 下）")
    ip = Column(String(64), comment="签到时的客户端 IP")
