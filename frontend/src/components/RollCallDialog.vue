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

      <!-- 排除名单要说清楚是谁、为什么，不然「全班 34 人」对不上花名册会让人怀疑数字错了 -->
      <el-alert v-if="excluded.length" type="info" :closable="false" class="rc-excluded">
        <template #title>
          已排除 {{ excluded.length }} 名在校状态非「正常」的同学，不参与点名
        </template>
        <div class="rc-excluded-list">
          <span v-for="s in excluded" :key="s.student_no" class="rc-excluded-item">
            {{ s.name }}（{{ s.school_status || '未填' }}）
          </span>
        </div>
      </el-alert>

      <!-- 请假的人不在场，逐个点名时不会叫到，但应到人数里得算一个「请假」——
           不然「全班 34 人」点到一半变成 32 人，看着像漏了谁 -->
      <el-alert v-if="onLeave.length" type="info" :closable="false" class="rc-excluded">
        <template #title>
          有 {{ onLeave.length }} 名同学当前在已批准的请假区间内，将自动记为「请假」
        </template>
        <div class="rc-excluded-list">
          <span v-for="s in onLeave" :key="s.student_no" class="rc-excluded-item">
            {{ s.student_name }}（{{ s.leave_type }}）
          </span>
        </div>
      </el-alert>

      <div class="rc-scope-btns">
        <el-button size="large" :disabled="!counts.male" @click="startCall('男生')">
          <el-icon><Male /></el-icon>男生（{{ counts.male }}）
        </el-button>
        <el-button size="large" :disabled="!counts.female" @click="startCall('女生')">
          <el-icon><Female /></el-icon>女生（{{ counts.female }}）
        </el-button>
        <el-button size="large" :disabled="!counts.league" @click="startCall('共青团员')">
          <el-icon><Star /></el-icon>共青团员（{{ counts.league }}）
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

    <!-- 第三步：汇总。应到 = 逐个点到的人 + 本范围内请假的人，
         口径和「考勤记录」页完全一致（那边也是从明细里数出来的） -->
    <div v-else-if="step === 'result'" class="rc-result">
      <div v-if="!absentList.length && !leaveInScope.length" class="rc-all-present">
        <el-icon style="font-size: 40px; color: #67c23a;"><CircleCheck /></el-icon>
        <p>全部到齐（共 {{ scopeTotal }} 人）</p>
      </div>
      <template v-else>
        <p class="rc-tip">
          {{ scope }}应到 {{ scopeTotal }} 人，实到 {{ presentCount }} 人，请假
          {{ leaveInScope.length }} 人，<strong :class="absentList.length ? 'rc-absent-count' : ''"
            >无应答 {{ absentList.length }} 人</strong
          >
        </p>
        <div v-if="absentList.length" class="rc-absent-list">
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
import { getStudentList } from '@/api/student'
import { createAttendance } from '@/api/attendance'
import { getLeaveList } from '@/api/leave'
// 名单规则与抽签共用，规则说明见 utils/roster.js
import { onLeaveNow, pickByScope, splitByLeave, splitBySchoolStatus } from '@/utils/roster'

const visible = ref(false)
const loading = ref(false)

// scope=选范围，calling=逐个点名，result=汇总
const step = ref('scope')
const scope = ref('全班')
const roster = ref([])   // 能参与点名的名单（open 时一次性拉回，已滤掉在校状态非正常的）
const excluded = ref([]) // 被滤掉的人，只用来在第一步提示一句
const queue = ref([])    // 本次要点的人（不含请假的）
const answers = ref([])  // 与 queue 一一对应的结果，true=到，false=无应答

// 请假联动：这三项在第一次点名时定下来，汇总和上报都用它们
const onLeave = ref([])      // 当前处在已批准请假区间内的人（第一步提示用）
const leaveInScope = ref([]) // 本次范围内应记为「请假」的人
const scopeTotal = ref(0)    // 本次应到人数 = queue + leaveInScope
// 学号 → 请假记录。startCall 每次都拿它求交集，所以要留住
const leaveByNoRef = ref(new Map())

const counts = computed(() => ({
  male: pickByScope(roster.value, '男生').length,
  female: pickByScope(roster.value, '女生').length,
  league: pickByScope(roster.value, '共青团员').length,
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

/** 点到的人里答「到」的；请假的不算在内（他们压根没被叫） */
const presentCount = computed(() => answers.value.filter((a) => a === true).length)

function open() {
  reset()
  visible.value = true
  fetchRoster()
}

function reset() {
  step.value = 'scope'
  scope.value = '全班'
  roster.value = []   // 一并清掉，否则拉取失败时会拿着上一轮的人数误报
  excluded.value = []
  queue.value = []
  answers.value = []
  onLeave.value = []
  leaveInScope.value = []
  scopeTotal.value = 0
  leaveByNoRef.value = new Map()
}

/** 一次性拉全量名单 + 已批准的请假：后端 page_size 上限 500，够全班用，无需分页 */
async function fetchRoster() {
  loading.value = true
  try {
    const [res, leaves] = await Promise.all([
      getStudentList({ page: 1, page_size: 500, sort_by: 'student_no', sort_order: 'asc' }),
      // 请假列表是班委及以上才看得到，点名本来就只有班委点得了，权限对得上。
      // 复用现成接口，不另开一个「查谁在请假」的接口 —— 那要把区间比较写两遍
      getLeaveList('approved')
    ])
    // 过滤只在这里做一次，roster 只装能点名的人。counts 和 queue 都是从 roster
    // 出来的，所以按钮上的数字和实际叫到的人不会对不上
    const { active, excluded: skipped } = splitBySchoolStatus(res.items || [])
    roster.value = active
    excluded.value = skipped

    // 只看「此刻正落在请假区间内」的，判定规则见 utils/roster.js
    const leaveByNo = onLeaveNow(active, leaves, Date.now())
    onLeave.value = [...leaveByNo.values()]
    leaveByNoRef.value = leaveByNo
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取学生名单失败')
  } finally {
    loading.value = false
  }
}

function startCall(picked) {
  scope.value = picked
  const inScope = pickByScope(roster.value, picked)

  // 请假的人不在场（也就不该被叫到），从队列里剔掉，但留在应到人数里。
  // splitByLeave 内部会和 inScope 求交集 —— 不然选「男生」时请假的女生也会被算进来
  const { calling, onLeave: leaving } = splitByLeave(inScope, leaveByNoRef.value)
  queue.value = calling
  leaveInScope.value = leaving
  scopeTotal.value = inScope.length

  answers.value = []

  // 整个范围都在请假时没人可点，直接出汇总（否则会卡在第二步不动）
  if (!queue.value.length) {
    finish()
    return
  }
  step.value = 'calling'
}

/** 记一个人的结果；记满自动进汇总 */
function mark(answered) {
  if (!currentStudent.value) return
  answers.value.push(answered)
  if (answers.value.length >= queue.value.length) finish()
}

function undo() {
  if (!answers.value.length) return
  answers.value.pop()
}

function finish() {
  step.value = 'result'
  reportResult()
}

/** 上报落库：结果已经在界面上了，上报失败只提示，不回滚界面 */
async function reportResult() {
  try {
    // 点到的每个人都要报（不只是缺席的）：考勤明细要能逐个改状态，
    // 后端也就存了全部人，两边的「应到」才是同一个数
    const records = [
      ...queue.value.map((s, i) => ({
        student_no: s.student_no,
        name: s.name,
        status: answers.value[i] === false ? 'absent' : 'present'
      })),
      ...leaveInScope.value.map((s) => ({
        student_no: s.student_no,
        name: s.student_name,
        status: 'leave'
      }))
    ]
    await createAttendance({ scope: scope.value, records })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '点名结果保存失败')
  }
}

function backToScope() {
  step.value = 'scope'
  queue.value = []
  answers.value = []
  leaveInScope.value = []
  scopeTotal.value = 0
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
  color: var(--el-text-color-regular);
}

.rc-excluded {
  margin-bottom: 14px;
}

/* 手机上一行长名字会溢出，用 inline 元素自然折行 */
.rc-excluded-list {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
}

.rc-excluded-item {
  margin-right: 10px;
  white-space: nowrap;
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
  color: var(--el-text-color-secondary);
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
  color: var(--el-text-color-secondary);
}

.rc-name {
  font-size: 30px;
  font-weight: 600;
  letter-spacing: 4px;
  color: var(--el-text-color-primary);
}

.rc-no {
  margin-top: 6px;
  font-size: 14px;
  color: var(--el-text-color-secondary);
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
  color: var(--el-text-color-disabled);
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
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

.rc-absent-item {
  display: flex;
  justify-content: space-between;
  padding: 10px 14px;
  font-size: 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.rc-absent-item:last-child {
  border-bottom: none;
}

.rc-absent-name {
  font-weight: 500;
}

.rc-absent-no {
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .rc-name {
    font-size: 26px;
  }

  /* 手机上没有物理键盘，快捷键提示只会占地方 */
  .rc-keys {
    display: none;
  }
}
</style>
