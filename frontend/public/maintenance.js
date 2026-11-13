/* 维护页独立运行，后端恢复后回到原页面。只接受本站路径。 */
const site = window.__SITE__ || {}
const siteName = site.name || '班级信息管理系统'
document.getElementById('site-name').textContent = siteName
document.title = `维护中 - ${siteName}`
if (site.logoUrl) document.getElementById('site-logo').src = site.logoUrl

const params = new URLSearchParams(window.location.search)
const original = window.location.pathname === '/maintenance.html'
  ? params.get('return') || '/'
  : window.location.pathname + window.location.search + window.location.hash
let target = new URL('/', window.location.origin)
try {
  const candidate = new URL(original, window.location.origin)
  if (candidate.origin === window.location.origin && candidate.pathname !== '/maintenance.html') {
    target = candidate
  }
} catch {
  // 无效返回地址使用本站首页。
}
document.getElementById('retry').href = target.href
document.querySelector('meta[http-equiv="refresh"]').content = `60;url=${target.href}`
