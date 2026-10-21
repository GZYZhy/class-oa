<!--
  收集外链页：/share/collect/{token}

  公开信息（标题、完整描述、范围、时间、份数/名额、记名情况）任何人可见；
  题目和作答只对登录且在范围内的人下发。

  每人只能填 1 份时，交过卷的人再打开就是「查看自己的答卷」；
  发起人允许时可撤回，撤回会释放竞争名额。
-->
<template>
  <ShareLayout kind-label="收集" :back-to="info?.is_login ? '/vote?tab=collect' : ''">
    <ShareState v-if="loading" type="loading" title="正在读取收集…" />

    <ShareState
      v-else-if="error"
      :type="notFound ? 'invalid' : 'network'"
      :title="notFound ? '' : '打不开这场收集'"
      :description="error"
      :retry="!notFound"
      @retry="load()"
    />

    <template v-else-if="info">
      <div class="sc-wrap">
        <!-- 题目、作答和「我的答卷」都要带「谁在看」的水印 -->
        <Watermark :text="watermarkText" />

        <div class="sc-title-row">
          <h2 class="sc-title">{{ info.title }}</h2>
          <el-tag :type="statusTag(info.status)" size="small">{{ statusLabel(info.status) }}</el-tag>
          <el-tag v-if="info.anonymous" type="warning" size="small" effect="plain">不记名</el-tag>
          <el-tag v-if="info.allow_withdraw" type="info" size="small" effect="plain">可撤回</el-tag>
        </div>

        <!-- 公开信息：标题、完整描述（Markdown）、范围、时间、份数 -->
        <div
          v-if="info.description"
          class="sc-desc markdown-body"
          v-html="renderMarkdown(info.description)"
        ></div>
        <div class="sc-meta">
          <span>范围：{{ info.scope_label || '—' }}</span>
          <span>应填 {{ info.target_count }} 人</span>
          <span>每人 {{ info.submit_quota }} 份</span>
          <span v-if="info.max_responses">
            限收 {{ info.max_responses }} 份（已收 {{ info.submitted_count }} 份）
          </span>
          <span v-else>已收 {{ info.submitted_count }} 份</span>
          <span>{{ formatDateTime(info.start_at) }} 起</span>
          <span>截止 {{ formatDateTime(info.end_at) }}</span>
        </div>

        <!-- 游客：公开信息照常看，登录后才能填写 -->
        <div v-if="!info.is_login" class="sc-cta">
          <p class="sc-tip">登录后即可查看题目并填写收集</p>
          <a :href="loginHref"><el-button type="primary" size="large">登录后填写</el-button></a>
        </div>

        <!-- 登录了但不在范围内：统一无权限提示 -->
        <ShareState
          v-else-if="!info.in_scope"
          type="forbidden"
          title="没有权限查看题目"
          description="你不在本次收集的可填写范围内，只能看公开信息"
          :home="false"
        />

        <template v-else>
          <el-alert
            v-if="justSubmitted"
            type="success"
            :closable="false"
            show-icon
            class="sc-alert"
            title="答卷已提交"
            :description="submittedTip"
          />

          <!-- 我的答卷：交过就回显（1 份时整页以它为主），允许时可逐份撤回 -->
          <section v-if="info.my_responses.length" class="sc-mine">
            <div class="sc-mine-head">
              <h3 class="sc-section-title">我的答卷</h3>
              <span class="sc-sub">共 {{ info.my_responses.length }} 份</span>
            </div>
            <div v-for="response in info.my_responses" :key="response.id" class="sc-response">
              <div class="sc-response-head">
                <span>
                  第 {{ response.seq_no }} 份 · {{ formatDateTime(response.submitted_at) }}
                </span>
                <el-button
                  v-if="canWithdraw"
                  link
                  type="danger"
                  :loading="withdrawingId === response.id"
                  @click="handleWithdraw(response)"
                >
                  撤回答卷
                </el-button>
              </div>
              <CollectionAnswers
                :questions="info.questions"
                :answers="response.answers"
                :collection-id="info.id"
                :response-id="response.id"
              />
            </div>
          </section>

          <!-- 还能填：继续用同一张表单（每人多份时交完一份还能再填） -->
          <section v-if="info.can_submit" class="sc-form">
            <el-alert
              v-if="info.submit_quota > 1"
              type="info"
              :closable="false"
              show-icon
              class="sc-alert"
              :title="`你已填 ${info.my_submitted_count}/${info.submit_quota} 份，还可以再填 ${info.my_remaining} 份`"
            />
            <el-alert
              v-if="info.anonymous"
              type="warning"
              :closable="false"
              show-icon
              class="sc-alert"
              title="本次收集不记名"
              description="发起人看答卷时不显示你的姓名和学号，但能看出谁还没填"
            />
            <CollectBallot
              :key="ballotKey"
              :collection="info"
              :submitting="submitting"
              @submit="handleSubmit"
            />
          </section>

          <!-- 不能填时把原因说清楚；有自己答卷的也顺带说明为什么不能再填 -->
          <p v-else-if="stateReason" class="sc-state">{{ stateReason }}</p>
        </template>
      </div>
    </template>
  </ShareLayout>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import CollectBallot from '@/components/CollectBallot.vue'
import CollectionAnswers from '@/components/CollectionAnswers.vue'
import ShareLayout from '@/components/share/ShareLayout.vue'
import ShareState from '@/components/share/ShareState.vue'
import Watermark from '@/components/Watermark.vue'
import {
  getCollectionShareInfo,
  submitCollectionResponse,
  withdrawCollectionResponse
} from '@/api/collection'
import { useWatermark } from '@/composables/useWatermark'
import { statusLabel, statusTag, markdownPreview } from '@/utils/collection'
import { formatDateTime } from '@/utils/format'
import { renderMarkdown } from '@/utils/markdown'
import { errText } from '@/utils/request'
import { applyShareMeta, resetShareMeta } from '@/utils/share-meta'
import { attachSharePath, detachSharePath, sharePath, shareUrl } from '@/utils/share-url'

const route = useRoute()
const watermarkText = useWatermark()

const token = computed(() => String(route.params.token || ''))
const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const info = ref(null)
const submitting = ref(false)
const withdrawingId = ref(null)
const justSubmitted = ref(false)
/** 提交/撤回后换一个 key，整张表单重置（同时回收图片预览地址） */
const ballotKey = ref(0)

const loginHref = computed(() => `#/login?redirect=${encodeURIComponent(route.fullPath)}`)

const canWithdraw = computed(
  () =>
    !!info.value?.allow_withdraw &&
    (info.value?.status === 'open' || info.value?.status === 'paused')
)

const stateReason = computed(() => {
  const data = info.value
  if (!data) return ''
  if (data.status === 'pending') return '收集还没开始，到开始时间后才能填写'
  if (data.status === 'closed') return '收集已结束'
  if (data.status === 'paused') return '收集已暂停，等发起人恢复后才能填写'
  if (data.cap_reached) return '竞争名额已满'
  if (data.quota_reached) return `你已经填满 ${data.submit_quota} 份`
  return '现在不能填写'
})

const submittedTip = computed(() => {
  const data = info.value
  if (!data) return ''
  if (data.cap_reached) return '竞争名额已满，答卷不能再改'
  if (data.quota_reached) return `你已填满 ${data.submit_quota} 份`
  if (data.can_submit && data.submit_quota > 1) {
    return `还可以再填 ${data.my_remaining} 份；再填一份请用下面的表单`
  }
  return '提交后不能修改'
})

/** 卡片摘要：和站内分享弹窗、服务端 meta 用同一套口径 */
function cardOf(data) {
  const tail = [
    statusLabel(data.status),
    data.scope_label,
    data.anonymous ? '不记名' : '记名',
    `每人 ${data.submit_quota} 份`,
    data.max_responses ? `限收 ${data.max_responses} 份` : '',
    `截止 ${formatDateTime(data.end_at)}`
  ]
    .filter(Boolean)
    .join(' · ')
  const preview = markdownPreview(data.description, 60)
  return {
    title: `收集：${data.title || '收集'}`,
    description: preview ? `${preview}｜${tail}` : tail,
    url: shareUrl('collect', token.value)
  }
}

async function load() {
  if (!token.value) {
    loading.value = false
    notFound.value = true
    error.value = '链接不完整，请向发布人重新要一次收集链接'
    return
  }

  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    const data = await getCollectionShareInfo(token.value)
    info.value = data
    justSubmitted.value = false
    applyShareMeta({ ...cardOf(data), index: true })
    attachSharePath(sharePath('collect', token.value))
  } catch (e) {
    if (e?.response?.status === 404) {
      notFound.value = true
      error.value = '这场收集不存在、已删除，或链接已失效'
    } else {
      error.value = '网络不稳定，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}

async function refresh() {
  info.value = await getCollectionShareInfo(token.value)
  applyShareMeta({ ...cardOf(info.value), index: true })
  ballotKey.value += 1
}

async function handleSubmit(answers) {
  submitting.value = true
  try {
    const res = await submitCollectionResponse(info.value.id, answers)
    ElMessage.success(`第 ${res.seq_no} 份答卷已提交`)
    justSubmitted.value = true
    await refresh()
  } catch (e) {
    ElMessage.error(errText(e, '提交失败'))
  } finally {
    submitting.value = false
  }
}

async function handleWithdraw(response) {
  try {
    await ElMessageBox.confirm(
      '撤回后这份答卷会被删除，竞争名额同时释放；撤回后可以重新填写。确定撤回吗？',
      '撤回答卷',
      { type: 'warning', confirmButtonText: '撤回', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  withdrawingId.value = response.id
  try {
    await withdrawCollectionResponse(info.value.id, response.id)
    ElMessage.success('已撤回答卷')
    justSubmitted.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(errText(e, '撤回失败'))
  } finally {
    withdrawingId.value = null
  }
}

onMounted(load)
watch(token, (next, prev) => {
  if (next && next !== prev) load()
})
onUnmounted(() => {
  detachSharePath('/share/collect/')
  resetShareMeta()
})
</script>

<style scoped>
.sc-wrap {
  /* 水印的定位基准 */
  position: relative;
}

.sc-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sc-title {
  margin: 0;
  font-size: 20px;
  line-height: 1.5;
  color: var(--el-text-color-primary);
}

/* 轻量 Markdown：只补排版，不引入富文本样式库 */
.sc-desc {
  margin-top: 10px;
  color: var(--el-text-color-regular);
  line-height: 1.7;
}

.sc-desc :deep(h1),
.sc-desc :deep(h2),
.sc-desc :deep(h3) {
  margin: 12px 0 6px;
  font-size: 16px;
  line-height: 1.5;
}

.sc-desc :deep(p) {
  margin: 6px 0;
}

.sc-desc :deep(ul),
.sc-desc :deep(ol) {
  margin: 6px 0;
  padding-left: 1.4em;
}

.sc-desc :deep(blockquote) {
  margin: 8px 0;
  padding: 4px 10px;
  border-left: 3px solid var(--el-border-color);
  color: var(--el-text-color-secondary);
}

.sc-desc :deep(code) {
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--el-fill-color-light);
  font-size: 0.92em;
}

.sc-desc :deep(a) {
  color: var(--el-color-primary);
}

.sc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin: 12px 0 18px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.sc-cta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 16px 0 8px;
}

.sc-tip {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.sc-alert {
  margin-bottom: 12px;
}

.sc-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.sc-mine {
  margin-bottom: 22px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.sc-mine-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}

.sc-section-title {
  margin: 0;
  font-size: 16px;
  color: var(--el-text-color-primary);
}

.sc-response {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.sc-response-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.sc-state {
  margin: 8px 0 0;
  padding: 12px 14px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  text-align: center;
}

.sc-form {
  margin-top: 4px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
