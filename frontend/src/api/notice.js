import request from '@/utils/request'

/**
 * 通知列表（支持标题、发布时间搜索）
 */
export function getNotices(params) {
  return request({ url: '/notices', method: 'get', params })
}

/**
 * 发布通知
 */
export function createNotice(data) {
  return request({ url: '/notices', method: 'post', data })
}

/**
 * 编辑通知（后端会自动记录更新时间）
 */
export function updateNotice(id, data) {
  return request({ url: `/notices/${id}`, method: 'put', data })
}

/**
 * 删除通知
 */
export function deleteNotice(id) {
  return request({ url: `/notices/${id}`, method: 'delete' })
}

/**
 * 标记某条通知为已读（展开时调，重复调用无副作用）
 */
export function markNoticeRead(id) {
  return request({ url: `/notices/${id}/read`, method: 'post' })
}

/**
 * 某条通知的已读情况（班委及以上）
 *
 * 返回 { total, read_count, rows: [{ student_no, name, read_at, frozen }] }，
 * rows 里未读的排在前面，read_at 为空表示未读。
 */
export function getNoticeReads(id) {
  return request({ url: `/notices/${id}/reads`, method: 'get' })
}
