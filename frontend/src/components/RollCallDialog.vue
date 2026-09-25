<template>
  <!-- 点名：选范围 → 逐个叫 → 汇总未应答名单 -->
  <el-dialog
    v-model="visible"
    title="点名"
    width="520px"
    :close-on-click-modal="false"
    :before-close="handleBeforeClose"
    @closed="reset"
  >
    <!-- 第一步：选范围 -->
    <div v-if="step === 'scope'" v-loading="loading" class="rc-scope">
      <p class="rc-tip">选择本次点名的范围：</p>
      <div class="rc-scope-btns">
        <el-button size="large" :disabled="!counts.male" @click="startCall('男生')">
          <el-icon><Male /></el-icon>男生（{{ counts.male }}）
        </el-button>
        <el-button size="large" :disabled="!counts.female" @click="startCall('女生')">
          <el-icon><Female /></el-icon>女生（{{ counts.female }}）
        </el-button>
        <el-button size="large" type="primary" :disabled="!counts.all" @click="startCall('全班')">
          <el-icon><UserFilled /></el-icon>全班（{{ counts.all }}）
        </el-button>
      </div>
      <p v-if="!loading && !counts.all" class="rc-empty">没有可点名的同学</p>
    </div>

    <!-- 第二步：逐个点名 -->
    <div v-else-if="step === 'calling' && currentStudent" class="rc-calling">
      <div class="rc-progress">
        <span class="rc-progress-text">第 {{ answers.length + 1 }} / {{ queue.length }} 位</span>
        <el-progress :percentage="progressPercent" :show-text="false" />
      </div>

      <div class="rc-photo">
        <img
          v-if="currentStudent.gaokao_photo && !photoBroken"
          :src="photoUrl(currentStudent)"
          class="rc-img"
          @error="photoBroken = true"
        />
        <div v-else class="rc-placeholder">
          <el-icon style="font-size: 48px;"><Avatar /></el-icon>
        </div>
      </div>

      <div class="rc-name">{{ currentStudent.name }}</div>
      <div class="rc-no">{{ currentStudent.student_no }}</div>

      <div class="rc-actions">
        <el-button size="large" type="danger" plain @click="mark(false)">无应答</el-button>
        <el-button size="large" :disabled="!answers.length" @click="undo">
          <el-icon><RefreshLeft /></el-icon>回退
        </el-button>
        <el-button size="large" type="success" @click="mark(true)">到</el-button>
      </div>

      <!-- 手机上没键盘，靠媒体查询隐藏 -->
      <p class="rc-keys">Enter / 空格 = 到 · ← = 无应答 · Backspace = 回退</p>
    </div>

    <!-- 第三步：汇总 -->
    <div v-else-if="step === 'result'" class="rc-result">
      <div v-if="!absentList.length" class="rc-all-present">
        <el-icon style="font-size: 40px; color: #67c23a;"><CircleCheck /></el-icon>
        <p>全部到齐（共 {{ queue.length }} 人）</p>
      </div>
      <template v-else>
        <p class="rc-tip">
          {{ scope }}共 {{ queue.length }} 人，<strong class="rc-absent-count">无应答 {{ absentList.length }} 人</strong>：
        </p>
        <div class="rc-absent-list">
          <div v-for="item in absentList" :key="item.student_no" class="rc-absent-item">
            <span class="rc-absent-name">{{ item.name }}</span>
            <span class="rc-absent-no">{{ item.student_no }}</span>
          </div>
        </div>
      </template>
    </div>

    <template #footer>
      <el-button v-if="step === 'scope'" @click="visible = false">取消</el-button>
      <el-button v-else-if="step === 'calling'" @click="handleCancel">取消点名</el-button>
      <template v-else>
        <el-button @click="backToScope">再点一次</el-button>
        <el-button type="primary" @click="visible = false">完成</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getStudentList, logRollCall } from '@/api/student'

const visible = ref(false)
const loading = ref(false)

// scope=选范围，calling=逐个点名，result=汇总
const step = ref('scope')
const scope = ref('全班')
const roster = ref([])   // 全班名单（open 时一次性拉回）
const queue = ref([])    // 本次要点的人
const answers = ref([])  // 与 queue 一一对应的结果，true=到，false=无应答
const photoBroken = ref(false)

/** 范围名 → 学生表 gender 字段里的实际取值。
    按钮上和日志里都写「男生」，但库里存的是「男」，这两个必须对上。
    单独拎出来是因为踩过坑：筛选逻辑原来在 counts 和 startCall 里各写了一份，
    counts 用了单字、startCall 却拿按钮上的「男生」直接比，于是选男生/女生
    永远是空名单，只有不筛选的「全班」正常。 */
const GENDER_BY_SCOPE = { 男生: '男', 女生: '女' }

/** 按范围取人。counts 和 startCall 共用它，就不会再各写一套比法 */
function pickByScope(list, scopeName) {
  if (scopeName === '全班') return [...list]
  return list.filter((s) => s.gender === GENDER_BY_SCOPE[scopeName])
}

const counts = computed(() => ({
  male: pickByScope(roster.value, '男生').length,
  female: pickByScope(roster.value, '女生').length,
  all: roster.value.length
}))

/** 当前要点到的人；answers 的长度天然就是进度指针，回退只需 pop */
const currentStudent = computed(() => queue.value[answers.value.length])

const progressPercent = computed(() =>
  queue.value.length ? Math.round((answers.value.length / queue.value.length) * 100) : 0
)

/** 逐条对照 queue 和 answers，挑出无应答的人 */
const absentList = computed(() =>
  queue.value.filter((_, i) => answers.value[i] === false)
)

function open() {
  reset()
  visible.value = true
  fetchRoster()
}

function reset() {
  step.value = 'scope'
  scope.value = '全班'
  roster.value = []   // 一并清掉，否则拉取失败时会拿着上一轮的人数误报
  queue.value = []
  answers.value = []
  photoBroken.value = false
}

/** 一次性拉全量名单：后端 page_size 上限 500，够全班用，无需分页 */
async function fetchRoster() {
  loading.value = true
  try {
    const res = await getStudentList({
      page: 1,
      page_size: 500,
      sort_by: 'student_no',
      sort_order: 'asc'
    })
    roster.value = res.items || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取学生名单失败')
  } finally {
    loading.value = false
  }
}

function startCall(picked) {
  scope.value = picked
  queue.value = pickByScope(roster.value, picked)
  answers.value = []
  photoBroken.value = false
  step.value = 'calling'
}

/** 记一个人的结果；记满自动进汇总 */
function mark(answered) {
  if (!currentStudent.value) return
  answers.value.push(answered)
  photoBroken.value = false
  if (answers.value.length >= queue.value.length) finish()
}

function undo() {
  if (!answers.value.length) return
  answers.value.pop()
  photoBroken.value = false
}

function finish() {
  step.value = 'result'
  reportResult()
}

/** 上报日志：结果已经在界面上了，上报失败只提示，不回滚界面 */
async function reportResult() {
  try {
    await logRollCall({
      scope: scope.value,
      total: queue.value.length,
      absent: absentList.value.map((s) => ({ student_no: s.student_no, name: s.name }))
    })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '点名结果未能记入操作日志')
  }
}

function backToScope() {
  step.value = 'scope'
  queue.value = []
  answers.value = []
}

/** 照片走带鉴权的接口，靠 Cookie 自动带凭证，与「学生信息」表格里一致 */
function photoUrl(student) {
  return `/api/students/${student.id}/photo?type=gaokao`
}

// 点了半天再关掉等于白点，先问一句
async function confirmDiscard() {
  if (step.value !== 'calling' || !answers.value.length) return true
  try {
    await ElMessageBox.confirm(
      `已经点了 ${answers.value.length} 人，现在关闭会丢失这些记录。确定关闭吗？`,
      '提示',
      { confirmButtonText: '确定关闭', cancelButtonText: '继续点名', type: 'warning' }
    )
    return true
  } catch {
    return false
  }
}

async function handleCancel() {
  if (await confirmDiscard()) visible.value = false
}

/** 右上角的 × 也要走同一个确认，否则它会绕过取消按钮的拦截 */
async function handleBeforeClose(done) {
  if (await confirmDiscard()) done()
}

/**
 * 键盘快捷键：Enter/空格/→ = 到，← = 无应答，Backspace = 回退。
 * 弹窗里没有任何输入框，不会和打字冲突；手机上没键盘，提示行由 CSS 隐藏。
 */
function handleKeydown(e) {
  if (!visible.value || step.value !== 'calling') return
  if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
    e.preventDefault()
    mark(true)
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault()
    mark(false)
  } else if (e.key === 'Backspace') {
    e.preventDefault()
    undo()
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onUnmounted(() => window.removeEventListener('keydown', handleKeydown))

// 让父组件通过 ref 调用 open()
defineExpose({ open })
</script>

<style scoped>
.rc-tip {
  margin: 0 0 14px 0;
  font-size: 14px;
  color: #606266;
}

.rc-scope-btns {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rc-scope-btns .el-button {
  width: 100%;
  margin-left: 0;
}

.rc-empty {
  margin: 16px 0 0;
  text-align: center;
  color: #909399;
  font-size: 14px;
}

/* ---- 逐个点名 ---- */
.rc-calling {
  text-align: center;
}

.rc-progress {
  margin-bottom: 18px;
}

.rc-progress-text {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: #909399;
}

.rc-photo {
  display: flex;
  justify-content: center;
  margin-bottom: 14px;
}

.rc-img,
.rc-placeholder {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid #fff;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.12);
}

.rc-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
  color: #c0c4cc;
}

.rc-name {
  font-size: 30px;
  font-weight: 600;
  letter-spacing: 4px;
  color: #303133;
}

.rc-no {
  margin-top: 6px;
  font-size: 14px;
  color: #909399;
}

.rc-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 22px;
}

.rc-actions .el-button {
  margin-left: 0;
}

.rc-keys {
  margin: 16px 0 0;
  font-size: 12px;
  color: #c0c4cc;
}

/* ---- 汇总 ---- */
.rc-all-present {
  padding: 12px 0;
  text-align: center;
  color: #67c23a;
}

.rc-all-present p {
  margin: 10px 0 0;
  font-size: 16px;
}

.rc-absent-count {
  color: #f56c6c;
}

.rc-absent-list {
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}

.rc-absent-item {
  display: flex;
  justify-content: space-between;
  padding: 10px 14px;
  font-size: 14px;
  border-bottom: 1px solid #ebeef5;
}

.rc-absent-item:last-child {
  border-bottom: none;
}

.rc-absent-name {
  font-weight: 500;
}

.rc-absent-no {
  color: #909399;
}

@media (max-width: 768px) {
  .rc-name {
    font-size: 26px;
  }

  .rc-img,
  .rc-placeholder {
    width: 96px;
    height: 96px;
  }

  /* 手机上没有物理键盘，快捷键提示只会占地方 */
  .rc-keys {
    display: none;
  }
}
</style>
