/* 外链分享页的启动引导
 *
 * 外链是真实路径 /share/{kind}/{token}（服务器能看到是哪一场，才能写 meta），
 * 而前端是 hash 路由。这个脚本在 Vue Router 初始化之前，把真实路径补成
 * /share/{kind}/{token}#/share/{kind}/{token}：
 *
 *   - 只改地址，不新增历史记录、不触发导航，所以用户不会看到第二次跳转；
 *   - 真实路径保留在地址栏里：微信转发时抓的是这个地址，爬虫能读到 meta；
 *   - 刷新、前进后退、登录回跳都靠保留的 hash 自然工作。
 *
 * 必须用普通脚本（不是 module）：module 天生 defer，会晚于路由初始化。
 */
;(function () {
  // kind 放开成通用段，以后新增 notice / form 等类型不用改这里
  var match = /^\/share\/([a-zA-Z0-9_-]+)\/([^/]+)\/?$/.exec(window.location.pathname)
  if (!match) return

  // 已经有 hash（比如登录回跳带了 #/login）就不覆盖
  var hash = window.location.hash
  if (hash && hash !== '#' && hash !== '#/') return

  var target = '#/share/' + match[1] + '/' + match[2]
  try {
    window.history.replaceState(
      window.history.state,
      '',
      window.location.pathname + window.location.search + target
    )
  } catch (e) {
    // replaceState 失败（极老的浏览器 / 沙箱）时退回最普通的写法：
    // 仍然只换 hash，不会产生网络请求
    window.location.hash = target
  }
})()
