"""导出申请相关 Schema"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ExportRequestCreate(BaseModel):
    """创建导出申请"""
    export_type: str = Field(..., description="导出类型：excel_list / pdf_individual")
    scope_type: str = Field(..., description="范围类型：all / filtered / selected / id_range")
    scope_param: Optional[dict] = Field(default=None, description="范围参数（JSON）")
    fields: Optional[List[str]] = Field(default=None, description="导出字段列表（Excel 用）")


class ExportRequestResponse(BaseModel):
    """导出申请详情"""
    id: int
    student_id: Optional[int] = None
    student_no: str
    student_name: str
    export_type: str
    scope_type: str
    scope_param: Optional[dict] = None
    fields: Optional[List[str]] = None
    file_original_name: Optional[str] = None
    status: str
    reviewer_name: Optional[str] = None
    reviewer_no: Optional[str] = None
    reject_reason: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    error_msg: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ExportRequestListResponse(BaseModel):
    """导出申请列表（分页）"""
    total: int
    items: List[ExportRequestResponse]


class ExportRejectRequest(BaseModel):
    """驳回申请"""
    reason: str = Field(..., min_length=1, max_length=500, description="驳回理由")
