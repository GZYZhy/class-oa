import request, { progressHandler } from '@/utils/request'

/**
 * 我的证明申请列表
 */
export function getMyCertificates() {
  return request({
    url: '/certificates/my',
    method: 'get'
  })
}

/**
 * 提交证明开具申请（multipart form）
 * @param {Object} data - { title, recipient, content, extra_request, files: File[] }
 * @param {Function} [onProgress] - 上传进度回调
 */
export function submitCertificate(data, onProgress) {
  const formData = new FormData()
  formData.append('title', data.title)
  formData.append('recipient', data.recipient || '')
  formData.append('content', data.content || '')
  formData.append('extra_request', data.extra_request || '')
  formData.append('confirmed', 'true')
  if (data.files) {
    data.files.forEach((f) => {
      formData.append('attachments', f)
    })
  }
  return request({
    url: '/certificates',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/**
 * 证明申请列表（班委及以上）
 * @param {string} [status] - pending/approved/rejected
 */
export function getCertificateList(status) {
  return request({
    url: '/certificates',
    method: 'get',
    params: status ? { status } : {}
  })
}

/**
 * 通过申请（管理员）
 */
export function approveCertificate(id) {
  return request({
    url: `/certificates/${id}/approve`,
    method: 'post'
  })
}

/**
 * 驳回申请（管理员）
 */
export function rejectCertificate(id, reason) {
  return request({
    url: `/certificates/${id}/reject`,
    method: 'post',
    data: { reason }
  })
}

/**
 * 上传成品 PDF（管理员）
 * @param {number} id
 * @param {File} file
 * @param {Function} [onProgress]
 */
export function uploadCertificateResult(id, file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  return request({
    url: `/certificates/${id}/result`,
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/**
 * 下载附件
 * @param {number} id - 申请 ID
 * @param {number} index - 附件下标
 * @param {boolean} [admin=false] - 是否走班委及以上路径
 */
export function downloadCertificateAttachment(id, index, admin = false) {
  const url = admin
    ? `/api/certificates/${id}/attachment/${index}/admin`
    : `/api/certificates/${id}/attachment/${index}`
  return request({
    url,
    method: 'get',
    responseType: 'blob'
  })
}

/**
 * 下载成品证明 PDF
 * @param {number} id
 * @param {boolean} [admin=false]
 */
export function downloadCertificateResult(id, admin = false) {
  const url = admin
    ? `/api/certificates/${id}/result/admin`
    : `/api/certificates/${id}/result`
  return request({
    url,
    method: 'get',
    responseType: 'blob'
  })
}
