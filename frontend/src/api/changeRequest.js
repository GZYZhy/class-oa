import request from '@/utils/request'

/**
 * 提交自己的信息修改申请
 *
 * data 只放要改的字段。可改字段的清单**不在这里抄一份** —— 那份清单是
 * utils/changeFields.js 的 CHANGE_FIELDS（与后端 change_requests.EDITABLE_FIELDS 一一对应），
 * 抄到这里只会像之前那样悄悄过期（原先这行注释就漏了 bed）。
 *
 * photo 是可选的 File（自备证件照）：文件塞不进 JSON，所以有它时改走 multipart。
 * 后端在同一个请求里落盘并建申请，学生拿不到文件名 —— 也就构造不出引用别人照片的申请。
 */
export function submitChangeRequest(data, photo) {
  if (!photo) {
    return request({
      url: '/change-requests',
      method: 'post',
      data
    })
  }

  const fd = new FormData()
  // 逐字段 append，而不是把整个 JSON 塞进一个字段：后端按 multipart 的文本项
  // 还原成同一份 schema，两条路径共用同一套校验
  for (const [key, value] of Object.entries(data)) fd.append(key, value)
  fd.append('photo', photo)

  return request({
    url: '/change-requests',
    method: 'post',
    data: fd,
    // request.js 给 axios 写死了 application/json，不改掉后端会按 JSON 解析、拿不到文件
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 我的申请记录（最新在前），用于「我的信息」页展示审核状态 */
export function getMyChangeRequests() {
  return request({
    url: '/change-requests/me',
    method: 'get'
  })
}

/** 申请列表（班委及以上）；status 可选 pending / approved / rejected，不传为全部 */
export function getChangeRequests(params) {
  return request({
    url: '/change-requests',
    method: 'get',
    params
  })
}

/** 通过申请：后端会把 changes 里的字段真正写进学生表 */
export function approveChangeRequest(id) {
  return request({
    url: `/change-requests/${id}/approve`,
    method: 'post'
  })
}

/** 驳回申请，需给出理由 */
export function rejectChangeRequest(id, reason) {
  return request({
    url: `/change-requests/${id}/reject`,
    method: 'post',
    data: { reason }
  })
}
