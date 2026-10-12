import request, { progressHandler } from '@/utils/request'

/** 我的请假记录 */
export function getMyLeaves() {
  return request({ url: '/leaves/my', method: 'get' })
}

/** 提交请假申请（form-data，带文件）
 *
 * onProgress：(loaded, total) => void，上传进度（证明材料多是拍照，可能有几 MB）
 */
export function submitLeave(formData, onProgress) {
  return request({
    url: '/leaves',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/** 下载我的请假证明 */
export function getMyLeaveProof(id) {
  return request({
    url: `/leaves/${id}/proof`,
    method: 'get',
    responseType: 'blob'
  })
}

/** 管理员：请假申请列表 */
export function getLeaveList(status) {
  return request({
    url: '/leaves',
    method: 'get',
    params: status ? { status } : {}
  })
}

/** 下载请假审批表 PDF（申请人本人和管理员都能下，下到的是一样的） */
export function downloadLeavePdf(id) {
  return request({
    url: `/leaves/${id}/pdf`,
    method: 'get',
    responseType: 'blob'
  })
}

/** 管理员：能当班导师签字人的账号（管理员、且签字图在盘上） */
export function getAdvisorSigners() {
  return request({ url: '/leaves/advisor-signers', method: 'get' })
}

/** 管理员：下载请假证明文件 */
export function downloadLeaveProof(id) {
  return request({
    url: `/leaves/${id}/proof/admin`,
    method: 'get',
    responseType: 'blob'
  })
}

/** 管理员：通过（可顺带填班导师意见、选谁的签字；两者都选填） */
export function approveLeave(id, payload) {
  return request({ url: `/leaves/${id}/approve`, method: 'post', data: payload })
}

/** 管理员：补签字（批准时选了「暂不签字」之后） */
export function advisorSign(id, payload) {
  return request({ url: `/leaves/${id}/advisor-sign`, method: 'post', data: payload })
}

/** 管理员：驳回 */
export function rejectLeave(id, reason) {
  return request({ url: `/leaves/${id}/reject`, method: 'post', data: { reason } })
}
