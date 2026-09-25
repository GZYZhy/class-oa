import { createRouter, createWebHashHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'
import { rankOf } from '@/utils/roles'

// meta 说明：
//   public: true  无需登录（首页、通知公告）
//   role: 'xxx'   需要该角色及以上（学生名单、分类统计要班委；系统管理要管理员）
const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', public: true, bare: true }
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '首页', public: true }
  },
  {
    path: '/my-info',
    name: 'MyInfo',
    component: () => import('@/views/MyInfo.vue'),
    meta: { title: '我的信息' }
  },
  {
    path: '/students',
    name: 'Students',
    component: () => import('@/views/StudentList.vue'),
    meta: { title: '学生信息', role: 'committee' }
  },
  {
    path: '/statistics',
    name: 'Statistics',
    component: () => import('@/views/Statistics.vue'),
    meta: { title: '分类统计', role: 'committee' }
  },
  {
    path: '/review',
    name: 'Review',
    component: () => import('@/views/Review.vue'),
    meta: { title: '审核审批', role: 'committee' }
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('@/views/Admin.vue'),
    meta: { title: '系统管理', role: 'admin' }
  },
  {
    path: '/notices',
    name: 'Notices',
    component: () => import('@/views/Notices.vue'),
    meta: { title: '通知公告', public: true }
  },
  {
    path: '/announcements',
    name: 'Announcements',
    component: () => import('@/views/Announcements.vue'),
    meta: { title: '文件公开' }
  },
  {
    path: '/downloads',
    name: 'Downloads',
    component: () => import('@/views/Downloads.vue'),
    meta: { title: '资料下载' }
  },
  {
    path: '/service',
    name: 'ServiceCenter',
    component: () => import('@/views/ServiceCenter.vue'),
    meta: { title: '办事中心' }
  },
  {
    path: '/leave',
    name: 'LeaveApply',
    component: () => import('@/views/LeaveApply.vue'),
    meta: { title: '请假申请' }
  },
  {
    path: '/feedback',
    name: 'Feedback',
    component: () => import('@/views/Feedback.vue'),
    meta: { title: '意见反馈' }
  },
  {
    path: '/about',
    name: 'About',
    component: () => import('@/views/About.vue'),
    meta: { title: '关于班级' }
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach(async (to) => {
  document.title = `${to.meta.title || '首页'} - 统26-1班`

  if (to.meta.public) return true

  const userStore = useUserStore()
  // 首次进入时用 Cookie 向后端确认一次登录状态
  if (!userStore.resolved) await userStore.fetchMe()

  // 未登录 → 去登录页，并记住原本想去的页面
  if (!userStore.isLogin) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 角色不够 → 弹回首页。
  // 菜单里本来就不显示这些项，这一层是防手敲地址栏（后端也有同样的校验兜底）
  if (to.meta.role && rankOf(userStore.info?.role) < rankOf(to.meta.role)) {
    ElMessage.warning('权限不足')
    return { path: '/dashboard' }
  }

  return true
})

export default router
