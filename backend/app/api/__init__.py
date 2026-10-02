from fastapi import APIRouter

from .auth import router as auth_router
from .public import router as public_router
from .students import router as students_router
from .announcements import router as announcements_router
from .resources import router as resources_router
from .notices import router as notices_router
from .change_requests import router as change_requests_router
from .admin import router as admin_router
from .about import router as about_router
from .leaves import router as leaves_router
from .feedback import router as feedback_router
from .badges import router as badges_router
from .ev_passes import router as ev_passes_router
from .exports import router as exports_router
from .certificates import router as certificates_router
from .workspace import router as workspace_router
from .birthday import router as birthday_router

api_router = APIRouter()
api_router.include_router(public_router)   # 首页摘要：公开
api_router.include_router(auth_router)     # 登录/退出/改密
api_router.include_router(notices_router)  # 通知公告：列表公开，管理需班委
api_router.include_router(students_router)      # 学生信息：班委及以上
api_router.include_router(announcements_router)  # 文件公开：登录可看，管理需班委
api_router.include_router(resources_router)      # 资料下载：登录即可
api_router.include_router(about_router)          # 关于班级：登录即可
api_router.include_router(change_requests_router)  # 修改申请：学生提交，班委审核
api_router.include_router(leaves_router)         # 请假申请：学生提交，管理员审核
api_router.include_router(feedback_router)       # 意见反馈：学生提交，班委回复
api_router.include_router(badges_router)         # 菜单红点：需登录
api_router.include_router(ev_passes_router)      # 电动车通行证：学生提交，班委只读，管理员审核
api_router.include_router(exports_router)        # 学生信息导出申请：班委提交，管理员审核
api_router.include_router(certificates_router)   # 证明/介绍信开具：学生提交，班委只读，管理员审批+传成品
api_router.include_router(workspace_router)      # 办件空间：我申请的/我审批的聚合列表
api_router.include_router(birthday_router)       # 生日关怀：条幅公开，设置与测试仅管理员
api_router.include_router(admin_router)          # 系统管理：仅管理员
