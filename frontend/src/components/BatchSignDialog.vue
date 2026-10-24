<!--
  批量签字：管理员在「学生信息 → 更多」里打开。

  两种范围：
    - 补充缺失：把所有还没有签字图的学生排成一队
    - 勾选覆盖：只处理表格里勾中的人，已有签字图的会被新签名覆盖

  每签完一位立刻上传（复用学生签字图那个接口），所以中途关掉不会丢已经签好的；
  某个人上传失败时停在这一位，可以重试，也可以跳过。
-->
<template>
  <el-dialog append-to-body
    v-model="visible"
    title="批量签字"
    :width="dialogWidth"
    :close-on-click-modal="false"
    @closed="handleClosed"
  >
    <!-- ==================== 第一步：选范围 ==================== -->
    <div v-if="step === 'choose'" v-loading="loading" class="bs-step">
      <p class="bs-tip">
        一次给多位同学生成签字图。每位同学签完立刻上传，中途关掉不会丢已经签好的。
      </p>

      <el-alert
        v-if="loadError"
        type="error"
        :closable="false"
        show-icon
        title="学生名单加载失败，请关闭弹窗后重试"
      />

      <el-radio-group v-else v-model="mode" class="bs-modes">
        <el-radio value="missing" border :disabled="!missingStudents.length">
          补充缺失（{{ missingStudents.length }} 人）
        </el-radio>
        <el-radio value="selected" border :disabled="!selectedCount">
          勾选覆盖（{{ selectedCount }} 人）
        </el-radio>
      </el-radio-group>

      <div v-if="mode === 'selected' && selectedExistingCount" class="bs-warn">
        选中的 {{ selectedCount }} 人里有 {{ selectedExistingCount }} 人已有签字图，
        确认后会覆盖原图。
      </div>
      <div v-if="mode === 'missing' && !missingStudents.length && !loading && !loadError" class="bs-warn">
        全班都已有签字图，没有需要补充的人；可以勾选学生后用「勾选覆盖」重签。
      </div>

      <template v-if="queue.length">
        <div class="bs-count">
          本次将采集 <b>{{ queue.length }}</b> 位同学的签名
        </div>
        <el-table :data="queue" size="small" border max-height="260">
          <el-table-column prop="name" label="姓名" width="110" />
          <el-table-column prop="student_no" label="学号" min-width="130" />
          <el-table-column label="签字图" width="130" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.has_sign_photo" type="warning" size="small" effect="plain">
                已有，将覆盖
              </el-tag>
              <el-tag v-else type="info" size="small" effect="plain">缺失</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>

    <!-- ==================== 第二步：逐人签名 ==================== -->
    <div v-else-if="step === 'sign'" class="bs-step">
      <div class="bs-progress">
        <span class="bs-progress-text">
          第 {{ index + 1 }} / {{ queueItems.length }} 人
        </span>
        <el-progress
          :percentage="progressPercent"
          :show-text="false"
          :stroke-width="6"
          class="bs-progress-bar"
        />
        <el-button link :disabled="uploading" @click="skipCurrent">跳过此人</el-button>
      </div>

      <SignaturePad
        ref="padRef"
        :signer-name="current?.name"
        :signer-no="current?.student_no"
        :submitting="uploading"
        @confirm="handleConfirm"
      />
    </div>

    <!-- ==================== 第三步：结果 ==================== -->
    <div v-else class="bs-step">
      <el-result :icon="resultIcon" title="批量签字完成" :sub-title="resultText">
        <template #extra>
          <div class="bs-stats">
            <div><b>{{ doneCount }}</b><span>已保存</span></div>
            <div><b>{{ skippedCount }}</b><span>跳过</span></div>
            <div><b>{{ failedCount }}</b><span>失败</span></div>
          </div>
        </template>
      </el-result>

      <el-alert
        v-if="failedItems.length"
        type="error"
        :closable="false"
        show-icon
        title="这些同学没有保存成功，可以再签一次"
      >
        <ul class="bs-list">
          <li v-for="item in failedItems" :key="item.id">
            {{ item.name }}（{{ item.student_no }}）
          </li>
        </ul>
      </el-alert>
    </div>

    <template #footer>
      <template v-if="step === 'choose'">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :disabled="!queue.length || loading" @click="start">
          开始签字
        </el-button>
      </template>
      <template v-else-if="step === 'sign'">
        <el-button :disabled="uploading" @click="finishEarly">结束并查看结果</el-button>
      </template>
      <template v-else>
        <el-button type="primary" @click="visible = false">完成</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import SignaturePad from '@/components/SignaturePad.vue'
import { getStudentList } from '@/api/student'
import { uploadSignImage } from '@/api/signPhoto'
import { useIsMobile } from '@/composables/useIsMobile'

const emit = defineEmits(['done'])

const isMobile = useIsMobile()
const dialogWidth = computed(() => (isMobile.value ? '94%' : '640px'))

const visible = ref(false)
const step = ref('choose') // choose / sign / result
const loading = ref(false)
const loadError = ref(false)
const roster = ref([])
const selectedIds = ref([])
const mode = ref('missing')

// 真正开始之后用的队列：复制一份并带上每人自己的处理状态
const queueItems = ref([])
const index = ref(0)
const uploading = ref(false)
const padRef = ref(null)

const missingStudents = computed(() => roster.value.filter((s) => !s.has_sign_photo))
const selectedStudents = computed(() =>
  roster.value.filter((s) => selectedIds.value.includes(s.id))
)
const selectedCount = computed(() => selectedStudents.value.length)
const selectedExistingCount = computed(
  () => selectedStudents.value.filter((s) => s.has_sign_photo).length
)

const queue = computed(() =>
  mode.value === 'selected' ? selectedStudents.value : missingStudents.value
)

const current = computed(() => queueItems.value[index.value])
const progressPercent = computed(() =>
  queueItems.value.length ? Math.round((index.value / queueItems.value.length) * 100) : 0
)

const doneCount = computed(() => queueItems.value.filter((i) => i.status === 'done').length)
const skippedCount = computed(() => queueItems.value.filter((i) => i.status === 'skipped').length)
const failedItems = computed(() => queueItems.value.filter((i) => i.status === 'failed'))
const failedCount = computed(() => failedItems.value.length)

const resultIcon = computed(() => {
  if (failedCount.value) return 'warning'
  return doneCount.value ? 'success' : 'info'
})

const resultText = computed(() => {
  const parts = [`已保存 ${doneCount.value} 位同学的签名`]
  if (skippedCount.value) parts.push(`跳过 ${skippedCount.value} 位`)
  if (failedCount.value) parts.push(`失败 ${failedCount.value} 位`)
  return parts.join('，')
})

/** 打开弹窗。selected 是表格里勾选的行，没有勾选时只提供「补充缺失」 */
function open(selected = []) {
  resetAll()
  selectedIds.value = (selected || []).map((s) => s.id)
  mode.value = selectedIds.value.length ? 'selected' : 'missing'
  visible.value = true
  loadRoster()
}

async function loadRoster() {
  loading.value = true
  loadError.value = false
  try {
    // 一次拉全量：page_size 后端上限 500，够一个班
    const res = await getStudentList({
      page: 1,
      page_size: 500,
      sort_by: 'student_no',
      sort_order: 'asc'
    })
    roster.value = res.items || []
  } catch (e) {
    loadError.value = true
    roster.value = []
  } finally {
    loading.value = false
  }
}

function start() {
  if (!queue.value.length) return
  queueItems.value = queue.value.map((s) => ({ ...s, status: 'pending' }))
  index.value = 0
  step.value = 'sign'
  // 等签名板真正显示出来再量尺寸，否则宽度是 0
  nextTick(() => padRef.value?.init())
}

/** 确认使用：先上传，成功才换下一个人；失败停在这一位，可以重试或跳过 */
async function handleConfirm(blob) {
  const item = current.value
  if (!item || uploading.value) return

  uploading.value = true
  try {
    const fileName = `sign-${item.student_no || item.id}.png`
    await uploadSignImage(item.id, new File([blob], fileName, { type: 'image/png' }))
    item.status = 'done'
    ElMessage.success(`已保存 ${item.name} 的签名`)
    advance()
  } catch (e) {
    item.status = 'failed'
    ElMessage.error(e?.response?.data?.detail || '上传失败，可重试或跳过此人')
  } finally {
    uploading.value = false
  }
}

function skipCurrent() {
  if (current.value) current.value.status = 'skipped'
  advance()
}

function advance() {
  if (index.value + 1 >= queueItems.value.length) {
    step.value = 'result'
    return
  }
  index.value += 1
  padRef.value?.reset()
}

function finishEarly() {
  step.value = 'result'
}

function resetAll() {
  step.value = 'choose'
  loading.value = false
  loadError.value = false
  roster.value = []
  selectedIds.value = []
  mode.value = 'missing'
  queueItems.value = []
  index.value = 0
  uploading.value = false
}

function handleClosed() {
  const saved = doneCount.value
  resetAll()
  if (saved) emit('done')
}

defineExpose({ open })
</script>

<style scoped>
.bs-step {
  min-height: 220px;
}

.bs-tip {
  margin: 0 0 12px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.bs-modes {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.bs-warn {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-color-warning);
}

.bs-count {
  margin: 14px 0 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.bs-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.bs-progress-text {
  flex: none;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.bs-progress-bar {
  flex: 1;
}

.bs-stats {
  display: flex;
  justify-content: center;
  gap: 32px;
}

.bs-stats b {
  display: block;
  font-size: 22px;
}

.bs-stats span {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.bs-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}
</style>
