from pydantic import BaseModel, Field


class CommitteeMember(BaseModel):
    """班委成员：只有姓名和职务，不含任何联系方式"""
    name: str
    position: str


class AboutIntro(BaseModel):
    """班级简介卡片。enabled 为假时前端整张卡片都不渲染"""
    enabled: bool = False
    # 原文 Markdown：渲染交给前端（与通知公告同一条链路，DOMPurify 也在那边）
    markdown: str = ""


class AboutResponse(BaseModel):
    """「关于班级」页需要的全部数据"""
    total: int
    gender: dict[str, int]
    committee: list[CommitteeMember]
    # 系统版本号，页面上显示成「系统版本 1.1」。值只有 settings.app_version 一份，
    # 前端不另写：两处各写一个版本号，迟早会出现页面上和 /api/health 对不上的情况
    version: str = ""
    # 管理员可配的两块：简介卡片、任职表显示与否
    intro: AboutIntro = Field(default_factory=AboutIntro)
    roster_enabled: bool = True


class AboutMember(BaseModel):
    """管理端用的成员条目：多一个学号，排序按学号走"""
    student_no: str
    name: str
    position: str


class AboutAdminResponse(BaseModel):
    """系统管理里「关于班级」那一块的配置回显"""
    intro_enabled: bool
    intro_markdown: str
    roster_enabled: bool
    # 已保存的顺序（学号数组）。members 已经按它排好，这里给出来是为了
    # 前端在成员增减后还能把顺序原样交回来
    order: list[str] = Field(default_factory=list)
    members: list[AboutMember] = Field(default_factory=list)


class AboutSettingsUpdate(BaseModel):
    """保存「关于班级」的配置（整体覆盖）"""
    intro_enabled: bool = False
    intro_markdown: str = ""
    roster_enabled: bool = True
    # 传什么顺序就存什么顺序；不在列表里的成员页面会自动接在后面
    order: list[str] = Field(default_factory=list)
