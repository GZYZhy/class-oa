<!--
  单人签字弹窗：给「我的档案」这类只需要签一张的地方用。
  批量签字不走这个组件 —— 它要一直开着逐人切换，直接把 SignaturePad 内嵌在批量弹窗里更省事。
-->
<template>
  <el-dialog
    v-model="visible"
    :title="title"
    :width="dialogWidth"
    :close-on-click-modal="false"
    @opened="padRef?.init()"
  >
    <SignaturePad
      ref="padRef"
      :signer-name="signerName"
      :signer-no="signerNo"
      :submitting="submitting"
      @confirm="(blob, meta) => emit('confirm', blob, meta)"
    />
    <template #footer>
      <el-button :disabled="submitting" @click="visible = false">取消</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import SignaturePad from '@/components/SignaturePad.vue'
import { useIsMobile } from '@/composables/useIsMobile'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '手写签名' },
  signerName: { type: String, default: '' },
  signerNo: { type: String, default: '' },
  submitting: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'confirm'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

// 窄屏用百分比：固定 560px 在手机上会超出屏幕
const isMobile = useIsMobile()
const dialogWidth = computed(() => (isMobile.value ? '94%' : '560px'))

const padRef = ref(null)
</script>
