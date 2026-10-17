import { createRouter, createWebHashHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'
import { rankOf } from '@/utils/roles'
import { SITE } from '@/utils/site'

// meta 说明：
//   public: true     无需登录（首页、通知公告）
//   role: 'xxx'      需要该角色及以上（学生名单、分类统计要班委；系统管理要管理员）
//   studentOnly: true 只有学生账号能进（域外账号没有学生记录，这些页面用不了）
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
    path: '/attendance',
    name: 'Attendance',
    component: () => import('@/views/Attendance.vue'),
    meta: { title: '考勤记录', role: 'committee' }
  },
  {
    path: '/grades',
    name: 'Grade',
    component: () => import('@/views/Grade.vue'),
    meta: { title: '成绩管理', role: 'committee' }
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
    path: '/inbox',
    name: 'Inbox',
    component: () => import('@/views/Inbox.vue'),
    meta: { title: '我的消息' }
  },
  {
    // 不加 role：参与者是普通学生。发起投票靠页面里的按钮级权限（后端 committee_required 兜底）
    path: '/vote',
    name: 'Vote',
    component: () => import('@/views/Vote.vue'),
    meta: { title: '投票表决' }
  },
  {
    path: '/schedule',
    name: 'Schedule',
    component: () => import('@/views/Schedule.vue'),
    meta: { title: '我的日程', studentOnly: true }
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
    meta: { title: '办事中心', studentOnly: true }
  },
  {
    path: '/leave',
    name: 'LeaveApply',
    component: () => import('@/views/LeaveApply.vue'),
    meta: { title: '请假申请', studentOnly: true }
  },
  {
    path: '/ev-pass',
    name: 'EvPass',
    component: () => import('@/views/EvPass.vue'),
    meta: { title: '电动车通行证补办', studentOnly: true }
  },
  {
    path: '/feedback',
    name: 'Feedback',
    component: () => import('@/views/Feedback.vue'),
    meta: { title: '意见反馈', studentOnly: true }
  },
  {
    path: '/certificate',
    name: 'Certificate',
    component: () => import('@/views/Certificate.vue'),
    meta: { title: '证明开具', studentOnly: true }
  },
  {
    path: '/about',
    name: 'About',
    component: () => import('@/views/About.vue'),
    meta: { title: '关于班级' }
  },
  // 兜底：地址输错 / 旧链接失效。没有它 router-view 什么都不渲染，正文区一片空白，
  // 用户分不清是链接错了还是系统坏了。必须放最后一条 —— 前面的具名路由先匹配
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFound.vue'),
    meta: { title: '页面不存在' }
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach(async (to) => {
  document.title = `${to.meta.title || '首页'} - ${SITE.shortName}`

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

  // 域外账号（老师等）没有学生记录，「我的信息」「办事中心」这些页面用不了。
  // 菜单里不显示入口，这一层是防手敲地址栏（后端接口同样会拒绝）
  if (to.meta.studentOnly && userStore.isExternal) {
    ElMessage.warning('域外账号不支持该功能')
    return { path: '/dashboard' }
  }

  return true
})

/**
 * 部署新版本后，旧页面里再点菜单会去请求已被删掉的旧哈希 chunk，
 * 浏览器报「Failed to fetch dynamically imported module」，页面却纹丝不动 ——
 * 用户只会觉得点了没反应。这里整页刷新一次，拿到新的 index.html 就恢复。
 *
 * 10 秒内再失败（真断网、部署还没完成）就不再刷，只提示，避免反复刷新；
 * 断网时刷新只会跳到浏览器的离线页，也单独拦下。
 */
const RELOAD_KEY = 'chunk-reload-at'

router.onError((error, to) => {
  const msg = error?.message || ''
  if (!/dynamically imported module|Importing a module script failed|ChunkLoadError/i.test(msg)) return

  if (!navigator.onLine) {
    ElMessage.error('网络已断开，请检查网络后重试')
    return
  }

  const last = Number(sessionStorage.getItem(RELOAD_KEY) || 0)
  if (Date.now() - last < 10000) {
    ElMessage.error('页面版本已更新，请刷新后重试')
    return
  }
  sessionStorage.setItem(RELOAD_KEY, String(Date.now()))

  // hash 路由：先把地址改成用户想去的页面，刷新后不用再点一次
  window.location.hash = to.fullPath
  window.location.reload()
})

export default router
