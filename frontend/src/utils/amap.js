/**
 * 高德地图 JS API 的按需加载
 *
 * Key / 安全密钥来自 site-config.js（见 utils/site.js）。没配置时这里直接拒绝，
 * 由调用方降级成手填经纬度 —— **签到主体功能不依赖地图**。
 *
 * 所有 window / document 引用都放在函数里：SSR 测试里 top-level 不能碰这些。
 */

import { SITE } from './site'

/** 有没有配 Key。配了才值得去碰地图 */
export function hasAmap() {
  return !!SITE.amapKey
}

/** 正在加载的 Promise（单例）。失败时清空，允许下次重试 */
let loading = null

/**
 * 加载高德 JS API，resolve 出 window.AMap
 *
 * 2.0 版要求安全密钥在脚本加载**之前**写到 window._AMapSecurityConfig；
 * 只建了 Key 没配安全密钥的账号，这个字段留空也能用。
 */
export function loadAmap() {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return Promise.reject(new Error('当前环境不支持地图'))
  }
  if (window.AMap) return Promise.resolve(window.AMap)
  if (!hasAmap()) return Promise.reject(new Error('未配置高德地图'))
  if (loading) return loading

  loading = new Promise((resolve, reject) => {
    if (SITE.amapSecurityCode) {
      window._AMapSecurityConfig = { securityJsCode: SITE.amapSecurityCode }
    }
    const script = document.createElement('script')
    // Geocoder 反查地址、PlaceSearch 搜地点、Scale 比例尺，
    // 都跟着主脚本一起拉，省异步插件加载
    script.src =
      `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(SITE.amapKey)}` +
      '&plugin=AMap.Geocoder,AMap.PlaceSearch,AMap.Scale'
    script.async = true
    script.onload = () => {
      if (window.AMap) {
        resolve(window.AMap)
      } else {
        loading = null
        script.remove()
        reject(new Error('高德地图加载失败'))
      }
    }
    script.onerror = () => {
      loading = null
      script.remove()
      reject(new Error('高德地图加载失败，请检查网络'))
    }
    document.head.appendChild(script)
  })
  return loading
}

/**
 * 用高德把坐标反查成地名（「示例市示例区示例路1号」这种）
 *
 * 失败（没配 Key、网络断、查不到）一律 resolve 空串，不抛错：
 * 地点名只是给人看的补充，发布人本来就能手填。
 */
export function reverseGeocode(AMap, lat, lng) {
  return new Promise((resolve) => {
    try {
      const geocoder = new AMap.Geocoder({ radius: 500 })
      geocoder.getAddress([lng, lat], (status, result) => {
        const address = status === 'complete' ? result?.regeocode?.formattedAddress : ''
        resolve(address || '')
      })
    } catch {
      resolve('')
    }
  })
}
