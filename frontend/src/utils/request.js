import axios from 'axios'

const request = axios.create({
  baseURL: '/api',
  timeout: 15000,
  // 会话靠 Cookie 传递，跨域场景下也需要携带
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json'
  }
})

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
