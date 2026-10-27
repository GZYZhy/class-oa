<!--
  外链分享的统一入口：/share/{kind}/{token}

  新增一种外链类型时，只需要：
    1. 后端 api/share_meta.py 的注册表里加一个 resolver；
    2. 这里 COMPONENTS 里加一行懒加载。
  路由、nginx、index.html 都不用改。
-->
<template>
  <component :is="page" v-if="page" />
  <ShareLayout v-else kind-label="分享">
    <ShareState type="invalid" />
  </ShareLayout>
</template>

<script setup>
import { computed, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import ShareLayout from '@/components/share/ShareLayout.vue'
import ShareState from '@/components/share/ShareState.vue'

const COMPONENTS = {
  vote: defineAsyncComponent(() => import('./ShareVote.vue')),
  checkin: defineAsyncComponent(() => import('./ShareCheckin.vue')),
  notice: defineAsyncComponent(() => import('./ShareNotice.vue')),
  collect: defineAsyncComponent(() => import('./ShareCollect.vue')),
  // 资料下载外链：拿到链接的人不用登录就能下
  resource: defineAsyncComponent(() => import('./ShareResource.vue'))
}

const route = useRoute()
// 只认白名单里的 kind，未知类型走统一失效页，不会去加载任意组件
const page = computed(() => COMPONENTS[String(route.params.kind || '')] || null)
</script>
