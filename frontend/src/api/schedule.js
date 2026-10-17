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
 * 按名称搜索日程（搜我的全部日程，不限于当前这一周）
 * 每条日程只回一行：重复日程给离今天最近的那一次，靠 instance_date 区分是哪一天
 * @param {string} keyword - 日程名称关键词
 */
export function searchSchedules(keyword) {
  return request({
    url: '/schedules/search',
    method: 'get',
    params: { keyword }
  })
}

/**
 * 各学期的周次区间。页面上的「第几周」按它算，别在前端另估一套
 * （按「9 月 1 日所在周」估出来比表名早两周，显示会整体偏早）。
 * 每项：week_start 是编号基准（第 1 周的周一，导入时按用户选的周次锚点推算写入），
 * first_day / last_day 是那份课表**实际覆盖到**的范围 —— 补课表可能只覆盖第 8–10 周，
 * 只有覆盖到的周才显示周次号。下学期再导入一份，就是又一个区间
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
 * @param {boolean} share - 是否一并改掉其他学生的表（只有分配者能传 true）
 */
export function updateSchedule(id, instanceDate, data, share = false) {
  return request({
    url: `/schedules/item/${id}`,
    method: 'put',
    // share 走 query 不走 body：后端把 body 里所有非 scope 字段当业务字段写入，
    // 混一个开关进去迟早写坏数据
    params: { instance_date: instanceDate, share },
    data
  })
}

/**
 * 删除日程
 * @param {number} id - 日程 ID
 * @param {string} instanceDate - 实例日期
 * @param {string} scope - 删除范围 single/forward/all
 * @param {boolean} share - 是否一并从其他学生的表里删掉（只有分配者能传 true）
 */
export function deleteSchedule(id, instanceDate, scope = 'all', share = false) {
  return request({
    url: `/schedules/item/${id}`,
    method: 'delete',
    params: { instance_date: instanceDate, scope, share }
  })
}

// ---------- 导入（班委） ----------

/**
 * 上传日程 Excel 并预览
 * @param {File} file - xlsx 文件
 */
export function importPreview(file, anchorMonday) {
  const formData = new FormData()
  formData.append('file', file)
  // 周次锚点：文件里最小周次那一周的周一（'YYYY-MM-DD'）。不给就由后端按表头猜一个
  if (anchorMonday) formData.append('anchor_monday', anchorMonday)
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
