<template>
  <!-- 初始化临时账号：整屏浮层，连布局都不渲染。
       必须用 v-if 把这个外壳整个换掉 —— 拿个弹窗盖在上面的做法行不通：
       底下的路由页面照样挂载、onMounted 照样发请求，然后撞一堵 403 墙 -->
  <SetupWizard v-if="userStore.isBootstrap" />

  <template v-else>
    <!-- 登录页、签到页使用独立全屏布局，不套侧边栏 -->
    <router-view v-if="route.meta.bare" />

    <AppLayout v-else />

    <!-- 强制改密挂在布局外面：签到/登录这种 bare 页也要弹，改完留在原页面 -->
    <ForcePasswordDialog />
  </template>
</template>

<script setup>
import { defineAsyncComponent, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/store/user'
import { useBadgeStore } from '@/store/badge'
import { saveWebpushSubscription } from '@/api/webpush'
import { captureInstallPrompt, currentSubscription, unsubscribe } from '@/utils/webpush'
import ForcePasswordDialog from '@/components/ForcePasswordDialog.vue'

// 布局和初始化浮层都按需加载：签到、登录这类整屏页（meta.bare）用不到整套菜单与弹窗。
// 这样签到页在弱网下只需等这份小外壳，不用先下载用不上的布局代码
const SetupWizard = defineAsyncComponent(() => import('@/components/SetupWizard.vue'))
const AppLayout = defineAsyncComponent(() => import('@/components/AppLayout.vue'))

const route = useRoute()
const userStore = useUserStore()
const badgeStore = useBadgeStore()

// 浏览器订阅是**按浏览器**（endpoint 唯一）存的。班级系统会在机房、共用电脑上
// 登录，换人时必须改绑或解除，否则 B 会收到推给 A 的隐私通知（请假驳回理由之类）。
//
// 挂在这里而不是 login()/logout() 里，是因为刷新页面靠 cookie 恢复登录走的是
// fetchMe()，压根不经过 login()；而两种情况下 isLogin 都会从 false 变 true，
// 一个 watch 就全覆盖了。
watch(
  () => userStore.isLogin,
  async (now) => {
    // 初始化临时账号到此为止：它被闸门限制着，红点和推送接口都会 403。
    // 浮层正在接管整个界面，这里也没有任何东西需要更新
    if (userStore.isBootstrap) return

    // 红点与推送无关，所以放在 try 外面：推送这套失败不该连累红线
    // （只在登录时拉一次，未登录的游客不会去碰这个必然 401 的接口）
    if (now) badgeStore.refresh()
    else badgeStore.clear()

    try {
      if (now) {
        // 本机没有订阅就什么都不用做；有的话把 endpoint 改绑到当前账号。
        // subscribe 接口按 endpoint upsert，一次 POST 就够，不需要新端点
        const sub = await currentSubscription()
        if (sub) await saveWebpushSubscription(sub.toJSON())
      } else {
        // 退出登录：只解除浏览器这一侧的订阅，**不要**去调服务端的删除接口。
        // 会话此时已经失效，那个请求会拿到 401，而 401 会被响应拦截器当成
        // 「会话过期」直接跳登录页 —— 和 logout 之后的 router.push 打架。
        //
        // 只做本地退订就够了：sub.unsubscribe() 会让这个 endpoint 在推送服务
        // 那边立刻失效，送达当即停止；服务端剩下的那行是收不到任何东西的死数据，
        // 下次发送时推送服务返回 404/410 就会自动清掉。
        await unsubscribe()
      }
    } catch (e) {
      /* 静默：通知是附加功能，不能因为它影响登录本身 */
    }
  }
)

onMounted(() => {
  // 公开页（签到、通知公告）路由守卫直接放行，不会问后端登录状态。
  // 这里补一次，强制改密浮层才知道当前用户是不是还带着 must_change_password；
  // 未登录时 /auth/me 返回 401，fetchMe 会吞掉，不会把游客赶去登录页。
  //
  // 登录页除外：那里的 fetchMe 是必 401 的，如果它比用户登录请求晚回来，
  // 会把刚写进 store 的登录态覆盖成 null。登录页本来也不需要这个探测。
  if (!userStore.resolved && route.name !== 'Login') userStore.fetchMe()

  // 接住浏览器的 PWA 安装提示事件（Chrome/Edge/Android 才有，iOS 没有）
  captureInstallPrompt()
})
</script>
