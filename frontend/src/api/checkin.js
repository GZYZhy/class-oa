import request, { progressHandler } from '@/utils/request'

/**
 * 签到式点名
 *
 * 班委端（发布 / 列表 / 详情 / 提前结束 / 看照片）都要求班委及以上；
 * 公开端凭链接就能读，签到本身必须登录且在当前这次签到的范围内。
 */

/**
 * 发布一次签到（班委及以上）
 *
 * @param {{title: string, remark: string, end_at: string,
 *          require_photo: boolean, targets: string[],
 *          location?: {lat: number, lng: number, radius_m: number, name: string}}} data
 *   end_at 用 'YYYY-MM-DD HH:mm'（和投票一样，后端按本地时间比）
 *   targets 是学号数组；姓名由后端从 Student 表取，不信任前端
 *   location 不传 = 不要求定位
 */
export function createCheckin(data) {
  return request({ url: '/checkins', method: 'post', data })
}

/** 签到详情（班委及以上），带每个人的签到状态、距离和照片地址 */
export function getCheckin(id) {
  return request({ url: `/checkins/${id}`, method: 'get' })
}

/** 提前结束并立即结算（班委及以上） */
export function closeCheckin(id) {
  return request({ url: `/checkins/${id}/close`, method: 'post' })
}

/** 截止前把截止时间往后推 5 分钟，可以反复点（班委及以上） */
export function extendCheckin(id) {
  return request({ url: `/checkins/${id}/extend`, method: 'post' })
}

/** 给还没签到的人发站内信（班委及以上），返回 { reminded } */
export function remindCheckin(id) {
  return request({ url: `/checkins/${id}/remind`, method: 'post' })
}

/**
 * 改签到标题
 *
 * 列表的「标题」列显示的就是它，搜索也搜它；标题不能为空。
 */
export function updateCheckinTitle(id, title) {
  return request({ url: `/checkins/${id}`, method: 'patch', data: { title } })
}

/** 删除一次签到（连带它结算生成的考勤记录） */
export function deleteCheckin(id) {
  return request({ url: `/checkins/${id}`, method: 'delete' })
}

/**
 * 公开信息：凭链接读，不登录也能看
 *
 * 登录状态下后端会附带 is_target / can_sign / signed_at 等本人字段；
 * 页面只认这些字段，不自己拿时间判断能不能签（口径只在后端一处）。
 */
export function getCheckinPublic(code) {
  return request({ url: `/checkins/public/${code}`, method: 'get' })
}

/**
 * 先上传签到照片，返回 { token }
 *
 * 选中照片就调它，不等点「签到」—— 大照片在手机上要传一阵，等到最后再传
 * 很容易传完时已经截止。后端会把「开始上传」的时刻签进令牌，截止前开始传的
 * 照片之后仍可用。
 *
 * @param {string} code
 * @param {File} photo 已经压缩过的图片
 * @param {{onProgress?: Function}} options onProgress(loaded, total)
 */
export function uploadCheckinPhoto(code, photo, { onProgress } = {}) {
  const form = new FormData()
  form.append('photo', photo)
  return request({
    url: `/checkins/public/${code}/photo`,
    method: 'post',
    data: form,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/**
 * 学生签到
 *
 * @param {string} code
 * @param {{lat?: number, lng?: number, photoToken?: string}} payload
 *   lat/lng 是 **GCJ-02**（高德坐标），由 utils/geolocation.js 从浏览器定位转过来
 *   photoToken 来自 uploadCheckinPhoto，不再在这里传文件
 */
export function signCheckin(code, { lat, lng, photoToken } = {}) {
  const form = new FormData()
  if (lat != null && lng != null) {
    form.append('lat', String(lat))
    form.append('lng', String(lng))
  }
  if (photoToken) form.append('photo_token', photoToken)

  return request({
    url: `/checkins/public/${code}/sign`,
    method: 'post',
    data: form,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
