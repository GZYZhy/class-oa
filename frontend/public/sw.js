/* 站点的 Service Worker
 *
 * 只做两件事：收推送、点通知。
 *
 * 刻意**不拦截 fetch**：本站不做离线缓存。一是班级数据含隐私
 * （身份证、家庭住址、照片），不该落到磁盘上；二是没有缓存就没有
 * 「用户拿着旧缓存等不到新数据」那一整类麻烦。
 */

/* 站点品牌：和页面共用同一个运行时配置文件（见 site-config.js.template）。
 *
 * 必须用 try 包住：这个文件万一没部署成功，importScripts 会抛错，而顶层抛错
 * 会让整个 SW 装不上 —— 推送整块废掉，比通知标题不好看严重得多。
 * 拿不到就用下面 APP_NAME 的兜底文案。 */
try {
  importScripts('/site-config.js')
} catch (e) {
  /* 忽略：下面的 APP_NAME 会退回兜底值 */
}

// 和 src/utils/site.js 保持一致：没注入成功就用兜底文案
const APP_NAME = self.__SITE__?.name || '班级信息管理系统'

self.addEventListener('install', () => {
  // 不等用户关页面，新版 SW 立刻进入等待
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  // 立刻接管已经打开的页面，否则要刷新一次才生效
  event.waitUntil(self.clients.claim())
})

// 收到推送。
//
// iOS 规定这里**必须无条件调用 showNotification**：累计 3 次收到 push
// 却没有显示通知，Safari 会直接撤销本站在该设备上的推送权限。
// 所以下面不允许出现任何「看情况决定显不显示」的分支。
self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (e) {
    // 后端发的是 JSON；万一不是，也要照样弹一条，不能因为解析失败就不显示
    data = {}
  }

  const options = {
    body: data.body || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    // 同一类通知（同一个 tag）覆盖上一条，避免多条请假互相刷屏；
    // renotify 让覆盖时仍然震动/响铃一次 —— 漏掉「请假被驳回」比多震一下更糟
    tag: data.tag || 'oa-notify',
    renotify: true,
    data: { url: data.url || '/' }
  }

  event.waitUntil(self.registration.showNotification(data.title || APP_NAME, options))
})

// 点通知：优先聚焦已经打开的窗口，没有才新开一个。
// 前端是 hash 路由，payload 里的 url 已经是 /#/xxx 这种形式。
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = event.notification.data?.url || '/'

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        // 同源窗口里随便挑一个，先把它切到目标路由再聚焦
        if ('focus' in client) {
          client.navigate(url)
          return client.focus()
        }
      }
      return self.clients.openWindow(url)
    })
  )
})
