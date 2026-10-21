from fastapi import APIRouter

from .auth import router as auth_router
from .public import router as public_router
from .share_meta import router as share_meta_router
from .setup import router as setup_router
from .students import router as students_router
from .announcements import router as announcements_router
from .resources import router as resources_router
from .notices import router as notices_router
from .change_requests import router as change_requests_router
from .admin import router as admin_router
from .about import router as about_router
from .leaves import router as leaves_router
from .attendance import router as attendance_router
from .checkins import router as checkins_router
from .feedback import router as feedback_router
from .badges import router as badges_router
from .ev_passes import router as ev_passes_router
from .exports import router as exports_router
from .certificates import router as certificates_router
from .workspace import router as workspace_router
from .inbox import router as inbox_router
from .birthday import router as birthday_router
from .polls import router as polls_router
from .collections import router as collections_router
from .grades import router as grades_router
from .schedules import router as schedules_router
from .sign_photos import router as sign_photos_router
from .passkeys import router as passkeys_router
from .two_factor import router as two_factor_router

api_router = APIRouter()
api_router.include_router(public_router)   # 首页摘要：公开
api_router.include_router(share_meta_router)  # 外链分享卡片：公开，给 nginx SSI 用
api_router.include_router(auth_router)     # 登录/退出/改密
api_router.include_router(setup_router)    # 初始化：空库引导，用完即废
api_router.include_router(notices_router)  # 通知公告：列表公开，管理需班委
api_router.include_router(students_router)      # 学生信息：班委及以上
api_router.include_router(announcements_router)  # 文件公开：登录可看，管理需班委
api_router.include_router(resources_router)      # 资料下载：登录即可
api_router.include_router(about_router)          # 关于班级：登录即可
api_router.include_router(change_requests_router)  # 修改申请：学生提交，班委审核
api_router.include_router(leaves_router)         # 请假申请：学生提交，管理员审核
api_router.include_router(attendance_router)     # 考勤记录：班委及以上
api_router.include_router(checkins_router)       # 签到式点名：发布需班委，签到需登录且在范围内
api_router.include_router(feedback_router)       # 意见反馈：学生提交，班委回复
api_router.include_router(badges_router)         # 菜单红点：需登录
api_router.include_router(ev_passes_router)      # 电动车通行证：学生提交，班委只读，管理员审核
api_router.include_router(exports_router)        # 学生信息导出申请：班委提交，管理员审核
api_router.include_router(certificates_router)   # 证明/介绍信开具：学生提交，班委只读，管理员审批+传成品
api_router.include_router(workspace_router)      # 办件空间：我申请的/我审批的聚合列表
api_router.include_router(inbox_router)          # 站内信：所有推送的存档，登录即可看自己的
api_router.include_router(birthday_router)       # 生日关怀：条幅公开，设置与测试仅管理员
api_router.include_router(polls_router)          # 投票表决：发起需班委，表决看名单
api_router.include_router(collections_router)    # 投票收集：多题型、多份、竞争名额
api_router.include_router(grades_router)         # 成绩管理：录入与编辑需班委，学生只看自己
api_router.include_router(schedules_router)      # 我的日程：日历式日程管理，班委可批量导入
api_router.include_router(sign_photos_router)    # 签字图：管理员上传，班委申请、管理员批准后才看得到
api_router.include_router(passkeys_router)       # 通行密钥：密码之外的登录方式，登记需登录
api_router.include_router(two_factor_router)     # 二次验证：登录时校验，设置需登录+密码
api_router.include_router(admin_router)          # 系统管理：仅管理员
