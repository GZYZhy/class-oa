<template>
  <!-- 照片批量导入：上传 zip → 逐张确认去向 → 结果 -->
  <el-dialog
    v-model="visible"
    title="批量导入照片"
    width="760px"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <!-- 第一步：选类型 + 传 zip -->
    <div v-if="step === 1" class="pi-step">
      <el-form label-width="76px">
        <el-form-item label="照片类型">
          <el-radio-group v-model="photoType">
            <el-radio-button value="gaokao">高考照片</el-radio-button>
            <el-radio-button value="on_site">实地采集</el-radio-button>
            <el-radio-button value="id">自备证件照</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <el-upload
        ref="uploadRef"
        drag
        :auto-upload="false"
        :limit="1"
        accept=".zip"
        :on-exceed="handleExceed"
        :on-change="handleFileChange"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">把 zip 压缩包拖到这里，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">
            每张照片一个文件，文件名里带学号或姓名（如 <code>20260101.jpg</code>、
            <code>张三.jpg</code>）；认不出的下一步可以手工指认。
            支持 jpg / png / gif / bmp / webp，单张不超过 10MB。iPhone 的 HEIC 请先转成 JPG。
          </div>
        </template>
      </el-upload>
    </div>

    <!-- 第二步：逐张确认 -->
    <div v-else-if="step === 2" class="pi-step">
      <el-alert type="info" :closable="false" show-icon class="pi-summary">
        <template #title>
          zip 里共 {{ preview.total }} 个文件：可导入 {{ counts.ok }} 张，
          认不出 {{ counts.unmatched }} 张，其余 {{ preview.total - counts.ok - counts.unmatched }} 张不能用
        </template>
      </el-alert>

      <div class="pi-overwrite">
        <el-checkbox v-model="overwrite">已有照片也覆盖</el-checkbox>
        <span v-if="preview.will_overwrite" class="pi-hint">
          有 {{ preview.will_overwrite }} 张对应的学生已经有照片了
        </span>
        <span v-else class="pi-hint">没有学生会因此丢掉旧照片</span>
      </div>

      <el-table :data="preview.items" size="small" border max-height="360">
        <el-table-column prop="filename" label="文件名" min-width="180" show-overflow-tooltip />
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ formatSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="判定" width="110">
          <template #default="{ row }">
            <el-tag :type="tagType(row.status)" size="small" effect="plain">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="算作谁的照片" min-width="200">
          <template #default="{ row }">
            <!-- 认不出的才给下拉；认出来的只显示结果，要改就得改文件名重传 -->
            <el-select
              v-if="row.status === 'unmatched'"
              v-model="manual[row.raw_name]"
              placeholder="指认给某位同学"
              size="small"
              filterable
              clearable
              style="width: 100%"
            >
              <el-option
                v-for="s in roster"
                :key="s.student_no"
                :label="`${s.name}（${s.student_no}）`"
                :value="s.student_no"
              />
            </el-select>
            <span v-else-if="row.student_no" class="pi-owner">
              {{ row.student_name }}（{{ row.student_no }}）
              <el-tag v-if="row.has_photo" size="small" type="warning" effect="plain">已有照片</el-tag>
            </span>
            <span v-else class="pi-reason">{{ row.reason }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 第三步：结果 -->
    <div v-else class="pi-step">
      <el-result icon="success" title="导入完成" :sub-title="result.message">
        <template #extra>
          <div class="pi-stats">
            <div><b>{{ result.saved }}</b><span>写入</span></div>
            <div><b>{{ result.overwritten }}</b><span>覆盖</span></div>
            <div><b>{{ result.skipped_exists }}</b><span>因已有照片跳过</span></div>
          </div>
        </template>
      </el-result>

      <el-alert v-if="result.failed?.length" type="error" :closable="false" show-icon title="这些没能导入">
        <ul class="pi-list">
          <li v-for="(msg, i) in result.failed" :key="i">{{ msg }}</li>
        </ul>
      </el-alert>

      <!-- 第三步把没导进去的再列一遍：用户改完文件名重传时不用凭记忆 -->
      <el-alert v-if="leftovers.length" type="warning" :closable="false" show-icon title="还有这些没处理">
        <ul class="pi-list">
          <li v-for="item in leftovers" :key="item.raw_name">
            {{ item.filename }} —— {{ item.reason || statusLabel(item.status) }}
          </li>
        </ul>
      </el-alert>
    </div>

    <template #footer>
      <template v-if="step === 1">
        <el-button @click="visible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!file || previewLoading"
          :loading="previewLoading"
          @click="doPreview"
        >
          下一步：预览
        </el-button>
      </template>
      <template v-else-if="step === 2">
        <el-button @click="step = 1">上一步</el-button>
        <el-button type="primary" :loading="confirmLoading" @click="doImport">确认导入</el-button>
      </template>
      <template v-else>
        <el-button type="primary" @click="visible = false">完成</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { getStudentList, photoImportPreview, photoImportConfirm } from '@/api/student'

const emit = defineEmits(['done'])

const visible = ref(false)
const step = ref(1) // 1=上传 2=预览 3=结果
const photoType = ref('gaokao')
const file = ref(null)
const uploadRef = ref(null)
const previewLoading = ref(false)
const confirmLoading = ref(false)
const preview = ref(null)
const result = ref(null)
const overwrite = ref(false)
// 人工指认：zip 成员名 → 学号。只填认不出的那些
const manual = reactive({})
const roster = ref([])

const counts = computed(() => ({
  ok: preview.value?.counts?.ok || 0,
  unmatched: preview.value?.counts?.unmatched || 0
}))

// 没导进去的：改文件名重传时要照着这张单子改
const leftovers = computed(() =>
  (preview.value?.items || []).filter((i) =>
    ['unmatched', 'conflict', 'unsupported', 'too_large'].includes(i.status)
  )
)

function open() {
  reset()
  visible.value = true
  fetchRoster()
}

function reset() {
  step.value = 1
  photoType.value = 'gaokao'
  file.value = null
  preview.value = null
  result.value = null
  overwrite.value = false
  previewLoading.value = false
  confirmLoading.value = false
  for (const key of Object.keys(manual)) delete manual[key]
  if (uploadRef.value) uploadRef.value.clearFiles()
}

/** 一次性拉全量名单：指认下拉要用，后端 page_size 上限 500，够全班 */
async function fetchRoster() {
  try {
    const res = await getStudentList({ page: 1, page_size: 500, sort_by: 'student_no', sort_order: 'asc' })
    roster.value = res.items || []
  } catch (e) {
    // 拦截器已经弹过错了；指认下拉会空着，但预览本身还能用
  }
}

function handleFileChange(f) {
  file.value = f.raw || f
}

function handleExceed() {
  ElMessage.warning('只能上传一个压缩包')
}

async function doPreview() {
  if (!file.value) {
    ElMessage.warning('请先选择 zip 压缩包')
    return
  }
  previewLoading.value = true
  try {
    preview.value = await photoImportPreview(file.value, photoType.value)
    step.value = 2
  } catch (e) {
    // 拦截器会弹错误消息
  } finally {
    previewLoading.value = false
  }
}

async function doImport() {
  if (!preview.value?.token) {
    ElMessage.error('预览已过期，请重新上传')
    step.value = 1
    return
  }
  confirmLoading.value = true
  try {
    result.value = await photoImportConfirm({
      token: preview.value.token,
      photo_type: photoType.value,
      overwrite: overwrite.value,
      manual: { ...manual }
    })
    step.value = 3
    emit('done')
  } catch (e) {
    // 拦截器会弹错
  } finally {
    confirmLoading.value = false
  }
}

const STATUS_LABELS = {
  ok: '可导入',
  unmatched: '认不出',
  conflict: '重复',
  unsupported: '格式不支持',
  too_large: '太大',
  ignored: '已忽略'
}
const STATUS_TAGS = {
  ok: 'success',
  unmatched: 'warning',
  conflict: 'warning',
  unsupported: 'danger',
  too_large: 'danger',
  ignored: 'info'
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

function tagType(status) {
  return STATUS_TAGS[status] || 'info'
}

function formatSize(bytes) {
  if (!bytes) return '0 KB'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

defineExpose({ open })
</script>

<style scoped>
.pi-step {
  min-height: 200px;
}

.pi-summary {
  margin-bottom: 12px;
}

.pi-overwrite {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.pi-hint {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.pi-owner {
  font-size: 13px;
}

.pi-reason {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.pi-stats {
  display: flex;
  justify-content: center;
  gap: 32px;
}

.pi-stats b {
  display: block;
  font-size: 22px;
}

.pi-stats span {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.pi-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}
</style>
