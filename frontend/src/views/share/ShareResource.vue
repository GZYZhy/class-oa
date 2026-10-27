<!--
  资料分享外链：/share/resource/{token}

  和公告/投票/签到/收集共用同一套外壳与状态页。外链由分享人在「资料下载」里
  创建，有效期自己选（1 天 / 7 天 / 30 天 / 永久），管理员可以随时吊销。
  过期 / 被吊销时说明具体原因 —— 游客看到「已过期」比统一一句「链接失效」有用。
-->
<template>
  <ShareLayout kind-label="资料" :back-to="userStore.isLogin ? '/downloads' : ''">
    <ShareState v-if="loading" type="loading" title="正在读取资料…" />

    <ShareState
      v-else-if="error"
      :type="notFound ? 'invalid' : 'network'"
      :title="notFound ? '' : '打不开这个分享页'"
      :description="error"
      :retry="!notFound"
      @retry="load()"
    />

    <template v-else-if="info">
      <ShareState
        v-if="!info.valid"
        type="invalid"
        :title="stateTitle"
        :description="stateDesc"
      />

      <template v-else>
        <div class="sr-file">
          <div class="sr-icon" :class="iconClass">
            <el-icon><component :is="iconName" /></el-icon>
          </div>
          <div class="sr-info">
            <h2 class="sr-name">{{ info.resource_name }}</h2>
            <div class="sr-meta">
              <span>{{ info.category }}</span>
              <span>{{ formatFileSize(info.size) }}</span>
            </div>
            <div class="sr-expiry">{{ expiryText }}</div>
          </div>
        </div>

        <div class="sr-actions">
          <el-button type="primary" size="large" :loading="downloading" @click="download">
            <el-icon v-if="!downloading"><Download /></el-icon>
            下载
          </el-button>
        </div>

        <p class="sr-tip">下载无需登录。文件来自班级资料库，请勿随意转发到班级之外。</p>
      </template>
    </template>
  </ShareLayout>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import ShareLayout from '@/components/share/ShareLayout.vue'
import ShareState from '@/components/share/ShareState.vue'
import { getResourceShareInfo } from '@/api/resources'
import { downloadFile } from '@/utils/download'
import { formatDateTime } from '@/utils/format'
import { formatFileSize } from '@/utils/markdown'
import { applyShareMeta, resetShareMeta } from '@/utils/share-meta'
import { attachSharePath, detachSharePath, sharePath, shareUrl } from '@/utils/share-url'
import { useUserStore } from '@/store/user'

const route = useRoute()
const userStore = useUserStore()

const token = computed(() => String(route.params.token || ''))
const loading = ref(true)
const downloading = ref(false)
const error = ref('')
const notFound = ref(false)
const info = ref(null)

/** 文件类型 → 图标与配色，和资料卡片同一套视觉 */
const FILE_TYPES = [
  { test: /\.(jpe?g|png|gif|webp|heic)$/, cls: 'type-image', icon: 'Picture' },
  { test: /\.pdf$/, cls: 'type-pdf', icon: 'Document' },
  { test: /\.xlsx?$/, cls: 'type-excel', icon: 'Grid' },
  { test: /\.docx?$/, cls: 'type-word', icon: 'EditPen' }
]
const fileType = computed(
  () => FILE_TYPES.find((item) => item.test.test(info.value?.file_ext || '')) || {
    cls: 'type-file',
    icon: 'Files'
  }
)
const iconClass = computed(() => fileType.value.cls)
const iconName = computed(() => fileType.value.icon)

const expiryText = computed(() => {
  if (!info.value) return ''
  return info.value.expires_at
    ? `有效期至 ${formatDateTime(info.value.expires_at)}`
    : '永久有效'
})

/** 失效原因分别给一句能指导下一步的话 */
const STATE_TEXT = {
  expired: ['链接已过期', '这条分享链接过了有效期，请向分享人要一条新的'],
  revoked: ['链接已被收回', '分享人已收回这条链接，需要的话请让对方重新分享'],
  missing: ['文件暂不可用', '资料文件已不在服务器上，请联系管理员']
}
const stateText = computed(() => STATE_TEXT[info.value?.reason] || STATE_TEXT.expired)
const stateTitle = computed(() => stateText.value[0])
const stateDesc = computed(() => stateText.value[1])

function cardDescription(data) {
  const parts = [data.category, formatFileSize(data.size)]
  parts.push(
    data.expires_at ? `有效期至 ${formatDateTime(data.expires_at)}` : '永久有效'
  )
  return parts.filter(Boolean).join(' · ')
}

async function load() {
  if (!token.value) {
    loading.value = false
    notFound.value = true
    error.value = '链接不完整，请向分享人重新要一次'
    return
  }

  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    const data = await getResourceShareInfo(token.value)
    info.value = data

    // 客户端补一份 meta；服务端 SSI 已经写过一份，helper 会更新而不是重复添加
    applyShareMeta({
      title: data.valid ? `资料：${data.resource_name}` : '链接已失效',
      description: data.valid ? cardDescription(data) : '分享链接已过期或被收回',
      url: shareUrl('resource', token.value),
      index: data.valid
    })
    // 站内 hash 地址补成真实路径，转发时爬虫才能读到 meta
    attachSharePath(sharePath('resource', token.value))
  } catch (e) {
    const status = e?.response?.status
    if (status === 404) {
      notFound.value = true
      error.value = '这条分享链接不存在或已被删除'
    } else {
      error.value = '网络不稳定，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}

async function download() {
  if (!info.value?.download_url) return
  downloading.value = true
  try {
    await downloadFile(info.value.download_url, info.value.download_name || info.value.resource_name)
  } catch (e) {
    ElMessage.error('下载失败，请稍后重试')
  } finally {
    downloading.value = false
  }
}

onMounted(load)
watch(token, (next, prev) => {
  if (next && next !== prev) load()
})
onUnmounted(() => {
  detachSharePath('/share/resource/')
  resetShareMeta()
})
</script>

<style scoped>
.sr-file {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--app-line);
  border-radius: 14px;
  background: var(--el-fill-color-light);
}

.sr-icon {
  width: 52px;
  height: 52px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  font-size: 26px;
  color: #fff;
}

.sr-info {
  min-width: 0;
}

.sr-name {
  margin: 0;
  font-size: 18px;
  line-height: 1.5;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.sr-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.sr-expiry {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.sr-actions {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}

.sr-actions .el-button {
  min-width: 180px;
}

.sr-tip {
  margin: 14px 0 0;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
  color: var(--el-text-color-secondary);
}

/* 和 Downloads.vue 的资料卡片同一套配色 */
.type-image { background: linear-gradient(135deg, #9b59b6, #b07cc6); }
.type-pdf { background: linear-gradient(135deg, #e74c3c, #ec7063); }
.type-excel { background: linear-gradient(135deg, #27ae60, #58d68d); }
.type-word { background: linear-gradient(135deg, #2980b9, #5dade2); }
.type-file { background: linear-gradient(135deg, #7f8c8d, #a6b3b4); }
</style>
