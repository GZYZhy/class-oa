import { ref, onMounted, onUnmounted } from 'vue'

/** 与样式表里的断点保持一致（main.css、App.vue 都用的 768px） */
const QUERY = '(max-width: 768px)'

/**
 * 当前是否窄屏。
 *
 * 默认 768px，与样式表里的手机断点一致。**可以传一个更大的宽度**给
 * 「一栏就挤」的场景用：iPad 竖屏常见 810 / 820 / 834，都在 768 之上，
 * 表格操作列若仍按桌面宽度摆三四个按钮，整张表会被挤进横向滚动。
 *
 * 给那些「必须靠 JS 才能改」的组件属性用 —— 比如 el-descriptions 的 column，
 * CSS 改不动它，只能在窄屏上从 3 列变 1 列，否则标签会被挤成竖排。
 * 纯样式问题请写在 CSS 媒体查询里，不要用这个。
 */
export function useIsMobile(maxWidth = 768) {
  const mql = window.matchMedia(`(max-width: ${maxWidth}px)`)
  const isMobile = ref(mql.matches)

  const onChange = (e) => {
    isMobile.value = e.matches
  }

  onMounted(() => mql.addEventListener('change', onChange))
  onUnmounted(() => mql.removeEventListener('change', onChange))

  return isMobile
}
