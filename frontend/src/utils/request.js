import axios from 'axios'

/**
 * 文件传输（上传/下载）专用的超时。
 *
 * 全局那 15 秒是给普通接口（查列表、提交表单）的，那类请求慢到 15 秒本来也该报错。
 * 但文件不一样：公告 PDF 大到 50MB、反馈附件单个 20MB，手机信号差的时候光传输
 * 就要几分钟，按 15 秒算必定中断 —— 用户看到的是「上传失败」，而不是「慢慢传完了」。
 *
 * axios 的 timeout 是**整个请求的总时长**，不是两次数据之间的间隔，所以大文件
 * 必须放宽，否则传得完也等不到。
 */
export const FILE_TIMEOUT = 5 * 60 * 1000

/** 普通接口的超时，文件传输除外（见上面的 FILE_TIMEOUT） */
const API_TIMEOUT = 15000

/**
 * 从请求异常里取一句能给用户看的话
 *
 * 后端的错误文案在 detail 里（都是中文，见 api/polls.py 的模块说明）。
 * **但 detail 不一定是字符串**：422 的那种（字段长度、必填、类型不对）是个数组，
 * 直接塞进 ElMessage 会显示成 "[object Object]" —— 所以数组和不认识的东西
 * 一律退回兜底文案。调用点全是 `ElMessage.error(errText(e, '提交失败'))`。
 */
export function errText(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' && detail ? detail : fallback
}

const request = axios.create({
  baseURL: '/api',
  timeout: API_TIMEOUT,
  // 会话靠 Cookie 传递，跨域场景下也需要携带
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json'
  }
})

/**
 * 是不是「搬文件」的请求
 *
 * 判断放在拦截器里而不是各个调用点各自传 timeout：上传点有十来处（公告、通知、
 * 资料、反馈、请假、通行证、照片、水印溯源…），一处一处写必然漏 —— 事实上就漏过，
 * 只有反馈那一处单独写了 120 秒，别处全在闷声用 15 秒。
 * 以后新增上传接口也不用记得加，FormData 一传就自动放宽。
 */
function isFileTransfer(config) {
  // FormData = 上传；blob = 下载（取回文件再存盘/预览）
  return config.data instanceof FormData || config.responseType === 'blob'
}

request.interceptors.request.use((config) => {
  if (isFileTransfer(config) && config.timeout === API_TIMEOUT) {
    config.timeout = FILE_TIMEOUT
  }
  return config
})

/**
 * 把 axios 的上传进度事件转成 (loaded, total) 回调，省掉每个调用点的重复解构
 *
 * total 为 0 表示拿不到总大小（浏览器算不出来），调用方按「未知」处理，
 * 别显示成 0%。
 */
export function progressHandler(onProgress) {
  if (!onProgress) return undefined
  return (e) => onProgress(e.loaded || 0, e.total || 0)
}

/** 会话已失效：清掉本地登录态，再回登录页
 *
 * store 用动态 import 取，是为了避开「store → api → request → store」的循环依赖；
 * 路由也走 location.hash 而不是 router，同理。带上 .catch 兜底：
 * 拦截器里抛异常会变成未处理的 rejection，反而把真正要报的那个错误盖掉。
 */
function redirectToLogin() {
  import('@/store/user')
    .then(({ useUserStore }) => {
      useUserStore().info = null
    })
    .catch(() => {})

  const path = window.location.hash.slice(1) || '/dashboard'
  // 已经在登录页就不用再改一次 hash —— 那只会把 redirect 参数覆盖掉
  if (!path.startsWith('/login')) {
    window.location.hash = `#/login?redirect=${encodeURIComponent(path)}`
  }
}

// 响应拦截器
request.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    // 401 = 会话没了（过期、被冻结、被吊销），无论当前在不在公开页面都要回登录页 ——
    // 停在公开页面上装作没掉线，顶栏还挂着姓名头像，反而更让人摸不着头脑。
    //
    // 唯一的例外是登录态探测请求（/auth/me，见 api/auth.js 的 skipAuthRedirect）：
    // 它问的本来就是「我登录了吗」，401 是预期答案而不是会话刚失效。未登录的游客
    // 逛首页时也会走到它，若一并发起跳转，等于把游客强行赶去登录页。
    // 它由调用方处理：fetchMe 的 catch 会把 info 置空，顶栏照样如实显示「未登录」。
    if (error.response?.status === 401 && !error.config?.skipAuthRedirect) {
      redirectToLogin()
    }
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

export default request
