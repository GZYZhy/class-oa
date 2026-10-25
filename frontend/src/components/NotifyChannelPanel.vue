<template>
  <el-collapse v-model="active" class="channel-panel">
    <el-collapse-item :name="name">
      <template #title>
        <span class="collapse-title">{{ title }}</span>
        <!-- 折叠着也要能看出这条渠道现在发不发，否则用户得逐个展开确认 -->
        <span v-if="badge" class="collapse-badge" :class="{ off: badgeOff }">{{ badge }}</span>
      </template>

      <div v-if="sub" class="panel-sub">{{ sub }}</div>
      <slot />
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
/**
 * 通知渠道的折叠外壳
 *
 * 通知设置页现在是一条条折叠项：默认全部收起，点开哪条看哪条 ——
 * 一屏能扫完五个渠道，且各自带着「开 / 关」状态。
 *
 * ⚠ 只给 MyInfo 里那种**内联**渠道用（浏览器通知、Bark）。
 * 邮件 / Webhook / 天气 各自带着读写逻辑，折叠外壳写在组件内部；
 * 但都用 main.css 里那套 .collapse-title / .collapse-badge 样式，
 * 所以看起来是同一批控件。
 */
import { ref } from 'vue'

defineProps({
  name: { type: String, required: true },
  title: { type: String, required: true },
  sub: { type: String, default: '' },
  badge: { type: String, default: '' },
  badgeOff: { type: Boolean, default: false }
})

// 空数组 = 全部收起。默认展开的话，一进「通知设置」就是好几屏表单
const active = ref([])
</script>

<style scoped>
.panel-sub {
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
