import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from ..utils.email_addr import is_valid_email


class ChangeRequestCreate(BaseModel):
    """学生提交的信息修改申请

    字段与 student_service 的可修改白名单一一对应（学号、姓名、身份证号等不开放）。
    没传的字段表示不改；显式传 null 表示要清空。
    """
    qq: Optional[str] = Field(None, max_length=30, description="QQ号码")
    email: Optional[str] = Field(None, max_length=100, description="电子邮箱")
    phone: Optional[str] = Field(None, max_length=50, description="本人电话")
    family_phone: Optional[str] = Field(None, max_length=100, description="家庭电话")
    family_address: Optional[str] = Field(None, max_length=200, description="家庭通信地址")
    postal_code: Optional[str] = Field(None, max_length=10, description="邮政编码")
    league_position: Optional[str] = Field(None, max_length=50, description="团学会职务")
    is_poor: Optional[str] = Field(None, max_length=10, description="是否贫困生")
    bed: Optional[str] = Field(None, max_length=20, description="床位号")

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
