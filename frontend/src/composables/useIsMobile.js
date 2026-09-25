import { ref, onMounted, onUnmounted } from 'vue'

/** 与样式表里的断点保持一致（main.css、App.vue 都用的 768px） */
const QUERY = '(max-width: 768px)'

/**
 * 当前是否窄屏（手机）。
 *
 * 给那些「必须靠 JS 才能改」的组件属性用 —— 比如 el-descriptions 的 column，
 * CSS 改不动它，只能在手机上从 3 列变 1 列，否则标签会被挤成竖排。
 * 纯样式问题请写在 CSS 媒体查询里，不要用这个。
 */
export function useIsMobile() {
  const mql = window.matchMedia(QUERY)
  const isMobile = ref(mql.matches)

  const onChange = (e) => {
    isMobile.value = e.matches
  }

  onMounted(() => mql.addEventListener('change', onChange))
  onUnmounted(() => mql.removeEventListener('change', onChange))

  return isMobile
}
