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
