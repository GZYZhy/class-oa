import request, { progressHandler } from '@/utils/request'

/** 收集列表（标题/描述搜索 + 状态，服务端分页） */
export function getCollections(params) {
  return request({ url: '/collections', method: 'get', params })
}

/** 收集详情（范围内或发起人/管理员） */
export function getCollection(id) {
  return request({ url: `/collections/${id}`, method: 'get' })
}

/** 可填写名单（发起人/管理员，复用旧卷时带过范围用） */
export function getCollectionTargets(id) {
  return request({ url: `/collections/${id}/targets`, method: 'get' })
}

/** 发起收集（班委及以上） */
export function createCollection(data) {
  return request({ url: '/collections', method: 'post', data })
}

/** 编辑收集（发起人/管理员） */
export function updateCollection(id, data) {
  return request({ url: `/collections/${id}`, method: 'patch', data })
}

/** 删除收集 */
export function deleteCollection(id) {
  return request({ url: `/collections/${id}`, method: 'delete' })
}

/** 立即结束 */
export function closeCollection(id) {
  return request({ url: `/collections/${id}/close`, method: 'post' })
}

/** 暂停收集（只停收答卷，不是结束；到点仍会自动结束） */
export function pauseCollection(id) {
  return request({ url: `/collections/${id}/pause`, method: 'post' })
}

/** 恢复收集 */
export function resumeCollection(id) {
  return request({ url: `/collections/${id}/resume`, method: 'post' })
}

/** 截止时间延长 5 分钟 */
export function extendCollection(id) {
  return request({ url: `/collections/${id}/extend`, method: 'post' })
}

/** 提交一份答卷；durationSeconds = 从打开填写页到提交的秒数 */
export function submitCollectionResponse(id, answers, durationSeconds) {
  const data = { answers }
  if (durationSeconds != null) data.duration_seconds = Math.max(0, Math.round(durationSeconds))
  return request({ url: `/collections/${id}/responses`, method: 'post', data })
}

/** 答卷列表（发起人/管理员，服务端按提交时间排序） */
export function getCollectionResponses(id, params) {
  return request({ url: `/collections/${id}/responses`, method: 'get', params })
}

/** 未填名单 */
export function getCollectionPending(id) {
  return request({ url: `/collections/${id}/pending`, method: 'get' })
}

/** 删除一份答卷（仅管理员） */
export function deleteCollectionResponse(id, responseId) {
  return request({ url: `/collections/${id}/responses/${responseId}`, method: 'delete' })
}

/** 答题人撤回自己的答卷（出卷人开启「允许撤回」时） */
export function withdrawCollectionResponse(id, responseId) {
  return request({
    url: `/collections/${id}/responses/${responseId}/withdraw`,
    method: 'post'
  })
}

/** 批量删除答卷（仅管理员） */
export function batchDeleteCollectionResponses(id, responseIds) {
  return request({
    url: `/collections/${id}/responses/batch-delete`,
    method: 'post',
    data: { response_ids: responseIds }
  })
}

/**
 * 提醒未填 / 未填满的人
 * scope: unfilled 只催一份没交的；partial 只催交过但没填满的；all 两者都催
 */
export function remindCollection(id, scope = 'all') {
  return request({
    url: `/collections/${id}/remind`,
    method: 'post',
    params: { scope }
  })
}

/** 统计 */
export function getCollectionStatistics(id) {
  return request({ url: `/collections/${id}/statistics`, method: 'get' })
}

/** 分享页公开信息（无需登录） */
export function getCollectionShareInfo(token) {
  return request({
    url: `/collections/share/${encodeURIComponent(token)}/info`,
    method: 'get'
  })
}

/** 上传答卷图片，返回 { token, name, size } */
export function uploadCollectionFile(id, file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  return request({
    url: `/collections/${id}/files`,
    method: 'post',
    data: form,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/** 导出地址（前端用 downloadFile 带 Cookie 下载） */
export function collectionExportUrl(id, order = 'asc') {
  return `/api/collections/${id}/responses/export?order=${encodeURIComponent(order)}`
}
