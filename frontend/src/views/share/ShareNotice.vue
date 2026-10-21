<!--
  公告外链页：/share/notice/{id}

  通知公告本身是公开内容，不需要登录就能看；路径直接用自增 id，
  所以每条公告都有一个稳定、可被爬取的真实地址。
  登录状态下打开外链也会记已读（和站内展开通知同一口径）。
-->
<template>
  <ShareLayout kind-label="公告" :back-to="userStore.isLogin ? '/notices' : ''">
    <ShareState v-if="loading" type="loading" title="正在读取公告…" />

    <ShareState
      v-else-if="error"
      :type="notFound ? 'invalid' : 'network'"
      :title="notFound ? '' : '打不开这条公告'"
      :description="error"
      :retry="!notFound"
      @retry="load()"
    />

    <template v-else-if="notice">
      <h2 class="sn-title">公告：{{ notice.title }}</h2>

      <div class="sn-meta">
        <span>{{ notice.publisher || '未知' }} 发布</span>
        <span>{{ notice.publish_date }}</span>
        <el-tag v-if="notice.updated_at" size="small" type="warning" effect="plain">
          已于 {{ formatDateTime(notice.updated_at) }} 更新
        </el-tag>
      </div>

      <!-- 正文就是站内通知的 Markdown 渲染，同一套样式 -->
      <div class="markdown-body sn-body" v-html="renderMarkdown(notice.content)"></div>

      <div v-if="notice.attachments?.length" class="sn-attachments">
        <div class="sn-attach-title">
          <el-icon><Paperclip /></el-icon>
          附件（{{ notice.attachments.length }}）
        </div>
        <div class="sn-attach-list">
          <div
            v-for="(att, idx) in notice.attachments"
            :key="idx"
            class="sn-attach-item"
            @click="downloadAttachment(idx, att.name)"
          >
            <el-icon><Document /></el-icon>
            <span class="sn-attach-name">{{ att.name }}</span>
            <span class="sn-attach-size">{{ formatFileSize(att.size) }}</span>
            <el-icon class="sn-attach-download"><Download /></el-icon>
          </div>
        </div>
      </div>

      <div class="sn-actions">
        <el-button type="primary" @click="router.push('/notices')">更多通知</el-button>
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
import { getNotice, markNoticeRead } from '@/api/notice'
import { downloadFile } from '@/utils/download'
import { formatDateTime } from '@/utils/format'
import { formatFileSize, renderMarkdown } from '@/utils/markdown'
import { applyShareMeta, resetShareMeta } from '@/utils/share-meta'
import { attachSharePath, detachSharePath, sharePath, shareUrl } from '@/utils/share-url'
import { useUserStore } from '@/store/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const token = computed(() => String(route.params.token || ''))
const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const notice = ref(null)

/** 正文 → 单行摘要。前端只做粗略去符号，真正的卡片摘要以后端 meta 为准 */
function preview(content) {
  return String(content || '')
    .replace(/[#*_>`~[\]()!-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60)
}

async function load() {
  const id = Number(token.value)
  if (!id) {
    loading.value = false
    notFound.value = true
    error.value = '链接不完整，请向发布人重新要一次公告链接'
    return
  }

  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    const data = await getNotice(id)
    notice.value = data

    // 客户端补一份 meta；服务端 SSI 已经写过一份，helper 会更新而不是重复添加
    applyShareMeta({
      title: `公告：${data.title}`,
      description: preview(data.content) || `发布于 ${data.publish_date}`,
      url: shareUrl('notice', data.id),
      index: true
    })
    // 站内 hash 地址补成真实路径，转发时爬虫才能读到 meta
    attachSharePath(sharePath('notice', data.id))

    // 登录状态下打开外链也记已读（游客不记，也没有地方记）
    markReadIfLogin(data.id)
  } catch (e) {
    const status = e?.response?.status
    if (status === 404) {
      notFound.value = true
      error.value = '这条公告不存在或已被删除'
    } else {
      error.value = '网络不稳定，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}

async function markReadIfLogin(id) {
  try {
    // App.vue 也在恢复登录态；resolved 之后直接用结果，避免重复请求
    if (!userStore.resolved) await userStore.fetchMe()
    if (userStore.isLogin) await markNoticeRead(id)
  } catch (e) {
    /* 已读是附加行为，失败不影响阅读 */
  }
}

async function downloadAttachment(index, name) {
  try {
    await downloadFile(`/api/notices/${notice.value.id}/attachments/${index}`, name)
  } catch (e) {
    ElMessage.error('下载失败')
  }
}

onMounted(load)
watch(token, (next, prev) => {
  if (next && next !== prev) load()
})
onUnmounted(() => {
  detachSharePath('/share/notice/')
  resetShareMeta()
})
</script>

<style scoped>
.sn-title {
  margin: 0;
  font-size: 20px;
  line-height: 1.5;
  color: var(--el-text-color-primary);
}

.sn-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 16px;
  margin: 10px 0 16px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.sn-body {
  max-height: none;
}

.sn-attachments {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.sn-attach-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}

.sn-attach-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sn-attach-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  cursor: pointer;
}

.sn-attach-item:hover {
  background: var(--el-fill-color);
}

.sn-attach-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sn-attach-size {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.sn-attach-download {
  color: var(--el-color-primary);
}

.sn-actions {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}
</style>
