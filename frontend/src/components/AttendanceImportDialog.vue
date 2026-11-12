<template>
  <el-dialog
    append-to-body
    v-model="visible"
    title="导入考勤"
    width="860px"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <div v-if="step === 1">
      <el-upload
        ref="uploadRef"
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx"
        :on-change="handleFileChange"
        :on-exceed="handleExceed"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">把 Excel 拖到这里，或 <em>点击选择</em></div>
        <template #tip>
          <div class="ai-tip">
            第一行至少要有「学号」或「姓名」列；「序号」「性别」等信息列会忽略，
            其余列都当作场次，列头就是标题。空白、无、-、/ 表示该场次不在范围内。
          </div>
        </template>
      </el-upload>
    </div>

    <div v-else-if="step === 2 && preview">
      <el-alert type="info" :closable="false" show-icon>
        <template #title>
          工作表「{{ preview.sheet_name }}」：{{ preview.sessions.length }} 个场次，
          {{ preview.rows.length }} 名学生
        </template>
      </el-alert>

      <div class="ai-times">
        <div v-for="session in preview.sessions" :key="session.key" class="ai-time-row">
          <span class="ai-time-title">{{ session.title }}</span>
          <el-date-picker
            v-model="times[session.key]"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="选择发生时间"
            style="width: 230px"
          />
        </div>
      </div>

      <el-table :data="preview.rows" size="small" border max-height="360" class="ai-preview">
        <el-table-column prop="student_no" label="学号" width="125" fixed="left" />
        <el-table-column prop="name" label="姓名" width="90" fixed="left" />
        <el-table-column
          v-for="session in preview.sessions"
          :key="session.key"
          :label="session.title"
          min-width="90"
        >
          <template #default="{ row }">
            {{ STATUS_LABELS[row.values[session.key]] || '—' }}
          </template>
        </el-table-column>
      </el-table>

      <el-alert
        v-for="(warning, index) in preview.warnings"
        :key="index"
        type="warning"
        :closable="false"
        show-icon
        :title="warning"
        class="ai-warning"
      />
    </div>

    <div v-else-if="step === 3 && result" class="ai-result">
      <el-result icon="success" title="导入完成">
        <template #sub-title>
          生成 {{ result.records_created }} 条导入记录、{{ result.items_created }} 条明细
          <template v-if="result.skipped_sessions">
            ；{{ result.skipped_sessions }} 个全空场次已跳过
          </template>
        </template>
      </el-result>
    </div>

    <template #footer>
      <template v-if="step === 1">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :disabled="!file" :loading="previewLoading" @click="doPreview">
          下一步：预览
        </el-button>
      </template>
      <template v-else-if="step === 2">
        <el-button @click="step = 1">上一步</el-button>
        <el-button type="primary" :loading="confirmLoading" @click="doImport">
          确认导入
        </el-button>
      </template>
      <template v-else>
        <el-button type="primary" @click="visible = false">完成</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmAttendanceImport, previewAttendanceImport } from '@/api/attendance'
import { errText } from '@/utils/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'imported'])

const STATUS_LABELS = {
  present: '到',
  late: '迟到',
  absent: '无应答',
  leave: '请假'
}

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})
const uploadRef = ref(null)
const step = ref(1)
const file = ref(null)
const preview = ref(null)
const result = ref(null)
const times = reactive({})
const previewLoading = ref(false)
const confirmLoading = ref(false)

function reset() {
  step.value = 1
  file.value = null
  preview.value = null
  result.value = null
  previewLoading.value = false
  confirmLoading.value = false
  Object.keys(times).forEach((key) => delete times[key])
  uploadRef.value?.clearFiles()
}

function handleFileChange(uploadFile) {
  file.value = uploadFile.raw || null
}

function handleExceed(files) {
  uploadRef.value?.clearFiles()
  uploadRef.value?.handleStart(files[0])
  file.value = files[0]
}

async function doPreview() {
  if (!file.value) return
  previewLoading.value = true
  try {
    preview.value = await previewAttendanceImport(file.value)
    preview.value.sessions.forEach((session) => {
      times[session.key] = ''
    })
    step.value = 2
  } catch (e) {
    ElMessage.error(errText(e, '解析失败'))
  } finally {
    previewLoading.value = false
  }
}

async function doImport() {
  const missing = (preview.value?.sessions || []).filter((session) => !times[session.key])
  if (missing.length) {
    ElMessage.warning(`还没有选择发生时间：${missing.map((s) => s.title).join('、')}`)
    return
  }
  confirmLoading.value = true
  try {
    result.value = await confirmAttendanceImport({
      token: preview.value.token,
      sessions: preview.value.sessions.map((session) => ({
        key: session.key,
        occurred_at: times[session.key]
      }))
    })
    step.value = 3
    emit('imported')
  } catch (e) {
    ElMessage.error(errText(e, '导入失败'))
  } finally {
    confirmLoading.value = false
  }
}
</script>

<style scoped>
.ai-tip {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.7;
}
.ai-times {
  display: grid;
  gap: 8px;
  margin: 16px 0;
}
.ai-time-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.ai-time-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.ai-preview {
  margin-top: 10px;
}
.ai-warning {
  margin-top: 10px;
}
.ai-result {
  padding: 10px 0;
}
@media (max-width: 640px) {
  .ai-time-row {
    align-items: stretch;
    flex-direction: column;
    gap: 4px;
  }
  .ai-time-row :deep(.el-date-editor) {
    width: 100% !important;
  }
}
</style>
