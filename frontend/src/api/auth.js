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

/** 当前 IP 是否需要填验证码（登录失败 1 次后 10 分钟内需要） */
export function getCaptchaRequired() {
  return request({ url: '/auth/captcha-required', method: 'get' })
}

/** 退出登录 */
export function logout() {
  return request({ url: '/auth/logout', method: 'post' })
}

/** 当前登录用户信息 */
export function getMe() {
  return request({ url: '/auth/me', method: 'get' })
}

/** 首次登录设置密码（无需原密码） */
export function setInitialPassword(data) {
  return request({ url: '/auth/set-initial-password', method: 'post', data })
}

/** 主动修改密码（需原密码） */
export function changePassword(data) {
  return request({ url: '/auth/change-password', method: 'post', data })
}

/** 首页公开摘要（无需登录） */
export function getPublicSummary() {
  return request({ url: '/public/summary', method: 'get' })
}
