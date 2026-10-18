/**
 * 定位与坐标换算
 *
 * 全站的签到坐标统一用 **GCJ-02**（高德地图用的坐标系）：
 * - 发布人在地图上点选，拿到的本来就是 GCJ-02；
 * - 浏览器 navigator.geolocation 返回的是 WGS-84，学生签到前必须先转，
 *   否则在国内会有几百米的系统性偏差，100 米的半径直接判错。
 *
 * 这里不碰 window / navigator 的顶层属性（都在函数里取），SSR 测试可以安全 import。
 */

/** GCJ-02 对 WGS-84 的偏移参数（行业里通用的公开算法） */
const A = 6378245.0
const EE = 0.00669342162296594323

/** 粗略判断是否在中国范围内。境外原样返回，不做偏移 */
function outOfChina(lat, lng) {
  return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271
}

function transformLat(x, y) {
  let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0
  ret += ((20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin((y / 3.0) * Math.PI)) * 2.0) / 3.0
  ret += ((160.0 * Math.sin((y / 12.0) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30.0)) * 2.0) / 3.0
  return ret
}

function transformLng(x, y) {
  let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0
  ret += ((20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin((x / 3.0) * Math.PI)) * 2.0) / 3.0
  ret += ((150.0 * Math.sin((x / 12.0) * Math.PI) + 300.0 * Math.sin((x / 30.0) * Math.PI)) * 2.0) / 3.0
  return ret
}

/** WGS-84 → GCJ-02。境外坐标原样返回；返回值保留 6 位小数（约 0.1 米） */
export function wgs84ToGcj02(lat, lng) {
  if (outOfChina(lat, lng)) return { lat, lng }
  let dLat = transformLat(lng - 105.0, lat - 35.0)
  let dLng = transformLng(lng - 105.0, lat - 35.0)
  const radLat = (lat / 180.0) * Math.PI
  let magic = Math.sin(radLat)
  magic = 1 - EE * magic * magic
  const sqrtMagic = Math.sqrt(magic)
  dLat = (dLat * 180.0) / (((A * (1 - EE)) / (magic * sqrtMagic)) * Math.PI)
  dLng = (dLng * 180.0) / ((A / sqrtMagic) * Math.cos(radLat) * Math.PI)
  return {
    lat: Number((lat + dLat).toFixed(6)),
    lng: Number((lng + dLng).toFixed(6))
  }
}

/** 两点间的球面距离（米），和服务器结算用的是同一个公式（haversine） */
export function distanceMeters(lat1, lng1, lat2, lng2) {
  const R = 6371000
  const toRad = (deg) => (deg * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLng = toRad(lng2 - lng1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(Math.min(1, a)))
}

/**
 * 取当前位置，返回 GCJ-02 坐标 { lat, lng, accuracy }
 *
 * accuracy 是浏览器给的定位精度（米）。手机上室内定位可能差几百米，
 * 调用方可以把它提示给用户，但**不要**拿它去放宽半径 —— 半径是发布人定的。
 */
export function getCurrentLocation(options = {}) {
  return new Promise((resolve, reject) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      reject(new Error('当前浏览器不支持定位'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const gcj = wgs84ToGcj02(pos.coords.latitude, pos.coords.longitude)
        resolve({ ...gcj, accuracy: Math.round(pos.coords.accuracy || 0) })
      },
      (err) => {
        // 浏览器的错误对象里只有英文/代码，这里换成能看懂的中文。
        // code 要带出去：降级逻辑靠它判断「权限被拒」还是「信号不好」。
        const messages = {
          1: '定位权限被拒绝，请在浏览器设置里允许本站获取位置',
          2: '暂时获取不到位置，请到室外或信号好的地方重试',
          3: '定位超时，请重试'
        }
        const error = new Error(messages[err?.code] || '定位失败，请重试')
        error.code = err?.code
        reject(error)
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0,
        ...options
      }
    )
  })
}

/** 两步定位的阶段：high = 高精度，low = 低精度兜底 */
export const GEO_STAGE_HIGH = 'high'
export const GEO_STAGE_LOW = 'low'

/**
 * 签到用的两步定位：先高精度（8 秒），失败再走低精度（12 秒）
 *
 * 室外第一次通常就成功。室内 / 地下室 GPS 弱，高精度可能一直等不到；
 * 低精度会走 Wi-Fi / 基站，往往更快，但精度可能差几百米 —— 精度只用于
 * 提示用户，**不拿它去放宽签到半径**（半径是发布人定的）。
 *
 * maximumAge 适当放宽：刚进楼、GPS 刚丢时，30 秒内的位置通常还在同一栋楼；
 * 低精度阶段允许用 2 分钟内的 Wi-Fi / 基站定位。位置再旧就可能不是这个人
 * 此刻所在的地方了，不再放宽。
 *
 * 权限被拒绝时直接抛出，不做第二次：浏览器不会因为换参数就放行。
 *
 * @param {(stage: 'high'|'low') => void} [onStage] 进入某个阶段时回调（页面显示「正在尝试低精度定位」）
 */
export async function getCurrentLocationStaged(onStage) {
  try {
    return await getCurrentLocation({
      enableHighAccuracy: true,
      timeout: 8000,
      maximumAge: 30000           // 刚进楼时，30 秒内的位置通常还能用
    })
  } catch (e) {
    if (e?.code === 1) throw e    // 权限拒绝，再试也没用
    onStage?.(GEO_STAGE_LOW)
    return getCurrentLocation({
      enableHighAccuracy: false,
      timeout: 12000,
      maximumAge: 120000          // 最近 2 分钟内的 Wi-Fi / 基站定位可以用
    })
  }
}
