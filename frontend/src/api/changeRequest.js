import request from '@/utils/request'

/**
 * 提交自己的信息修改申请
 * data 只放要改的字段（后端白名单：qq/email/family_address/postal_code/league_position/is_poor）
 */
export function submitChangeRequest(data) {
  return request({
    url: '/change-requests',
    method: 'post',
    data
  })
}

/** 我的申请记录（最新在前），用于「我的信息」页展示审核状态 */
export function getMyChangeRequests() {
  return request({
    url: '/change-requests/me',
    method: 'get'
  })
}

/** 申请列表（班委及以上）；status 可选 pending / approved / rejected，不传为全部 */
export function getChangeRequests(params) {
  return request({
    url: '/change-requests',
    method: 'get',
    params
  })
}

/** 通过申请：后端会把 changes 里的字段真正写进学生表 */
export function approveChangeRequest(id) {
  return request({
    url: `/change-requests/${id}/approve`,
    method: 'post'
  })
}

/** 驳回申请，需给出理由 */
export function rejectChangeRequest(id, reason) {
  return request({
    url: `/change-requests/${id}/reject`,
    method: 'post',
    data: { reason }
  })
}
