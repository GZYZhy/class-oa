import request from '@/utils/request'

/**
 * 完整档案查看申请（后端 api/archive_views.py）
 *
 * 流程与签字图申请一致：班委申请 → 管理员批准 → 只有申请人在一小时内能看
 * 学生的身份证号、家庭电话、高考分数、实地采集照片等敏感字段。管理员和
 * 学生本人不受限。
 */

/** 我对某个学生完整档案的状态：none / pending / approved / expired（班委及以上） */
export function getArchiveStatus(studentId) {
  return request({
    url: `/archive-views/status/${studentId}`,
    method: 'get'
  })
}

/** 申请查看某学生的完整档案（班委及以上） */
export function requestArchiveView(studentId) {
  return request({
    url: '/archive-views/requests',
    method: 'post',
    data: { student_id: studentId }
  })
}

/** 申请列表（仅管理员） */
export function getArchiveRequests(params) {
  return request({
    url: '/archive-views/requests',
    method: 'get',
    params
  })
}

/** 通过申请（仅管理员） */
export function approveArchiveRequest(id) {
  return request({
    url: `/archive-views/requests/${id}/approve`,
    method: 'post'
  })
}

/** 驳回申请（仅管理员），reason 会推给申请人 */
export function rejectArchiveRequest(id, reason) {
  return request({
    url: `/archive-views/requests/${id}/reject`,
    method: 'post',
    data: { reason }
  })
}
