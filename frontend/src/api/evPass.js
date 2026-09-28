import request from '@/utils/request'

/** 我的电动车通行证申请列表 */
export function getMyEvPasses() {
  return request({ url: '/ev-passes/my', method: 'get' })
}

/** 提交申请（multipart：brand / plate_number / license_file） */
export function submitEvPass(formData) {
  return request({
    url: '/ev-passes',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
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

/** 通过申请（管理员） */
export function approveEvPass(id) {
  return request({ url: `/ev-passes/${id}/approve`, method: 'post' })
}

/** 驳回申请（管理员） */
export function rejectEvPass(id, reason) {
  return request({
    url: `/ev-passes/${id}/reject`,
    method: 'post',
    data: { reason }
  })
}
