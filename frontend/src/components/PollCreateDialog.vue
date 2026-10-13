<template>
  <!-- 出卷：基本信息 → 有权表决的人 → 题目，一次定完。
       也当编辑弹窗用（父组件调 openForEdit）—— 那时候标题和描述随时能改，
       **题目只在还没开始时能改**，**时间按状态分档**（见 utils/poll.js 的
       canEditTimes：没开始的两个都能改、开始了只能改截止时间），表决范围只读 -->
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑投票' : '发起投票'"
    width="720px"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <div class="pc-body">
      <!-- ---------- 一、基本信息 ---------- -->
      <h4 class="pc-h">一、基本信息</h4>
      <el-form label-width="88px">
        <el-form-item label="标题" required>
          <el-input
            v-model="form.title"
            maxlength="200"
            show-word-limit
            placeholder="例如：关于班服款式的表决"
          />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            maxlength="2000"
            placeholder="选填。写清背景或注意事项"
          />
        </el-form-item>
        <el-form-item label="开始时间" required>
          <el-date-picker
            v-model="form.start_at"
            type="datetime"
            placeholder="选过去的时间 = 立刻开始"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DD HH:mm"
            style="width: 100%;"
            :disabled="!timeEdit.start_at"
          />
        </el-form-item>
        <el-form-item label="截止时间" required>
          <el-date-picker
            v-model="form.end_at"
            type="datetime"
            placeholder="到点自动结束，不用守着"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DD HH:mm"
            style="width: 100%;"
            :disabled="!timeEdit.end_at"
          />
        </el-form-item>
        <!-- 灰掉的框要说清为什么灰，不然看着像坏了。能改的时候不占地方 -->
        <div v-if="!timeEdit.start_at" class="pc-tip">
          投票已经开始，开始时间改不了了（它已经过去）。截止时间还能调
        </div>
        <div v-if="!timeEdit.end_at" class="pc-tip">
          投票已经结束，时间改不了了
        </div>
        <el-form-item label="是否记名">
          <el-switch
            v-model="form.anonymous"
            active-text="不记名"
            inactive-text="记名"
            :disabled="startedLocked"
            @change="onAnonymousChange"
          />
          <div class="pc-tip">
            {{ form.anonymous
              ? '不记名：发起人也查不到谁选了什么。界面上会明确标出「不记名」'
              : '记名：默认不额外标注，需要时发起人可以查每个人选了什么' }}
          </div>
          <!-- 灰掉的开关要说清为什么灰，跟上面两个时间框一个道理 -->
          <div v-if="startedLocked" class="pc-tip">投票已经开始，记名方式改不了了</div>
        </el-form-item>
      </el-form>

      <!-- ---------- 二、有权表决的人 ---------- -->
      <h4 class="pc-h">
        二、有权表决的人
        <span v-if="isEdit" class="pc-count">共 {{ editTargetCount }} 人 · 不能改</span>
        <span v-else class="pc-count">已选 {{ form.targets.length }} / 共 {{ roster.length }} 人</span>
      </h4>
      <!-- 编辑时整块名单都不渲染：范围改不了（把已经投过的人挪出去，他那张票就算不清了），
           上面 h4 里的「共 N 人 · 不能改」就是全部信息 -->
      <template v-if="!isEdit">
        <div class="pc-scope-btns">
          <el-button size="small" @click="selectAll">全选</el-button>
          <el-button size="small" @click="form.targets = []">全不选</el-button>
          <el-button size="small" @click="selectCommittee">仅班委</el-button>
          <el-button size="small" @click="selectLeague">仅团员</el-button>
        </div>
        <!-- 发起人常常默认自己在里面，一旦勾掉自己得能看出来，否则会以为自己也能投 -->
        <div v-if="iAmOutOfScope" class="pc-tip pc-warn">
          你自己不在这次投票的表决范围内（只出卷、不投票）
        </div>
        <div v-loading="rosterLoading" class="pc-roster">
          <el-checkbox-group v-model="form.targets">
            <el-checkbox v-for="s in roster" :key="s.student_no" :value="s.student_no">
              {{ s.name }}<span class="pc-no">{{ s.student_no }}</span>
            </el-checkbox>
          </el-checkbox-group>
          <p v-if="!rosterLoading && !roster.length" class="pc-empty">没有可表决的同学</p>
        </div>
      </template>

      <!-- ---------- 三、题目 ---------- -->
      <h4 class="pc-h">
        三、题目
        <span class="pc-count">共 {{ form.questions.length }} 题</span>
        <span v-if="startedLocked" class="pc-count">已开始，题目不能改了</span>
      </h4>
      <div v-if="startedLocked" class="pc-tip">
        投票已经开始，题目就锁住了：作答存的是选项的序号，这时候删掉一个选项，
        已经投过的人那张票就对不上了。标题和描述还能改
      </div>
      <div v-for="(q, i) in form.questions" :key="i" class="pc-q">
        <div class="pc-q-head">
          <span class="pc-q-no">第 {{ i + 1 }} 题</span>
          <el-radio-group
            v-model="q.multiple"
            size="small"
            :disabled="startedLocked"
            @change="onMultipleChange(q)"
          >
            <el-radio-button :value="false">单选</el-radio-button>
            <el-radio-button :value="true">多选</el-radio-button>
          </el-radio-group>
          <span v-if="q.multiple" class="pc-max">
            最多选
            <el-input-number
              v-model="q.max_choices"
              :min="2"
              :max="q.options.length"
              size="small"
              controls-position="right"
              style="width: 92px;"
              :disabled="startedLocked"
            />
            项
          </span>
          <el-button
            class="pc-q-del"
            link
            type="danger"
            :disabled="startedLocked || form.questions.length <= 1"
            @click="removeQuestion(i)"
          >删除本题</el-button>
        </div>

        <el-input
          v-model="q.title"
          maxlength="500"
          placeholder="题干，例如：你赞成哪一款班服？"
          class="pc-q-title"
          :disabled="startedLocked"
        />

        <div v-for="(opt, j) in q.options" :key="j" class="pc-opt">
          <span class="pc-opt-label">{{ letters[j] }}</span>
          <el-input
            v-model="q.options[j]"
            maxlength="200"
            :placeholder="`选项 ${j + 1}`"
            :disabled="startedLocked"
          />
          <el-button
            link
            type="danger"
            :disabled="startedLocked || q.options.length <= 2"
            @click="removeOption(q, j)"
          >删除</el-button>
        </div>

        <el-button
          size="small"
          :disabled="startedLocked || q.options.length >= 20"
          @click="q.options.push('')"
        >
          添加选项
        </el-button>
        <span class="pc-tip pc-tip-inline">
          选项最多 20 个。要「弃权」就单独列成一个选项 —— 每题都必须作答
        </span>
      </div>

      <el-button
        :disabled="startedLocked || form.questions.length >= 30"
        @click="addQuestion"
      >
        添加题目（最多 30 题）
      </el-button>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">
        {{ isEdit ? '保存修改' : '发起投票' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createPoll, getRoster, updatePoll } from '@/api/vote'
import { errText } from '@/utils/request'
import {
  POLL_LETTERS,
  blankForm,
  blankQuestion,
  canEditBeforeStart,
  canEditTimes,
  formFromPoll,
} from '@/utils/poll'
// 「仅团员」的判据与点名、分类统计共用一份，见 utils/roster.js
import { isLeagueMember } from '@/utils/roster'
import { useUserStore } from '@/store/user'

// 出卷和编辑都发这个：父组件一律重拉列表，不用分两种情况
const emit = defineEmits(['saved'])
const userStore = useUserStore()

const visible = ref(false)
const submitting = ref(false)
const rosterLoading = ref(false)
const roster = ref([])

/** 正在编辑的投票 ID；null = 出卷（新建）。标题、按钮文案、只读与否都看它 */
const editingId = ref(null)
const isEdit = computed(() => editingId.value !== null)
/** 编辑中的那场处于什么状态。时间、题目、记名改不改得了都看它，出卷时是 pending */
const editingStatus = ref('pending')
/** 两个时间各能不能改（分档规则见 utils/poll.js 的 canEditTimes，后端按同一套判） */
const timeEdit = computed(() => canEditTimes(editingStatus.value))
/**
 * 已经开始了 → 「只有没开始才能改」的那几样一起锁上：**题目和记名与否**
 *
 * 两样的理由是同一条：都会「换一张票」。题目换了下标错位，记名方式换了则等于把
 * 已经投出去的票重新定义一遍。没开始时库里不可能有作答（can_vote 要求状态是 open），
 * 所以那时改怎么都安全 —— 出卷时状态恒为 pending，这个锁自然是开的。
 */
const startedLocked = computed(() => !canEditBeforeStart(editingStatus.value))
/** 编辑时只显示表决范围的人数：名单不拉（范围本来就改不了），人数从详情里带过来 */
const editTargetCount = ref(0)

/** 选项前面的序号，和表决、结果里显示的是同一套 */
const letters = POLL_LETTERS

// blankForm / blankQuestion / formFromPoll 都在 utils/poll.js：SSR 下 el-input 不输出
// value，表单填回来没有只能靠真跑那段映射来验，所以它得是可单独 import 的纯函数
const form = reactive(blankForm())

/** 勾选里没有我 → 提示一句。发起人默认全选时通常在里面，但改范围时容易把自己漏掉 */
const iAmOutOfScope = computed(() => {
  const myNo = userStore.info?.student_no
  return !!myNo && form.targets.length > 0 && !form.targets.includes(myNo)
})

function open() {
  Object.assign(form, blankForm())
  editingId.value = null
  editingStatus.value = 'pending'
  visible.value = true
  fetchRoster()
}

/**
 * 打开编辑。参数是 GET /api/polls/{id} 的详情 —— 列表行里没有题目
 *
 * 编辑时**不拉表决名单**：范围本来就改不了，名单区整个不显示，省一次请求。
 */
function openForEdit(poll) {
  Object.assign(form, blankForm(), formFromPoll(poll))
  editingId.value = poll.id
  editingStatus.value = poll.status || 'pending'
  editTargetCount.value = poll.target_count || 0
  roster.value = []
  visible.value = true
}

function reset() {
  Object.assign(form, blankForm())
  roster.value = []
  editingId.value = null
  editingStatus.value = 'pending'
  editTargetCount.value = 0
}

async function fetchRoster() {
  rosterLoading.value = true
  try {
    const { items } = await getRoster()
    roster.value = items
    form.targets = items.map((s) => s.student_no) // 默认全选
  } catch (e) {
    roster.value = []
    form.targets = []
    ElMessage.error(errText(e, '读取学生名单失败'))
  } finally {
    rosterLoading.value = false
  }
}

function selectAll() {
  form.targets = roster.value.map((s) => s.student_no)
}

function selectCommittee() {
  form.targets = roster.value.filter((s) => s.committee).map((s) => s.student_no)
}

function selectLeague() {
  form.targets = roster.value.filter(isLeagueMember).map((s) => s.student_no)
}

function addQuestion() {
  if (form.questions.length >= 30) return
  form.questions.push(blankQuestion())
}

function removeQuestion(index) {
  if (form.questions.length <= 1) return // 至少留一题
  form.questions.splice(index, 1)
}

function removeOption(q, index) {
  if (q.options.length <= 2) return // 至少留两个选项
  q.options.splice(index, 1)
  // 少了一个选项，「最多选几项」可能就超了：这里先夹回合法区间，
  // 让界面上的数字始终是能提交的（后端的校验不夹紧，只会拒）
  if (q.max_choices > q.options.length) q.max_choices = q.options.length
  if (q.lastMax > q.options.length) q.lastMax = q.options.length
}

function onMultipleChange(q) {
  if (q.multiple) {
    q.max_choices = Math.min(Math.max(q.lastMax || 2, 2), q.options.length)
  } else {
    if (q.max_choices > 1) q.lastMax = q.max_choices
    q.max_choices = 1
  }
}

function onAnonymousChange(value) {
  // 改成不记名是要紧事，给一次确认 —— 发出去之后改不了：编辑接口只管标题、描述、
  // 时间和题目，记名与否不在可编辑之列（改了等于换了一种票）
  if (value) ElMessage.info('已设为不记名：发起人也查不到谁选了什么')
}

/** 提交前的校验。**后端才是唯一的闸**，这里只是让用户早点看到问题
 *
 * 一条条收集、只报第一条：表单是动态增删的，用 el-form 的深层 prop（questions.0.options.1）
 * 在这种结构下极脆，项目里也没这个先例，所以照 LeaveApply.vue 的办法手写。
 */
function firstError() {
  if (!form.title.trim()) return '请填写标题'

  // 时间：出卷时必填，编辑时看这场还能不能改。拿 end_at 当开关 —— 它俩是一起松一起
  // 紧的（只有「已结束」两个才全灰），所以「截止时间改得动」就等于这段时间得校验
  if (timeEdit.value.end_at) {
    if (!form.start_at) return '请选择开始时间'
    if (!form.end_at) return '请选择截止时间'

    const start = new Date(form.start_at.replace(' ', 'T'))
    const end = new Date(form.end_at.replace(' ', 'T'))
    if (!(end > start)) return '截止时间必须晚于开始时间'
    if (end.getTime() <= Date.now()) return '截止时间已经过了'
    if (end - start > 365 * 24 * 3600 * 1000) return '投票跨度不能超过一年'
  }

  // 表决范围只有出卷时才要选：编辑时那块是只读的，人数从详情里带过来
  if (!isEdit.value && !form.targets.length) return '至少要选一名有权表决的同学'

  // 题目锁着（已经开始的投票）就原样提交，没什么可校验的 —— 能锁住就说明当初校验过
  if (startedLocked.value) return ''
  return questionsError()
}

/** 题目那一段单独拎出来：编辑已经开始的投票时，这一整段要跳过 */
function questionsError() {
  for (let i = 0; i < form.questions.length; i++) {
    const q = form.questions[i]
    const no = i + 1
    if (!q.title.trim()) return `第 ${no} 题的题干不能为空`
    const options = q.options.map((o) => o.trim())
    if (options.some((o) => !o)) return `第 ${no} 题有空白选项`
    if (new Set(options).size !== options.length) return `第 ${no} 题有重复的选项`
    if (q.multiple && (q.max_choices < 2 || q.max_choices > options.length)) {
      return `第 ${no} 题「最多选几项」要在 2 到 ${options.length} 之间`
    }
  }
  return ''
}

/** 表单里的题目 → 提交用的题目 */
function buildQuestions() {
  return form.questions.map((q) => ({
    title: q.title.trim(),
    multiple: q.multiple,
    max_choices: q.multiple ? q.max_choices : 1,
    options: q.options.map((o) => o.trim())
  }))
}

async function handleSubmit() {
  const problem = firstError()
  if (problem) return ElMessage.warning(problem)

  submitting.value = true
  try {
    if (isEdit.value) {
      const payload = { title: form.title.trim(), description: form.description.trim() }
      // **题目锁着就一个字都不传**：后端只在收到 questions 时才替换题目，
      // 已经开始的那场带了会被 400（见 api/vote.js 的 updatePoll）
      if (!startedLocked.value) payload.questions = buildQuestions()
      // 时间同理：不能改的那个字段一个字都别带。原样回传也不会写坏什么（后端比对过
      // 值才落库），但灰着的框还往上传，读代码的人会以为它真的能改
      if (timeEdit.value.start_at) payload.start_at = form.start_at
      if (timeEdit.value.end_at) payload.end_at = form.end_at
      // 记名与否和题目同款：只有没开始才传得出去
      if (!startedLocked.value) payload.anonymous = form.anonymous
      await updatePoll(editingId.value, payload)
      ElMessage.success('已保存')
    } else {
      await createPoll({
        title: form.title.trim(),
        description: form.description.trim(),
        anonymous: form.anonymous,
        start_at: form.start_at,
        end_at: form.end_at,
        targets: [...form.targets],
        questions: buildQuestions()
      })
      ElMessage.success('已发起，范围内的同学会收到提醒')
    }
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(errText(e, isEdit.value ? '保存失败' : '发起失败'))
  } finally {
    submitting.value = false
  }
}

// 让父组件通过 ref 调用（出卷走 open，编辑走 openForEdit）
defineExpose({ open, openForEdit })
</script>

<style scoped>
/* 两层 v-for 加名单，弹窗会很长：限高滚动，别把整页撑破 */
.pc-body {
  max-height: 62vh;
  overflow-y: auto;
  padding-right: 6px;
}

.pc-h {
  margin: 18px 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.pc-body > .pc-h:first-child {
  margin-top: 0;
}

.pc-count {
  margin-left: 8px;
  font-weight: 400;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.pc-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.pc-warn {
  color: var(--el-color-warning);
}

.pc-tip-inline {
  margin-left: 10px;
}

.pc-scope-btns {
  margin-bottom: 8px;
}

.pc-roster {
  max-height: 190px;
  overflow-y: auto;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

.pc-no {
  margin-left: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.pc-empty {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.pc-q {
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

.pc-q-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.pc-q-no {
  font-size: 13px;
  font-weight: 600;
}

.pc-max {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

/* 靠右推开，和模态框的关闭按钮保持距离，免得误点 */
.pc-q-del {
  margin-left: auto;
}

.pc-q-title {
  margin-bottom: 8px;
}

.pc-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.pc-opt-label {
  width: 16px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  flex: none;
}
</style>
