<!--
  外链分享页的统一外壳

  投票、签到、通知公告（以后还有更多）都套这一层：同一个深色渐变背景、
  同一张白色卡片、同一个页头（校徽 + 站点名 + 类型）和同一个页脚。
  页面内容只负责卡片里的正文，不再各自写一套布局。
-->
<template>
  <div class="share-page">
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
  background: linear-gradient(135deg, #1f2d3d 0%, #2c3e50 55%, #3a5169 100%);
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
  background: var(--el-bg-color);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 21, 41, 0.3);
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
