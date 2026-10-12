<template>
  <!--
    通用文件预览弹框。
    支持图片（直接 <img> 显示）和 PDF（用 PDF.js 在 canvas 上渲染）两种类型。
    可通过 showDownload 控制是否显示下载按钮；下载时可用 downloadName 指定保存文件名。
    走 axios 取 blob（带登录态、被 401 拦截器接住），不用 window.open。
  -->
  <el-dialog
    :model-value="modelValue"
    :title="title || fileName || '文件预览'"
    width="90vw"
    top="5vh"
    :close-on-click-modal="false"
    append-to-body
    destroy-on-close
    @update:model-value="v => emit('update:modelValue', v)"
    @closed="handleClosed"
  >
    <div class="viewer-container" @contextmenu.prevent>
      <!-- 图片 -->
      <div v-if="fileType === 'image'" class="image-wrap">
        <!-- 缩放与 PDF 共用那一排按钮（zoomIn / zoomOut / fitWidth 本来就分了图片分支，
             原先只是没把控件渲染出来）。签字图要靠它放大看笔画，所以补上 -->
        <div class="viewer-toolbar">
          <el-button size="small" :disabled="scale <= 0.2" @click="zoomOut">
            <el-icon><ZoomOut /></el-icon>
          </el-button>
          <span class="scale-text">{{ Math.round(scale * 100) }}%</span>
          <el-button size="small" :disabled="scale >= 3" @click="zoomIn">
            <el-icon><ZoomIn /></el-icon>
          </el-button>
          <el-button size="small" @click="fitWidth">适应窗口</el-button>
        </div>
        <div class="image-canvas-wrap">
          <img
            v-if="imageUrl"
            :src="imageUrl"
            :style="{ transform: `scale(${scale}) rotate(${rotate}deg)` }"
            class="preview-image"
            draggable="false"
            alt="预览图片"
          />
        </div>
      </div>

      <!-- PDF -->
      <div v-else-if="fileType === 'pdf'" class="pdf-wrap">
        <div class="viewer-toolbar">
          <el-button size="small" :disabled="currentPage <= 1" @click="prevPage">
            <el-icon><ArrowLeft /></el-icon>上一页
          </el-button>
          <span class="page-info">
            第 {{ currentPage }} / {{ totalPages }} 页
          </span>
          <el-button size="small" :disabled="currentPage >= totalPages" @click="nextPage">
            下一页<el-icon><ArrowRight /></el-icon>
          </el-button>
          <span class="toolbar-divider" />
          <el-button size="small" :disabled="scale <= 0.5" @click="zoomOut">
            <el-icon><ZoomOut /></el-icon>
          </el-button>
          <span class="scale-text">{{ Math.round(scale * 100) }}%</span>
          <el-button size="small" :disabled="scale >= 3" @click="zoomIn">
            <el-icon><ZoomIn /></el-icon>
          </el-button>
          <el-button size="small" @click="fitWidth">适应宽度</el-button>
        </div>
        <div
          ref="pdfContainerRef"
          v-loading="loadingPdf"
          :element-loading-text="loadingText"
          class="pdf-canvas-wrap"
        >
          <canvas ref="pdfCanvasRef" class="pdf-canvas" />
        </div>
      </div>

      <!-- 不支持的类型 -->
      <div v-else class="unsupported-wrap">
        <el-icon class="unsupported-icon"><Warning /></el-icon>
        <p>不支持在线预览此文件类型</p>
        <p class="unsupported-tip">请点击右上角下载按钮保存后查看</p>
      </div>
    </div>

    <template #footer>
      <span v-if="showDownload && fileType !== 'unknown'">
        <el-button type="primary" :loading="downloading" @click="handleDownload">
          <el-icon v-if="!downloading"><Download /></el-icon>
          <!-- 慢网络下大文件传得久，把百分比写出来免得让人以为卡死了 -->
          {{ downloading && progress ? progress + '%' : '下载' }}
        </el-button>
      </span>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, nextTick, computed, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import * as pdfjsLib from 'pdfjs-dist'
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { fetchBlob, downloadFile, blobErrorDetail } from '@/utils/download'

pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorker

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 文件后端路径，如 /api/leaves/1/proof */
  fileUrl: { type: String, default: '' },
  /** 文件名（用于标题和下载保存名） */
  fileName: { type: String, default: '' },
  /** 弹框标题，不传则用 fileName */
  title: { type: String, default: '' },
  /** 是否显示下载按钮 */
  showDownload: { type: Boolean, default: true },
  /** 下载时的保存文件名，不传则用 fileName */
  downloadName: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

// ---- 判断文件类型 ----
const fileType = computed(() => {
  const name = (props.fileName || '').toLowerCase()
  if (/\.(png|jpe?g|gif|bmp|webp|heic|heif)$/.test(name)) return 'image'
  if (/\.pdf$/.test(name)) return 'pdf'
  return 'unknown'
})

// ---- 图片预览 ----
const imageUrl = ref('')
const scale = ref(1)
const rotate = ref(0)

// ---- PDF 预览 ----
const pdfContainerRef = ref(null)
const pdfCanvasRef = ref(null)
const loadingPdf = ref(false)
const currentPage = ref(1)
const totalPages = ref(0)
let pdfDoc = null
const pdfScale = ref(1.2)

const downloading = ref(false)
// 当前这次取文件的进度 { loaded, total }（total 为 0 表示后端没给 Content-Length）
const progress = ref(null)

// 遮罩上的文字：有 Content-Length 就写清楚下到哪了，没有就只说在加载
const loadingText = computed(() => {
  const p = progress.value
  if (!p || !p.total) return '正在加载…'
  const mb = (n) => (n / 1048576).toFixed(1)
  return `正在加载 ${mb(p.loaded)} / ${mb(p.total)} MB（${Math.round((p.loaded / p.total) * 100)}%）`
})

// 监听弹框打开
watch(() => props.modelValue, async (val) => {
  if (!val) return
  // 重置状态
  scale.value = 1
  rotate.value = 0
  currentPage.value = 1
  totalPages.value = 0
  pdfDoc = null
  imageUrl.value = ''

  await nextTick()

  if (fileType.value === 'image') {
    loadImage()
  } else if (fileType.value === 'pdf') {
    loadPdf()
  }
})

// ---- 加载图片 ----
async function loadImage() {
  try {
    const blob = await fetchBlob(props.fileUrl)
    imageUrl.value = URL.createObjectURL(blob)
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e, '加载失败'))
    emit('update:modelValue', false)
  }
}

// ---- 加载 PDF ----
async function loadPdf() {
  loadingPdf.value = true
  progress.value = null
  try {
    const blob = await fetchBlob(props.fileUrl, (loaded, total) => {
      progress.value = { loaded, total }
    })
    const arrayBuffer = await blob.arrayBuffer()
    const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer })
    pdfDoc = await loadingTask.promise
    totalPages.value = pdfDoc.numPages
    await nextTick()
    await fitWidth()
  } catch (e) {
    ElMessage.error('PDF 加载失败：' + (e.message || '未知错误'))
    emit('update:modelValue', false)
  } finally {
    loadingPdf.value = false
  }
}

async function renderPdfPage(pageNum) {
  if (!pdfDoc || !pdfCanvasRef.value) return
  try {
    const page = await pdfDoc.getPage(pageNum)
    const viewport = page.getViewport({ scale: pdfScale.value })
    const canvas = pdfCanvasRef.value
    const ctx = canvas.getContext('2d')
    const dpr = window.devicePixelRatio || 1
    canvas.width = viewport.width * dpr
    canvas.height = viewport.height * dpr
    canvas.style.width = viewport.width + 'px'
    canvas.style.height = viewport.height + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    await page.render({ canvasContext: ctx, viewport }).promise
  } catch (e) {
    console.warn('渲染 PDF 页失败', e)
  }
}

function prevPage() {
  if (currentPage.value > 1) {
    currentPage.value--
    renderPdfPage(currentPage.value)
  }
}

function nextPage() {
  if (currentPage.value < totalPages.value) {
    currentPage.value++
    renderPdfPage(currentPage.value)
  }
}

function zoomIn() {
  if (fileType.value === 'image') {
    scale.value = Math.min(3, +(scale.value + 0.2).toFixed(1))
  } else if (fileType.value === 'pdf') {
    pdfScale.value = Math.min(3, +(pdfScale.value + 0.2).toFixed(1))
    renderPdfPage(currentPage.value)
  }
}

function zoomOut() {
  if (fileType.value === 'image') {
    scale.value = Math.max(0.2, +(scale.value - 0.2).toFixed(1))
  } else if (fileType.value === 'pdf') {
    pdfScale.value = Math.max(0.5, +(pdfScale.value - 0.2).toFixed(1))
    renderPdfPage(currentPage.value)
  }
}

async function fitWidth() {
  if (fileType.value === 'image') {
    scale.value = 1
  } else if (fileType.value === 'pdf' && pdfDoc && pdfContainerRef.value) {
    const page = await pdfDoc.getPage(1)
    const containerWidth = pdfContainerRef.value.clientWidth - 40
    const viewport = page.getViewport({ scale: 1 })
    pdfScale.value = +(containerWidth / viewport.width).toFixed(2)
    renderPdfPage(currentPage.value)
  }
}

// ---- 下载 ----
async function handleDownload() {
  const saveName = props.downloadName || props.fileName || 'download'
  downloading.value = true
  progress.value = null
  try {
    await downloadFile(props.fileUrl, saveName, (loaded, total) => {
      progress.value = { loaded, total }
    })
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e))
  } finally {
    downloading.value = false
  }
}

// ---- 清理 ----
function handleClosed() {
  if (imageUrl.value) {
    URL.revokeObjectURL(imageUrl.value)
    imageUrl.value = ''
  }
  if (pdfDoc) {
    pdfDoc = null
  }
  scale.value = 1
  pdfScale.value = 1.2
  currentPage.value = 1
  totalPages.value = 0
}

onBeforeUnmount(() => {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  if (pdfDoc) pdfDoc = null
})
</script>

<style scoped>
.viewer-container {
  width: 100%;
  min-height: 300px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
}

/* 图片预览 */
.image-wrap {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: calc(90vh - 200px);
}

.image-canvas-wrap {
  flex: 1;
  overflow: auto;
  padding: 20px;
  box-sizing: border-box;
  display: flex;
}

.preview-image {
  /* margin: auto 而不是 justify-content: center —— 放大到溢出时，
     居中会把左上角推到滚动区外面，滚不回去 */
  margin: auto;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  transition: transform 0.2s;
  user-select: none;
  -webkit-user-drag: none;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
}

/* PDF 预览 */
.pdf-wrap {
  display: flex;
  flex-direction: column;
  height: calc(90vh - 200px);
}

/* 图片与 PDF 共用的一排工具按钮 */
.viewer-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
}

.page-info {
  font-size: 13px;
  color: var(--el-text-color-regular);
  min-width: 90px;
  text-align: center;
}

.toolbar-divider {
  width: 1px;
  height: 20px;
  background: var(--el-border-color-light);
  margin: 0 6px;
}

.scale-text {
  font-size: 13px;
  color: var(--el-text-color-regular);
  min-width: 48px;
  text-align: center;
}

.pdf-canvas-wrap {
  position: relative;
  flex: 1;
  overflow: auto;
  padding: 20px;
  box-sizing: border-box;
  display: flex;
  justify-content: center;
}

.pdf-canvas {
  display: block;
  /* 这里固定白色，不跟深色模式：PDF 渲染出来就是一页白纸，
     画布跟着变深反而会在纸的边缘露出一圈灰底 */
  background: #fff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
  -webkit-user-drag: none;
  user-select: none;
}

/* 不支持预览 */
.unsupported-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: calc(90vh - 200px);
  color: var(--el-text-color-secondary);
}

.unsupported-icon {
  font-size: 48px;
  margin-bottom: 12px;
  color: #e6a23c;
}

.unsupported-wrap p {
  margin: 4px 0;
}

.unsupported-tip {
  font-size: 12px;
  color: var(--el-text-color-disabled);
}
</style>
