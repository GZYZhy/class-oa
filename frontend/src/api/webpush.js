import request from '@/utils/request'

/** 读取浏览器通知状态：订阅用的 VAPID 公钥 + 本账号已订阅的设备数 */
export function getWebpushState() {
  return request({ url: '/auth/webpush', method: 'get' })
}

/**
 * 把浏览器当前的订阅登记到当前登录账号名下
 *
 * endpoint 是 upsert 键：同一台浏览器换账号登录时是改绑，不会多出一行。
 */
export function saveWebpushSubscription(subscription) {
  return request({ url: '/auth/webpush/subscribe', method: 'post', data: subscription })
}

/** 解除一条订阅（只能解除自己账号名下的） */
export function removeWebpushSubscription(endpoint) {
  return request({ url: '/auth/webpush/unsubscribe', method: 'post', data: { endpoint } })
}

/**
 * 给本账号已订阅的设备发一条测试通知
 *
 * 后端逐台发送、慢的超时是逐 IP 计算的，最坏情况十几秒，
 * 所以这里单独放宽到 30 秒，免得用户看到的是「网络错误」而不是真实结果。
 */
export function testWebpush() {
  return request({ url: '/auth/webpush/test', method: 'post', timeout: 30000 })
}
