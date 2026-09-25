import axios from 'axios'

// 无需登录即可访问的页面（会话过期时不必跳登录页）
const PUBLIC_PAGES = ['/login', '/dashboard', '/notices']

const request = axios.create({
  baseURL: '/api',
  timeout: 15000,
  // 会话靠 Cookie 传递，跨域场景下也需要携带
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 响应拦截器
request.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    if (error.response?.status === 401) {
      // 会话已过期：回登录页。
      // 这里用 location.hash 而非 router，避免与 store/router 形成循环依赖
      const path = window.location.hash.slice(1) || '/dashboard'
      const isPublic = PUBLIC_PAGES.some((p) => path.startsWith(p))
      if (!isPublic) {
        window.location.hash = `#/login?redirect=${encodeURIComponent(path)}`
      }
    }
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

export default request
