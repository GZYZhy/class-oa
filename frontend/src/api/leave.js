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

/** 修改自己的请假申请（待受理、待补正时；表单整套覆盖，改完回到受理流程）
 *
 * 不传 proof 就是「证明材料不动」；onProgress 同 submitLeave（重传证明时看得到进度）
 */
export function updateLeave(id, formData, onProgress) {
  return request({
    url: `/leaves/${id}`,
    method: 'put',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/** 撤销自己的请假申请（只有待受理时能撤，记录和证明材料一起删掉） */
export function deleteLeave(id) {
  return request({ url: `/leaves/${id}`, method: 'delete' })
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

/** 下载请假审批表 PDF（申请人本人和管理员都能下，下到的是一样的）
 *
 * onProgress：(loaded, total) => void，下载进度（PDF 里嵌着签字图，可能不小）
 */
export function downloadLeavePdf(id, onProgress) {
  return request({
    url: `/leaves/${id}/pdf`,
    method: 'get',
    responseType: 'blob',
    onDownloadProgress: progressHandler(onProgress)
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

/** 管理员：受理（看过材料了，可以进入审批）。已受理的重复调用无副作用 */
export function acceptLeave(id) {
  return request({ url: `/leaves/${id}/accept`, method: 'post' })
}

/** 管理员：撤回受理（受理点错了的回头路） */
export function unacceptLeave(id) {
  return request({ url: `/leaves/${id}/unaccept`, method: 'post' })
}

/** 管理员：退回补正（材料不对，打回让申请人补齐；理由必填，会通知申请人） */
export function correctLeave(id, reason) {
  return request({ url: `/leaves/${id}/correcting`, method: 'post', data: { reason } })
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
