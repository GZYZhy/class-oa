/**
 * 浏览器通知（Web Push）—— 只管浏览器这一侧的事
 *
 * 注册 Service Worker、申请权限、订阅/退订都在这里。
 * 把订阅信息交给后端存下来是 api/webpush.js 的活。
 *
 * 几条硬约束（踩过才知道）：
 * - 非安全上下文注册不了 SW。生产必须 HTTPS，localhost 算安全，局域网 IP 不算。
 * - Notification.requestPermission() 必须在用户点击的**同步路径**里调用，
 *   前面不能先 await 别的请求，否则 Safari 会静默拒绝。
 * - iPhone 上 Safari 只有在「添加到主屏」并**从主屏图标启动**之后才有
 *   PushManager，普通标签页里连权限弹窗都弹不出来。
 */

const SW_URL = '/sw.js'

/** 当前环境是否具备做浏览器通知的条件 */
export function isSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

/** 是否以「添加到主屏」的独立应用形态运行 */
export function isStandalone() {
  return (
    window.navigator.standalone === true ||
    window.matchMedia?.('(display-mode: standalone)').matches === true
  )
}

// ===== PWA 原生安装提示（beforeinstallprompt） =====
//
// 只有 Chrome / Edge / Android 支持这个事件，iOS Safari 没有。
// 用法：在应用启动时调用 captureInstallPrompt() 把事件接住，
// 然后需要弹的时候调用 triggerInstallPrompt()。

let deferredPrompt = null

/** 接住浏览器的 beforeinstallprompt 事件，存起来后面手动触发 */
export function captureInstallPrompt() {
  if (typeof window === 'undefined') return
  window.addEventListener('beforeinstallprompt', (e) => {
    // 阻止浏览器自动弹安装横幅（我们想在合适的时机自己弹）
    e.preventDefault()
    deferredPrompt = e
  })
  // 安装成功后清掉
  window.addEventListener('appinstalled', () => {
    deferredPrompt = null
  })
}

/** 当前能不能触发安装提示 */
export function canInstall() {
  return !!deferredPrompt
}

/** 触发浏览器原生的安装横幅。返回是否安装成功（用户点了"安装"） */
export async function triggerInstallPrompt() {
  if (!deferredPrompt) return false
  deferredPrompt.prompt()
  const { outcome } = await deferredPrompt.userChoice
  deferredPrompt = null
  return outcome === 'accepted'
}

/** 是不是 iOS/iPadOS。iPadOS 会把自己报成 Mac，所以补一条触摸点数判断 */
export function isIos() {
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  )
}

/**
 * 注册 Service Worker（幂等，重复调用返回同一个 registration）
 *
 * 必须先 register 再等 ready：页面上从来没注册过 SW 时，
 * navigator.serviceWorker.ready 会永远 pending（不是 reject），
 * 直接 await 它就是一个静默死锁。
 */
export async function register() {
  await navigator.serviceWorker.register(SW_URL)
  return navigator.serviceWorker.ready
}

/** 取当前浏览器已有的订阅；没有订阅时返回 null */
export async function currentSubscription() {
  if (!isSupported()) return null
  const reg = await register()
  return reg.pushManager.getSubscription()
}

/**
 * 开启通知：申请权限 + 订阅
 *
 * 调用方必须从点击事件里直接调进来，中间不要插 await。
 */
export async function subscribe(vapidPublicKey) {
  if (!isSupported()) throw new Error('当前浏览器不支持通知')

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error('浏览器没有允许通知，可在地址栏左侧的站点设置里改回来')

  const reg = await register()
  return reg.pushManager.subscribe({
    // 浏览器强制要求，含义是「每条推送都必须显示通知」；
    // iOS 也正是靠这条来保证不会拿推送当后台同步用
    userVisibleOnly: true,
    applicationServerKey: base64UrlToUint8Array(vapidPublicKey)
  })
}

/** 关闭通知：解除浏览器这一侧的订阅 */
export async function unsubscribe() {
  const sub = await currentSubscription()
  if (sub) await sub.unsubscribe()
}

/**
 * VAPID 公钥从 base64url 文本转成字节数组
 *
 * pushManager.subscribe 的 applicationServerKey 要字节数组：Chrome 能直接吃字符串，
 * Safari 不行。统一转成数组，两边都不会踩坑。
 */
function base64UrlToUint8Array(base64Url) {
  // base64url 省略了尾部的 =，atob 要求补回来
  const padding = '='.repeat((4 - (base64Url.length % 4)) % 4)
  const base64 = (base64Url + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}
