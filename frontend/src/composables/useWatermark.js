import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useUserStore } from '@/store/user'
import { formatStamp } from '@/utils/format'
import { SITE } from '@/utils/site'

/**
 * 水印字样：「当前登录人姓名@示例班 9月24日 14:30」
 *
 * 在需要盖水印的页面 setup 里调用一次，把返回值绑给 <Watermark :text="..." /> 即可，
 * 离开页面时计时器会自动清掉。
 *
 * 每分钟刷一次：页面开久了不刷新，截图上的时间会和实际操作时间对不上。
 */
export function useWatermark() {
  const userStore = useUserStore()
  // 时间每分钟变一次；姓名用 computed，等登录态异步加载完自动跟上。
  // 以前在 onMounted 里一次性拼好字符串，分享页打开时 fetchMe 还没回来，
  // 整页水印会一直写着「未知用户」，直到下一分钟才刷新。
  const stamp = ref(formatStamp())
  const text = computed(
    () => `${userStore.info?.name || '未知用户'}@${SITE.shortName} ${stamp.value}`
  )

  let timer = null
  onMounted(() => {
    stamp.value = formatStamp()
    timer = setInterval(() => {
      stamp.value = formatStamp()
    }, 60000)
  })
  onUnmounted(() => clearInterval(timer))

  return text
}
