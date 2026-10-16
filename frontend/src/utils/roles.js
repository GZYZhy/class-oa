/**
 * 角色等级：数值越大权限越高
 *
 * 路由守卫（router/index.js）和侧边菜单（App.vue）共用这一份，
 * 避免两处各写一遍权限判断、日后改不干净。
 */
export const ROLE_RANK = { student: 0, committee: 1, admin: 2 }

/** 取某角色的等级；认不出来的（含未登录的 undefined）一律按普通学生算 */
export function rankOf(role) {
  return ROLE_RANK[role] ?? ROLE_RANK.student
}

/** 角色显示名，用于系统管理页 */
export const ROLE_LABELS = { student: '普通学生', committee: '班委', admin: '管理员' }

/**
 * 一个入口对当前账号可不可见
 *
 * 侧边菜单（App.vue）和首页的快捷入口共用这一份 —— 各写一遍的话，
 * 「域外账号看不到学生功能」这类规则迟早只改一边。
 *
 * item 的字段：public = 未登录也可见；studentOnly = 只有学生账号可见
 * （域外账号没有学生记录，这些页面用不了）；role = 可见的最低角色，不写则登录即可见。
 * user 直接把 pinia 的 userStore 传进来就行（只用它三个 getter），
 * 测试里传个普通对象也能跑。
 */
export function canSee(item, user) {
  if (item.public) return true
  if (!user.isLogin) return false
  if (item.studentOnly && user.isExternal) return false
  return rankOf(user.info?.role) >= rankOf(item.role || 'student')
}
