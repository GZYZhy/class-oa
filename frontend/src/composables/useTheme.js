import { computed, ref, watch } from 'vue'

/**
 * 主题三态：auto（跟随系统）/ light / dark。
 *
 * 为什么要有 auto：设备在晚上自动切深色是很多人的默认设置，
 * 强制浅色反而刺眼；但有人就想要固定浅色。所以给三档，默认 auto（和以前行为一致）。
 *
 * 选择记在 cookie 里（一年），不是 localStorage —— 与站内其它偏好保持同一套存储方式，
 * 也方便在服务端渲染 / nginx 注入时读到（构建期就能按偏好出骨架色）。
 *
 * 深浅的实际落地只有一个动作：给 <html> 挂 .dark 类（Element 的深色变量挂在这个类上），
 * 项目自己的样式统一用 var(--el-*)，跟着一起翻。
 */

export const THEME_MODES = ['auto', 'light', 'dark']

const COOKIE_KEY = 'theme'
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365

function readCookie() {
  // 测试里 SSR 渲染没有 document，这里不能直接摸
  if (typeof document === 'undefined') return ''
  const hit = document.cookie.split('; ').find((part) => part.startsWith(`${COOKIE_KEY}=`))
  return hit ? decodeURIComponent(hit.slice(COOKIE_KEY.length + 1)) : ''
}

function writeCookie(value) {
  if (typeof document === 'undefined') return
  document.cookie = `${COOKIE_KEY}=${encodeURIComponent(value)}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`
}

const stored = readCookie()
// 全局单例：顶栏按钮和任何页面读到的都是同一个 mode
const mode = ref(THEME_MODES.includes(stored) ? stored : 'auto')

const media =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null

const systemDark = ref(Boolean(media && media.matches))

const isDark = computed(() => mode.value === 'dark' || (mode.value === 'auto' && systemDark.value))

function paint() {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', isDark.value)
}

let started = false

/**
 * 启动时调一次（main.js 在挂载前调，避免先闪一下浅色）。
 * 幂等：页面自己调 useTheme() 时也会走这里，不会重复注册监听。
 */
export function initTheme() {
  if (started) return
  started = true
  // 用户在系统设置里改深浅时实时跟随（只有 auto 会真正变色，另外两档靠 isDark 判断）
  media?.addEventListener('change', (e) => {
    systemDark.value = e.matches
  })
  watch(isDark, paint, { immediate: true })
}

export function useTheme() {
  initTheme()

  /** 循环切换：自动 → 浅色 → 深色 → 自动 */
  function next() {
    const index = THEME_MODES.indexOf(mode.value)
    mode.value = THEME_MODES[(index + 1) % THEME_MODES.length]
    writeCookie(mode.value)
  }

  const label = computed(
    () => ({ auto: '跟随系统', light: '浅色', dark: '深色' })[mode.value] || '跟随系统'
  )

  // 图标跟着当前档走：自动用显示器、浅色用太阳、深色用月亮
  const icon = computed(
    () => ({ auto: 'Monitor', light: 'Sunny', dark: 'Moon' })[mode.value] || 'Monitor'
  )

  return { mode, isDark, label, icon, next }
}
