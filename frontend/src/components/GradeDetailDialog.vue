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
        <span class="gd-hint">
          格子填 0~{{ 1000 }} 的数字、<b>留空表示清空</b>，或
          {{ (data?.mark_values || []).join(' / ') }}
        </span>
      </div>

      <el-table
        :key="tableKey"
        :data="data?.rows || []"
        size="small"
        border
        max-height="56vh"
        row-key="student_no"
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
          width="130"
        >
          <template #header>
            <span class="gd-head">
              <span>{{ s.name }}</span>
              <el-button link type="danger" size="small" @click="handleRemoveSubject(s)">删除</el-button>
            </span>
          </template>
          <template #default="{ row }">
            <el-input
              v-model="row.values[String(s.id)]"
              size="small"
              :placeholder="'—'"
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
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addGradeSubject,
  getGradeDetail,
  putGradeScore,
  removeGradeSubject
} from '@/api/grade'
import { formatDate } from '@/utils/format'
import { errText } from '@/utils/request'

const emit = defineEmits(['done'])

const visible = ref(false)
const loading = ref(false)
const subjectLoading = ref(false)
const data = ref(null)
const testId = ref(null)
const newSubject = ref('')
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
  } catch (e) {
    // 拉到一半失败会把空表留在弹窗里，看着像「这场没录过成绩」，得说清楚
    ElMessage.error(errText(e, '读取明细失败'))
  } finally {
    loading.value = false
  }
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
    refreshCounts()
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
  gap: 6px;
}

.gd-empty {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
