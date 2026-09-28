import request, { progressHandler } from '@/utils/request'

/** 我的反馈列表 */
export function getMyFeedback() {
  return request({ url: '/feedback/my', method: 'get' })
}

/** 提交反馈（form-data：正文和附件一起发）
 *
 * 单个附件可达 20MB，超时不用在这里写：request.js 的拦截器看到 FormData
 * 会放宽到文件传输的时长（原先这里单独写死 120 秒，是全项目唯一一处这么干的，
 * 结果别处的上传都还在用 15 秒）
 *
 * onProgress：(loaded, total) => void，上传进度
 */
export function submitFeedback(formData, onProgress) {
  return request({
    url: '/feedback',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/** 下载反馈附件（index 取自 feedback.attachments[].index）
 *
 * 超时同样交给拦截器（responseType 是 blob） */
export function downloadFeedbackAttachment(feedbackId, index) {
  return request({
    url: `/feedback/${feedbackId}/attachments/${index}`,
    method: 'get',
    responseType: 'blob'
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
