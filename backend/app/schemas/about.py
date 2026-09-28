from pydantic import BaseModel


class CommitteeMember(BaseModel):
    """班委成员：只有姓名和职务，不含任何联系方式"""
    name: str
    position: str


class AboutResponse(BaseModel):
    """「关于班级」页需要的全部数据"""
    total: int
    gender: dict[str, int]
    committee: list[CommitteeMember]
    # 系统版本号，页面上显示成「系统版本 1.1」。值只有 settings.app_version 一份，
    # 前端不另写：两处各写一个版本号，迟早会出现页面上和 /api/health 对不上的情况
    version: str = ""
