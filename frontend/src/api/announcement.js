import request from '@/utils/request'

/**
 * 公告列表
 */
export function getAnnouncements() {
  return request({ url: '/announcements', method: 'get' })
}

/**
 * 发布公告（上传 PDF）
 * 使用 FormData：file + 标题 + 文号 + 发布时间
 */
export function createAnnouncement(formData) {
  return request({
    url: '/announcements',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/**
 * 删除公告
 */
export function deleteAnnouncement(id) {
  return request({ url: `/announcements/${id}`, method: 'delete' })
}
