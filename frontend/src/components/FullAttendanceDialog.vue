<template>
  <el-dialog
    append-to-body
    v-model="visible"
    title="全勤名单"
    width="620px"
    destroy-on-close
  >
    <div class="fa-toolbar">
      <el-date-picker
        v-model="range"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
      />
      <el-checkbox v-model="lateCounts">迟到算全勤</el-checkbox>
      <el-checkbox v-model="leaveCounts">请假算全勤</el-checkbox>
      <el-button type="primary" :loading="loading" @click="load">统计</el-button>
    </div>

    <div v-loading="loading" class="fa-body">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="只统计已结算的考勤记录；未结算的签到不计入。"
      />

      <div v-if="error" class="fa-error">
        {{ error }}
        <el-button link type="primary" @click="load">重试</el-button>
      </div>

      <template v-else-if="result">
        <div class="fa-summary">
          <span>统计 {{ result.total_records }} 次考勤</span>
          <span>覆盖 {{ result.checked_students }} 人</span>
          <strong>{{ result.items.length }} 人全勤</strong>
        </div>

        <div v-if="result.items.length" class="fa-list">
          <div v-for="item in result.items" :key="item.student_no" class="fa-person">
            <span>{{ item.name }}</span>
            <span class="fa-no">{{ item.student_no }}</span>
            <span v-if="item.late_count" class="fa-tag">迟到 {{ item.late_count }} 次</span>
            <span v-if="item.leave_count" class="fa-tag">请假 {{ item.leave_count }} 次</span>
          </div>
        </div>
        <el-empty v-else description="这个周期没有全勤人员" :image-size="72" />

        <div v-if="result.items.length" class="fa-copy">
          <el-button type="primary" plain @click="copyList">复制名单</el-button>
          <span class="fa-tip">复制为「姓名（学号）」，每行一人</span>
        </div>
      </template>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getFullAttendance } from '@/api/attendance'
import { copyText } from '@/utils/clipboard'
import { errText } from '@/utils/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})
const range = ref([])
const lateCounts = ref(true)
const leaveCounts = ref(false)
const loading = ref(false)
const error = ref('')
const result = ref(null)

function iso(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function defaultMonth() {
  const now = new Date()
  range.value = [
    iso(new Date(now.getFullYear(), now.getMonth(), 1)),
    iso(new Date(now.getFullYear(), now.getMonth() + 1, 0))
  ]
}

async function load() {
  if (!range.value?.[0] || !range.value?.[1]) {
    ElMessage.warning('请选择统计周期')
    return
  }
  loading.value = true
  error.value = ''
  try {
    result.value = await getFullAttendance({
      start: range.value[0],
      end: range.value[1],
      late_counts: lateCounts.value,
      leave_counts: leaveCounts.value
    })
  } catch (e) {
    error.value = errText(e, '读取全勤名单失败')
  } finally {
    loading.value = false
  }
}

function copyList() {
  if (!result.value?.items.length) return
  copyText(result.value.items.map((item) => `${item.name}（${item.student_no}）`).join('\n'))
}

watch(() => props.modelValue, (open) => {
  if (!open) return
  if (!range.value?.length) defaultMonth()
  load()
})
</script>

<style scoped>
.fa-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}
.fa-body {
  min-height: 180px;
}
.fa-error {
  padding: 24px 0;
  color: var(--el-color-danger);
  text-align: center;
}
.fa-summary {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 16px;
  margin: 16px 0 10px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.fa-summary strong {
  color: var(--el-text-color-primary);
  font-size: 15px;
}
.fa-list {
  max-height: 300px;
  overflow-y: auto;
  border-top: 1px solid var(--el-border-color-lighter);
}
.fa-person {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 2px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}
.fa-no {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.fa-tag {
  margin-left: auto;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.fa-tag + .fa-tag {
  margin-left: 0;
}
.fa-copy {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}
.fa-tip {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
@media (max-width: 640px) {
  .fa-toolbar :deep(.el-date-editor) {
    width: 100%;
  }
  .fa-tip {
    line-height: 1.5;
  }
}
</style>
