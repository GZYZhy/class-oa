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

/** 冻结账号：禁止登录，已登录的会话下一个请求就 401 */
export function freezeUser(studentNo) {
  return request({
    url: `/admin/users/${studentNo}/freeze`,
    method: 'post'
  })
}

/** 解冻账号 */
export function unfreezeUser(studentNo) {
  return request({
    url: `/admin/users/${studentNo}/unfreeze`,
    method: 'post'
  })
}

/** 吊销该账号的所有会话：把所有设备踢下线，但账号仍可正常登录 */
export function revokeUserSessions(studentNo) {
  return request({
    url: `/admin/users/${studentNo}/revoke-sessions`,
    method: 'post'
  })
}

/**
 * 某个账号的日志
 *
 * 返回 { student_no, name, operations: {total, items}, events, events_total, events_since }
 * operations 是它作为操作人的全部操作日志（分页）；
 * events 是最近 7 天的登录 / 自行改密，不分页，超过 200 条时看 events_total。
 */
export function getUserLogs(studentNo, params) {
  return request({
    url: `/admin/users/${studentNo}/logs`,
    method: 'get',
    params
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

/** 清空全部操作日志（不可恢复；清空本身会留一条「清空了日志」） */
export function clearLogs() {
  return request({
    url: '/admin/logs',
    method: 'delete'
  })
}

// ==================== IP 封禁 ====================

/** 封禁中的 IP 列表（分页 + 按 IP/网段模糊搜索），附带 self_ip 供提示「不能封自己」 */
export function getIpBans(params) {
  return request({
    url: '/admin/ip-bans',
    method: 'get',
    params
  })
}

/** 手动封禁。target 是单个 IP 或 CIDR 网段，minutes 为 null 表示永久 */
export function createIpBan({ target, minutes, reason }) {
  return request({
    url: '/admin/ip-bans',
    method: 'post',
    data: { target, minutes, reason }
  })
}

/** 解封（按记录 id，不用 target —— 网段和 IPv6 在 URL 路径里要转义） */
export function deleteIpBan(id) {
  return request({
    url: `/admin/ip-bans/${id}`,
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

// ==================== 文件访问日志 ====================

/** 文件访问日志列表（查看/下载），分页 + 筛选 */
export function getFileAccessLogs(params) {
  return request({
    url: '/admin/file-access-logs',
    method: 'get',
    params
  })
}

/** 从上传的 PDF 中提取不可见水印，返回下载人/时间/文件信息 */
export function extractWatermark(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request({
    url: '/admin/file-access-logs/extract',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
