<template>
  <!--
    内嵌式 PDF 查看器（弹框）。
    用 PDF.js 在 canvas 上渲染，不走浏览器原生 PDF 查看器，
    这样可以：1) 不放下载/打印按钮；2) 在内容上层叠水印；3) 禁用右键另存为。
    注：前端层面只能提高绕过门槛，不能做到 100% 防下载（抓包仍能拿到 blob）。
    真正的权限边界在后端（普通学生调不到 download=true）。
  -->
  <el-dialog
    :model-value="modelValue"
    :title="title || '查看文件'"
    width="90vw"
    top="5vh"
    :close-on-click-modal="false"
    append-to-body
    destroy-on-close
    @update:model-value="v => emit('update:modelValue', v)"
    @closed="handleClosed"
  >
    <div class="pdf-toolbar">
      <div class="toolbar-left">
        <el-button size="small" :disabled="currentPage <= 1" @click="prevPage">
          <el-icon><ArrowLeft /></el-icon>
          上一页
        </el-button>
        <span class="page-indicator">
          第
          <el-input-number
            v-model="currentPage"
            :min="1"
            :max="totalPages || 1"
            size="small"
            controls-position="right"
            style="width: 110px; margin: 0 4px;"
            @change="renderPage(currentPage)"
          />
          页 / 共 {{ totalPages }} 页
        </span>
        <el-button size="small" :disabled="currentPage >= totalPages" @click="nextPage">
          下一页
          <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-button size="small" :disabled="scale <= 0.5" @click="zoomOut">
          <el-icon><ZoomOut /></el-icon>
        </el-button>
        <span class="scale-text">{{ Math.round(scale * 100) }}%</span>
        <el-button size="small" :disabled="scale >= 3" @click="zoomIn">
          <el-icon><ZoomIn /></el-icon>
        </el-button>
        <el-button size="small" @click="fitWidth">
          <el-icon><Aim /></el-icon>
          <span class="fit-width-text">适应宽度</span>
        </el-button>
      </div>
    </div>

    <!-- 外层：定位基准，不滚动。热区和底部栏挂在这里，一直固定在视口位置 -->
    <div class="pdf-viewer-wrap">
      <!-- 滚动区：canvas + 水印在这里面滚，滚到哪里水印都铺在内容上 -->
      <div
        ref="containerRef"
        v-loading="loading"
        :element-loading-text="loadingText"
        class="pdf-container"
        @contextmenu.prevent="onContextMenu"
      >
        <div class="canvas-wrap">
          <canvas ref="canvasRef" class="pdf-canvas" />
          <!-- keep-dark：水印铺在白纸画布上，深色模式下也不该反转 -->
          <Watermark :text="watermarkText" class="canvas-watermark" keep-dark />
        </div>
      </div>

      <!-- 左右两侧点击热区：挂在外层，固定在视口左右，不随内容滚动 -->
      <div
        class="page-hit page-hit-left"
        :class="{ disabled: currentPage <= 1 }"
        @click="prevPage"
        aria-label="上一页"
      >
        <el-icon v-if="totalPages > 1" class="hit-icon"><ArrowLeft /></el-icon>
      </div>
      <div
        class="page-hit page-hit-right"
        :class="{ disabled: currentPage >= totalPages }"
        @click="nextPage"
        aria-label="下一页"
      >
        <el-icon v-if="totalPages > 1" class="hit-icon"><ArrowRight /></el-icon>
      </div>

      <!-- 底部浮动翻页栏：挂在外层，固定在视口底部，不随内容滚动 -->
      <div v-if="totalPages > 1" class="bottom-bar">
        <el-button size="small" :disabled="currentPage <= 1" @click="prevPage">
          <el-icon><ArrowLeft /></el-icon>
          上一页
        </el-button>
        <span class="bottom-page-text">
          {{ currentPage }} / {{ totalPages }}
        </span>
        <el-button size="small" :disabled="currentPage >= totalPages" @click="nextPage">
          下一页
          <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import * as pdfjsLib from 'pdfjs-dist'
// Vite 打包时 worker 走 ?url 形式，避免额外配置
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import Watermark from './Watermark.vue'
import { useWatermark } from '@/composables/useWatermark'
import { fetchBlob } from '@/utils/download'

// 设置 PDF.js worker
pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorker

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** PDF 文件的后端路径，如 /api/announcements/file/xxx.pdf */
  fileUrl: { type: String, default: '' },
  /** 弹框标题 */
  title: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

const watermarkText = useWatermark()

const containerRef = ref(null)
const canvasRef = ref(null)
const loading = ref(false)
const currentPage = ref(1)
const totalPages = ref(0)
const scale = ref(1.2)
// 下载进度 { loaded, total }，还没拿到 Content-Length 时 total 为 0
const progress = ref(null)

let pdfDoc = null
// 当前这次取文件的请求（关弹框时要把它掐掉，见 handleClosed）
let abortCtrl = null

// 遮罩上的文字。后端给了 Content-Length 就写清楚「下到哪了」，
// 没给就只说在加载 —— 编不出进度就别编
const loadingText = computed(() => {
  const p = progress.value
  if (!p || !p.total) return '正在加载…'
  const mb = (n) => (n / 1048576).toFixed(1)
  return `正在加载 ${mb(p.loaded)} / ${mb(p.total)} MB（${Math.round((p.loaded / p.total) * 100)}%）`
})

// 监听弹框打开：加载 PDF
watch(() => props.modelValue, async (val) => {
  if (val && props.fileUrl) {
    await nextTick()
    loadPdf()
  }
})

async function loadPdf() {
  if (!props.fileUrl) return
  loading.value = true
  currentPage.value = 1
  progress.value = null
  try {
    // 经 axios 取回 blob（这样带登录态、能被 401 拦截器接住），
    // 再转成 ArrayBuffer 喂给 PDF.js。回调把进度写进 loadingText
    abortCtrl = new AbortController()
    const blob = await fetchBlob(props.fileUrl, (loaded, total) => {
      progress.value = { loaded, total }
    }, abortCtrl.signal)
    const arrayBuffer = await blob.arrayBuffer()
    const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer })
    pdfDoc = await loadingTask.promise
    totalPages.value = pdfDoc.numPages
    // 等 DOM 就绪再渲染第一页
    await nextTick()
    await fitWidth()
  } catch (e) {
    // 自己掐掉的（关弹框）不算失败：别弹红字，也别再去关一次已经关了的弹框
    if (e?.code === 'ERR_CANCELED' || e?.name === 'CanceledError') return
    ElMessage.error('文件加载失败：' + (e.message || '未知错误'))
    emit('update:modelValue', false)
  } finally {
    loading.value = false
  }
}

async function renderPage(pageNum) {
  if (!pdfDoc || !canvasRef.value) return
  try {
    const page = await pdfDoc.getPage(pageNum)
    const viewport = page.getViewport({ scale: scale.value })
    const canvas = canvasRef.value
    const ctx = canvas.getContext('2d')
    // 按设备像素比渲染，避免高分屏发虚
    const dpr = window.devicePixelRatio || 1
    canvas.width = viewport.width * dpr
    canvas.height = viewport.height * dpr
    canvas.style.width = viewport.width + 'px'
    canvas.style.height = viewport.height + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    await page.render({
      canvasContext: ctx,
      viewport: viewport,
    }).promise
  } catch (e) {
    // 页码输入不合法等情况
    console.warn('渲染 PDF 页失败', e)
  }
}

function prevPage() {
  if (currentPage.value > 1) {
    currentPage.value--
    renderPage(currentPage.value)
  }
}

function nextPage() {
  if (currentPage.value < totalPages.value) {
    currentPage.value++
    renderPage(currentPage.value)
  }
}

function zoomIn() {
  if (scale.value < 3) {
    scale.value = Math.min(3, +(scale.value + 0.2).toFixed(1))
    renderPage(currentPage.value)
  }
}

function zoomOut() {
  if (scale.value > 0.5) {
    scale.value = Math.max(0.5, +(scale.value - 0.2).toFixed(1))
    renderPage(currentPage.value)
  }
}

/** 按容器宽度自动适配缩放 */
async function fitWidth() {
  if (!pdfDoc || !containerRef.value) return
  const page = await pdfDoc.getPage(1)
  // 容器内边距留 40px 余量，避免出现横向滚动条
  const containerWidth = containerRef.value.clientWidth - 40
  const viewport = page.getViewport({ scale: 1 })
  scale.value = +(containerWidth / viewport.width).toFixed(2)
  renderPage(currentPage.value)
}

/** 阻止右键菜单（防另存为图片等） */
function onContextMenu() {
  // 静默阻止，不弹提示，免得用户觉得此地无银
}

/** 全局键盘：阻止保存/打印，再加翻页快捷键 */
function onKeydown(e) {
  if (!props.modelValue) return

  // Ctrl/Cmd + S 保存、Ctrl/Cmd + P 打印
  if ((e.ctrlKey || e.metaKey) && ['s', 'p', 'S', 'P'].includes(e.key)) {
    e.preventDefault()
    return
  }

  // 翻页快捷键：弹框打开时生效
  // 左箭头 / PageUp / Backspace → 上一页
  // 右箭头 / 空格 / PageDown / Enter → 下一页
  // Home → 第一页，End → 最后一页
  switch (e.key) {
    case 'ArrowLeft':
    case 'PageUp':
    case 'Backspace':
      if (currentPage.value > 1) {
        e.preventDefault()
        prevPage()
      }
      break
    case 'ArrowRight':
    case ' ':
    case 'PageDown':
    case 'Enter':
      if (currentPage.value < totalPages.value) {
        e.preventDefault()
        nextPage()
      }
      break
    case 'Home':
      if (currentPage.value !== 1) {
        e.preventDefault()
        currentPage.value = 1
        renderPage(1)
      }
      break
    case 'End':
      if (currentPage.value !== totalPages.value) {
        e.preventDefault()
        currentPage.value = totalPages.value
        renderPage(totalPages.value)
      }
      break
    case '+':
    case '=':
      e.preventDefault()
      zoomIn()
      break
    case '-':
    case '_':
      e.preventDefault()
      zoomOut()
      break
  }
}

function handleClosed() {
  // 弹框关闭时释放资源
  pdfDoc = null
  totalPages.value = 0
  currentPage.value = 1
  scale.value = 1.2
  progress.value = null
  // 文件还在传就掐掉它：慢网络下大文件能传好几分钟，
  // 用户已经关掉弹框了，没必要继续占着带宽
  if (abortCtrl) {
    abortCtrl.abort()
    abortCtrl = null
  }
  if (canvasRef.value) {
    const ctx = canvasRef.value.getContext('2d')
    ctx.clearRect(0, 0, canvasRef.value.width, canvasRef.value.height)
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (pdfDoc) pdfDoc = null
  // 离开页面时同理：别把一个还在传的大文件留在后台
  if (abortCtrl) abortCtrl.abort()
})
</script>

<style scoped>
.pdf-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  margin-bottom: 12px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  flex-wrap: wrap;
  row-gap: 6px;
  column-gap: 8px;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.page-indicator {
  font-size: 13px;
  color: var(--el-text-color-regular);
  display: flex;
  align-items: center;
}

.scale-text {
  font-size: 13px;
  color: var(--el-text-color-regular);
  min-width: 48px;
  text-align: center;
}

/* 外层：定位基准，不滚动。热区和底部栏都挂在这里 */
.pdf-viewer-wrap {
  position: relative;
  width: 100%;
  height: calc(90vh - 160px);
  border-radius: 4px;
  overflow: hidden; /* 防止底部栏/热区溢出圆角 */
}

/* 滚动区：负责内容滚动 + v-loading 的定位基准 */
.pdf-container {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: auto;
  /* 白纸周围的留白。用 fill-color 而不是写死的浅灰，深色模式下才有一圈深灰衬着 */
  background: var(--el-fill-color);
}

.canvas-wrap {
  position: relative; /* 作为水印的定位基准 */
  display: flex;
  justify-content: center;
  padding: 20px;
  min-height: 100%;
}

/* 水印跟着 canvas 走：宽高等于 canvas 内容区域，随内容一起滚动，
   这样滚到任何位置水印都铺在上面，不会出现下半页空白 */
.canvas-watermark {
  position: absolute !important;
  inset: 20px; /* 和 canvas-wrap 的 padding 对齐，刚好覆盖 canvas 区域 */
  width: auto !important;
  height: auto !important;
}

.pdf-canvas {
  display: block;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
  /* 这里固定白色，不跟深色模式：PDF 渲染出来就是一页白纸，
     画布跟着变深反而会在纸的边缘露出一圈灰底 */
  background: #fff;
  /* 防止被拖拽保存 */
  -webkit-user-drag: none;
  user-select: none;
}

/* ---- 左右两侧点击热区：手机上点左/右半页翻页 ---- */
.page-hit {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 25%;
  z-index: 10;
  cursor: pointer;
  display: flex;
  align-items: center;
  /* 默认轻微可见，让用户知道这里能点；hover 时变明显 */
  opacity: 0.3;
  transition: opacity 0.2s;
}
.page-hit:hover {
  opacity: 1;
}
.page-hit.disabled {
  cursor: default;
  opacity: 0 !important;
  pointer-events: none;
}
.page-hit-left {
  left: 0;
  justify-content: flex-start;
  padding-left: 12px;
}
.page-hit-right {
  right: 0;
  justify-content: flex-end;
  padding-right: 12px;
}
.hit-icon {
  font-size: 32px;
  color: rgba(0, 0, 0, 0.25);
  background: rgba(255, 255, 255, 0.6);
  border-radius: 50%;
  padding: 8px;
}

/* ---- 底部浮动翻页栏 ---- */
.bottom-bar {
  position: absolute;
  left: 50%;
  bottom: 16px;
  transform: translateX(-50%);
  z-index: 11;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  border-radius: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.12);
}
.bottom-page-text {
  font-size: 13px;
  color: var(--el-text-color-regular);
  min-width: 60px;
  text-align: center;
}

/* 窄屏 / 手机：工具栏挤的时候，把「适应宽度」文字收起来只留图标，
   再把左右两组的间距收一收，避免溢出弹框 */
@media (max-width: 640px) {
  .fit-width-text {
    display: none;
  }
  .toolbar-left,
  .toolbar-right {
    gap: 4px;
  }
  .page-indicator {
    font-size: 12px;
  }
  .scale-text {
    font-size: 12px;
    min-width: 40px;
  }
  /* 手机上点击热区留一点可见提示，不然用户不知道能点 */
  .page-hit {
    opacity: 0.4;
  }
  .hit-icon {
    font-size: 24px;
    padding: 6px;
  }
  .bottom-bar {
    bottom: 10px;
    gap: 8px;
    padding: 4px 8px;
  }
}
</style>
