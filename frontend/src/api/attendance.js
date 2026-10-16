import request from '@/utils/request'

/**
 * 考勤记录列表（班委及以上）
 *
 * 只带聚合计数，不带明细 —— 明细走 getAttendance。
 * params: { start, end, page, page_size }
 */
export function getAttendanceList(params) {
  return request({ url: '/attendance', method: 'get', params })
}

/** 考勤详情，带每个人的状态（改状态的对话框用） */
export function getAttendance(id) {
  return request({ url: `/attendance/${id}`, method: 'get' })
}

/**
 * 上报一次点名（班委及以上）
 *
 * @param {{scope: string, records: {student_no: string, name: string, status: string}[]}} data
 *   status 取 present（到）/ absent（无应答）/ leave（请假）
 */
export function createAttendance(data) {
  return request({ url: '/attendance', method: 'post', data })
}

/**
 * 写某次点名的备注
 *
 * 整条替换：传什么存什么，传空串 = 清掉（后端就是这么理解的，没有单独的删除接口）
 */
export function updateAttendanceRemark(id, remark) {
  return request({ url: `/attendance/${id}`, method: 'patch', data: { remark } })
}

/** 改某人状态 */
export function updateAttendanceItem(recordId, studentNo, status) {
  return request({
    url: `/attendance/${recordId}/items/${studentNo}`,
    method: 'patch',
    data: { status }
  })
}

/** 删除一条考勤记录（含明细） */
export function deleteAttendance(id) {
  return request({ url: `/attendance/${id}`, method: 'delete' })
}

/**
 * 导出考勤记录（班委及以上）的下载地址
 *
 * 只拼地址不下载：下载要走 utils/download.js 的 downloadFile（带登录态、
 * 会被 401 拦截器接住），直接用 <a href> 拿到的可能是一个 401 的 JSON。
 */
export function attendanceExportUrl(start, end) {
  const params = new URLSearchParams()
  if (start) params.set('start', start)
  if (end) params.set('end', end)
  const query = params.toString()
  return `/api/attendance/export${query ? `?${query}` : ''}`
}
