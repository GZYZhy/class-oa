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
