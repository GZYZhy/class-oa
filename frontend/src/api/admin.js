import request from '@/utils/request'

/** 账号列表（学号 / 姓名 / 角色 / 是否待改密） */
export function getUsers() {
  return request({
    url: '/admin/users',
    method: 'get'
  })
}

/** 设置某个账号的角色：student | committee | admin */
export function setUserRole(studentNo, role) {
  return request({
    url: `/admin/users/${studentNo}/role`,
    method: 'put',
    data: { role }
  })
}

/** 重置为原始密码（身份证号后 6 位），重置后该生首次登录仍需改密 */
export function resetUserPassword(studentNo) {
  return request({
    url: `/admin/users/${studentNo}/reset-password`,
    method: 'post'
  })
}

/** 操作日志，分页 + 按操作人/动作筛选 */
export function getLogs(params) {
  return request({
    url: '/admin/logs',
    method: 'get',
    params
  })
}

/** 清空全部操作日志（不可恢复，且不会留下「谁清的」记录） */
export function clearLogs() {
  return request({
    url: '/admin/logs',
    method: 'delete'
  })
}

// ==================== 资料下载管理 ====================

/** 资料列表（管理员用，不分组，按分类+排序） */
export function listResources() {
  return request({
    url: '/admin/resources',
    method: 'get'
  })
}

/** 上传新资料
 *  formData: { name, category, file }
 */
export function uploadResource(formData) {
  return request({
    url: '/admin/resources',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 修改资料名称 / 分类 */
export function updateResource(id, formData) {
  return request({
    url: `/admin/resources/${id}`,
    method: 'put',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 重排某个分类下的资料顺序 */
export function reorderResources(category, order) {
  return request({
    url: `/admin/resources/reorder/${encodeURIComponent(category)}`,
    method: 'put',
    data: order
  })
}

/** 删除资料（同时删文件） */
export function deleteResource(id) {
  return request({
    url: `/admin/resources/${id}`,
    method: 'delete'
  })
}
