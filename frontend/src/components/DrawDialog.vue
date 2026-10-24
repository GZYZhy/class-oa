<template>
  <!-- 抽签：选范围与模式 → 抽取 → 结果 -->
  <el-dialog append-to-body
    v-model="visible"
    title="抽签"
    width="520px"
    :close-on-click-modal="false"
    :before-close="handleBeforeClose"
    @closed="handleClosed"
  >
    <!-- 第一步：选范围与模式 -->
    <div v-if="step === 'setup'" v-loading="loading" class="dr-setup">
      <!-- 排除名单要说清楚是谁、为什么，不然「全班 34 人」对不上花名册会让人怀疑数字错了 -->
      <el-alert v-if="excluded.length" type="info" :closable="false" class="dr-excluded">
        <template #title>
          已排除 {{ excluded.length }} 名在校状态非「正常」的同学，不参与抽签
        </template>
        <div class="dr-excluded-list">
          <span v-for="s in excluded" :key="s.student_no" class="dr-excluded-item">
            {{ s.name }}（{{ s.school_status || '未填' }}）
          </span>
        </div>
      </el-alert>

      <p class="dr-label">抽取范围</p>
      <el-radio-group v-model="scope" class="dr-radios">
        <el-radio value="从表格里选" :disabled="!selected.length">
          从表格里选（{{ selected.length }}）
        </el-radio>
        <el-radio value="男生" :disabled="!counts.male">男生（{{ counts.male }}）</el-radio>
        <el-radio value="女生" :disabled="!counts.female">女生（{{ counts.female }}）</el-radio>
        <el-radio value="全班" :disabled="!counts.all">全班（{{ counts.all }}）</el-radio>
      </el-radio-group>

      <p class="dr-label">抽取模式</p>
      <el-radio-group v-model="mode" class="dr-radios">
        <div class="dr-mode-row">
          <el-radio value="batch">一次抽取</el-radio>
          <!-- 跟着选中态出现：没选这个模式时摆一个输入框只会让人以为它也算数 -->
          <template v-if="mode === 'batch'">
            <el-input-number
              v-model="batchCount"
              :min="1"
              :max="Math.max(pool.length, 1)"
              size="small"
              class="dr-count"
            />
            <span class="dr-unit">人</span>
          </template>
        </div>
        <div class="dr-mode-row">
          <el-radio value="one">点一回取一个</el-radio>
        </div>
      </el-radio-group>

      <div v-if="mode === 'one'" class="dr-repeat">
        <el-checkbox v-model="repeatable">允许重复抽到同一人</el-checkbox>
        <p class="dr-hint">每次都是独立的一次随机，可能连着抽到同一个人</p>
      </div>

      <p v-if="!loading && !pool.length" class="dr-empty">这个范围里没有可抽的同学</p>
    </div>

    <!-- 第二步：抽取 -->
    <div v-else class="dr-drawing">
      <!-- 舞台：两种模式的展示方式不同，下面的结果列表是共用的 -->
      <div class="dr-stage">
        <template v-if="mode === 'one'">
          <div class="dr-name">{{ latest ? latest.name : '还没抽' }}</div>
          <div class="dr-no">{{ latest ? latest.student_no : '' }}</div>

          <p v-if="!repeatable" class="dr-progress">
            本轮已抽 {{ roundDrawnIds.length }} / {{ pool.length }}
          </p>
          <p v-if="exhausted" class="dr-exhausted">
            本轮 {{ pool.length }} 人都抽过了。可重置本轮再抽一轮，抽取历史会保留
          </p>

          <div class="dr-actions">
            <el-button size="large" type="primary" :disabled="exhausted" @click="drawOne">
              <el-icon><Aim /></el-icon>{{ exhausted ? '已抽完' : '抽一个' }}
            </el-button>
          </div>
        </template>
        <p v-else class="dr-batch-summary">已抽取 {{ picked.length }} 人</p>
      </div>

      <p class="dr-list-title">{{ mode === 'batch' ? '本次抽中' : '抽取历史' }}</p>
      <div v-if="picked.length" class="dr-list">
        <!-- 允许重复时同一个人会出现两次，只能用序号做 key -->
        <div v-for="(s, i) in picked" :key="i" class="dr-list-item">
          <span class="dr-list-idx">{{ i + 1 }}</span>
          <span class="dr-list-name">{{ s.name }}</span>
          <span class="dr-list-no">{{ s.student_no }}</span>
        </div>
      </div>
      <p v-else class="dr-empty">还没有抽到人</p>
    </div>

    <template #footer>
      <template v-if="step === 'setup'">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :disabled="!pool.length" @click="start">开始抽取</el-button>
      </template>
      <template v-else>
        <el-button :disabled="!picked.length" @click="copyResult">复制</el-button>
        <!-- 「一次抽取」换一批；「点一回取一个」的列表是攒出来的，不给一键清空 -->
        <el-button v-if="mode === 'batch' && picked.length" @click="drawBatch">重新抽</el-button>
        <el-button v-if="canResetRound" @click="resetRound">重置本轮</el-button>
        <el-button type="primary" @click="visible = false">完成</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getStudentList, logDraw } from '@/api/student'
import { copyText } from '@/utils/clipboard'
// 名单规则与点名共用（谁是「能参与的人」、男生/女生各对应库里哪个值），见 utils/roster.js
import { pickByScope, splitBySchoolStatus, sample } from '@/utils/roster'

const props = defineProps({
  /** 表格里勾选的学生。变化要实时反映到「从表格里选（N）」上，所以用 prop 而不是 open 传参 */
  selected: { type: Array, default: () => [] }
})

const visible = ref(false)
const loading = ref(false)

// setup=选范围与模式，drawing=抽取中
const step = ref('setup')
const scope = ref('全班')      // 从表格里选 / 男生 / 女生 / 全班
const mode = ref('batch')      // batch=一次抽取 x 人，one=点一回取一个
const repeatable = ref(false)  // 仅 one 模式：是否允许抽到同一个人

const roster = ref([])   // 能参与抽签的名单（open 时一次性拉回，已滤掉在校状态非正常的）
const excluded = ref([]) // 被滤掉的人，只用来在第一步提示一句
const picked = ref([])   // 抽中名单：显示的和复制的都是它
const latest = ref(null) // 仅 one 模式：舞台上展示的最新一个
// 仅「不重复」用：本轮抽过谁。重置本轮时清空，picked 不动
const roundDrawnIds = ref([])

const counts = computed(() => ({
  male: pickByScope(roster.value, '男生').length,
  female: pickByScope(roster.value, '女生').length,
  all: roster.value.length
}))

/** 本次抽取的池子 */
const pool = computed(() =>
  scope.value === '从表格里选' ? [...props.selected] : pickByScope(roster.value, scope.value)
)

/** 「点一回取一个」的候选：可重复时是整池，否则是本轮还没抽过的 */
const remain = computed(() => {
  if (repeatable.value) return pool.value
  const used = new Set(roundDrawnIds.value)
  return pool.value.filter((s) => !used.has(s.id))
})

const exhausted = computed(() => !repeatable.value && !remain.value.length)

/** 本轮抽过人才有得重置；可重复模式没有「本轮」的概念 */
const canResetRound = computed(
  () => mode.value === 'one' && !repeatable.value && roundDrawnIds.value.length > 0
)

// 人数不直接存 ref，而是读写分离：写进 rawCount，读出来时按当前池子夹一次。
// 因为 el-input-number 只 watch 自己的值 —— :max 变小时它不回头改，于是「全班 40 人时
// 填了 5、切到只有 3 人的男生」会让输入框停在 5，用户被卡在一个抽不出来的数字上。
// 夹在「读」这一侧就不用管池子是被换范围还是被取消勾选弄小的，也不必和时机较劲
const rawCount = ref(1)
const batchCount = computed({
  get: () => {
    const n = Number(rawCount.value)
    return Number.isFinite(n) && n >= 1 ? Math.min(n, Math.max(pool.value.length, 1)) : 1
  },
  set: (v) => {
    rawCount.value = v
  }
})

function open() {
  reset()
  // 表格里已经勾了人就默认按勾选抽 —— 那是用户已经挑过人的意思
  if (props.selected.length) scope.value = '从表格里选'
  visible.value = true
  fetchRoster()
}

function reset() {
  step.value = 'setup'
  scope.value = '全班'
  mode.value = 'batch'
  repeatable.value = false
  rawCount.value = 1
  roster.value = []   // 一并清掉，否则拉取失败时会拿着上一轮的人数误报
  excluded.value = []
  picked.value = []
  latest.value = null
  roundDrawnIds.value = []
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
    const { active, excluded: skipped } = splitBySchoolStatus(res.items || [])
    roster.value = active
    excluded.value = skipped
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取学生名单失败')
  } finally {
    loading.value = false
  }
}

function start() {
  if (!pool.value.length) return
  step.value = 'drawing'
  picked.value = []
  latest.value = null
  roundDrawnIds.value = []
  if (mode.value === 'batch') drawBatch()
  else drawOne()
}

/** 一次抽取：换一批（替换上次的结果） */
function drawBatch() {
  picked.value = sample(pool.value, batchCount.value)
  latest.value = null
}

/** 点一回取一个：往历史里追加一个 */
function drawOne() {
  if (!remain.value.length) return
  const [one] = sample(remain.value, 1)
  latest.value = one
  picked.value.push(one)
  roundDrawnIds.value.push(one.id)
}

/** 只清空本轮的排除集，抽取历史原样保留 */
function resetRound() {
  roundDrawnIds.value = []
}

function copyResult() {
  copyText(picked.value.map((s) => s.name).join('\n'))
}

// 抽了人再关掉，先问一句。结果本来就不落库，所以文案说的是「不再显示」而不是「会丢失记录」
async function confirmDiscard() {
  if (!picked.value.length) return true
  try {
    await ElMessageBox.confirm(
      `已经抽了 ${picked.value.length} 人，关闭后这份名单不再显示（可先复制）。确定关闭吗？`,
      '提示',
      { confirmButtonText: '确定关闭', cancelButtonText: '继续抽签', type: 'warning' }
    )
    return true
  } catch {
    return false
  }
}

/** 右上角的 × 也要走同一个确认，否则它会绕过取消按钮的拦截 */
async function handleBeforeClose(done) {
  if (await confirmDiscard()) done()
}

/**
 * 上报日志：整个会话只报一次，所以只能放在关闭时 —— 两种模式里只有这一瞬是共同的
 * （「点一回取一个」的名单是攒出来的，没有「抽完」那一刻）。
 *
 * 顺序不能动：先取快照、再 reset、最后才 await 上报。上报回来之前用户可能已经
 * 重开弹窗抽下一轮了，那时再 reset 会把新一轮的状态清掉。
 */
async function handleClosed() {
  const payload = { scope: scope.value, count: picked.value.length }
  reset()
  if (!payload.count) return  // 一个人没抽就关掉，不写空日志（@closed 是无条件触发的）
  try {
    await logDraw(payload)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '抽签记录保存失败')
  }
}

// 让父组件通过 ref 调用 open()
defineExpose({ open })
</script>

<style scoped>
.dr-label {
  margin: 18px 0 10px;
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.dr-label:first-child {
  margin-top: 0;
}

.dr-excluded {
  margin-bottom: 4px;
}

/* 手机上一行长名字会溢出，用 inline 元素自然折行 */
.dr-excluded-list {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
}

.dr-excluded-item {
  margin-right: 10px;
  white-space: nowrap;
}

/* 竖排：4 个范围带人数横排一定换行，不如一开始就一人一行 */
.dr-radios {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}

.dr-mode-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dr-count {
  width: 100px;
}

.dr-unit {
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.dr-repeat {
  margin-top: 12px;
  padding-left: 22px;
}

.dr-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.dr-empty {
  margin: 16px 0 0;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

/* ---- 抽取 ---- */
.dr-stage {
  text-align: center;
}

.dr-name {
  font-size: 30px;
  font-weight: 600;
  letter-spacing: 4px;
  color: var(--el-text-color-primary);
}

.dr-no {
  margin-top: 6px;
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.dr-progress {
  margin: 10px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.dr-exhausted {
  margin: 10px 0 0;
  font-size: 13px;
  color: var(--el-color-warning);
}

.dr-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 18px;
}

.dr-actions .el-button {
  margin-left: 0;
}

.dr-batch-summary {
  margin: 8px 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

/* ---- 结果列表（两种模式共用） ---- */
.dr-list-title {
  margin: 20px 0 8px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.dr-list {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

.dr-list-item {
  display: flex;
  align-items: center;
  padding: 8px 14px;
  font-size: 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.dr-list-item:last-child {
  border-bottom: none;
}

.dr-list-idx {
  width: 28px;
  flex: none;
  color: var(--el-text-color-secondary);
}

.dr-list-name {
  font-weight: 500;
}

.dr-list-no {
  margin-left: auto;
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .dr-name {
    font-size: 26px;
  }
}
</style>
