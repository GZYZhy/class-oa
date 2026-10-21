<!--
  投票答卷（整卷）

  从投票页原来的弹窗里抽出来，现在只给外链分享页用：站内列表点「投票」
  也跳到同一张整页。组件只负责草稿、校验和确认，真正的提交由父组件调接口。
-->
<template>
  <div class="vb">
    <div class="vb-meta">
      <el-tag v-if="poll.anonymous" type="warning" size="small">不记名</el-tag>
      <span class="vb-sub">
        {{ formatDateTime(poll.start_at) }} 起，{{ formatDateTime(poll.end_at) }} 截止
      </span>
    </div>

    <el-alert
      v-if="poll.anonymous"
      type="warning"
      :closable="false"
      show-icon
      class="vb-alert"
      title="本次投票不记名"
      description="发起人也看不到你选了什么。只有「谁投了、谁还没投」是公开的"
    />
    <el-alert
      v-if="!canVote && poll.has_voted"
      type="success"
      :closable="false"
      show-icon
      class="vb-alert"
      title="你已经投过票了"
      description="投出去就定死了，不能改票也不能重投。下面是你的选择"
    />
    <el-alert
      v-else-if="!canVote"
      type="info"
      :closable="false"
      show-icon
      class="vb-alert"
      :title="blockReason"
    />

    <p v-if="canVote" class="vb-hint">
      每题都必须作答（要弃权就选「弃权」那一项）；提交后不能改票，请确认无误再提交
    </p>

    <div v-for="(q, i) in poll.questions" :key="q.id" class="vb-q">
      <div class="vb-q-title">
        <span>{{ i + 1 }}. {{ q.title }}</span>
        <el-tag size="small" type="info" effect="plain">
          {{ q.multiple ? `多选，最多 ${q.max_choices} 项` : '单选' }}
        </el-tag>
      </div>

      <!-- 能投：真正的作答控件 -->
      <template v-if="canVote">
        <!-- el-radio-group 的 v-model 要的是单个值，而 draft 里统一存数组，
             所以单选走 :model-value + @change 手工回写，两种题型的数据形状保持一致 -->
        <el-radio-group
          v-if="!q.multiple"
          :model-value="draft[q.id]?.[0]"
          @change="(value) => (draft[q.id] = [value])"
        >
          <el-radio v-for="(opt, j) in q.options" :key="j" :value="j">
            <span class="vb-opt-letter">{{ letters[j] }}.</span> {{ opt }}
          </el-radio>
        </el-radio-group>
        <el-checkbox-group v-else v-model="draft[q.id]" :max="q.max_choices">
          <el-checkbox v-for="(opt, j) in q.options" :key="j" :value="j">
            <span class="vb-opt-letter">{{ letters[j] }}.</span> {{ opt }}
          </el-checkbox>
        </el-checkbox-group>
      </template>

      <!-- 投过 / 不能投：只读回显 -->
      <template v-else>
        <div
          v-for="(opt, j) in q.options"
          :key="j"
          class="vb-ro"
          :class="{ 'vb-picked': picked(q, j) }"
        >
          <el-icon v-if="picked(q, j)"><Select /></el-icon>
          <span v-else class="vb-ro-dot"></span>
          <span class="vb-opt-letter">{{ letters[j] }}.</span> {{ opt }}
        </div>
      </template>
    </div>

    <div v-if="showFooter" class="vb-actions">
      <el-button @click="$emit('close')">{{ canVote ? '取消' : '关闭' }}</el-button>
      <el-button v-if="canVote" type="primary" :loading="submitting" @click="handleSubmit">
        提交投票
      </el-button>
      <el-button v-else-if="poll.has_voted" type="success" disabled>已投票</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { POLL_LETTERS as letters, voteBlockReason } from '@/utils/poll'
import { formatDateTime } from '@/utils/format'

const props = defineProps({
  poll: { type: Object, required: true },
  submitting: { type: Boolean, default: false },
  /** 强制只读（比如父组件想在投完后只展示） */
  readonly: { type: Boolean, default: false },
  showFooter: { type: Boolean, default: true }
})
const emit = defineEmits(['submit', 'close'])

/** 我的勾选：{题目 ID: 下标数组}。单选也存数组，两种题型提交时形状一致 */
const draft = reactive({})

const canVote = computed(() => !props.readonly && !!props.poll?.can_vote)
const blockReason = computed(() => voteBlockReason(props.poll))

function fill(detail) {
  Object.keys(draft).forEach((key) => delete draft[key])
  ;(detail?.questions || []).forEach((q) => {
    draft[q.id] = []
  })
}

watch(() => props.poll, fill, { immediate: true })

function picked(question, index) {
  return (question.my_choices || []).includes(index)
}

async function handleSubmit() {
  const questions = props.poll.questions || []
  for (let i = 0; i < questions.length; i += 1) {
    const q = questions[i]
    const chosen = draft[q.id] || []
    // 空选也拦下：后端要求每题必答，「已投」的判定才不含糊
    if (!chosen.length) return ElMessage.warning(`第 ${i + 1} 题还没作答，每题都必须作答`)
    if (q.multiple && chosen.length > q.max_choices) {
      return ElMessage.warning(`第 ${i + 1} 题最多选 ${q.max_choices} 项`)
    }
  }

  try {
    await ElMessageBox.confirm(
      '提交后不能改票，也不能重投。确定提交吗？',
      '提交确认',
      { type: 'warning', confirmButtonText: '确定提交', cancelButtonText: '再想想' }
    )
  } catch {
    return // 点了取消
  }

  emit(
    'submit',
    questions.map((q) => ({
      question_id: q.id,
      choices: [...(draft[q.id] || [])].sort((a, b) => a - b)
    }))
  )
}
</script>

<style scoped>
.vb-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.vb-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.vb-alert {
  margin-bottom: 10px;
}

.vb-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.vb-q {
  margin-bottom: 16px;
}

.vb-q-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-weight: 600;
}

.vb-q :deep(.el-radio-group),
.vb-q :deep(.el-checkbox-group) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

/* 只读回显：投过的选项打勾，其余留白 */
.vb-ro {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
  color: var(--el-text-color-regular);
}

.vb-picked {
  color: var(--el-color-primary);
  font-weight: 600;
}

.vb-ro-dot {
  display: inline-block;
  width: 14px;
}

/* 字母单占一格定宽，选项名的起点才不会跟着字母宽度左右跳 */
.vb-opt-letter {
  display: inline-block;
  min-width: 1.5em;
}

.vb-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
