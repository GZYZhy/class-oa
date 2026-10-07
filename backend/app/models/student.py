from sqlalchemy import Column, Integer, String, Date, DateTime, Text

from ..database import Base


class Student(Base):
    """学生信息表"""
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True, comment="自增ID")
    student_no = Column(String(20), unique=True, index=True, comment="学号")
    name = Column(String(50), index=True, comment="姓名")
    gender = Column(String(10), index=True, comment="性别")
    major = Column(String(100), comment="专业")
    class_name = Column(String(50), index=True, comment="班级")
    birth_date = Column(Date, comment="出生日期")
    ethnicity = Column(String(50), index=True, comment="民族")
    political_status = Column(String(50), index=True, comment="政治面貌")
    hometown = Column(String(200), index=True, comment="生源地")
    id_card = Column(String(20), comment="身份证号")
    exam_no = Column(String(20), comment="考生号")
    exam_category = Column(String(50), comment="考生类别")
    subject_type = Column(String(50), comment="科类")
    exam_type = Column(String(50), comment="考试类型")
    admission_batch = Column(String(50), comment="录取批次")
    gaokao_score = Column(Integer, comment="高考总分")
    high_school = Column(String(200), comment="毕业中学")
    registration_status = Column(String(20), comment="报到状态")
    registration_time = Column(DateTime, comment="报到时间")
    school_status = Column(String(20), default="正常", comment="在校状态")
    phone = Column(String(50), comment="本人电话")
    family_phone = Column(String(100), comment="家庭电话")
    qq = Column(String(20), comment="QQ号码")
    email = Column(String(100), comment="本人电子邮箱")
    family_address = Column(String(500), comment="家庭通信地址")
    postal_code = Column(String(10), comment="邮政编码")
    dormitory = Column(String(50), index=True, comment="宿舍")
    bed = Column(String(20), comment="床位")
    class_position = Column(String(100), comment="班委职务")
    league_position = Column(String(100), comment="团学会职务")
    is_poor = Column(String(10), default="否", comment="是否贫困生")
    remark = Column(Text, comment="备注（Markdown）")
    # 备注附件列表，JSON 字符串（格式与 notices.attachments 一致）。
    # 格式：[{"file": "uuid名", "name": "原始名", "size": 12345}, ...]
    remark_attachments = Column(Text, default="", comment="备注附件列表（JSON）")
    gaokao_photo = Column(String(200), comment="高考照片路径")
    on_site_photo = Column(String(200), comment="实地采集照片路径")
    id_photo = Column(String(200), comment="自备证件照路径")
