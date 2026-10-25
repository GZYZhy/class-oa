import request from '@/utils/request'

/**
 * 首页天气卡
 *
 * 走后端 `/api/weather`：位置名、经纬度、点开的天气网站都在 .env 里，
 * 服务端取数并缓存 10 分钟（全班刷新只产生个位数外呼）。
 * 接口公开 —— 游客也要能看首页这张卡。
 *
 * 浏览器这边再加一层 5 分钟缓存：SPA 里来回切页（首页 → 通知 → 首页）
 * 不该每次都打一次请求。失败的**不缓存**，下次进来还应该再试。
 */
const CLIENT_TTL = 5 * 60 * 1000
let cached = null

export async function getWeather() {
  const now = Date.now()
  if (cached && now - cached.at < CLIENT_TTL) return cached.data

  const data = await request({
    url: '/weather',
    method: 'get',
    // 比全局 15 秒短：后端自己 3 秒就放弃，这边留点余量就够；
    // 真挂了也别让卡片一直转圈
    timeout: 8000
  })

  if (data?.state !== 'error') cached = { at: now, data }
  return data
}

/**
 * 我的天气提醒设置（登录）
 *
 * 返回里带 available_conditions / windows 两份元数据（中文标签），
 * 前端照着渲染即可 —— 加一种天气条件只改后端一处。
 */
export function getWeatherNotify() {
  return request({ url: '/weather/notify', method: 'get' })
}

/** 保存我的天气提醒设置（整体覆盖） */
export function saveWeatherNotify(data) {
  return request({ url: '/weather/notify', method: 'put', data })
}
