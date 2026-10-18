import json
import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from ..utils.email_addr import is_valid_email


class ChangeRequestCreate(BaseModel):
    """学生提交的信息修改申请

    字段与 student_service 的可修改白名单一一对应（学号、姓名等不开放）。
    身份证号是个例外：只允许「补空」，档案里一旦有值就不能再改（见 change_requests.py）。
    没传的字段表示不改；显式传 null 表示要清空。
    """
    qq: Optional[str] = Field(None, max_length=30, description="QQ号码")
    email: Optional[str] = Field(None, max_length=100, description="电子邮箱")
    phone: Optional[str] = Field(None, max_length=50, description="本人电话")
    family_phone: Optional[str] = Field(None, max_length=100, description="家庭电话")
    family_address: Optional[str] = Field(None, max_length=200, description="家庭通信地址")
    postal_code: Optional[str] = Field(None, max_length=10, description="邮政编码")
    league_position: Optional[str] = Field(None, max_length=50, description="团学会职务")
    dormitory: Optional[str] = Field(None, max_length=50, description="宿舍")
    bed: Optional[str] = Field(None, max_length=20, description="床位号")
    # 只用于档案里还没有身份证号时补录；已有值的学生连这一格都看不到
    id_card: Optional[str] = Field(None, max_length=20, description="身份证号（仅在缺失时补充）")

    # 照片字段在这里只当**探测器**用：它不开放给学生填值（值由后端落盘后注入），
    # 声明出来是为了明确拒绝，而不是静默丢掉。不声明的话，学生塞进来的
    # {"id_photo": "2024000002_id.jpg"} 会被 pydantic 忽略，申请照建不误 ——
    # 而学生以为照片已经改了，这个误会要到班委点通过之后才会暴露
    id_photo: Optional[str] = Field(None, description="自备证件照（只能上传文件，不接受直接传值）")

    @field_validator("id_photo")
    @classmethod
    def reject_id_photo(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            raise ValueError("自备证件照请通过上传文件的方式提交")
        return v

    @field_validator("id_card")
    @classmethod
    def check_id_card(cls, v: Optional[str]) -> Optional[str]:
        """只接受 18 位号码；末位小写 x 统一成大写

        这一项进了改动就一定是「补充」，空值不该出现在申请里 —— 想留空就别传。
        """
        if v is None:
            return v
        v = v.strip().upper()
        if not re.fullmatch(r"\d{17}[\dX]", v):
            raise ValueError("身份证号应为 18 位，最后一位可以是 X")
        return v

    @field_validator("email")
    @classmethod
    def check_email(cls, v: Optional[str]) -> Optional[str]:
        """邮箱必须过格式校验，不能只限长度

        原先只写了 max_length=100，所以 "a@b.com\\nBcc: victim@x.com" 这种是能存进来的。
        这个值被班委审批通过后会直接写进 students.email，而它随后就是**邮件通知的
        收件人** —— 等于学生借一条正常的审批流，给全班通知开出一个抄送口。

        留空 / null 都合法：前者表示不改这一项，后者表示清空。
        发送侧还有一道 is_valid_email（email_service 里），这里是把口子堵在源头。
        """
        if v and not is_valid_email(v):
            raise ValueError("电子邮箱格式不正确")
        return v


class RejectRequest(BaseModel):
    """驳回申请"""
    reason: str = Field(..., max_length=200, description="驳回理由")


class ChangeRequestResponse(BaseModel):
    id: int
    student_no: str
    student_name: str
    changes: dict[str, Any]
    status: str
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewer_name: Optional[str] = None
    # 该学生这些字段当前的真实值，供前端并排展示「原值 → 新值」
    current: dict[str, Any] = {}

    class Config:
        from_attributes = True

    @field_validator("changes", mode="before")
    @classmethod
    def parse_changes(cls, v: Any) -> Any:
        """库里存的是 JSON 串，出参转成对象"""
        if isinstance(v, str):
            return json.loads(v) if v.strip() else {}
        return v
