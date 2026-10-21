/**
 * 外链分享的地址工具
 *
 * 外链统一是真实路径 `/share/{kind}/{token}`，后端 services/share_service.py
 * 的 share_path 拼的是同一个形状；两处保持一致，换一种类型不用改路由。
 */

/** 站内路径（也是浏览器地址里的真实路径） */
export function sharePath(kind, token) {
  return `/share/${kind}/${encodeURIComponent(token)}`
}

/** 绝对地址：复制链接、生成二维码用 */
export function shareUrl(kind, token) {
  return `${window.location.origin}${sharePath(kind, token)}`
}

/**
 * 把真实路径补到地址栏，同时保留 hash
 *
 * 站内从 `#/share/vote/xxx` 进入分享页时，地址只有 hash；微信转发抓的是当前
 * 地址，hash 后面的内容不会发给服务器。补成 `/share/vote/xxx#/share/vote/xxx`
 * 之后，转发出去的地址就是爬虫能读到 meta 的真实路径。
 *
 * 用 replaceState：只改地址，不新增历史记录、不触发路由。
 */
export function attachSharePath(path) {
  if (!path) return
  try {
    if (window.location.pathname === path) return
    window.history.replaceState(
      window.history.state,
      '',
      path + window.location.search + window.location.hash
    )
  } catch (e) {
    /* 地址栏保持不动也能用，只是转发时卡片退回站点级摘要 */
  }
}

/**
 * 离开分享页时把真实路径还原成 `/#...`
 *
 * 正常情况下路由跳转已经会把地址改回 `/#/...`，这里是兜底：
 * 只有 pathname 还停在 /share/ 下才动手，避免覆盖路由刚写入的地址。
 */
export function detachSharePath(prefix) {
  if (!prefix) return
  try {
    if (!window.location.pathname.startsWith(prefix)) return
    window.history.replaceState(
      window.history.state,
      '',
      '/' + (window.location.hash || '#/')
    )
  } catch (e) {
    /* 忽略：地址没还原不影响页面本身 */
  }
}
