<template>
  <div v-if="error" class="list-feedback" role="alert">
    <el-icon><Warning /></el-icon>
    <div class="list-feedback-copy">
      <strong>{{ error }}</strong>
      <span>检查网络后重试，当前查询条件会保留。</span>
    </div>
    <el-button :loading="loading" @click="$emit('retry')">重新加载</el-button>
  </div>
</template>

<script setup>
defineProps({ error: { type: String, default: '' }, loading: Boolean })
defineEmits(['retry'])
</script>

<style scoped>
.list-feedback {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 16px 0;
  padding: 14px 16px;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: 12px;
  background: var(--el-color-warning-light-9);
  color: var(--el-text-color-primary);
}
.list-feedback > .el-icon {
  color: var(--el-color-warning);
  font-size: 20px;
  flex-shrink: 0;
}
.list-feedback-copy {
  display: grid;
  flex: 1;
  gap: 4px;
}
.list-feedback-copy strong {
  font-size: 14px;
  font-weight: 600;
}
.list-feedback-copy span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
@media (max-width: 480px) {
  .list-feedback {
    flex-wrap: wrap;
  }
  .list-feedback-copy {
    min-width: 180px;
  }
  .list-feedback > .el-button {
    margin-left: 32px;
  }
}
</style>
