<!--
  外链分享页的统一状态提示

  失效、无权限、未登录、网络错误、不在范围，全部走这一个组件，
  文案和样式在各类型之间保持一致；调用方只需要传 type（必要时覆盖 title/description）。
-->
<template>
  <div v-if="type === 'loading'" class="share-loading">{{ title || '正在加载…' }}</div>

  <el-result v-else :icon="preset[0]" :title="title || preset[1]" :sub-title="description || preset[2]">
    <template #extra>
      <el-button v-if="retry" type="primary" @click="$emit('retry')">重新加载</el-button>
      <a v-if="showHome" href="#/" class="share-plain-link">回首页</a>
    </template>
  </el-result>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** loading / invalid / forbidden / login / network / not-target */
  type: { type: String, default: 'invalid' },
  /** 不传时按 type 取统一文案 */
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  /** 网络类错误给一个「重新加载」 */
  retry: { type: Boolean, default: false },
  /** 是否显示「回首页」，失效页默认显示 */
  home: { type: Boolean, default: true }
})
defineEmits(['retry'])

const DEFAULTS = {
  loading: ['info', '正在加载…', ''],
  invalid: ['warning', '链接已失效', '分享链接无效或已失效，请向发布人重新要一次'],
  forbidden: ['warning', '没有权限', '你没有权限查看这个页面'],
  login: ['info', '登录后即可继续', '请先登录，登录后会回到当前页面'],
  network: ['warning', '打不开这个页面', '网络不稳定，请稍后重试'],
  'not-target': ['info', '不在范围内', '你不在本次范围内，不需要操作']
}

const preset = computed(() => DEFAULTS[props.type] || DEFAULTS.invalid)
const showHome = computed(() => props.home && !['login', 'not-target'].includes(props.type))
</script>

<style scoped>
.share-loading {
  padding: 40px 0;
  text-align: center;
  color: var(--el-text-color-secondary);
}

.share-plain-link {
  margin-left: 12px;
  color: var(--el-color-primary);
  text-decoration: none;
}
</style>
