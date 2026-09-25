import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class ChangeRequestCreate(BaseModel):
    """学生提交的信息修改申请

    字段与 student_service 的可修改白名单一一对应（学号、姓名、身份证号等不开放）。
    没传的字段表示不改；显式传 null 表示要清空。
    """
    qq: Optional[str] = Field(None, max_length=30, description="QQ号码")
    email: Optional[str] = Field(None, max_length=100, description="电子邮箱")
    family_address: Optional[str] = Field(None, max_length=200, description="家庭通信地址")
    postal_code: Optional[str] = Field(None, max_length=10, description="邮政编码")
    league_position: Optional[str] = Field(None, max_length=50, description="团学会职务")
    is_poor: Optional[str] = Field(None, max_length=10, description="是否贫困生")
    bed: Optional[str] = Field(None, max_length=20, description="床位号")


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
