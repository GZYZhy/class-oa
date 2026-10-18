import request from '@/utils/request'

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

/** 删除一条考勤记录（含明细）。签到生成的记录会连签到一起删 */
export function deleteAttendance(id) {
  return request({ url: `/attendance/${id}`, method: 'delete' })
}

/**
 * 批量删除勾选的记录
 *
 * 点名和签到的 id 各自独立，分两组传。签到会连带删掉照片和结算生成的考勤，
 * 链接随即失效；签到生成的考勤若被单独勾中，后端会把身后的签到一起删
 */
export function batchDeleteAttendance({ recordIds = [], checkinIds = [] } = {}) {
  return request({
    url: '/attendance/batch-delete',
    method: 'post',
    data: { record_ids: recordIds, checkin_ids: checkinIds }
  })
}

/**
 * 点名与签到合并后的列表（班委及以上）
 *
 * 每行带 type（attendance / checkin），前端按它取各自的列。
 * params: { start, end, keyword, page, page_size }
 */
export function getAttendanceOverview(params) {
  return request({ url: '/attendance/overview', method: 'get', params })
}

/**
 * 我的考勤情况（学生本人）：只包含自己参与的点名与签到
 *
 * 返回 { total, items }，每行带 category（点名/签到）、scope、status_label。
 */
export function getMyAttendance() {
  return request({ url: '/attendance/mine', method: 'get' })
}

/** 学生详情卡片里的考勤情况（班委及以上），内容与学生端一致 */
export function getStudentAttendance(studentId) {
  return request({ url: `/attendance/student/${studentId}`, method: 'get' })
}

/**
 * 导出考勤记录（班委及以上）的下载地址
 *
 * 两种模式二选一：
 * - 传 recordIds / checkinIds：只导出勾选的记录；
 * - 都不传：按 start / end / keyword 导出当前筛选结果。
 *
 * 只拼地址不下载：下载要走 utils/download.js 的 downloadFile（带登录态、
 * 会被 401 拦截器接住），直接用 <a href> 拿到的可能是一个 401 的 JSON。
 */
export function attendanceExportUrl({ start, end, keyword, recordIds, checkinIds } = {}) {
  const params = new URLSearchParams()
  if (start) params.set('start', start)
  if (end) params.set('end', end)
  if (keyword) params.set('keyword', keyword)
  for (const id of recordIds || []) params.append('record_ids', id)
  for (const id of checkinIds || []) params.append('checkin_ids', id)
  const query = params.toString()
  return `/api/attendance/export${query ? `?${query}` : ''}`
}
