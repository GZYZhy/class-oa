import request, { progressHandler } from '@/utils/request'

/**
 * 签到式点名
 *
 * 班委端（发布 / 列表 / 详情 / 提前结束 / 看照片）都要求班委及以上；
 * 公开端凭链接就能读，签到本身必须登录且在当前这次签到的范围内。
 */

/** 签到列表（班委及以上），返回 { total, items } */
export function getCheckins() {
  return request({ url: '/checkins', method: 'get' })
}

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
 * 学生签到
 *
 * @param {string} code
 * @param {{lat?: number, lng?: number, photo?: File, onProgress?: Function}} payload
 *   lat/lng 是 **GCJ-02**（高德坐标），由 utils/geolocation.js 从浏览器定位转过来
 */
export function signCheckin(code, { lat, lng, photo, onProgress } = {}) {
  const form = new FormData()
  if (lat != null && lng != null) {
    form.append('lat', String(lat))
    form.append('lng', String(lng))
  }
  if (photo) form.append('photo', photo)

  return request({
    url: `/checkins/public/${code}/sign`,
    method: 'post',
    data: form,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: progressHandler(onProgress)
  })
}

/** 签到照片的地址（班委端，img 的 src 直接用，Cookie 会带上） */
export function checkinPhotoUrl(id, studentNo) {
  return `/api/checkins/${id}/targets/${encodeURIComponent(studentNo)}/photo`
}
