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

/** 全部申请列表（班委及以上，可按状态筛选） */
export function getEvPassList(status) {
  return request({
    url: '/ev-passes',
    method: 'get',
    params: { status: status || undefined }
  })
}

/** 通过申请（管理员）
 *
 * payload 可省：{ sign_no } —— 选一位管理员的签字（空串 = 暂不签署）。
 * 不带 body 时后端按「暂不签署」办，老调用点不会因为多一个参数而报错。
 */
export function approveEvPass(id, payload) {
  return request({ url: `/ev-passes/${id}/approve`, method: 'post', data: payload })
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

/** 下载申请表 PDF。本人或班委及以上，且申请已通过 */
export function downloadEvPassPdf(id) {
  return request({
    url: `/ev-passes/${id}/pass-pdf`,
    method: 'get',
    responseType: 'blob'
  })
}

/** 下载承诺书 PDF。本人或班委及以上，且申请已通过 */
export function downloadEvPromisePdf(id) {
  return request({
    url: `/ev-passes/${id}/promise-pdf`,
    method: 'get',
    responseType: 'blob'
  })
}
