import { onScopeDispose } from 'vue'

/** 切换筛选条件或离开页面后，较早请求的结果失效。 */
export function useLatestRequest() {
  let sequence = 0
  onScopeDispose(() => { sequence += 1 })
  return {
    start: () => ++sequence,
    isCurrent: (id) => id === sequence
  }
}
