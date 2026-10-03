import request from '@/utils/request'

/**
 * 我的站内信（分页，按时间倒序）
 *
 * 返回 { total, page, page_size, unread, items }。unread 是**全量**未读数
 * （不只是这一页的），拿它同步菜单红点。
 *
 * 写入不在这里：所有推送都会由后端顺手存一份（见后端 notify_service），
 * 本文件只有「看」和「标记已读」。
 */
export function getInbox(params) {
  return request({ url: '/inbox', method: 'get', params })
}

/** 标记一条为已读（重复调用无副作用） */
export function markInboxRead(id) {
  return request({ url: `/inbox/${id}/read`, method: 'post' })
}

/** 全部标为已读 */
export function markAllInboxRead() {
  return request({ url: '/inbox/read-all', method: 'post' })
}
