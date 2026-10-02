import request from '@/utils/request'

/** 登录（账号=学号，默认密码=身份证号后6位） */
export function login(data) {
  return request({ url: '/auth/login', method: 'post', data })
}

/** 获取验证码（SVG 图片，直接设到 <img src> 上就行） */
export function getCaptcha() {
  return request({ url: '/auth/captcha', method: 'get', responseType: 'blob' })
    .then(blob => URL.createObjectURL(blob))
}

/**
 * 当前 IP 是否需要人机验证，以及用哪一种（登录失败 1 次后 10 分钟内需要）
 *
 * 返回 { required, mode: 'math' | 'turnstile', site_key }。
 * mode 由后端 .env 有没有配 Turnstile 决定；site_key 只有 turnstile 时才有值，
 * 它本来就是公开的，配了才需要发给浏览器。
 */
export function getCaptchaRequired() {
  return request({ url: '/auth/captcha-required', method: 'get' })
}

/** 退出登录 */
export function logout() {
  return request({ url: '/auth/logout', method: 'post' })
}

/** 当前登录用户信息
 *
 * skipAuthRedirect：这是一次「我登录了吗」的探测，401 是预期答案、不是会话刚失效，
 * 所以不让响应拦截器跳登录页 —— 未登录的游客逛首页时也会走到这里，
 * 一跳就等于把游客强行赶去登录页。调用方 store.fetchMe() 会把 info 置空。
 */
export function getMe() {
  return request({ url: '/auth/me', method: 'get', skipAuthRedirect: true })
}

/** 首次登录设置密码（无需原密码） */
export function setInitialPassword(data) {
  return request({ url: '/auth/set-initial-password', method: 'post', data })
}

/** 主动修改密码（需原密码） */
export function changePassword(data) {
  return request({ url: '/auth/change-password', method: 'post', data })
}

/** 我的日志（本人自助）
 *
 * 返回 { operations: {total, items}, events, events_total, events_since }。
 * operations 是我作为操作人的记录（分页）；events 是最近 7 天的登录 / 自行改密。
 * 和管理员「查日志」是同一套查询，但**不给「被操作记录」** —— 那是管理员视角。
 */
export function getMyLogs(params) {
  return request({ url: '/auth/my-logs', method: 'get', params })
}

/** 首页公开摘要（无需登录） */
export function getPublicSummary() {
  return request({ url: '/public/summary', method: 'get' })
}

/* ---------- 访问令牌（给脚本 / MCP 用的长期凭据） ----------
 * 这三个接口后端都挂了 require_cookie_auth：**带令牌调一律 403**，
 * 免得一把泄露的令牌能自己再铸一把长期令牌。所以它们只能在浏览器里用。
 */

/** 列出我的访问令牌。返回 { items: [...], max_count }，**不含明文** */
export function getAccessTokens() {
  return request({ url: '/auth/tokens', method: 'get' })
}

/** 创建访问令牌。响应里的 token 是明文，**只出现这一次**，要提示用户立刻复制 */
export function createAccessToken(data) {
  return request({ url: '/auth/tokens', method: 'post', data })
}

/** 吊销访问令牌（只能吊销自己的） */
export function revokeAccessToken(id) {
  return request({ url: `/auth/tokens/${id}`, method: 'delete' })
}
