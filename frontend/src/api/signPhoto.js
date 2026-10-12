import request, { progressHandler } from '@/utils/request'

/**
 * 签字图相关接口（后端 api/sign_photos.py）
 *
 * 和另外三张照片不是一条链路：照片是「能看这个学生就能看」，签字是
 * 「班委申请 → 管理员批准 → 只有申请人在一小时内能看」，管理员自己不受限。
 * 所以取图不在这里，图片走 request.js 的 blob 通道（见 utils/download.js 的 fetchBlob）。
 */

/** 我对某个学生签字图的状态：none / pending / approved / expired（班委及以上） */
export function getSignStatus(studentId) {
  return request({
    url: `/sign-photos/status/${studentId}`,
    method: 'get'
  })
}

/** 申请查看某学生的签字图（班委及以上） */
export function requestSignView(studentId) {
  return request({
    url: '/sign-photos/requests',
    method: 'post',
    data: { student_id: studentId }
  })
}

/**
 * 签字的取图地址。给 FileViewer 当 fileUrl 用，它自己会带鉴权去取
 *
 * version 传下载名即可（后端这个响应是 no-store，本来就不该被缓存；带上只是
 * 万一中间还有别的层在缓，换个图名就能绕开）
 */
export function signImageUrl(studentId, version = '') {
  return `/api/sign-photos/image/${studentId}?v=${encodeURIComponent(version)}`
}

/** 申请列表（仅管理员） */
export function getSignRequests(params) {
  return request({
    url: '/sign-photos/requests',
    method: 'get',
    params
  })
}

/** 通过申请（仅管理员） */
export function approveSignRequest(id) {
  return request({
    url: `/sign-photos/requests/${id}/approve`,
    method: 'post'
  })
}

/** 驳回申请（仅管理员），reason 会推给申请人 */
export function rejectSignRequest(id, reason) {
  return request({
    url: `/sign-photos/requests/${id}/reject`,
    method: 'post',
    data: { reason }
  })
}

/** 上传 / 替换签字图（仅管理员） */
export function uploadSignImage(studentId, file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  return request({
    url: `/sign-photos/image/${studentId}`,
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/** 删除签字图（仅管理员） */
export function deleteSignImage(studentId) {
  return request({
    url: `/sign-photos/image/${studentId}`,
    method: 'delete'
  })
}
