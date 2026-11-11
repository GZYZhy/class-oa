import { isRef, nextTick, onMounted, onScopeDispose, toRaw, unref, watch } from 'vue'
import { useUserStore } from '@/store/user'

// 只保存当前标签页内的查询条件，不保存名单、正文或附件。
const pages = new Map()

export function clearPageStates() {
  pages.clear()
}

export function usePageState(key, fields, loading) {
  const user = useUserStore()
  const owner = () => `${user.info?.student_no || ''}:${user.info?.role || ''}`
  const initialOwner = owner()
  const saved = pages.get(key)
  let restored = false

  async function restoreScroll() {
    await nextTick()
    if (restored || loading?.value || typeof document === 'undefined') return
    const main = document.querySelector('.layout-main')
    if (main) main.scrollTop = saved?.owner === initialOwner ? saved.scrollTop : 0
    restored = true
  }

  onMounted(restoreScroll)
  if (loading) watch(loading, restoreScroll, { flush: 'post' })

  if (saved?.owner === initialOwner) {
    for (const [name, field] of Object.entries(fields)) {
      if (!(name in saved.values)) continue
      const value = structuredClone(saved.values[name])
      if (isRef(field)) field.value = value
      else Object.assign(field, value)
    }
  }

  onScopeDispose(() => {
    if (owner() !== initialOwner) return
    const values = Object.fromEntries(Object.entries(fields).map(([name, field]) => [
      name, structuredClone(toRaw(unref(field)))
    ]))
    const scrollTop = typeof document === 'undefined' ? 0 : document.querySelector('.layout-main')?.scrollTop || 0
    pages.set(key, { owner: initialOwner, values, scrollTop })
  })
}
