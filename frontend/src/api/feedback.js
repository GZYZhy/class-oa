import request from '@/utils/request'

/** 我的反馈列表 */
export function getMyFeedback() {
  return request({ url: '/feedback/my', method: 'get' })
}

/** 提交反馈（form-data：正文和附件一起发） */
export function submitFeedback(formData) {
  return request({
    url: '/feedback',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    // 单个附件可达 20MB，默认的 15 秒在手机网络上必然超时
    timeout: 120000
  })
}

/** 下载反馈附件（index 取自 feedback.attachments[].index） */
export function downloadFeedbackAttachment(feedbackId, index) {
  return request({
    url: `/feedback/${feedbackId}/attachments/${index}`,
    method: 'get',
    responseType: 'blob',
    timeout: 120000
  })
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
