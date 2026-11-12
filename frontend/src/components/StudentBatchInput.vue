<template>
  <div class="student-batch-input">
    <el-input
      v-model="text"
      type="textarea"
      :rows="3"
      placeholder="每行一个学号、姓名或「学号 姓名」"
    />
    <div class="sbi-actions">
      <el-button size="small" type="primary" plain @click="apply">解析并勾选</el-button>
      <span class="sbi-tip">会替换当前勾选</span>
    </div>
    <div v-if="unknown.length" class="sbi-unknown">
      未匹配：{{ unknown.join('；') }}
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { parseStudentInput } from '@/utils/studentInput'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  modelValue: { type: Array, default: () => [] },
  valueKey: { type: String, default: 'student_no' }
})
const emit = defineEmits(['update:modelValue'])

const text = ref('')
const unknown = ref([])

function apply() {
  const result = parseStudentInput(text.value, props.rows, props.valueKey)
  unknown.value = result.unknown
  if (!result.values.length) return
  emit('update:modelValue', result.values)
  text.value = result.unknown.join('\n')
}
</script>

<style scoped>
.student-batch-input {
  margin-bottom: 12px;
}

.sbi-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

.sbi-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.sbi-unknown {
  margin-top: 6px;
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
</style>
