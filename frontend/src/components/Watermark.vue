<template>
  <!--
    斜线循环水印。用法：把 <Watermark :text="..." /> 放进一个 position: relative 的容器里，
    它会铺满整个容器。
    水印只做展示，不挡操作也不可选中（pointer-events / user-select 均已关掉）。
  -->
  <div class="watermark">
    <span v-for="i in COUNT" :key="i" class="watermark-text">{{ text }}</span>
  </div>
</template>

<script setup>
defineProps({
  /** 水印字样，形如「张邗语@统26-1班 9月24日 14:30」 */
  text: { type: String, required: true }
})

// 铺满容器需要多少个字样随容器大小变化。这里取一个够用的固定值，
// 多出来的会被 overflow: hidden 裁掉 —— 好过用 JS 去量容器尺寸
const COUNT = 160
</script>

<style scoped>
.watermark {
  position: absolute;
  inset: 0;
  z-index: 9;
  overflow: hidden;
  display: flex;
  flex-wrap: wrap;
  align-content: flex-start;
  justify-content: space-between;
  pointer-events: none;
  user-select: none;
}

.watermark-text {
  padding: 30px 12px;
  font-size: 18px;
  color: rgba(0, 0, 0, 0.08);
  white-space: nowrap;
  transform: rotate(-24deg);
}

/* 手机上屏幕窄，字号跟着收一点，否则一行放不下几个字样、显得糊成一片 */
@media (max-width: 768px) {
  .watermark-text {
    padding: 22px 8px;
    font-size: 13px;
  }
}
</style>
