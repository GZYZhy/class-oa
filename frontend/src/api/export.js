/**
 * 学生信息导出申请 API
 *
 * 班委提交 → 管理员审核 → 通过后生成文件 → 下载
 */

import request from '@/utils/request'

// ---------- 字段元信息 ----------

/** 获取导出字段分组（前端渲染复选框用） */
export function getExportFieldGroups() {
  return request.get('/export-requests/field-groups')
}

// ---------- 学生 / 班委侧 ----------

/** 提交导出申请 */
export function createExportRequest(data) {
  return request.post('/export-requests', data)
}

/** 我的导出申请列表 */
export function getMyExportRequests(params) {
  return request.get('/export-requests/mine', { params })
}

/** 下载已通过的导出文件 */
export function downloadExportFile(id, onProgress, signal) {
  return request.get(`/export-requests/${id}/download`, {
    responseType: 'blob',
    onDownloadProgress: (e) => onProgress && onProgress(e.loaded || 0, e.total || 0),
    signal
  })
}

// ---------- 管理员侧 ----------

/** 导出申请列表（管理员） */
export function getExportRequests(params) {
  return request.get('/export-requests', { params })
}

/** 通过导出申请 */
export function approveExportRequest(id) {
  return request.post(`/export-requests/${id}/approve`)
}

/** 驳回导出申请 */
export function rejectExportRequest(id, reason) {
  return request.post(`/export-requests/${id}/reject`, { reason })
}
