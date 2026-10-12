"""签字图查看申请：入参、出参、状态查询

签字图本身不在这里 —— 它是二进制，走 FileResponse。StudentResponse 里也**没有**
签字字段，学生的通用详情接口永远不返回它，这正是「不向学生展示」的实现方式。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SignPhotoRequestCreate(BaseModel):
    """班委提交：申请查看某个学生的签字图"""
    student_id: int = Field(..., description="被查看签字的学生 ID")


class SignPhotoRequestResponse(BaseModel):
    id: int
    student_id: int
    student_no: str
    student_name: str
    applicant_no: str
    applicant_name: str
    status: str
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewer_name: Optional[str] = None

    class Config:
        from_attributes = True


class SignPhotoRequestListResponse(BaseModel):
    total: int
    items: list[SignPhotoRequestResponse]


class SignPhotoStatusResponse(BaseModel):
    """当前用户对某个学生的签字查看状态，给详情页那个按钮用

    status: none 没申请过（或被驳回）| pending 待审批 | approved 可看 | expired 已过期
    expires_at: 仅 approved 时有值，前端用来提示「有效期至 HH:MM」
    download_name: 后端拼好的下载文件名（含后缀）。前端拿它当预览组件的文件名 ——
        库里那个裸文件名是 uuid4 hex，一个字符都不出网
    """
    status: str
    expires_at: Optional[datetime] = None
    download_name: str = ""
