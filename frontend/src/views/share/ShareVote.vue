<!--
  投票外链页：/share/vote/{token}

  站内列表点「投票」也跳到这里 —— 站内站外是同一张整页，不再经过
  「投票列表 → 弹窗」两级。

  公开信息（标题、完整描述、范围、状态、时间、人数）任何人可见；
  题目、选项、作答和票数只在登录且在范围内时由后端下发。
-->
<template>
  <ShareLayout kind-label="投票" :back-to="poll?.is_login ? '/vote' : ''">
    <ShareState v-if="loading" type="loading" title="正在读取投票…" />

    <ShareState
      v-else-if="error"
      :type="notFound ? 'invalid' : 'network'"
      :title="notFound ? '' : '打不开这场投票'"
      :description="error"
      :retry="!notFound"
      @retry="load()"
    />

    <template v-else-if="poll">
      <div class="sv-wrap">
        <!-- 题目和作答要带「谁在看」的水印，和站内投票页一致 -->
        <Watermark :text="watermarkText" />

        <div class="sv-title-row">
          <h2 class="sv-title">{{ poll.title }}</h2>
          <el-tag :type="statusTag(poll.status)" size="small">{{ statusLabel(poll.status) }}</el-tag>
          <el-tag v-if="poll.anonymous" type="warning" size="small" effect="plain">不记名</el-tag>
        </div>

        <!-- 公开信息：标题、完整描述（Markdown）、范围、时间、人数 -->
        <div
          v-if="poll.description"
          class="sv-desc markdown-body"
          v-html="renderMarkdown(poll.description)"
        ></div>
        <div class="sv-meta">
          <span>范围：{{ poll.scope_label || '—' }}</span>
          <span>应投 {{ poll.target_count }} 人</span>
          <span>{{ poll.question_count }} 道题</span>
          <span>{{ formatDateTime(poll.start_at) }} 起</span>
          <span>截止 {{ formatDateTime(poll.end_at) }}</span>
        </div>

        <!-- 游客：公开信息照常看，登录后才能参与 -->
        <div v-if="!poll.is_login" class="sv-cta">
          <p class="sv-tip">登录后即可查看题目并参与投票</p>
          <a :href="loginHref"><el-button type="primary" size="large">登录后参与</el-button></a>
        </div>

        <!-- 登录了但不在范围内：统一的无权限提示，公开信息仍然保留 -->
        <ShareState
          v-else-if="!poll.in_scope"
          type="forbidden"
          title="没有权限查看题目"
          description="你不在本次投票的表决范围内，只能看公开信息"
          :home="false"
        />

        <!-- 范围内：整页答卷（投过 / 已结束会自动变成只读回显） -->
        <template v-else>
          <el-alert
            v-if="justVoted"
            type="success"
            :closable="false"
            show-icon
            class="sv-alert"
            title="投票已提交"
          />
          <VoteBallot
            :poll="poll"
            :submitting="submitting"
            @submit="handleSubmit"
            @close="router.push('/vote')"
          />
        </template>

        <!-- 结果：只对能看到结果的人（发起人/管理员/投票已结束的参与者）出现 -->
        <div v-if="poll.in_scope && poll.results_visible && poll.questions?.length" class="sv-results">
          <div class="sv-results-head">
            <h3 class="sv-results-title">投票结果</h3>
            <!-- 纯前端重排，不改票数：选举时先看谁领先 -->
            <el-button size="small" @click="tallySorted = !tallySorted">
              {{ tallySorted ? '按选项顺序' : '按得票排序' }}
            </el-button>
          </div>
          <p class="sv-hint">
            已投 {{ poll.voted_count }} / {{ poll.target_count }} 人。
            多选题每人可选的项数不止一个，所以一道题的票数之和会大于人数
          </p>
          <div v-for="(q, i) in poll.questions" :key="q.id" class="sv-rq">
            <div class="sv-q-title">
              <span>{{ i + 1 }}. {{ q.title }}</span>
              <el-tag v-if="q.multiple" size="small" type="info" effect="plain">多选</el-tag>
              <span class="sv-sub">共 {{ sumOf(q) }} 项选择</span>
            </div>
            <div v-for="j in tallyOrder(q, tallySorted)" :key="j" class="sv-opt">
              <span class="sv-opt-name">
                <span class="sv-opt-letter">{{ letters[j] }}.</span> {{ q.options[j] }}
              </span>
              <el-progress
                :percentage="percentOf(q, j)"
                :stroke-width="14"
                :show-text="false"
                class="sv-bar"
              />
              <span class="sv-opt-num">{{ q.tallies?.[j] ?? 0 }} 票</span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </ShareLayout>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import ShareLayout from '@/components/share/ShareLayout.vue'
import ShareState from '@/components/share/ShareState.vue'
import VoteBallot from '@/components/VoteBallot.vue'
import Watermark from '@/components/Watermark.vue'
import { getPollShareInfo, votePoll } from '@/api/vote'
import { useWatermark } from '@/composables/useWatermark'
import { markdownPreview } from '@/utils/collection'
import { formatDateTime } from '@/utils/format'
import { renderMarkdown } from '@/utils/markdown'
import { errText } from '@/utils/request'
import {
  POLL_LETTERS as letters,
  percentOf,
  statusLabel,
  statusTag,
  sumOf,
  tallyOrder
} from '@/utils/poll'
import { applyShareMeta, resetShareMeta } from '@/utils/share-meta'
import { attachSharePath, detachSharePath, sharePath, shareUrl } from '@/utils/share-url'

const route = useRoute()
const router = useRouter()
const watermarkText = useWatermark()

const token = computed(() => String(route.params.token || ''))
const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const poll = ref(null)
const submitting = ref(false)
const justVoted = ref(false)
/** 结果是否按得票从多到少排；只是看的习惯，换一场不用重设 */
const tallySorted = ref(false)

const loginHref = computed(() => `#/login?redirect=${encodeURIComponent(route.fullPath)}`)

/** 卡片摘要：和站内分享弹窗、服务端 meta 用同一套口径 */
function cardOf(data) {
  const tail = [
    statusLabel(data.status),
    data.scope_label,
    data.anonymous ? '不记名' : '记名',
    `应投 ${data.target_count} 人`,
    `${data.question_count} 道题`,
    `截止 ${formatDateTime(data.end_at)}`
  ]
    .filter(Boolean)
    .join(' · ')
  const description = data.description ? `${markdownPreview(data.description, 60)}｜${tail}` : tail
  return {
    title: `投票：${data.title || '投票表决'}`,
    description,
    url: shareUrl('vote', token.value)
  }
}

async function load() {
  if (!token.value) {
    loading.value = false
    notFound.value = true
    error.value = '链接不完整，请向发布人重新要一次投票链接'
    return
  }

  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    const data = await getPollShareInfo(token.value)
    poll.value = data
    justVoted.value = false

    applyShareMeta({ ...cardOf(data), index: true })
    // 站内 hash 地址补成真实路径，转发时爬虫才能读到 meta
    attachSharePath(sharePath('vote', token.value))
  } catch (e) {
    if (e?.response?.status === 404) {
      notFound.value = true
      error.value = '这场投票不存在、已删除，或链接已失效'
    } else {
      error.value = '网络不稳定，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}

async function handleSubmit(answers) {
  submitting.value = true
  try {
    await votePoll(poll.value.id, { answers })
    ElMessage.success('投票成功，谢谢参与')
    justVoted.value = true
    // 重新取一次分享信息：投过之后 can_vote / has_voted / 目标人数都以服务端为准
    poll.value = await getPollShareInfo(token.value)
    applyShareMeta({ ...cardOf(poll.value), index: true })
  } catch (e) {
    ElMessage.error(errText(e, '投票失败'))
  } finally {
    submitting.value = false
  }
}

onMounted(load)
watch(token, (next, prev) => {
  if (next && next !== prev) load()
})
onUnmounted(() => {
  detachSharePath('/share/vote/')
  resetShareMeta()
})
</script>

<style scoped>
.sv-wrap {
  /* 水印的定位基准 */
  position: relative;
}

.sv-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sv-title {
  margin: 0;
  font-size: 20px;
  line-height: 1.5;
  color: var(--el-text-color-primary);
}

.sv-desc {
  margin-top: 10px;
  color: var(--el-text-color-regular);
  line-height: 1.7;
}

/* 轻量 Markdown：只补排版，不引入富文本样式库 */
.sv-desc :deep(h1),
.sv-desc :deep(h2),
.sv-desc :deep(h3) {
  margin: 12px 0 6px;
  font-size: 16px;
  line-height: 1.5;
}

.sv-desc :deep(p) {
  margin: 6px 0;
}

.sv-desc :deep(ul),
.sv-desc :deep(ol) {
  margin: 6px 0;
  padding-left: 1.4em;
}

.sv-desc :deep(blockquote) {
  margin: 8px 0;
  padding: 4px 10px;
  border-left: 3px solid var(--el-border-color);
  color: var(--el-text-color-secondary);
}

.sv-desc :deep(code) {
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--el-fill-color-light);
  font-size: 0.92em;
}

.sv-desc :deep(a) {
  color: var(--el-color-primary);
}

.sv-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin: 12px 0 18px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.sv-cta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 16px 0 8px;
}

.sv-tip {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.sv-alert {
  margin-bottom: 12px;
}

.sv-results {
  margin-top: 24px;
  padding-top: 18px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.sv-results-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.sv-results-title {
  margin: 0;
  font-size: 16px;
  color: var(--el-text-color-primary);
}

.sv-hint {
  margin: 0 0 14px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.sv-rq {
  margin-bottom: 18px;
}

.sv-q-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-weight: 600;
}

.sv-sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.sv-opt {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.sv-opt-name {
  width: 190px;
  flex: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sv-opt-letter {
  display: inline-block;
  min-width: 1.5em;
}

.sv-bar {
  flex: 1;
}

.sv-opt-num {
  width: 52px;
  flex: none;
  text-align: right;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 560px) {
  .sv-opt-name {
    width: 120px;
  }
}
</style>
