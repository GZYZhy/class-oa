<!--
  发起 / 编辑收集

  和投票出卷弹窗分开：收集有六种题型、每人份数、竞争名额，字段形状差别很大。
  有答卷或已经开始后，题目结构、份数、记名、开始提醒锁定（后端同样校验）；
  标题、描述、截止时间仍可改。
-->
<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑收集' : '发起收集'"
    width="780px"
    :close-on-click-modal="false"
  >
    <div class="cc-body">
      <el-form label-width="90px">
        <el-form-item label="标题" required>
          <el-input
            v-model="form.title"
            maxlength="200"
            show-word-limit
            placeholder="例如：入党推优材料收集"
          />
        </el-form-item>
        <el-form-item label="详细说明">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="写清背景、要求；支持 Markdown"
          />
          <div class="cc-tip">支持 Markdown：标题、列表、加粗、链接</div>
        </el-form-item>
        <el-form-item label="开始时间" required>
          <el-date-picker
            v-model="form.start_at"
            type="datetime"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DD HH:mm"
            placeholder="选过去的时间 = 立刻开始"
            style="width: 100%;"
            :disabled="!timeEdit.start_at"
          />
        </el-form-item>
        <el-form-item label="截止时间" required>
          <el-date-picker
            v-model="form.end_at"
            type="datetime"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DD HH:mm"
            placeholder="到点自动结束"
            style="width: 100%;"
            :disabled="!timeEdit.end_at"
          />
        </el-form-item>
        <div v-if="isEdit && !timeEdit.start_at" class="cc-tip cc-tip-block">
          已经开始，开始时间改不了了；截止时间还能调
        </div>
        <el-form-item label="是否记名">
          <el-switch
            v-model="form.anonymous"
            active-text="不记名"
            inactive-text="记名"
            :disabled="structuralLocked"
          />
          <div class="cc-tip">
            {{ form.anonymous
              ? '不记名：管理端看答卷时不显示姓名/学号，但仍能看出谁还没填'
              : '记名：管理端能看到每份答卷是谁交的' }}
          </div>
        </el-form-item>
        <el-form-item label="开始提醒">
          <el-switch
            v-model="form.notify_on_start"
            active-text="提醒"
            inactive-text="不提醒"
            :disabled="notifyLocked"
          />
          <div class="cc-tip">
            开启后到「开始时间」才发一次提醒；改了开始时间，提醒跟着新时间走
          </div>
          <div v-if="notifyLocked" class="cc-tip">已经开始或已经发过提醒，改不了了</div>
        </el-form-item>
        <el-form-item label="允许撤回">
          <el-switch
            v-model="form.allow_withdraw"
            active-text="允许"
            inactive-text="不允许"
            :disabled="isEdit && editingStatus === 'closed'"
          />
          <div class="cc-tip">
            允许答题人在进行中撤回自己的答卷；撤回后会释放竞争名额，也可以重新填写。
            收集结束后答卷定稿，这个开关不再生效
          </div>
        </el-form-item>
        <el-form-item label="每人份数">
          <el-input-number
            v-model="form.submit_quota"
            :min="1"
            :max="50"
            :disabled="structuralLocked"
          />
          <span class="cc-inline-tip">每人最多可填几份</span>
        </el-form-item>
        <el-form-item label="竞争填写">
          <el-switch
            v-model="competition"
            active-text="限收"
            inactive-text="不限"
            :disabled="structuralLocked"
            @change="onCompetitionChange"
          />
          <template v-if="competition">
            <span class="cc-inline-tip">只收前</span>
            <el-input-number
              v-model="form.max_responses"
              :min="Math.max(1, form.submit_quota)"
              :max="9999"
              :disabled="structuralLocked"
            />
            <span class="cc-inline-tip">份；删除答卷会释放名额</span>
          </template>
        </el-form-item>
      </el-form>

      <h4 class="cc-h">
        可填写范围
        <span v-if="isEdit" class="cc-count">共 {{ editTargetCount }} 人 · 不能改</span>
        <span v-else class="cc-count">已选 {{ form.targets.length }} / 共 {{ roster.length }} 人</span>
      </h4>
      <template v-if="!isEdit">
        <div class="cc-scope-btns">
          <el-button size="small" @click="selectAll">全班</el-button>
          <el-button size="small" @click="selectCommittee">仅班委</el-button>
          <el-button size="small" @click="selectLeague">仅团员</el-button>
          <el-button size="small" @click="form.targets = []">全不选</el-button>
        </div>
        <div v-loading="rosterLoading" class="cc-roster">
          <el-checkbox-group v-model="form.targets">
            <el-checkbox
              v-for="student in roster"
              :key="student.student_no"
              :value="student.student_no"
              class="cc-roster-item"
            >
              {{ student.name }}
              <span class="cc-no">{{ student.student_no }}</span>
              <el-tag v-if="student.committee" size="small" type="warning" effect="plain">班委</el-tag>
            </el-checkbox>
          </el-checkbox-group>
        </div>
      </template>

      <h4 class="cc-h">
        题目
        <span class="cc-count">{{ form.questions.length }} 道</span>
      </h4>
      <div v-for="(question, index) in form.questions" :key="index" class="cc-q">
        <div class="cc-q-head">
          <span class="cc-q-index">第 {{ index + 1 }} 题</span>
          <el-input
            v-model="question.title"
            maxlength="500"
            placeholder="题干"
            :disabled="structuralLocked"
            class="cc-q-title"
          />
          <el-select
            v-model="question.qtype"
            style="width: 140px;"
            :disabled="structuralLocked"
            @change="onTypeChange(question)"
          >
            <el-option
              v-for="type in QUESTION_TYPES"
              :key="type.value"
              :label="type.label"
              :value="type.value"
            />
          </el-select>
          <el-checkbox v-model="question.required" :disabled="structuralLocked">
            必答
          </el-checkbox>
          <el-button
            link
            type="danger"
            :disabled="structuralLocked || form.questions.length <= 1"
            @click="form.questions.splice(index, 1)"
          >
            删除
          </el-button>
        </div>

        <template v-if="CHOICE_TYPES.has(question.qtype)">
          <div v-for="(option, oi) in question.options" :key="oi" class="cc-opt">
            <span class="cc-letter">{{ letters[oi] }}.</span>
            <el-input
              v-model="question.options[oi]"
              placeholder="选项内容"
              :disabled="structuralLocked"
            />
            <el-button
              link
              type="danger"
              :disabled="structuralLocked || question.options.length <= 2"
              @click="question.options.splice(oi, 1)"
            >
              删除
            </el-button>
          </div>
          <div class="cc-opt-actions">
            <el-button
              size="small"
              :disabled="structuralLocked || question.options.length >= 20"
              @click="question.options.push('')"
            >
              添加选项
            </el-button>
            <template v-if="question.qtype === 'multiple'">
              <span class="cc-inline-tip">最多选</span>
              <el-input-number
                v-model="question.max_choices"
                :min="2"
                :max="Math.max(2, question.options.length)"
                size="small"
                :disabled="structuralLocked"
              />
              <span class="cc-inline-tip">项</span>
            </template>
          </div>
        </template>
        <div v-else class="cc-tip">{{ typeHint(question.qtype) }}</div>
      </div>
      <el-button
        :disabled="structuralLocked || form.questions.length >= 30"
        @click="form.questions.push(blankQuestion())"
      >
        添加题目
      </el-button>

      <div v-if="structuralLocked" class="cc-tip cc-tip-block">
        已经开始或有答卷后，题目、份数、记名方式和开始提醒改不了了；标题、描述和截止时间仍可改
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">
        {{ isEdit ? '保存修改' : '发起收集' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createCollection, getCollection, updateCollection } from '@/api/collection'
import { getRoster } from '@/api/vote'
import { canEditTimes, POLL_LETTERS as letters } from '@/utils/poll'
import {
  CHOICE_TYPES,
  QUESTION_TYPES,
  blankForm,
  blankQuestion,
  formFromCollection
} from '@/utils/collection'
import { isLeagueMember } from '@/utils/roster'
import { errText } from '@/utils/request'

const emit = defineEmits(['saved'])

const visible = ref(false)
const submitting = ref(false)
const rosterLoading = ref(false)
const roster = ref([])

const editingId = ref(null)
const isEdit = computed(() => editingId.value !== null)
const editingStatus = ref('pending')
const editTargetCount = ref(0)
const editingNotified = ref(false)
const timeEdit = computed(() => canEditTimes(editingStatus.value))
/** 已经开始（或有答卷）：题目结构、份数、记名登录锁定 */
const structuralLocked = computed(() => isEdit.value && editingStatus.value !== 'pending')
const notifyLocked = computed(() => structuralLocked.value || editingNotified.value)

const form = reactive(blankForm())
const competition = ref(false)

function reset() {
  Object.assign(form, blankForm())
  competition.value = false
  editingId.value = null
  editingStatus.value = 'pending'
  editTargetCount.value = 0
  editingNotified.value = false
}

function open() {
  reset()
  visible.value = true
  fetchRoster()
}

async function openForEdit(row) {
  reset()
  try {
    const collection = await getCollection(row.id)
    Object.assign(form, blankForm(), formFromCollection(collection))
    editingId.value = collection.id
    editingStatus.value = collection.status || 'pending'
    editTargetCount.value = collection.target_count || 0
    editingNotified.value = !!collection.start_notified_at
    competition.value = !!collection.max_responses
    roster.value = []
    visible.value = true
  } catch (e) {
    ElMessage.error(errText(e, '读取收集失败'))
  }
}

async function fetchRoster() {
  rosterLoading.value = true
  try {
    const { items } = await getRoster()
    roster.value = items
    form.targets = items.map((student) => student.student_no)
  } catch (e) {
    ElMessage.error(errText(e, '读取名单失败'))
  } finally {
    rosterLoading.value = false
  }
}

function selectAll() {
  form.targets = roster.value.map((student) => student.student_no)
}
function selectCommittee() {
  form.targets = roster.value.filter((student) => student.committee).map((s) => s.student_no)
}
function selectLeague() {
  form.targets = roster.value.filter(isLeagueMember).map((s) => s.student_no)
}

/** 打开竞争填写时，总数至少得容得下每人份数 */
function onCompetitionChange(enabled) {
  if (enabled && form.max_responses < form.submit_quota) {
    form.max_responses = form.submit_quota
  }
}

function onTypeChange(question) {
  if (CHOICE_TYPES.has(question.qtype)) {
    if (!question.options?.length) question.options = ['', '']
    question.max_choices = Math.min(Math.max(question.max_choices || 2, 2), question.options.length)
  } else {
    question.options = []
    question.max_choices = 1
  }
}

function typeHint(qtype) {
  if (qtype === 'short_text') return '短文本：最多 200 字'
  if (qtype === 'long_text') return '长文本：最多 2000 字'
  if (qtype === 'image') return '图片：每题最多 3 张，单张 10MB，前端会自动压缩'
  if (qtype === 'rating') return '评分：1–5 分'
  return ''
}

function buildQuestions() {
  return form.questions.map((question) => {
    const choice = CHOICE_TYPES.has(question.qtype)
    return {
      title: question.title.trim(),
      qtype: question.qtype,
      required: question.required,
      options: choice ? question.options.map((option) => option.trim()) : [],
      max_choices:
        question.qtype === 'multiple'
          ? Math.min(question.max_choices || 2, question.options.length)
          : choice
            ? 1
            : null
    }
  })
}

function firstError() {
  if (!form.title.trim()) return '请填写标题'
  if (!form.start_at) return '请选择开始时间'
  if (!form.end_at) return '请选择截止时间'
  if (form.end_at <= form.start_at) return '截止时间必须晚于开始时间'
  if (!isEdit.value && !form.targets.length) return '至少要选一名可填写的同学'
  if (!form.questions.length) return '至少一道题'
  for (let i = 0; i < form.questions.length; i += 1) {
    const question = form.questions[i]
    if (!question.title.trim()) return `第 ${i + 1} 题还没写题干`
    if (CHOICE_TYPES.has(question.qtype)) {
      const options = question.options.map((option) => option.trim())
      if (options.length < 2) return `第 ${i + 1} 题至少要有两个选项`
      if (options.some((option) => !option)) return `第 ${i + 1} 题有空白选项`
      if (new Set(options).size !== options.length) return `第 ${i + 1} 题有重复的选项`
      if (question.qtype === 'multiple' && (question.max_choices || 0) > options.length) {
        return `第 ${i + 1} 题的「最多选几项」不能超过选项数`
      }
    }
  }
  if (form.submit_quota < 1) return '每人份数至少 1'
  if (competition.value && form.max_responses < form.submit_quota) {
    return '竞争总份数不能小于每人可填份数'
  }
  return ''
}

async function handleSubmit() {
  const problem = firstError()
  if (problem) return ElMessage.warning(problem)

  submitting.value = true
  try {
    const questions = buildQuestions()
    const maxResponses = competition.value ? form.max_responses : 0
    if (isEdit.value) {
      const payload = {
        title: form.title.trim(),
        description: form.description.trim()
      }
      if (timeEdit.value.start_at) payload.start_at = form.start_at
      if (timeEdit.value.end_at) payload.end_at = form.end_at
      if (!structuralLocked.value) {
        payload.anonymous = form.anonymous
        payload.submit_quota = form.submit_quota
        payload.max_responses = maxResponses
        payload.questions = questions
      }
      if (!notifyLocked.value) payload.notify_on_start = form.notify_on_start
      payload.allow_withdraw = form.allow_withdraw
      await updateCollection(editingId.value, payload)
      ElMessage.success('已保存')
    } else {
      await createCollection({
        title: form.title.trim(),
        description: form.description.trim(),
        anonymous: form.anonymous,
        allow_withdraw: form.allow_withdraw,
        start_at: form.start_at,
        end_at: form.end_at,
        notify_on_start: form.notify_on_start,
        submit_quota: form.submit_quota,
        max_responses: maxResponses,
        targets: [...form.targets],
        questions
      })
      ElMessage.success(
        form.notify_on_start ? '已发起，开始时将提醒范围内的同学' : '已发起'
      )
    }
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(errText(e, isEdit.value ? '保存失败' : '发起失败'))
  } finally {
    submitting.value = false
  }
}

defineExpose({ open, openForEdit })
</script>

<style scoped>
.cc-body {
  max-height: 68vh;
  overflow-y: auto;
  padding-right: 6px;
}

.cc-h {
  margin: 22px 0 10px;
  font-size: 15px;
  color: var(--el-text-color-primary);
}

.cc-count {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.cc-tip {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.cc-tip-block {
  margin-top: 12px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
}

.cc-inline-tip {
  margin: 0 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cc-scope-btns {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.cc-roster {
  max-height: 180px;
  overflow-y: auto;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.cc-roster :deep(.el-checkbox-group) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.cc-roster-item {
  margin-right: 0;
}

.cc-no {
  margin: 0 6px 0 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cc-q {
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.cc-q-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cc-q-index {
  flex: none;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}

.cc-q-title {
  flex: 1;
  min-width: 180px;
}

.cc-opt {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.cc-letter {
  display: inline-block;
  min-width: 1.5em;
  flex: none;
}

.cc-opt-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
</style>
