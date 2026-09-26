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

/**
 * 重置密码
 *
 * 学生账号：不用传 newPassword，重置为身份证号后 6 位，首次登录仍需改密。
 * 域外账号：必须传 newPassword（管理员直接指定），设完即可用。
 */
export function resetUserPassword(studentNo, newPassword) {
  return request({
    url: `/admin/users/${studentNo}/reset-password`,
    method: 'post',
    data: newPassword ? { password: newPassword } : {}
  })
}

/** 新建域外账号（不与学生关联的账号：老师、协助人员等） */
export function createExternalUser(formData) {
  return request({
    url: '/admin/external-users',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 修改域外账号的展示名 / 角色 / 头像 */
export function updateExternalUser(loginName, formData) {
  return request({
    url: `/admin/external-users/${loginName}`,
    method: 'put',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 删除域外账号（连同它的头像文件和推送订阅） */
export function deleteExternalUser(loginName) {
  return request({
    url: `/admin/external-users/${loginName}`,
    method: 'delete'
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
