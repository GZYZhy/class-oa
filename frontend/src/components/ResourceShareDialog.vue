<!--
  资料分享弹窗：先选有效期，再给出链接 + 二维码

  外链落地在 /share/resource/{token}（share/ShareResource.vue），拿到链接的人
  不需要登录就能下载。有效期四档由分享人自己选；创建成功后管理员可以在
  「资料下载管理 → 分享外链」里看到并吊销。
-->
<template>
  <el-dialog
    v-model="visible"
    title="分享资料"
    :width="isMobile ? '92%' : '520px'"
    append-to-body
    :close-on-click-modal="false"
    @closed="reset"
  >
    <div class="rs-head">
      <div class="rs-name">{{ resource?.name || '' }}</div>
      <div class="rs-sub">拿到链接的人无需登录即可下载</div>
    </div>

    <template v-if="!created">
      <div class="rs-label">链接有效期</div>
      <el-radio-group v-model="days" class="rs-days">
        <el-radio-button v-for="opt in DAY_OPTIONS" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </el-radio-button>
      </el-radio-group>
      <p class="rs-tip">
        到期后链接自动失效；管理员也可以随时在后台吊销，不用等到期。
      </p>
    </template>

    <template v-else>
      <div class="rs-link">
        <el-input :model-value="created.url" readonly />
        <el-button type="primary" @click="copyText(created.url)">复制</el-button>
      </div>
      <div class="rs-expiry">{{ expiryText }}</div>

      <div v-if="qrDataUrl" class="rs-qr-wrap">
        <img :src="qrDataUrl" class="rs-qr" alt="分享二维码" />
      </div>
    </template>

    <template #footer>
      <template v-if="!created">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submit">创建外链</el-button>
      </template>
      <template v-else>
        <el-button @click="openPage">打开分享页</el-button>
        <el-button type="primary" @click="visible = false">完成</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createResourceShare } from '@/api/resources'
import { useIsMobile } from '@/composables/useIsMobile'
import { copyText } from '@/utils/clipboard'
import { formatDateTime } from '@/utils/format'
import { makeQrDataUrl } from '@/utils/qr'
import { errText } from '@/utils/request'
import { openShareInNewTab } from '@/utils/share-url'
import { SITE } from '@/utils/site'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 要分享的资料：{ id, name, category, size, download_name } */
  resource: { type: Object, default: null }
})
const emit = defineEmits(['update:modelValue'])

// 四档有效期和后端 resource_service.SHARE_DAY_CHOICES 一一对应
const DAY_OPTIONS = [
  { value: 1, label: '1 天' },
  { value: 7, label: '7 天' },
  { value: 30, label: '30 天' },
  { value: 0, label: '永久' }
]

const isMobile = useIsMobile()
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const days = ref(7)
const creating = ref(false)
const created = ref(null)
const qrDataUrl = ref('')

const expiryText = computed(() => {
  if (!created.value) return ''
  return created.value.expires_at
    ? `有效期至 ${formatDateTime(created.value.expires_at)}`
    : '永久有效'
})

async function submit() {
  if (!props.resource?.id) return
  creating.value = true
  try {
    created.value = await createResourceShare(props.resource.id, days.value)
    makeQr(created.value.url)
  } catch (e) {
    ElMessage.error(errText(e, '创建外链失败'))
  } finally {
    creating.value = false
  }
}

async function makeQr(url) {
  qrDataUrl.value = ''
  try {
    qrDataUrl.value = await makeQrDataUrl(url, { logoUrl: SITE.logoUrl })
  } catch (e) {
    // 二维码只是方便转发的补充，生成失败照样能复制链接
    ElMessage.error('二维码生成失败，可以直接复制链接')
  }
}

function openPage() {
  if (!created.value) return
  openShareInNewTab('resource', created.value.token)
}

function reset() {
  days.value = 7
  creating.value = false
  created.value = null
  qrDataUrl.value = ''
}
</script>

<style scoped>
.rs-head {
  margin-bottom: 16px;
}

.rs-name {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.rs-sub {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.rs-label {
  margin-bottom: 8px;
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.rs-days {
  flex-wrap: wrap;
}

.rs-tip {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.rs-link {
  display: flex;
  gap: 8px;
}

.rs-expiry {
  margin-top: 10px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.rs-qr-wrap {
  display: flex;
  justify-content: center;
  margin-top: 18px;
}

.rs-qr {
  width: 200px;
  height: 200px;
}
</style>
