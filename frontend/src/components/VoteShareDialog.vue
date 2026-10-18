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
    <el-result icon="success" :title="`投票：${poll?.title || '投票表决'}`">
      <template #sub-title>
        <div class="vs-badges">
          <el-tag :type="poll?.anonymous ? 'warning' : 'primary'" size="small">
            {{ poll?.anonymous ? '不记名' : '记名' }}
          </el-tag>
          <span>应投 {{ poll?.target_count || 0 }} 人</span>
          <span>· {{ poll?.question_count || 0 }} 道题</span>
        </div>
      </template>
    </el-result>

    <div v-if="poll?.description" class="vs-remark">
      <span class="vs-label">备注</span>
      <span>{{ poll.description }}</span>
    </div>
    <p class="vs-deadline">截止 {{ formatDateTime(poll?.end_at) }}</p>

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
import { formatDateTime } from '@/utils/format'
import { makeQrDataUrl } from '@/utils/qr'
import { SITE } from '@/utils/site'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  link: { type: String, default: '' },
  poll: { type: Object, default: () => ({}) }
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
.vs-badges {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.vs-remark {
  display: flex;
  gap: 8px;
  max-width: 420px;
  margin: 4px auto 0;
  color: var(--el-text-color-regular);
  font-size: 14px;
  line-height: 1.7;
}

.vs-label {
  flex: none;
  color: var(--el-text-color-secondary);
}

.vs-deadline {
  margin: 8px 0 16px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

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
