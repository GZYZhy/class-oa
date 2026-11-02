<!--
  拖动拼图验证码

  后端出图（一张挖了缺口的背景 + 一块从背景上真实抠下来的拼图），前端只负责把块
  拖过去。**答案不在前端**：v-model 交出去的是「按原图坐标算的横向位置」，
  对错由登录接口校验，所以拖到哪儿都不会在本地出现「通过」字样。

  显示宽度跟着容器走（手机上也放得下），提交前用显示宽度换算回原图坐标。
-->
<template>
  <div class="sc">
    <div ref="stageRef" class="sc-stage" :style="{ aspectRatio: ratio }">
      <template v-if="data">
        <img class="sc-bg" :src="data.background" alt="" draggable="false" />
        <img
          class="sc-piece"
          :src="data.puzzle"
          alt=""
          draggable="false"
          :style="{ left: offset + 'px', top: pieceTop + 'px', width: pieceWidth + 'px' }"
        />
      </template>

      <div v-else-if="failed" class="sc-placeholder" @click="load">
        <el-icon><Refresh /></el-icon>
        <span>验证码加载失败，点击重试</span>
      </div>
      <div v-else class="sc-placeholder">
        <span>正在生成拼图…</span>
      </div>

      <!-- 换一张：不改变答案之外的东西，只重新拉图 -->
      <div v-if="data" class="sc-refresh" title="换一张" @click="reset">
        <el-icon><Refresh /></el-icon>
      </div>
    </div>

    <div
      class="sc-track"
      @pointerdown="onDown"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="onUp"
    >
      <div class="sc-fill" :style="{ width: offset + 'px' }"></div>
      <div class="sc-thumb" :style="{ transform: `translateX(${offset}px)` }">
        <el-icon><ArrowRight /></el-icon>
      </div>
      <span class="sc-hint">{{ hint }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { getCaptchaSlide } from '@/api/auth'

const props = defineProps({
  /** 拖到的横向位置（原图坐标）。空串 = 还没拖 */
  modelValue: { type: [String, Number], default: '' }
})
const emit = defineEmits(['update:modelValue'])

const stageRef = ref(null)
const data = ref(null)
const failed = ref(false)
const offset = ref(0)
const stageWidth = ref(0)
const dragging = ref(false)
let startX = 0

const ratio = computed(() => {
  if (!data.value) return '320 / 160'
  return `${data.value.width} / ${data.value.height}`
})

/** 显示宽度 / 原图宽度。提交前乘回去，后端只认原图坐标 */
const scale = computed(() => {
  if (!data.value) return 1
  return data.value.width / (stageWidth.value || data.value.width)
})

const pieceWidth = computed(
  () => (data.value?.puzzle_width || data.value?.puzzle_size || 0) / scale.value
)
const pieceTop = computed(() => (data.value?.y || 0) / scale.value)
const maxOffset = computed(() => Math.max(0, stageWidth.value - pieceWidth.value))

const hint = computed(() => {
  if (!data.value) return failed.value ? '验证码不可用' : '正在加载验证码…'
  return '向右拖动滑块完成拼图'
})

function measure() {
  stageWidth.value = stageRef.value?.clientWidth || 0
}

async function load() {
  failed.value = false
  data.value = null
  offset.value = 0
  emit('update:modelValue', '')
  try {
    data.value = await getCaptchaSlide()
    await nextTick()
    measure()
  } catch (e) {
    // 拉不到图不影响登录其余部分：提示重试，别把页面卡住
    failed.value = true
  }
}

/** 换一张：位置和提交值一起清掉 */
function reset() {
  load()
}

function onDown(event) {
  if (!data.value) return
  dragging.value = true
  startX = event.clientX - offset.value
  // 指针移出轨道也要继续跟着走，否则手一抖就断
  event.currentTarget?.setPointerCapture?.(event.pointerId)
}

function onMove(event) {
  if (!dragging.value) return
  offset.value = Math.min(Math.max(event.clientX - startX, 0), maxOffset.value)
}

function onUp() {
  if (!dragging.value) return
  dragging.value = false
  // 交回原图坐标：显示宽度可能比 320 窄（手机）
  emit('update:modelValue', Math.round(offset.value * scale.value))
}

watch(() => props.modelValue, (value) => {
  // 父组件清空（登录失败）时把块也放回起点
  if ((value === '' || value === null) && offset.value !== 0) {
    offset.value = 0
  }
})

onMounted(() => {
  measure()
  window.addEventListener('resize', measure)
  load()
})

onUnmounted(() => {
  window.removeEventListener('resize', measure)
})

defineExpose({ reset })
</script>

<style scoped>
.sc {
  width: 100%;
}

.sc-stage {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: 10px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
  user-select: none;
  touch-action: pan-y;
}

.sc-bg {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  pointer-events: none;
}

.sc-piece {
  position: absolute;
  pointer-events: none;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.25));
}

.sc-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  cursor: pointer;
}

.sc-refresh {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.35);
  color: #fff;
  cursor: pointer;
  transition: background 0.2s;
}

.sc-refresh:hover {
  background: rgba(0, 0, 0, 0.55);
}

.sc-track {
  position: relative;
  height: 44px;
  margin-top: 10px;
  border-radius: 10px;
  background: var(--el-fill-color);
  border: 1px solid var(--el-border-color);
  overflow: hidden;
  touch-action: none;
  cursor: pointer;
}

.sc-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--el-color-primary-light-7);
}

.sc-thumb {
  position: absolute;
  top: -1px;
  left: 0;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: var(--el-color-primary);
  color: #fff;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.35);
  cursor: grab;
}

.sc-thumb:active {
  cursor: grabbing;
}

.sc-hint {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  pointer-events: none;
}
</style>
