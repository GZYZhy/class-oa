from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class StudentBase(BaseModel):
    """学生信息基础 schema"""
    student_no: Optional[str] = Field(None, description="学号")
    name: Optional[str] = Field(None, description="姓名")
    gender: Optional[str] = Field(None, description="性别")
    major: Optional[str] = Field(None, description="专业")
    class_name: Optional[str] = Field(None, description="班级")
    birth_date: Optional[date] = Field(None, description="出生日期")
    ethnicity: Optional[str] = Field(None, description="民族")
    political_status: Optional[str] = Field(None, description="政治面貌")
    hometown: Optional[str] = Field(None, description="生源地")
    id_card: Optional[str] = Field(None, description="身份证号")
    exam_no: Optional[str] = Field(None, description="考生号")
    exam_category: Optional[str] = Field(None, description="考生类别")
    subject_type: Optional[str] = Field(None, description="科类")
    exam_type: Optional[str] = Field(None, description="考试类型")
    admission_batch: Optional[str] = Field(None, description="录取批次")
    gaokao_score: Optional[int] = Field(None, description="高考总分")
    high_school: Optional[str] = Field(None, description="毕业中学")
    registration_status: Optional[str] = Field(None, description="报到状态")
    registration_time: Optional[datetime] = Field(None, description="报到时间")
    school_status: Optional[str] = Field("正常", description="在校状态")
    phone: Optional[str] = Field(None, description="本人电话")
    family_phone: Optional[str] = Field(None, description="家庭电话")
    qq: Optional[str] = Field(None, description="QQ号码")
    email: Optional[str] = Field(None, description="本人电子邮箱")
    family_address: Optional[str] = Field(None, description="家庭通信地址")
    postal_code: Optional[str] = Field(None, description="邮政编码")
    dormitory: Optional[str] = Field(None, description="宿舍")
    bed: Optional[str] = Field(None, description="床位")
    class_position: Optional[str] = Field(None, description="班委职务")
    league_position: Optional[str] = Field(None, description="团学会职务")
    is_poor: Optional[str] = Field("否", description="是否贫困生")
    remark: Optional[str] = Field(None, description="备注")
    gaokao_photo: Optional[str] = Field(None, description="高考照片URL")
    on_site_photo: Optional[str] = Field(None, description="实地采集照片URL")


class StudentCreate(StudentBase):
    """创建学生 schema"""
    student_no: str = Field(..., description="学号")
    name: str = Field(..., description="姓名")


class StudentUpdate(StudentBase):
    """更新学生 schema"""
    pass


class StudentResponse(StudentBase):
    """学生信息响应 schema"""
    id: int

    class Config:
        from_attributes = True


class StudentListResponse(BaseModel):
    """学生列表响应"""
    total: int
    items: list[StudentResponse]


class RollCallAbsentItem(BaseModel):
    """点名叫到但没人应答的一位同学"""
    student_no: str = Field(..., description="学号")
    name: str = Field(..., description="姓名")


class RollCallLogRequest(BaseModel):
    """点名结果上报

    只用来写一条操作日志，不落任何业务表 —— 点名结果本身没有留存价值，
    值得留下的是「谁在什么时候点了谁的名」。
    """
    scope: str = Field(..., description="点名范围：男生 / 女生 / 全班")
    total: int = Field(..., ge=0, description="本次点名总人数")
    absent: list[RollCallAbsentItem] = Field(default_factory=list, description="无应答名单")


def student_response(student: Any, viewer_role: str = "student") -> StudentResponse:
    """按查看者角色裁剪字段后再输出

    备注属于班委内部记录，普通学生看不到任何人的备注（连自己那条也看不到）。
    """
    data = StudentResponse.model_validate(student)
    if viewer_role == "student":
        data.remark = None
    return data
