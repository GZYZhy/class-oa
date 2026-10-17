import request, { progressHandler } from '@/utils/request'

/**
 * 公告列表
 * @param {object} [params] - keyword（标题或文号）、start_date、end_date
 */
export function getAnnouncements(params = {}) {
  return request({ url: '/announcements', method: 'get', params })
}

/**
 * 发布公告（上传 PDF）
 * 使用 FormData：file + 标题 + 文号 + 发布时间
 * @param {FormData} formData
 * @param {(loaded: number, total: number) => void} [onProgress] 上传进度
 */
export function createAnnouncement(formData, onProgress) {
  return request({
    url: '/announcements',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/**
 * 删除公告
 */
export function deleteAnnouncement(id) {
  return request({ url: `/announcements/${id}`, method: 'delete' })
}
