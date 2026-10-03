<template>
  <!-- 出卷：基本信息 → 有权表决的人 → 题目，一次定完，发起后不可编辑 -->
  <el-dialog
    v-model="visible"
    title="发起投票"
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
          />
        </el-form-item>
        <el-form-item label="是否记名">
          <el-switch
            v-model="form.anonymous"
            active-text="不记名"
            inactive-text="记名"
            @change="onAnonymousChange"
          />
          <div class="pc-tip">
            {{ form.anonymous
              ? '不记名：发起人也查不到谁选了什么。界面上会明确标出「不记名」'
              : '记名：默认不额外标注，需要时发起人可以查每个人选了什么' }}
          </div>
        </el-form-item>
      </el-form>

      <!-- ---------- 二、有权表决的人 ---------- -->
      <h4 class="pc-h">
        二、有权表决的人
        <span class="pc-count">已选 {{ form.targets.length }} / 共 {{ roster.length }} 人</span>
      </h4>
      <div class="pc-scope-btns">
        <el-button size="small" @click="selectAll">全选</el-button>
        <el-button size="small" @click="form.targets = []">全不选</el-button>
        <el-button size="small" @click="selectCommittee">仅班委</el-button>
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

      <!-- ---------- 三、题目 ---------- -->
      <h4 class="pc-h">
        三、题目
        <span class="pc-count">共 {{ form.questions.length }} 题</span>
      </h4>
      <div v-for="(q, i) in form.questions" :key="i" class="pc-q">
        <div class="pc-q-head">
          <span class="pc-q-no">第 {{ i + 1 }} 题</span>
          <el-radio-group v-model="q.multiple" size="small" @change="onMultipleChange(q)">
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
            />
            项
          </span>
          <el-button
            class="pc-q-del"
            link
            type="danger"
            :disabled="form.questions.length <= 1"
            @click="removeQuestion(i)"
          >删除本题</el-button>
        </div>

        <el-input
          v-model="q.title"
          maxlength="500"
          placeholder="题干，例如：你赞成哪一款班服？"
          class="pc-q-title"
        />

        <div v-for="(opt, j) in q.options" :key="j" class="pc-opt">
          <span class="pc-opt-label">{{ letters[j] }}</span>
          <el-input v-model="q.options[j]" maxlength="200" :placeholder="`选项 ${j + 1}`" />
          <el-button
            link
            type="danger"
            :disabled="q.options.length <= 2"
            @click="removeOption(q, j)"
          >删除</el-button>
        </div>

        <el-button size="small" :disabled="q.options.length >= 20" @click="q.options.push('')">
          添加选项
        </el-button>
        <span class="pc-tip pc-tip-inline">
          选项最多 20 个。要「弃权」就单独列成一个选项 —— 每题都必须作答
        </span>
      </div>

      <el-button :disabled="form.questions.length >= 30" @click="addQuestion">
        添加题目（最多 30 题）
      </el-button>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">发起投票</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createPoll, getRoster } from '@/api/vote'
import { errText } from '@/utils/request'
import { POLL_LETTERS } from '@/utils/poll'
import { useUserStore } from '@/store/user'

const emit = defineEmits(['created'])
const userStore = useUserStore()

const visible = ref(false)
const submitting = ref(false)
const rosterLoading = ref(false)
const roster = ref([])

/** 选项前面的序号，和表决、结果里显示的是同一套 */
const letters = POLL_LETTERS

function blankQuestion(multiple = false) {
  return {
    title: '',
    multiple,
    max_choices: multiple ? 2 : 1,
    options: ['', ''],
    // 切回多选时要恢复上次填的「最多选几项」，不然来回切一次就得重填
    lastMax: 2
  }
}

function blankForm() {
  return {
    title: '',
    description: '',
    anonymous: false,
    start_at: '',
    end_at: '',
    targets: [],
    questions: [blankQuestion()]
  }
}

const form = reactive(blankForm())

/** 勾选里没有我 → 提示一句。发起人默认全选时通常在里面，但改范围时容易把自己漏掉 */
const iAmOutOfScope = computed(() => {
  const myNo = userStore.info?.student_no
  return !!myNo && form.targets.length > 0 && !form.targets.includes(myNo)
})

function open() {
  Object.assign(form, blankForm())
  visible.value = true
  fetchRoster()
}

function reset() {
  Object.assign(form, blankForm())
  roster.value = []
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
  // 改成不记名是要紧事，给一次确认 —— 发出去之后改不了（没有编辑接口）
  if (value) ElMessage.info('已设为不记名：发起人也查不到谁选了什么')
}

/** 提交前的校验。**后端才是唯一的闸**，这里只是让用户早点看到问题
 *
 * 一条条收集、只报第一条：表单是动态增删的，用 el-form 的深层 prop（questions.0.options.1）
 * 在这种结构下极脆，项目里也没这个先例，所以照 LeaveApply.vue 的办法手写。
 */
function firstError() {
  if (!form.title.trim()) return '请填写标题'
  if (!form.start_at) return '请选择开始时间'
  if (!form.end_at) return '请选择截止时间'

  const start = new Date(form.start_at.replace(' ', 'T'))
  const end = new Date(form.end_at.replace(' ', 'T'))
  if (!(end > start)) return '截止时间必须晚于开始时间'
  if (end.getTime() <= Date.now()) return '截止时间已经过了'
  if (end - start > 365 * 24 * 3600 * 1000) return '投票跨度不能超过一年'

  if (!form.targets.length) return '至少要选一名有权表决的同学'

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

async function handleSubmit() {
  const problem = firstError()
  if (problem) return ElMessage.warning(problem)

  submitting.value = true
  try {
    await createPoll({
      title: form.title.trim(),
      description: form.description.trim(),
      anonymous: form.anonymous,
      start_at: form.start_at,
      end_at: form.end_at,
      targets: [...form.targets],
      questions: form.questions.map((q) => ({
        title: q.title.trim(),
        multiple: q.multiple,
        max_choices: q.multiple ? q.max_choices : 1,
        options: q.options.map((o) => o.trim())
      }))
    })
    ElMessage.success('已发起，范围内的同学会收到提醒')
    visible.value = false
    emit('created')
  } catch (e) {
    ElMessage.error(errText(e, '发起失败'))
  } finally {
    submitting.value = false
  }
}

// 让父组件通过 ref 调用 open()
defineExpose({ open })
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
