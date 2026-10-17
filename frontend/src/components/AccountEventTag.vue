<template>
  <el-tag v-if="meta" :type="meta.type" size="small">{{ meta.label }}</el-tag>
  <!-- 兜底显示原始事件名：后端将来加新事件类型时，这里不会变成一片空白 -->
  <span v-else>{{ event }}</span>
</template>

<script setup>
import { computed } from 'vue'

/** 「登录与账号操作」里的一条事件，映射成中文标签
 *
 * 库里存英文值，中文只在这里维护 —— 我的日志和管理员「按账号查日志」
 * 共用这一份，免得两边加漏了某一类、显示成英文原名。
 */
const props = defineProps({
  event: { type: String, required: true }
})

const EVENT_LABELS = {
  login: { label: '登录', type: 'info' },
  change_password: { label: '修改密码', type: 'warning' },
  token_create: { label: '创建令牌', type: 'success' },
  token_revoke: { label: '吊销令牌', type: 'danger' },
  passkey_add: { label: '添加通行密钥', type: 'success' },
  passkey_delete: { label: '删除通行密钥', type: 'danger' },
  two_factor_enable: { label: '开启二次验证', type: 'success' },
  two_factor_disable: { label: '关闭二次验证', type: 'warning' },
  recovery_regenerate: { label: '重新生成恢复码', type: 'warning' }
}

const meta = computed(() => EVENT_LABELS[props.event])
</script>
