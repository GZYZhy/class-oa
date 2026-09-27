import request from './request'

/**
 * 取回受保护的文件
 *
 * 为什么不直接挂 `<a href="/api/...">` 让浏览器下载：后端文件接口全都要登录
 * （resources / announcements 的 file 接口都是 Depends(get_current_user)），
 * 而浏览器自己发起的导航或下载**不经过 axios 拦截器**。会话一失效（过期、被冻结、
 * 被吊销），用户拿到的是一个 401 错误页，或者更糟 —— 一个内容是错误 JSON、
 * 大小只有几十字节的「文件」，看上去还以为是资料坏了。走 axios 才能被 401 拦截器
 * 接住，正常踢回登录页。
 *
 * 代价是文件名得靠 a[download] 自己指定，拿不到响应头里那个原始名（后端发的是
 * 百分号编码的，前端本来也不好直接取）。
 */

/** 后端下发的是完整路径（/api/resources/file/xxx），而 request 的 baseURL 已经是
 *  /api，直接丢给 axios 会拼成 /api/api/xxx，所以这里统一剥掉前缀 */
function toApiPath(url) {
  return url.startsWith('/api/') ? url.slice(4) : url
}

function fetchBlob(url) {
  return request({ url: toApiPath(url), method: 'get', responseType: 'blob' })
}

/**
 * 从失败响应里取出后端给的 detail
 *
 * responseType 是 blob 时，后端返回的 JSON 也被包成了 Blob，直接读 .detail 恒为
 * undefined，错误提示就永远是兜底文案。这里把它读回来再解析。
 */
export async function blobErrorDetail(e, fallback = '下载失败') {
  const data = e?.response?.data
  if (data instanceof Blob) {
    try {
      return JSON.parse(await data.text()).detail || fallback
    } catch {
      return fallback
    }
  }
  return data?.detail || fallback
}

/** 下载：拉成 blob 再用隐藏 a 标签存盘，保留原文件名 */
export async function downloadFile(url, filename) {
  const blob = await fetchBlob(url)
  const objectUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = filename || ''
  // 节点要挂进文档里再点才生效（Firefox 尤其）
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // 延后释放：刚点完就 revoke 有概率把还没读完的下载掐断
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60000)
}

/** 预览：拉成 blob 后在新标签页打开（PDF、图片等） */
export async function previewFile(url) {
  const blob = await fetchBlob(url)
  // 这里不能 revoke：新标签页是异步去读这个地址的，当场释放只会得到一张空白页。
  // 一个 blob 引用留到刷新页面为止，代价很小，不值得为它引一套回收逻辑
  window.open(URL.createObjectURL(blob), '_blank')
}
