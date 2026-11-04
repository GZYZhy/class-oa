import { onBeforeUnmount, reactive } from 'vue'
import { useRouter } from 'vue-router'

/**
 * 顶部路由进度条
 *
 * 为什么需要它：路由是懒加载的，弱网下一个 chunk 可能要等好几秒。这段时间里
 * 页面毫无反应，用户只会以为「点了没反应」，然后连点几次。一条 2px 的进度条
 * 不占布局、不解释任何业务，但能立刻回答「它在动了」。
 *
 * 状态机三档：
 *   active  —— 导航开始，条子淡入并缓慢爬向 90%（**故意不到 100%**：
 *              没拿到结果之前不能假装完成）
 *   done    —— 导航结束，补到 100% 再淡出
 *   都不是   —— 平时占位但不拦事件，pointer-events: none
 *
 * 使用：在 App.vue 的 setup 里调一次，模板上绑 active / done 两个类。
 */
export function useRouteProgress() {
  const router = useRouter()
  const state = reactive({ active: false, done: false })
  let fadeTimer = null

  function finish() {
    if (!state.active) return
    state.active = false
    state.done = true
    clearTimeout(fadeTimer)
    // 400ms 后把 done 也摘掉，条子回到「零宽不可见」的静止态，下次才能重播
    fadeTimer = setTimeout(() => {
      state.done = false
    }, 400)
  }

  const offBefore = router.beforeEach((to, from) => {
    // 同一页只换 hash / query 时不显示：那种导航不加载任何东西，闪一下反而像出错
    if (to.path === from.path && to.hash === from.hash) return
    clearTimeout(fadeTimer)
    state.done = false
    state.active = true
  })
  const offAfter = router.afterEach(() => finish())
  const offError = router.onError(() => finish())

  onBeforeUnmount(() => {
    offBefore()
    offAfter()
    offError()
    clearTimeout(fadeTimer)
  })

  return state
}
