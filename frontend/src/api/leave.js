import request from '@/utils/request'

/** 我的请假记录 */
export function getMyLeaves() {
  return request({ url: '/leaves/my', method: 'get' })
}

/** 提交请假申请（form-data，带文件） */
export function submitLeave(formData) {
  return request({
    url: '/leaves',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
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

/** 管理员：下载填好的 Word 请假表 */
export function downloadLeaveDocx(id) {
  return request({
    url: `/leaves/${id}/docx`,
    method: 'get',
    responseType: 'blob'
  })
}

/** 管理员：下载请假证明文件 */
export function downloadLeaveProof(id) {
  return request({
    url: `/leaves/${id}/proof/admin`,
    method: 'get',
    responseType: 'blob'
  })
}

/** 管理员：通过 */
export function approveLeave(id) {
  return request({ url: `/leaves/${id}/approve`, method: 'post' })
}

/** 管理员：驳回 */
export function rejectLeave(id, reason) {
  return request({ url: `/leaves/${id}/reject`, method: 'post', data: { reason } })
}
