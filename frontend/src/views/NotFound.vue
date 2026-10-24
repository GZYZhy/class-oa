<template>
  <!-- 路由没匹配上（地址输错 / 旧链接失效）。留在正常布局里，
       顶栏和菜单都还在，用户可以顺手点走，不用按浏览器返回 -->
  <div class="page-card">
    <el-empty description="页面不存在">
      <p class="not-found-tip">页面不存在或链接已失效。</p>
      <el-button type="primary" @click="router.push('/dashboard')">返回首页</el-button>
    </el-empty>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style scoped>
.not-found-tip {
  margin: 0 0 16px 0;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
</style>
