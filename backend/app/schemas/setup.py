"""初始化（空库引导）的出入参"""

from typing import List

from pydantic import BaseModel, Field


class SetupStudentItem(BaseModel):
    """名单里的一项，只用于让人挑「谁是管理员」"""

    student_no: str
    name: str


class SetupStateResponse(BaseModel):
    # 还不算初始化完，也就是那个临时账号现在应该存在
    needs_setup: bool
    # 已经有没有学生了。没有的话 finish 会被拒，前端据此把「指定管理员」那步置灰
    has_students: bool
    # 当前学生名单：让操作者直接选，不用手敲学号
    # （这份名单本来就是他自己刚导进来的，算不上多泄露什么）
    students: List[SetupStudentItem] = []


class SetupFinishRequest(BaseModel):
    """把哪个学号设为管理员

    必须是一个**学生**：临时账号自己不行（服务端会拒）。
    """
    admin_student_no: str = Field(..., min_length=1, max_length=20)
