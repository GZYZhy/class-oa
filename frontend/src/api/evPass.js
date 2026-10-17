import request, { progressHandler } from '@/utils/request'

/** 我的电动车通行证申请列表 */
export function getMyEvPasses() {
  return request({ url: '/ev-passes/my', method: 'get' })
}

/** 提交申请（multipart：brand / plate_number / license_file）
 *
 * onProgress：(loaded, total) => void，上传进度（行驶证照片可能有几 MB）
 */
export function submitEvPass(formData, onProgress) {
  return request({
    url: '/ev-passes',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/** 修改自己的申请（待受理、待补正时；表单整套覆盖）
 *
 * 不传 license_file 就是「行驶证不动」；onProgress 同 submitEvPass（重传照片时看得到进度）
 */
export function updateEvPass(id, formData, onProgress) {
  return request({
    url: `/ev-passes/${id}`,
    method: 'put',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/** 撤销自己的申请（只有待受理时能撤，记录和行驶证一起删掉） */
export function deleteEvPass(id) {
  return request({ url: `/ev-passes/${id}`, method: 'delete' })
}

/**
 * 全部申请列表（班委及以上）
 * @param {{status?: string, keyword?: string, start?: string, end?: string}} [params]
 *   keyword 匹配提交人姓名/学号；start/end 是提交日期（YYYY-MM-DD，含首尾）
 */
export function getEvPassList(params) {
  return request({ url: '/ev-passes', method: 'get', params: params || {} })
}

/** 通过申请（管理员）
 *
 * payload 可省：{ sign_no } —— 选一位管理员的签字（空串 = 暂不签署）。
 * 不带 body 时后端按「暂不签署」办，老调用点不会因为多一个参数而报错。
 */
export function approveEvPass(id, payload) {
  return request({ url: `/ev-passes/${id}/approve`, method: 'post', data: payload })
}

/** 管理员：受理（看过行驶证了，可以进入审批）。已受理的重复调用无副作用 */
export function acceptEvPass(id) {
  return request({ url: `/ev-passes/${id}/accept`, method: 'post' })
}

/** 管理员：撤回受理（受理点错了的回头路） */
export function unacceptEvPass(id) {
  return request({ url: `/ev-passes/${id}/unaccept`, method: 'post' })
}

/** 管理员：退回补正（材料不对，打回让申请人补齐；理由必填，会通知申请人） */
export function correctEvPass(id, reason) {
  return request({ url: `/ev-passes/${id}/correcting`, method: 'post', data: { reason } })
}

/** 管理员：撤销已通过（状态变已撤销，不能再编辑、不再提供两份 PDF；撤销不可恢复） */
export function revokeEvPass(id) {
  return request({ url: `/ev-passes/${id}/revoke`, method: 'post' })
}

/** 管理员：补签字（批准时选了「暂不签署」之后） */
export function signEvPass(id, payload) {
  return request({ url: `/ev-passes/${id}/sign`, method: 'post', data: payload })
}

/** 管理员：能当经办班委签字人的账号（管理员、且签字图在盘上） */
export function getEvPassSigners() {
  return request({ url: '/ev-passes/signers', method: 'get' })
}

/** 驳回申请（管理员） */
export function rejectEvPass(id, reason) {
  return request({
    url: `/ev-passes/${id}/reject`,
    method: 'post',
    data: { reason }
  })
}

/** 下载申请表 PDF。本人或班委及以上，且申请已通过
 *
 * onProgress：(loaded, total) => void，下载进度
 */
export function downloadEvPassPdf(id, onProgress) {
  return request({
    url: `/ev-passes/${id}/pass-pdf`,
    method: 'get',
    responseType: 'blob',
    onDownloadProgress: progressHandler(onProgress)
  })
}

/** 下载承诺书 PDF。本人或班委及以上，且申请已通过
 *
 * onProgress：(loaded, total) => void，下载进度
 */
export function downloadEvPromisePdf(id, onProgress) {
  return request({
    url: `/ev-passes/${id}/promise-pdf`,
    method: 'get',
    responseType: 'blob',
    onDownloadProgress: progressHandler(onProgress)
  })
}
