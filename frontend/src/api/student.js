import request, { progressHandler } from '@/utils/request'

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
 * 新增学生（仅管理员）
 *
 * 会连带开通登录账号。返回体里 fallback=true 表示该生没有身份证号、
 * 初始密码退化成了学号后 6 位，这时 password 字段带着明文，需要单独告知本人。
 */
export function createStudent(data) {
  return request({
    url: '/students',
    method: 'post',
    data
  })
}

/**
 * 上传/替换学生照片（仅管理员）
 * @param {number} id 学生 id
 * @param {string} type gaokao=高考照片，on_site=实地采集
 * @param {File} file 照片文件
 */
export function uploadStudentPhoto(id, type, file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  return request({
    url: `/students/${id}/photo`,
    method: 'post',
    params: { type },
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/** 删除学生照片（仅管理员），type 同上 */
export function deleteStudentPhoto(id, type) {
  return request({
    url: `/students/${id}/photo`,
    method: 'delete',
    params: { type }
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

/**
 * Excel 导入 - 预览解析结果（不写库）
 * @param {File} file - Excel 文件
 * @param {string} [sheetName] - 工作表名，留空自动选
 */
export function importPreview(file, sheetName) {
  const formData = new FormData()
  formData.append('file', file)
  const params = {}
  if (sheetName) params.sheet_name = sheetName
  return request({
    url: '/students/import/preview',
    method: 'post',
    params,
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/**
 * Excel 导入 - 确认导入
 * @param {string} token - 预览接口返回的令牌
 */
export function importConfirm(token) {
  return request({
    url: '/students/import',
    method: 'post',
    data: { token }
  })
}

/**
 * 批量删除学生（仅管理员）
 * @param {number[]} ids - 学生 id 列表
 */
export function batchDeleteStudents(ids) {
  return request({
    url: '/students/batch-delete',
    method: 'post',
    data: { ids }
  })
}
