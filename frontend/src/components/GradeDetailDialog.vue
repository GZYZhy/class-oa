<template>
  <!-- 成绩明细：逐格改分、加科目、删科目 -->
  <el-dialog
    v-model="visible"
    :title="data?.name || '成绩明细'"
    width="92%"
    top="6vh"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <div v-loading="loading" class="gd-body">
      <Watermark :text="watermarkText" />
      <div class="gd-meta">
        <span>{{ formatDate(data?.tested_at) }}</span>
        <span v-if="data?.remark" class="gd-remark">{{ data.remark }}</span>
        <span class="gd-count">
          已录 {{ data?.student_count || 0 }} 人 / {{ data?.subject_count || 0 }} 科
        </span>
      </div>

      <div class="gd-tools">
        <el-input
          v-model="newSubject"
          size="small"
          maxlength="50"
          placeholder="新科目名"
          style="width: 160px"
          @keyup.enter="handleAddSubject"
        />
        <el-button size="small" :loading="subjectLoading" @click="handleAddSubject">加科目</el-button>
        <el-button size="small" @click="statsRef.open(data)">统计</el-button>
        <span class="gd-hint">
          格子填 0~{{ 1000 }} 的数字、<b>留空表示清空</b>，或
          {{ (data?.mark_values || []).join(' / ') }}；
          通过制科目填「通过 / 不通过」
        </span>
      </div>

      <el-table
        :key="tableKey"
        :data="data?.rows || []"
        size="small"
        border
        max-height="56vh"
        row-key="student_no"
        show-summary
        :summary-method="summaryMethod"
      >
        <el-table-column prop="student_no" label="学号" width="120" fixed />
        <el-table-column label="姓名" width="100" fixed>
          <template #default="{ row }">
            {{ row.student_name }}
            <!-- 已删档（毕业）的人只剩成绩里的名字快照，标一下免得以为是脏数据 -->
            <el-tooltip v-if="!row.in_roster" content="已不在学生名单里（档案已删），只保留了成绩">
              <el-tag size="small" type="info" effect="plain">已删档</el-tag>
            </el-tooltip>
            <el-tooltip v-else-if="row.school_status && row.school_status !== '正常'"
                        :content="`在校状态：${row.school_status}`">
              <el-tag size="small" type="warning" effect="plain">{{ row.school_status }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column
          v-for="s in data?.subjects || []"
          :key="s.id"
          :label="s.name"
          :prop="`s_${s.id}`"
          width="160"
        >
          <template #header>
            <span class="gd-head">
              <span>{{ s.name }}</span>
              <!-- 形态和满分标在表头上：录入的人得知道这一科该填数字还是填「通过」 -->
              <el-tag v-if="s.mode === 'pass_fail'" size="small" type="success" effect="plain">
                通过制
              </el-tag>
              <el-tag v-else-if="s.full_score !== 100" size="small" effect="plain">
                {{ s.full_score }} 分
              </el-tag>
              <el-button link type="primary" size="small" @click="openSetting(s)">设置</el-button>
              <el-button link type="danger" size="small" @click="handleRemoveSubject(s)">删除</el-button>
            </span>
          </template>
          <template #default="{ row }">
            <el-input
              v-model="row.values[String(s.id)]"
              size="small"
              :placeholder="s.mode === 'pass_fail' ? '通过 / 不通过' : '—'"
              @change="(value) => saveCell(row, s, value)"
            />
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!(data?.subjects || []).length" class="gd-empty">
        这次测试还没有科目，用上面的输入框加一科。
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>

  <!-- 改一科的形态 / 满分。做成小弹窗而不是行内改：改形态可能被后端挡回来，
       得有一行地方把「这科已有分数，不能改成通过制」这种话写清楚 -->
  <el-dialog v-model="settingVisible" title="科目设置" width="400px" append-to-body>
    <div class="wm-host">
      <Watermark :text="watermarkText" />
      <el-form label-width="72px">
        <el-form-item label="科目">
          <span>{{ setting.name }}</span>
        </el-form-item>
        <el-form-item label="形态">
          <el-radio-group v-model="setting.mode">
            <el-radio value="score">计分</el-radio>
            <el-radio value="pass_fail">通过制</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="setting.mode === 'score'" label="满分">
          <el-input-number
            v-model="setting.full_score"
            :min="1"
            :max="1000"
            :controls="false"
            style="width: 90px"
          />
          <span class="gd-hint">及格线 {{ passLine }} 分</span>
        </el-form-item>
        <div class="gd-hint">
          通过制只记「通过 / 不通过」，不算平均分、最高最低和位次。
          改形态时若这一科已有对不上的成绩，会先拦住并告诉你还有多少条
        </div>
      </el-form>
    </div>
    <template #footer>
      <el-button @click="settingVisible = false">取消</el-button>
      <el-button type="primary" :loading="settingLoading" @click="handleSaveSetting">保存</el-button>
    </template>
  </el-dialog>

  <!-- 完整统计表。底部那行汇总只够看一眼平均分，分数段得点开看 -->
  <GradeStatsDialog ref="statsRef" />
</template>

<script setup>
import { computed, ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addGradeSubject,
  getGradeDetail,
  getGradeStats,
  putGradeScore,
  removeGradeSubject,
  updateGradeSubject
} from '@/api/grade'
import { formatDate } from '@/utils/format'
import { errText } from '@/utils/request'
import GradeStatsDialog from '@/components/GradeStatsDialog.vue'
import Watermark from '@/components/Watermark.vue'
import { useWatermark } from '@/composables/useWatermark'

const emit = defineEmits(['done'])

const watermarkText = useWatermark()
const visible = ref(false)
const loading = ref(false)
const subjectLoading = ref(false)
const data = ref(null)
const testId = ref(null)
const newSubject = ref('')
const statsRef = ref(null)
// 单科统计（班委及以上）。表格底部那行汇总就靠它，没有总分这个概念
const stats = ref(null)
// 科目设置弹窗
const settingVisible = ref(false)
const settingLoading = ref(false)
const setting = reactive({ id: null, name: '', mode: 'score', full_score: 100 })

const statsMap = computed(() => {
  const map = {}
  for (const s of stats.value?.subjects || []) map[String(s.subject_id)] = s
  return map
})

const passLine = computed(() => Math.round((setting.full_score || 0) * 0.6 * 100) / 100)
// 换科目列之后要让 el-table 重建：Element 的列在 mounted 时注册，
// 只换 data 不给 key 的话表头不跟着变
const tableKey = ref(0)
// 服务端当前的格子值。**回滚要拿它**：v-model 已经把用户敲的字写进了 row.values，
// 失败时必须写回这个快照，光提示是不够的
const saved = reactive({})
// 同一格子上一次保存的结果，用来丢弃重复请求
const inflight = new Set()

function cellKey(studentNo, subjectId) {
  return `${studentNo}:${subjectId}`
}

async function open(row) {
  testId.value = row.id
  visible.value = true
  // 先把列表里已有的信息填上，明细回来前界面就不空着
  data.value = { ...row, subjects: [], rows: [], mark_values: [] }
  await load()
}

function reset() {
  data.value = null
  testId.value = null
  newSubject.value = ''
  stats.value = null
  tableKey.value = 0
  for (const key of Object.keys(saved)) delete saved[key]
  // 关掉时让列表刷一次：这一趟可能加了科目、改了分数，列表上的计数就不准了
  emit('done')
}

async function load() {
  loading.value = true
  try {
    data.value = await getGradeDetail(testId.value)
    // 记下服务端现状：每行每科都有键，空串表示这格没录
    for (const key of Object.keys(saved)) delete saved[key]
    for (const row of data.value.rows || []) {
      for (const s of data.value.subjects || []) {
        saved[cellKey(row.student_no, s.id)] = row.values[String(s.id)] ?? ''
      }
    }
    tableKey.value += 1
    await refreshStats()
  } catch (e) {
    // 拉到一半失败会把空表留在弹窗里，看着像「这场没录过成绩」，得说清楚
    ElMessage.error(errText(e, '读取明细失败'))
  } finally {
    loading.value = false
  }
}

/** 拉单科统计。**失败不弹错**：统计只是表格底部一行参考，拿不到就空着，
 *  不能让它把正在改分的班委挡住 */
async function refreshStats() {
  try {
    stats.value = await getGradeStats(testId.value)
  } catch {
    stats.value = null
  }
}

/** 数字去掉多余的小数位：12.0 → 12，12.34 → 12.3 */
function fmtNum(v) {
  return v === null || v === undefined ? '—' : String(Math.round(v * 10) / 10)
}

/**
 * 表格底部那行汇总：每科两块信息，用换行分两行显示（样式里配了 pre-line）
 *
 * 列名带 s_ 前缀是为了在这儿认得出是哪一科 —— el-table 只把 prop 交回来，
 * 不给科目对象。学号 / 姓名两列认不出来，返回空串
 */
function summaryMethod({ columns }) {
  return columns.map((col) => {
    const stat = statsMap.value[String(col.property || '').replace(/^s_/, '')]
    if (!stat) return ''
    if (stat.mode === 'pass_fail') {
      if (!stat.passed_count && !stat.failed_count) return '暂无成绩'
      return `通过 ${fmtNum(stat.pass_rate)}%\n${stat.passed_count} 通过 / ${stat.failed_count} 不通过`
    }
    if (!stat.scored_count) return '暂无成绩'
    return `平均 ${fmtNum(stat.avg)}\n及格 ${fmtNum(stat.pass_rate)}%`
  })
}

async function saveCell(row, subject, value) {
  const key = cellKey(row.student_no, subject.id)
  const text = (value ?? '').trim()
  if (text === saved[key]) {
    // 只是加了空格、或者本来就没变：把显示归一化回去，不打扰后端
    row.values[String(subject.id)] = saved[key]
    return
  }
  if (inflight.has(key)) return
  inflight.add(key)
  try {
    const res = await putGradeScore(testId.value, {
      student_no: row.student_no,
      subject_id: subject.id,
      value: text
    })
    // 用服务端归一化后的文本回填（"90.0" → "90"，去掉多余空格）
    saved[key] = res.value
    row.values[String(subject.id)] = res.value
    // 录入人数本地就能数出来，统计条要问后端（平均分改一格就变）
    refreshCounts()
    refreshStats()
  } catch (e) {
    // 失败就写回旧值：不写回的话框里留着用户敲的错值，看着像存上了。
    // 光写回不够 —— 不弹一句的话，格子默默弹回原样，用户只会以为是自己没敲进去
    ElMessage.error(errText(e, '保存失败'))
    row.values[String(subject.id)] = saved[key]
  } finally {
    inflight.delete(key)
  }
}

/** 录入人数是后端算的，本地只知道哪格非空，改完顺手更新一下顶上的计数 */
function refreshCounts() {
  if (!data.value) return
  const subjects = data.value.subjects || []
  let people = 0
  for (const row of data.value.rows || []) {
    if (subjects.some((s) => (row.values[String(s.id)] || '') !== '')) people += 1
  }
  data.value.student_count = people
}

async function handleAddSubject() {
  const name = newSubject.value.trim()
  if (!name) {
    ElMessage.warning('请填写科目名')
    return
  }
  subjectLoading.value = true
  try {
    await addGradeSubject(testId.value, name)
    newSubject.value = ''
    await load()
  } catch (e) {
    ElMessage.error(errText(e, '添加科目失败'))
  } finally {
    subjectLoading.value = false
  }
}

function openSetting(subject) {
  setting.id = subject.id
  setting.name = subject.name
  setting.mode = subject.mode || 'score'
  setting.full_score = subject.full_score || 100
  settingVisible.value = true
}

async function handleSaveSetting() {
  settingLoading.value = true
  try {
    await updateGradeSubject(testId.value, setting.id, {
      mode: setting.mode,
      full_score: setting.full_score
    })
    settingVisible.value = false
    ElMessage.success('已保存')
    await load() // 表头上的形态 / 满分标记跟着重取
  } catch (e) {
    // 「已有 38 条分数成绩，不能改成通过制」这类文案后端给得很具体，原样弹
    ElMessage.error(errText(e, '保存失败'))
  } finally {
    settingLoading.value = false
  }
}

async function handleRemoveSubject(subject) {
  const cells = (data.value?.rows || []).filter(
    (row) => (row.values[String(subject.id)] || '') !== ''
  ).length
  const tip = cells
    ? `「${subject.name}」已经有 ${cells} 条成绩，删除后不可恢复。确定删除吗？`
    : `确定删除「${subject.name}」这一科吗？`
  try {
    await ElMessageBox.confirm(tip, '删除科目', { type: 'warning' })
  } catch {
    return // 取消
  }
  try {
    await removeGradeSubject(testId.value, subject.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(errText(e, '删除科目失败'))
  }
}

defineExpose({ open })
</script>

<style scoped>
/* 水印的定位基准：弹窗正文、科目设置的小表单各盖一层 */
.gd-body,
.wm-host {
  position: relative;
}

.gd-body {
  min-height: 200px;
}

.gd-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 10px;
}

.gd-remark {
  color: var(--el-text-color-regular);
}

.gd-count {
  margin-left: auto;
}

.gd-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.gd-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.gd-head {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

/* 汇总行每格塞两行（平均 + 及格率），pre-line 才认 summary-method 里的 \n */
:deep(.el-table__footer .cell) {
  white-space: pre-line;
  line-height: 1.5;
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.gd-empty {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
