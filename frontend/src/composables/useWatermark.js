import { ref, onMounted, onUnmounted } from 'vue'
import { useUserStore } from '@/store/user'
import { formatStamp } from '@/utils/format'
import { SITE } from '@/utils/site'

/**
 * 水印字样：「当前登录人姓名@统26-1班 9月24日 14:30」
 *
 * 在需要盖水印的页面 setup 里调用一次，把返回值绑给 <Watermark :text="..." /> 即可，
 * 离开页面时计时器会自动清掉。
 *
 * 每分钟刷一次：页面开久了不刷新，截图上的时间会和实际操作时间对不上。
 */
export function useWatermark() {
  const userStore = useUserStore()
  const text = ref('')

  function refresh() {
    text.value = `${userStore.info?.name || '未知用户'}@${SITE.shortName} ${formatStamp()}`
  }

  let timer = null
  onMounted(() => {
    refresh()
    timer = setInterval(refresh, 60000)
  })
  onUnmounted(() => clearInterval(timer))

  return text
}
