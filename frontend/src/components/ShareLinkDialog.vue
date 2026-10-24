<!--
  通用分享弹窗：标题 + 可复制链接 + 二维码

  通知公告每条都用它；以后别的外链类型也可以直接复用，不绑定具体业务。
-->
<template>
  <el-dialog append-to-body
    v-model="visible"
    :title="dialogTitle"
    width="520px"
    :close-on-click-modal="false"
    @closed="qrDataUrl = ''"
  >
    <div class="sl-head">
      <div class="sl-title">{{ title || '分享' }}</div>
      <div v-if="subtitle" class="sl-subtitle">{{ subtitle }}</div>
    </div>

    <div class="sl-link">
      <el-input :model-value="link" readonly />
      <el-button type="primary" @click="copyText(link)">复制</el-button>
    </div>

    <div v-if="qrDataUrl" class="sl-qr-wrap">
      <img :src="qrDataUrl" class="sl-qr" alt="分享二维码" />
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { copyText } from '@/utils/clipboard'
import { makeQrDataUrl } from '@/utils/qr'
import { SITE } from '@/utils/site'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 弹窗标题，默认「分享」 */
  dialogTitle: { type: String, default: '分享' },
  /** 内容标题，通常就是这一条的标题 */
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  link: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})
const qrDataUrl = ref('')

async function makeQr() {
  qrDataUrl.value = ''
  if (!props.link) return
  try {
    qrDataUrl.value = await makeQrDataUrl(props.link, { logoUrl: SITE.logoUrl })
  } catch (e) {
    ElMessage.error('二维码生成失败，可以直接复制链接')
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) makeQr()
    else qrDataUrl.value = ''
  }
)
</script>

<style scoped>
.sl-head {
  margin-bottom: 16px;
}

.sl-title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.sl-subtitle {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.sl-link {
  display: flex;
  gap: 8px;
}

.sl-qr-wrap {
  display: flex;
  justify-content: center;
  margin-top: 18px;
}

.sl-qr {
  width: 200px;
  height: 200px;
}
</style>
