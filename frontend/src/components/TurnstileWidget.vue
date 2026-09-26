<template>
  <!-- 容器不要带 cf-turnstile 类：我们用显式渲染（render=explicit），
       隐式渲染在 SPA 里会跟组件挂载抢时序 -->
  <div ref="box" class="turnstile-box"></div>
</template>

<script setup>
/**
 * Cloudflare Turnstile 人机验证控件
 *
 * 只做三件事：按需把 Cloudflare 的脚本拉进来、渲染控件、把 token 交给父组件。
 * 加载不出来（内地网络下真会发生）就 emit('unavailable')，由父组件退回算术验证码 ——
 * 这里不自己决定降级，也不自己画备用界面。
 *
 * 打开本站**不会有任何**对 challenges.cloudflare.com 的请求：
 * 脚本要等这个组件第一次挂载（也就是登录输错一次之后）才开始加载。
 */
import { ref, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  siteKey: { type: String, required: true }
})
const emit = defineEmits(['success', 'unavailable'])

const SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
// 内地网络下请求更可能是「挂住」而不是干脆报错。没有这条超时，
// 用户面对的就是一个永远空白的框，也不知道该重试还是该干别的
const LOAD_TIMEOUT = 8000

// 模块级的 Promise 就是「脚本只加载一次」这件事本身：组件反复挂载
// （输错密码 → 换账号 → 再输错）不会重复插 <script>
let scriptPromise = null

function loadScript() {
  if (window.turnstile) return Promise.resolve()
  if (scriptPromise) return scriptPromise

  scriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = SCRIPT_URL
    script.async = true

    const timer = setTimeout(() => reject(new Error('加载超时')), LOAD_TIMEOUT)

    script.onload = () => {
      clearTimeout(timer)
      // 脚本 onload 了但全局对象没出来，说明被拦截或改写了，同样不能当成功
      window.turnstile ? resolve() : reject(new Error('脚本已加载但没有 turnstile 对象'))
    }
    script.onerror = () => {
      clearTimeout(timer)
      reject(new Error('脚本加载失败'))
    }

    document.head.appendChild(script)
  })

  // 失败后清掉缓存的 Promise，否则这个会话里再也没有重试的机会。
  // 成功的那个一直留着复用。这里挂一个 catch 也顺手避免 unhandled rejection
  scriptPromise.catch(() => {
    scriptPromise = null
  })
  return scriptPromise
}

const box = ref(null)
let widgetId = null

onMounted(async () => {
  try {
    await loadScript()
  } catch (e) {
    console.warn('Turnstile 脚本加载失败，退回算术验证码：', e.message)
    emit('unavailable')
    return
  }

  try {
    widgetId = window.turnstile.render(box.value, {
      sitekey: props.siteKey,
      // 登录卡片内容区只有 312px，默认的 300px 控件几乎顶满，flexible 自适应更稳
      size: 'flexible',
      language: 'zh-cn',
      // 默认的 auto 会自己反复重试，我们要的是「不行就立刻退回算术题」，
      // 否则用户会盯着一个一直在转的控件，而算术题那条路明明能用
      retry: 'never',
      callback: (token) => emit('success', token),
      'error-callback': () => emit('unavailable'),
      // token 5 分钟就过期。先清掉手里的旧值，免得拿一个过期 token 去登录；
      // 刷新出新 token 时上面的 callback 会再调一次
      'expired-callback': () => emit('success', '')
    })
  } catch (e) {
    console.warn('Turnstile 控件渲染失败，退回算术验证码：', e.message)
    emit('unavailable')
  }
})

onBeforeUnmount(() => {
  if (widgetId && window.turnstile) {
    window.turnstile.remove(widgetId)
    widgetId = null
  }
})

/** 登录失败后换一个新 token —— token 是一次性的，验过一次就作废了 */
function reset() {
  if (widgetId && window.turnstile) window.turnstile.reset(widgetId)
}

defineExpose({ reset })
</script>

<style scoped>
/* 占住高度，脚本还在路上时表单不会先塌下去再弹开 */
.turnstile-box {
  width: 100%;
  min-height: 65px;
}
</style>
