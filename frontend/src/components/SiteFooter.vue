<!--
  全站版权脚栏。主布局和签到页共用同一份，别各写一套。
  COPYRIGHT_HTML 是 HTML（SITE_FOOTER 可以放链接），所以用 v-html；
  包一层 span 是因为 v-html 直接写在组件上会作用到根元素，容易踩坑。
-->
<template>
  <footer class="site-footer">
    <span v-html="COPYRIGHT_HTML"></span>
  </footer>
</template>

<script setup>
import { COPYRIGHT_HTML } from '@/utils/site'
</script>

<style scoped>
.site-footer {
  height: auto;
  padding: 10px 12px;
  text-align: center;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
  background: transparent;
  border-top: 1px solid var(--app-outline);
  flex-shrink: 0;
}
</style>
