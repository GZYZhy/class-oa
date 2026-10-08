import request from '@/utils/request'

// ---------- 个人日程 ----------

/**
 * 查询指定日期范围的日程
 * @param {string} startDate - 开始日期 YYYY-MM-DD
 * @param {string} endDate - 结束日期 YYYY-MM-DD
 */
export function listSchedules(startDate, endDate) {
  return request({
    url: '/schedules',
    method: 'get',
    params: { start_date: startDate, end_date: endDate }
  })
}

/**
 * 学期第 1 周的周一。页面上的「第几周」按它算：
 * 由课表导入时按表名「第N周」折算，别在前端另估一套
 */
export function getSemesterInfo() {
  return request({
    url: '/schedules/semester',
    method: 'get'
  })
}

/**
 * 获取单条日程详情
 * @param {number} id - 日程 ID
 * @param {string} instanceDate - 实例日期 YYYY-MM-DD
 */
export function getSchedule(id, instanceDate) {
  return request({
    url: `/schedules/item/${id}`,
    method: 'get',
    params: { instance_date: instanceDate }
  })
}

/**
 * 新建日程
 */
export function createSchedule(data) {
  return request({
    url: '/schedules',
    method: 'post',
    data
  })
}

/**
 * 编辑日程
 * @param {number} id - 日程 ID
 * @param {string} instanceDate - 实例日期
 * @param {object} data - 更新内容
 */
export function updateSchedule(id, instanceDate, data) {
  return request({
    url: `/schedules/item/${id}`,
    method: 'put',
    params: { instance_date: instanceDate },
    data
  })
}

/**
 * 删除日程
 * @param {number} id - 日程 ID
 * @param {string} instanceDate - 实例日期
 * @param {string} scope - 删除范围 single/forward/all
 */
export function deleteSchedule(id, instanceDate, scope = 'all') {
  return request({
    url: `/schedules/item/${id}`,
    method: 'delete',
    params: { instance_date: instanceDate, scope }
  })
}

// ---------- 导入（班委） ----------

/**
 * 上传日程 Excel 并预览
 * @param {File} file - xlsx 文件
 */
export function importPreview(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request({
    url: '/schedules/import/preview',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/**
 * 确认导入
 */
export function importConfirm(data) {
  return request({
    url: '/schedules/import',
    method: 'post',
    data
  })
}

/**
 * 查看导入批次列表
 */
export function listBatches() {
  return request({
    url: '/schedules/batches',
    method: 'get'
  })
}

/**
 * 撤销导入批次
 */
export function deleteBatch(batchId) {
  return request({
    url: `/schedules/batches/${batchId}`,
    method: 'delete'
  })
}

// ---------- iCal 订阅 ----------

/**
 * 获取 iCal 订阅链接
 */
export function getIcalToken() {
  return request({
    url: '/schedules/ical/token',
    method: 'get'
  })
}

/**
 * 重置 iCal 订阅令牌
 */
export function resetIcalToken() {
  return request({
    url: '/schedules/ical/token/reset',
    method: 'post'
  })
}
