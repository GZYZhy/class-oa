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
