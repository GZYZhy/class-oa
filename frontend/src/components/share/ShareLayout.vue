<!--
  外链分享页的统一外壳

  投票、签到、通知公告（以后还有更多）都套这一层：同一个深色渐变背景、
  同一张白色卡片、同一个页头（校徽 + 站点名 + 类型）和同一个页脚。
  页面内容只负责卡片里的正文，不再各自写一套布局。
-->
<template>
  <div class="share-page">
    <!-- 校徽纹样：和登录页、站内页面共用同一个全局类，固定在视口右下角。
         纯装饰，不接鼠标事件，也不进无障碍树 -->
    <img
      :src="SITE.logoUrl"
      class="app-emblem"
      alt=""
      aria-hidden="true"
      @error="$event.target.style.display = 'none'"
    />

    <div class="share-card">
      <div class="share-head">
        <img :src="SITE.logoUrl" class="share-logo" alt="校徽" />
        <h1 class="share-site">{{ SITE.name }}｜{{ kindLabel }}</h1>
        <!-- 站内进来时给一个回去的入口；外链游客看到的是登录提示。
             用普通 hash 链接而不是 router-link：和站内其它裸链接一致，
             也不给 SSR 测试额外塞一个路由组件。 -->
        <a v-if="backTo" :href="'#' + backTo" class="share-back">返回</a>
      </div>
      <slot />
    </div>
    <SiteFooter class="share-site-footer" />
  </div>
</template>

<script setup>
import SiteFooter from '@/components/SiteFooter.vue'
import { SITE } from '@/utils/site'

defineProps({
  /** 页面类型的中文名：投票 / 签到 / 公告 */
  kindLabel: { type: String, default: '分享' },
  /** 站内返回地址；外链游客留空 */
  backTo: { type: String, default: '' }
})
</script>

<style scoped>
.share-page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding: 32px 12px;
  box-sizing: border-box;
  /* 背景交给 #app 的全局蓝紫渐变 */
  background: transparent;
}

/* 纹样固定在视口，内容层抬到它上面，避免极淡的校徽盖住文字 */
.share-page > *:not(.app-emblem) {
  position: relative;
  z-index: 1;
}

/* 脚栏铺满整个页面底部，抵消页面左右/底部的内边距 */
.share-site-footer {
  width: calc(100% + 24px);
  margin: auto -12px -32px;
}

.share-card {
  width: 640px;
  max-width: 100%;
  padding: 28px 28px 24px;
  /* 内容再长也和底栏留出空隙：长表单最后一个按钮不会贴着页脚 */
  margin-bottom: 32px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 22px;
  box-shadow: var(--app-shadow-hover);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}

.share-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}

.share-logo {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  object-fit: cover;
  /* 同登录页：白底衬一圈，深色模式下校徽不会糊在卡片上 */
  background: #fff;
  padding: 3px;
  box-sizing: border-box;
  box-shadow: 0 6px 16px rgba(79, 70, 229, 0.16);
}

.share-site {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.share-back {
  margin-left: auto;
  font-size: 14px;
  color: var(--el-color-primary);
  text-decoration: none;
}
</style>
