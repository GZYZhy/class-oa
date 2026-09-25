import request from '@/utils/request'

/** 我的反馈列表 */
export function getMyFeedback() {
  return request({ url: '/feedback/my', method: 'get' })
}

/** 提交反馈 */
export function submitFeedback(data) {
  return request({ url: '/feedback', method: 'post', data })
}

/** 我的反馈详情 */
export function getMyFeedbackDetail(id) {
  return request({ url: `/feedback/${id}`, method: 'get' })
}

/** 班委：反馈列表 */
export function getFeedbackList(status) {
  return request({
    url: '/feedback',
    method: 'get',
    params: status ? { status } : {}
  })
}

/** 班委：反馈详情（查看自动标已读） */
export function getFeedbackDetail(id) {
  return request({ url: `/feedback/${id}/detail`, method: 'get' })
}

/** 班委：标记已读 */
export function markFeedbackRead(id) {
  return request({ url: `/feedback/${id}/mark-read`, method: 'post' })
}

/** 班委：回复 */
export function replyFeedback(id, content) {
  return request({ url: `/feedback/${id}/reply`, method: 'post', data: { content } })
}
