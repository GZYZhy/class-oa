import request, { progressHandler } from '@/utils/request'

/**
 * 通知列表（支持标题、发布时间搜索）
 */
export function getNotices(params) {
  return request({ url: '/notices', method: 'get', params })
}

/**
 * 单条通知（公开，外链分享页用）
 *
 * 通知公告本身就是公开内容，外链页凭 id 读取；不需要登录。
 */
export function getNotice(id) {
  return request({ url: `/notices/${id}`, method: 'get' })
}

/**
 * 发布通知（multipart form，支持附件）
 * @param {FormData} formData - 包含 title / publish_date / content / attachments(多个file)
 * @param {(loaded: number, total: number) => void} [onProgress] 上传进度
 */
export function createNotice(formData, onProgress) {
  return request({
    url: '/notices',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/**
 * 编辑通知（multipart form，支持修改附件）
 * @param {number} id
 * @param {FormData} formData - 包含 title / publish_date / content / 新附件 / keep_attachments
 * @param {(loaded: number, total: number) => void} [onProgress] 上传进度
 */
export function updateNotice(id, formData, onProgress) {
  return request({
    url: `/notices/${id}`,
    method: 'put',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/**
 * 删除通知
 */
export function deleteNotice(id) {
  return request({ url: `/notices/${id}`, method: 'delete' })
}

/**
 * 标记某条通知为已读（展开时调，重复调用无副作用）
 */
export function markNoticeRead(id) {
  return request({ url: `/notices/${id}/read`, method: 'post' })
}

/**
 * 某条通知的已读情况（班委及以上）
 *
 * 返回 { total, read_count, rows: [{ student_no, name, read_at, frozen }] }，
 * rows 里未读的排在前面，read_at 为空表示未读。
 */
export function getNoticeReads(id) {
  return request({ url: `/notices/${id}/reads`, method: 'get' })
}

/**
 * 提醒还没读这条通知的人（班委及以上）
 *
 * 返回 { reminded }。从前还有一个 unreachable（四个渠道都没订阅、因此什么都收不到
 * 的人），加了站内信之后这类人不存在了 —— 提醒一定落进对方的收件箱，
 * 所以这个数字就是真收到的人数。
 */
export function remindUnread(id) {
  return request({ url: `/notices/${id}/remind`, method: 'post' })
}

/**
 * 通知公告的 RSS 订阅链接（需登录）
 *
 * 返回 { token, url, last_accessed_at }。用的是「我的日程」那**同一个**订阅令牌，
 * 所以在日程页重置令牌会让这条链接一起失效。
 */
export function getRssToken() {
  return request({ url: '/notices/rss/token', method: 'get' })
}
