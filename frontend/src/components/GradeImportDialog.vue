<template>
  <!-- 上传成绩：传 Excel → 确认识别结果 → 结果 -->
  <el-dialog append-to-body
    v-model="visible"
    title="上传成绩"
    width="820px"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <div class="wm-host">
      <Watermark :text="watermarkText" />

      <!-- 第一步：传 Excel -->
      <div v-if="step === 1" class="gi-step">
      <el-upload
        ref="uploadRef"
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx"
        :on-exceed="handleExceed"
        :on-change="handleFileChange"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">把 Excel 拖到这里，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">
            第一行要有 <code>学号</code> 列，可选 <code>姓名</code> 列，其余每一列都当一科成绩。<br />
            学号列请设成<strong>文本格式</strong>，否则 Excel 会把开头的 0 吃掉；
            一格成绩填 0~1000 的数字，或 {{ (preview?.mark_values || []).join(' / ') || '缺考 / 免修 / 缓考 / 违纪' }}；
            只记通过 / 不通过的科目在下一步选「通过制」。
          </div>
        </template>
      </el-upload>
    </div>

    <!-- 第二步：确认识别结果 -->
    <div v-else-if="step === 2" class="gi-step">
      <el-alert type="info" :closable="false" show-icon class="gi-alert">
        <template #title>
          工作表「{{ preview.sheet_name }}」：找到 {{ preview.matched_count }} 名学生，
          识别出 {{ preview.columns.length }} 列
        </template>
      </el-alert>

      <el-form label-width="88px" class="gi-form">
        <el-form-item label="科目列">
          <!-- 每列一行：勾选 + 这科记分数还是记通过/不通过 + 满分。
               不用 el-checkbox-group 是因为形态下拉得跟勾选框排在同一行，
               塞进 checkbox 的 label 里点一下就顺手把勾给取消了 -->
          <div class="gi-subjects">
            <div v-for="c in preview.columns" :key="c.name" class="gi-subject-row">
              <el-checkbox
                :model-value="keptSubjects.includes(c.name)"
                @update:model-value="(v) => toggleSubject(c.name, v)"
              />
              <span class="gi-subject-name" :class="{ 'is-off': !keptSubjects.includes(c.name) }">
                {{ c.name }}
              </span>
              <el-select
                v-model="subjectModes[c.name]"
                size="small"
                style="width: 92px"
                :disabled="!keptSubjects.includes(c.name)"
              >
                <el-option label="计分" value="score" />
                <el-option label="通过制" value="pass_fail" />
              </el-select>
              <el-input-number
                v-if="subjectModes[c.name] !== 'pass_fail'"
                v-model="subjectFullScores[c.name]"
                size="small"
                :min="1"
                :max="1000"
                :controls="false"
                style="width: 76px"
                :disabled="!keptSubjects.includes(c.name)"
              />
              <span v-else class="gi-pass-tag">只记 通过 / 不通过</span>
              <span v-if="c.sample?.length" class="gi-sample">（如 {{ c.sample.join('、') }}）</span>
            </div>
          </div>
          <div class="gi-hint">
            不勾的列不会录进来（「序号」「总分」这类列已经默认不勾，勾回来可改）。
            满分决定及格线（满分的 60%）和分数段的划分，150 分制就填 150
          </div>
        </el-form-item>

        <el-form-item label="测试名称">
          <el-input v-model="form.name" maxlength="100" placeholder="如：高等数学期中考" />
        </el-form-item>
        <el-form-item label="测试日期">
          <el-date-picker
            v-model="form.tested_at"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            style="width: 180px"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="2000" placeholder="选填" />
        </el-form-item>
        <el-form-item label="通知">
          <el-checkbox v-model="form.notify">
            录入后给有成绩的学生发站内信和推送
          </el-checkbox>
        </el-form-item>
      </el-form>

      <el-table v-if="issues.length" :data="issues" size="small" border max-height="240">
        <el-table-column label="行号" width="70" prop="row" />
        <el-table-column label="判定" width="110">
          <template #default="{ row }">
            <el-tag :type="ISSUE_TAGS[row.status]" size="small" effect="plain">
              {{ ISSUE_LABELS[row.status] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="student_no" label="学号" width="130" />
        <el-table-column prop="detail" label="说明" min-width="260" show-overflow-tooltip />
      </el-table>

      <div v-if="preview.sample_rows?.length" class="gi-block">
        <div class="gi-block-title">读到的前几行（原样回显，确认列对不对）</div>
        <el-table :key="preview.columns.map((c) => c.name).join('|')" :data="preview.sample_rows"
                  size="small" border max-height="200">
          <el-table-column prop="学号" label="学号" width="120" />
          <el-table-column prop="姓名" label="姓名" width="100" />
          <el-table-column v-for="c in preview.columns" :key="c.name" :prop="c.name"
                           :label="c.name" min-width="90" />
        </el-table>
      </div>

      <el-alert v-for="(w, i) in preview.warnings" :key="i" type="warning" :closable="false"
                show-icon :title="w" class="gi-alert" />
    </div>

    <!-- 第三步：结果 -->
    <div v-else class="gi-step">
      <el-result icon="success" title="录入完成" :sub-title="result.message">
        <template #extra>
          <div class="gi-stats">
            <div><b>{{ result.student_count }}</b><span>录入人数</span></div>
            <div><b>{{ result.subject_count }}</b><span>科目</span></div>
            <div><b>{{ result.cell_count }}</b><span>成绩条数</span></div>
            <div><b>{{ result.skipped }}</b><span>跳过的行</span></div>
          </div>
        </template>
      </el-result>

      <el-alert v-for="(w, i) in result.warnings" :key="i" type="warning" :closable="false"
                show-icon :title="w" class="gi-alert" />
      <el-alert v-if="issues.length" type="info" :closable="false" show-icon
                title="这些行没有录入，回 Excel 改好可以再传一次补录" class="gi-alert">
        <ul class="gi-list">
          <li v-for="i in issues" :key="`${i.row}-${i.detail}`">
            第 {{ i.row }} 行：{{ i.detail }}
          </li>
        </ul>
      </el-alert>
    </div>
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
        <el-button type="primary" :loading="confirmLoading" @click="doImport">确认录入</el-button>
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
import { gradeImportConfirm, gradeImportPreview } from '@/api/grade'
import { errText } from '@/utils/request'
import Watermark from '@/components/Watermark.vue'
import { useWatermark } from '@/composables/useWatermark'

const emit = defineEmits(['done'])

const watermarkText = useWatermark()
const visible = ref(false)
const step = ref(1) // 1=上传 2=确认 3=结果
const file = ref(null)
const uploadRef = ref(null)
const previewLoading = ref(false)
const confirmLoading = ref(false)
const preview = ref(null)
const result = ref(null)
// 保留哪些科目列：预览回来后按后端的默认预判填上
const keptSubjects = ref([])
// 科目名 → 形态 / 满分。用 reactive 对象而不是数组：模板里按列名直接取，
// 不用为每一列去找下标
const subjectModes = reactive({})
const subjectFullScores = reactive({})
const form = reactive({ name: '', tested_at: '', remark: '', notify: true })

function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function open() {
  reset()
  visible.value = true
}

function reset() {
  step.value = 1
  file.value = null
  preview.value = null
  result.value = null
  keptSubjects.value = []
  for (const key of Object.keys(subjectModes)) delete subjectModes[key]
  for (const key of Object.keys(subjectFullScores)) delete subjectFullScores[key]
  form.name = ''
  form.tested_at = today() // 多数情况下就是今天考完当场录
  form.remark = ''
  form.notify = true
  previewLoading.value = false
  confirmLoading.value = false
  if (uploadRef.value) uploadRef.value.clearFiles()
}

function handleFileChange(f) {
  file.value = f.raw || f
}

function handleExceed() {
  ElMessage.warning('只能上传一个文件')
}

// 手动维护 keptSubjects：模板里没有用 el-checkbox-group（理由见模板注释）
function toggleSubject(name, checked) {
  if (checked && !keptSubjects.value.includes(name)) {
    keptSubjects.value = [...keptSubjects.value, name]
  } else if (!checked) {
    keptSubjects.value = keptSubjects.value.filter((n) => n !== name)
  }
}

async function doPreview() {
  if (!file.value) {
    ElMessage.warning('请先选择 Excel 文件')
    return
  }
  previewLoading.value = true
  try {
    preview.value = await gradeImportPreview(file.value)
    keptSubjects.value = preview.value.columns.filter((c) => c.keep_default).map((c) => c.name)
    for (const c of preview.value.columns) {
      // 后端扫过这一列的取值：全是「通过 / 不通过」就预选通过制，班委可改回来
      subjectModes[c.name] = c.suggest_pass_fail ? 'pass_fail' : 'score'
      subjectFullScores[c.name] = 100
    }
    step.value = 2
  } catch (e) {
    // 缺「学号」列、没有可用的工作表这类 400 文案由后端给，原样弹出来
    ElMessage.error(errText(e, '读取表格失败'))
  } finally {
    previewLoading.value = false
  }
}

async function doImport() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写测试名称')
    return
  }
  if (!form.tested_at) {
    ElMessage.warning('请选择测试日期')
    return
  }
  if (!keptSubjects.value.length) {
    ElMessage.warning('至少要保留一个科目')
    return
  }
  confirmLoading.value = true
  try {
    // 按预览里的列序传，勾选顺序不影响最终列序
    const subjects = preview.value.columns
      .map((c) => c.name).filter((n) => keptSubjects.value.includes(n))
    result.value = await gradeImportConfirm({
      token: preview.value.token,
      name: form.name.trim(),
      tested_at: form.tested_at,
      remark: form.remark,
      subjects,
      subject_modes: Object.fromEntries(subjects.map((n) => [n, subjectModes[n] || 'score'])),
      subject_full_scores: Object.fromEntries(subjects.map((n) => [n, subjectFullScores[n] || 100])),
      notify: form.notify
    })
    step.value = 3
    emit('done')
  } catch (e) {
    // 预览过期（超过 10 分钟）也走这里，后端会说清楚
    ElMessage.error(errText(e, '录入失败'))
  } finally {
    confirmLoading.value = false
  }
}

// 需要注意的行。**只列有问题的行**，几百行全列出来班委也看不过来；
// 「有问题」的定义见下表，其中姓名对不上只是提示（照常入库）
const ISSUE_LABELS = {
  problem: '格子填错',
  unmatched: '学号对不上',
  duplicate: '表内重复',
  mismatch: '姓名对不上'
}
const ISSUE_TAGS = {
  problem: 'danger',
  unmatched: 'danger',
  duplicate: 'warning',
  mismatch: 'warning'
}
// 排在前面的更需要处理：填错的格子会被丢掉，学号对不上整行不入库
const ISSUE_ORDER = { problem: 0, unmatched: 1, duplicate: 2, mismatch: 3 }

const issues = computed(() => {
  const p = preview.value
  if (!p) return []
  const list = []
  for (const r of p.problems || []) {
    list.push({ row: r.row, student_no: r.student_no, status: 'problem',
      detail: `「${r.column}」填的是「${r.raw}」，${r.reason}` })
  }
  for (const r of p.unmatched || []) {
    list.push({ row: r.row, student_no: r.student_no, status: 'unmatched',
      detail: `${r.student_name || '这一行'}：${r.reason}，整行不会录入` })
  }
  for (const r of p.duplicates || []) {
    list.push({ row: r.row, student_no: r.student_no, status: 'duplicate',
      detail: '同一个学号在上面已经出现过，这一行不会录入' })
  }
  for (const r of p.name_mismatch || []) {
    list.push({ row: r.row, student_no: r.student_no, status: 'mismatch',
      detail: `表里写的是「${r.excel_name}」，名单上是「${r.db_name}」，按名单上的算` })
  }
  return list.sort((a, b) =>
    (ISSUE_ORDER[a.status] - ISSUE_ORDER[b.status]) || (a.row - b.row))
})

defineExpose({ open })
</script>

<style scoped>
/* 水印的定位基准 */
.wm-host {
  position: relative;
}

.gi-step {
  min-height: 200px;
}

.gi-alert {
  margin-top: 10px;
}

.gi-form {
  margin-top: 14px;
}

.gi-subjects {
  /* 每列一行，勾掉的列不参与填写、但位置留着，方便回头勾回来 */
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  max-height: 220px;
  overflow-y: auto;
}

.gi-subject-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.gi-subject-name {
  min-width: 72px;
  font-size: 13px;
}

.gi-subject-name.is-off {
  color: var(--el-text-color-disabled);
}

.gi-pass-tag {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.gi-sample {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.gi-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.gi-block {
  margin-top: 14px;
}

.gi-block-title {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}

.gi-stats {
  display: flex;
  justify-content: center;
  gap: 32px;
}

.gi-stats b {
  display: block;
  font-size: 22px;
}

.gi-stats span {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.gi-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}
</style>
