import request from '@/utils/request'

// 「账户设置」里两条新通知渠道的接口：自定义 webhook 和电子邮件。
// Bark 和浏览器推送在 api/bark.js、api/webpush.js 里，四条渠道各管各的开关。

/** 读取我的自定义 webhook 设置（地址、body 模板，以及默认模板供占位提示用） */
export function getWebhookSetting() {
  return request({ url: '/auth/webhook', method: 'get' })
}

/** 保存 webhook 设置；地址传空串表示关闭这条渠道 */
export function saveWebhookSetting(url, template) {
  return request({ url: '/auth/webhook', method: 'put', data: { url, template } })
}

/**
 * 往我配置的地址发一条测试通知
 *
 * 放宽到 30 秒：后端要先解析域名、再等对方的 HTTP 响应，慢的时候几秒到十几秒
 * （总预算 20 秒），照默认的 15 秒算用户会看到「网络错误」而不是真实结果。
 * 理由和 api/webpush.js 的测试端点一样。
 */
export function testWebhook() {
  return request({ url: '/auth/webhook/test', method: 'post', timeout: 30000 })
}

/** 读取我的邮件通知设置（含学生档案里可用的邮箱，供占位提示用） */
export function getEmailNotifySetting() {
  return request({ url: '/auth/email-notify', method: 'get' })
}

/** 保存邮件通知设置；email 传空串表示用学生档案里的邮箱 */
export function saveEmailNotifySetting(email, enabled) {
  return request({ url: '/auth/email-notify', method: 'put', data: { email, enabled } })
}

/** 给我自己发一封测试邮件（后端只发当前账号自己的地址，不接受传入地址） */
export function testEmailNotify() {
  return request({ url: '/auth/email-notify/test', method: 'post', timeout: 30000 })
}
