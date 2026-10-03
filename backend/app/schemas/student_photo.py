"""照片批量导入（zip）的请求与响应 schema"""

from pydantic import BaseModel, Field


class PhotoZipItem(BaseModel):
    """zip 里的一张照片，以及它被判定成什么"""
    raw_name: str = Field(..., description="zip 里的完整成员名（含子目录），人工指认时按它回传")
    filename: str = Field(..., description="去掉目录后的文件名，只用来显示")
    size: int = Field(0, description="解压后大小（字节），取自 zip 清单")
    status: str = Field(
        "",
        description="ok=可导入 / unmatched=认不出是谁 / conflict=同一学生多张 / "
        "unsupported=格式不支持 / too_large=太大 / ignored=系统隐藏文件",
    )
    student_no: str | None = Field(None, description="匹配到的学号")
    student_name: str | None = Field(None, description="匹配到的姓名")
    has_photo: bool = Field(False, description="这个学生该类型已有照片，默认不覆盖")
    reason: str = Field("", description="不能导入的原因（status 非 ok 时）")


class PhotoZipPreviewResponse(BaseModel):
    """zip 解析预览（不写库、不写文件）"""
    token: str = Field(..., description="预览令牌，确认导入时传回")
    photo_type: str = Field(..., description="gaokao / on_site")
    total: int = Field(0, description="zip 里的成员总数")
    counts: dict[str, int] = Field(default_factory=dict, description="各状态的张数")
    will_overwrite: int = Field(0, description="其中会覆盖已有照片的张数")
    items: list[PhotoZipItem] = Field(default_factory=list, description="逐张的结论")


class PhotoZipConfirmRequest(BaseModel):
    """确认导入的请求体"""
    token: str = Field(..., description="预览接口返回的令牌")
    photo_type: str = Field(..., description="gaokao / on_site，与预览时一致")
    overwrite: bool = Field(False, description="已有照片也覆盖")
    manual: dict[str, str] = Field(
        default_factory=dict,
        description="人工指认：zip 成员名 → 学号，只对自动认不出的那些有意义",
    )


class PhotoZipResultResponse(BaseModel):
    """导入结果"""
    saved: int = Field(0, description="写入的照片数（含覆盖）")
    overwritten: int = Field(0, description="其中覆盖了原有照片的")
    skipped_exists: int = Field(0, description="因已有照片且未勾选覆盖而跳过")
    failed: list[str] = Field(default_factory=list, description="失败清单（文件名 + 原因）")
    message: str = Field("", description="总结信息")
