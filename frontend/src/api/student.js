import request from '@/utils/request'

/**
 * 获取学生列表
 */
export function getStudentList(params) {
  return request({
    url: '/students',
    method: 'get',
    params
  })
}

/**
 * 获取学生详情
 */
export function getStudent(id) {
  return request({
    url: `/students/${id}`,
    method: 'get'
  })
}

/**
 * 我的信息（当前登录者自己那条，普通学生也调得动）
 */
export function getMyInfo() {
  return request({
    url: '/students/me',
    method: 'get'
  })
}

/**
 * 获取统计数据
 */
export function getStatistics() {
  return request({
    url: '/students/statistics',
    method: 'get'
  })
}

/**
 * 获取筛选选项
 */
export function getFilterOptions() {
  return request({
    url: '/students/filter-options',
    method: 'get'
  })
}

/**
 * 上报点名结果（后端只写一条操作日志，不存业务数据）
 */
export function logRollCall(data) {
  return request({
    url: '/students/roll-call',
    method: 'post',
    data
  })
}

/**
 * 新增学生
 */
export function createStudent(data) {
  return request({
    url: '/students',
    method: 'post',
    data
  })
}

/**
 * 更新学生信息
 */
export function updateStudent(id, data) {
  return request({
    url: `/students/${id}`,
    method: 'put',
    data
  })
}

/**
 * 删除学生
 */
export function deleteStudent(id) {
  return request({
    url: `/students/${id}`,
    method: 'delete'
  })
}
