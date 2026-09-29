"""Excel 导入学生的请求与响应 schema"""

from pydantic import BaseModel, Field


class ImportPreviewSample(BaseModel):
    """预览中的样例行（新增或覆盖的前 5 条）"""
    student_no: str = Field(..., description="学号")
    name: str = Field(..., description="姓名")
    class_name: str = Field("", description="班级")


class ImportPreviewResponse(BaseModel):
    """Excel 解析预览结果（不写库）"""
    sheet_name: str = Field(..., description="实际使用的工作表名")
    available_sheets: list[str] = Field(default_factory=list, description="Excel 中所有工作表名")
    total_rows: int = Field(0, description="有效数据行数")
    will_create: int = Field(0, description="将新增的人数")
    will_update: int = Field(0, description="将覆盖的人数")
    skip_count: int = Field(0, description="跳过的行数")
    sample_create: list[ImportPreviewSample] = Field(default_factory=list, description="新增样例（前 5 条）")
    sample_update: list[ImportPreviewSample] = Field(default_factory=list, description="覆盖样例（前 5 条）")
    photo_count: int = Field(0, description="提取到的照片数")
    warnings: list[str] = Field(default_factory=list, description="警告信息")
    token: str = Field("", description="预览令牌，确认导入时传回服务端")


class ImportConfirmRequest(BaseModel):
    """确认导入的请求体"""
    token: str = Field(..., description="预览接口返回的令牌")


class ImportResultResponse(BaseModel):
    """导入结果"""
    created: int = Field(0, description="新增人数")
    updated: int = Field(0, description="覆盖人数")
    skipped: int = Field(0, description="跳过行数")
    warnings: list[str] = Field(default_factory=list, description="警告信息")
    message: str = Field("", description="总结信息")
