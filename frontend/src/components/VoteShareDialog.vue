<!--
  投票分享：链接 + 复制 + 二维码。
  和签到不同，投票不另做公开分享页 —— 链接就是投票页本身，
  页面打开时会写上 OG 标签，微信里转发时尽量用投票标题做卡片。
-->
<template>
  <el-dialog
    v-model="visible"
    title="分享投票"
    width="520px"
    :close-on-click-modal="false"
    @closed="qrDataUrl = ''"
  >
    <div class="vs-link">
      <el-input :model-value="link" readonly />
      <el-button type="primary" @click="copyText(link)">复制</el-button>
    </div>
    <div v-if="qrDataUrl" class="vs-qr-wrap">
      <img :src="qrDataUrl" class="vs-qr" alt="投票二维码" />
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
.vs-link {
  display: flex;
  gap: 8px;
}

.vs-qr-wrap {
  margin-top: 16px;
  text-align: center;
}

.vs-qr {
  width: 300px;
  max-width: 80vw;
  padding: 12px;
  box-sizing: border-box;
  background: #fff;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}
</style>
