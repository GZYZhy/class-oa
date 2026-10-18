<!--
  手写签名画布：学生「我的档案」和班委/管理员的批量签字共用这一块。

  产出固定是「黑色墨迹 + 透明背景」的 PNG，并且自动裁掉画布四周的空白 ——
  PDF 里签字图按整图等比缩放，留着大片空白会把名字缩得很小。
  使用方只需要监听 confirm 拿到 Blob，怎么传（传给自己 / 传给谁）由使用方决定。

  画布尺寸必须等容器可见之后再调 init()：
  el-dialog 的内容是打开时才渲染的，在 setup 里量出来是 0。
-->
<template>
  <div class="sign-pad">
    <div class="sp-head">
      <span class="sp-label">签名人</span>
      <span class="sp-name">{{ signerName || '—' }}</span>
      <span v-if="signerNo" class="sp-no">{{ signerNo }}</span>
    </div>

    <div class="sp-board" :class="{ 'is-previewing': previewing }">
      <!-- 两个元素互斥显示：canvas 一旦隐藏就不能继续画，但已经画好的内容还在 -->
      <canvas v-show="!previewing" ref="canvasRef" class="sp-canvas" />
      <img v-if="previewing" :src="previewUrl" class="sp-preview" alt="签名预览" />
      <span v-if="!previewing && !hasInk" class="sp-hint">请在此处签名</span>
    </div>

    <p class="sp-tip">
      用手指、触控笔或鼠标在框内书写；保存后自动裁剪留白，生成黑色墨迹、透明背景的 PNG。
    </p>

    <div class="sp-actions">
      <template v-if="!previewing">
        <el-button :disabled="submitting" @click="reset">重写</el-button>
        <el-button type="primary" :disabled="!hasInk || submitting" @click="openPreview">
          预览
        </el-button>
      </template>
      <template v-else>
        <span class="sp-size">
          透明 PNG · {{ previewSize }}<template v-if="previewDimensions"> · {{ previewDimensions }}</template>
        </span>
        <el-button :disabled="submitting" @click="reset">重写</el-button>
        <el-button :disabled="submitting" @click="backToEdit">返回修改</el-button>
        <el-button type="primary" :loading="submitting" @click="confirmUse">确认使用</el-button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import SignaturePadLib from 'signature_pad'
import { exportSignaturePng } from '@/utils/signatureImage'

const props = defineProps({
  signerName: { type: String, default: '' },
  signerNo: { type: String, default: '' },
  /** 使用方正在上传时置 true，锁住按钮并让「确认使用」转圈 */
  submitting: { type: Boolean, default: false }
})

const emit = defineEmits(['confirm'])

const canvasRef = ref(null)
// 有没有落过笔：决定「预览」按钮能不能点。不能直接用 pad.isEmpty()，
// 它只是个普通属性，改了不会触发重渲染
const hasInk = ref(false)
const previewing = ref(false)
const previewUrl = ref('')
const previewSize = ref('')
const previewDimensions = ref('')

let pad = null
let previewBlob = null

/**
 * 初始化（或重新初始化）画布。可以在每次打开弹窗 / 进入签名步骤时放心调用。
 *
 * signature_pad v5 不再自己处理高 DPI，坐标用的是 CSS 像素，
 * 所以这里按 devicePixelRatio 放大 backing store，再把上下文整体缩放回去，
 * 手指画的线才会清晰。
 */
function init() {
  const canvas = canvasRef.value
  if (!canvas) return

  backToEdit()

  const rect = canvas.getBoundingClientRect()
  if (!rect.width || !rect.height) return // 容器还不可见，等下一次

  const ratio = Math.min(window.devicePixelRatio || 1, 3)
  canvas.width = Math.round(rect.width * ratio)
  canvas.height = Math.round(rect.height * ratio)

  const ctx = canvas.getContext('2d')
  // 改 canvas.width 会清空上下文状态，缩放在这之后设
  ctx.scale(ratio, ratio)

  if (pad) pad.off()
  pad = new SignaturePadLib(canvas, {
    // 笔画细一点更接近真实签名；太粗在 PDF 的小框里会糊成一团
    minWidth: 0.6,
    maxWidth: 2.2,
    penColor: '#000'
  })
  pad.addEventListener('endStroke', () => {
    hasInk.value = !pad.isEmpty()
  })
  hasInk.value = false
}

/** 清空笔迹并回到书写状态。批量签字换到下一个人时调它 */
function reset() {
  backToEdit()
  if (pad) pad.clear()
  hasInk.value = false
}

/** 导出前先给用户看一眼，确认没问题再上传 */
async function openPreview() {
  const result = pad && !pad.isEmpty() ? await exportSignaturePng(canvasRef.value) : null
  if (!result) {
    ElMessage.warning('请先签名')
    return
  }

  releasePreview()
  previewBlob = result.blob
  previewUrl.value = URL.createObjectURL(result.blob)
  previewSize.value = formatSize(result.blob.size)
  previewDimensions.value = `${result.width} × ${result.height}`
  previewing.value = true
}

/** 回到书写状态但保留笔迹，方便再补几笔 */
function backToEdit() {
  previewing.value = false
  releasePreview()
}

function releasePreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  previewBlob = null
  previewSize.value = ''
  previewDimensions.value = ''
}

function confirmUse() {
  if (!previewBlob || props.submitting) return
  // 用元组多带一份尺寸/体积，使用方想提示大小的话直接用，不必再读一遍 blob
  emit('confirm', previewBlob, {
    size: previewBlob.size,
    width: previewDimensions.value
  })
}

function formatSize(bytes) {
  if (!bytes) return '0 KB'
  if (bytes < 1024) return `${bytes} B`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

onBeforeUnmount(() => {
  pad?.off()
  releasePreview()
})

// 父组件拿到 ref 后调 init() / reset()
defineExpose({ init, reset })
</script>

<style scoped>
.sp-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
}

.sp-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.sp-name {
  font-size: 18px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.sp-no {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: monospace;
}

/* 签名板固定白底：黑墨迹要有足够对比，深色模式下也保持「白纸」的样子 */
.sp-board {
  position: relative;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

/* 预览时铺一层浅色棋盘格，一眼能看出背景是透明的 */
.sp-board.is-previewing {
  background-color: #fff;
  background-image:
    linear-gradient(45deg, #f2f2f2 25%, transparent 25%),
    linear-gradient(-45deg, #f2f2f2 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #f2f2f2 75%),
    linear-gradient(-45deg, transparent 75%, #f2f2f2 75%);
  background-size: 16px 16px;
  background-position: 0 0, 0 8px, 8px -8px, -8px 0;
}

.sp-canvas {
  display: block;
  width: 100%;
  height: 200px;
  cursor: crosshair;
}

.sp-preview {
  display: block;
  margin: 16px auto;
  max-width: calc(100% - 32px);
  max-height: 160px;
}

.sp-hint {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #c0c4cc;
  pointer-events: none;
}

.sp-tip {
  margin: 8px 0 12px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.sp-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.sp-size {
  margin-right: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .sp-canvas {
    height: 170px;
  }
}
</style>
