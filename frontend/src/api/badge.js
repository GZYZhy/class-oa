import request from '@/utils/request'

/**
 * 侧边菜单的红点计数（需登录）
 *
 * 返回 { notice_unread: 通知未读数, review_pending: 待我审核数 }。
 * 两类合成一个接口：每换一次页面都要刷一次，分两个就是两次请求；
 * 「哪些算待办」的口径也按角色分叉，集中放在后端一处更好维护。
 */
export function getBadges() {
  return request({ url: '/badges', method: 'get' })
}
