/**
 * 页面 head 里的分享 meta
 *
 * 外链页的 meta 由后端在服务端写好（nginx SSI 注入，微信爬虫读的是那一份）。
 * 这里负责两件事：
 *   1. 客户端再补一份，给会执行 JS 的客户端和站内直接打开的情况；
 *   2. 关闭分享页 / 离开时恢复站点默认值。
 *
 * **只更新 head 里已有的同名标签，不盲目 append**：服务端 SSI 已经写好的标签
 * 如果再去 new 一个，页面就会出现两个 title / og:description，微信取到哪个
 * 全看实现，卡片会时对时错。
 */

import { SITE } from './site'

const FLAG = 'data-share-meta'
const DEFAULT_DESCRIPTION = SITE.description || SITE.name || ''
const DEFAULT_ROBOTS = 'noindex, nofollow'

function metas(key, attr) {
  return document.head.querySelectorAll(`meta[${attr}="${key}"]`)
}

/** 更新第一个同名标签；多余的重复项删掉；一个都没有才新建 */
function setMeta(key, content, attr = 'property') {
  const nodes = metas(key, attr)
  if (nodes.length) {
    nodes[0].setAttribute('content', content)
    for (let i = 1; i < nodes.length; i += 1) nodes[i].remove()
    return
  }
  const el = document.createElement('meta')
  el.setAttribute(attr, key)
  el.setAttribute('content', content)
  el.setAttribute(FLAG, '1')
  document.head.appendChild(el)
}

function removeMeta(key, attr = 'property') {
  metas(key, attr).forEach((el) => el.remove())
}

/** 512 的图标：logo.png 往往只有一百多像素，微信卡片可能因尺寸太小不显示图 */
function defaultImage() {
  return new URL('/icons/share-512.jpg', window.location.origin).href
}

/**
 * （重新）写入一场分享的 meta
 *
 * @param {{title: string, description?: string, url?: string, image?: string,
 *          index?: boolean}} data
 *   title 已经带好「投票：」「签到：」「公告：」前缀；
 *   index=false 表示失效页，写 noindex。
 */
export function applyShareMeta(data = {}) {
  const title = data.title || SITE.name
  const description = data.description || DEFAULT_DESCRIPTION
  const url = data.url || ''
  const image = data.image || defaultImage()

  document.title = title
  setMeta('description', description, 'name')
  setMeta('robots', data.index === false ? 'noindex, nofollow' : 'index,follow', 'name')
  setMeta('og:title', title)
  setMeta('og:description', description)
  if (url) setMeta('og:url', url)
  setMeta('og:image', image)
  setMeta('og:image:width', '512')
  setMeta('og:image:height', '512')
  setMeta('og:site_name', SITE.name)
  setMeta('og:locale', 'zh_CN')
  setMeta('twitter:card', 'summary', 'name')
  setMeta('twitter:title', title, 'name')
  setMeta('twitter:description', description, 'name')
  setMeta('twitter:image', image, 'name')
}

/**
 * 离开分享页 / 关闭分享弹窗：恢复站点默认的摘要和 robots
 *
 * og:title / og:url / twitter:* 是某一场的专属信息，直接删掉；
 * description / robots / og:description 恢复成站点值。
 * 服务端已经注入的标签也一并处理 —— 页面在 SPA 内已经切走了，
 * 它们只对下一次完整加载有意义（那时服务端会重新生成）。
 */
export function resetShareMeta() {
  setMeta('description', DEFAULT_DESCRIPTION, 'name')
  setMeta('robots', DEFAULT_ROBOTS, 'name')
  removeMeta('og:title')
  removeMeta('og:url')
  removeMeta('twitter:card', 'name')
  removeMeta('twitter:title', 'name')
  removeMeta('twitter:description', 'name')
  removeMeta('twitter:image', 'name')
  setMeta('og:description', DEFAULT_DESCRIPTION)
  setMeta('og:image', defaultImage())
  setMeta('og:image:width', '512')
  setMeta('og:image:height', '512')
  setMeta('og:site_name', SITE.name)
  setMeta('og:locale', 'zh_CN')
}
