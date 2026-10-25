<template>
  <!--
    斜线循环水印。用法：把 <Watermark :text="..." /> 放进一个 position: relative 的容器里，
    它会铺满整个容器。
    水印只做展示，不挡操作也不可选中（pointer-events / user-select 均已关掉）。

    实现：用 SVG 生成一个「水印单元」，再靠 background-repeat 平铺整个容器。
    比原先 flex 排 160 个 span 的方案更稳：
    1) 不管容器多高多窄都一定铺满，不会出现「下半页空白」「手机上右半边空白」
    2) 不生成上百个 DOM 节点，渲染更快
  -->
  <div
    class="watermark"
    :class="{ 'keep-dark': keepDark }"
    :style="{
      '--wm-svg': svgDataUrl,
      '--wm-svg-mobile': svgDataUrlMobile
    }"
  ></div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** 水印字样，形如「张三@示例班 9月24日 14:30」 */
  text: { type: String, required: true },
  /**
   * 底色固定是白的（如 PDF 的白纸画布）时传 true，水印保持深色不反转。
   * 详见样式里那段说明。
   */
  keepDark: { type: Boolean, default: false }
})

// 桌面端水印单元尺寸 / 字号
const FONT_SIZE = 18
// 手机端字号。**别再往小了调**：水印的全部价值是「截图上认得出是谁在看」，
// 13px 在手机上要凑到眼前才勉强看清，等于白盖一层。窄屏只是纸面变窄，
// 人眼到屏幕的距离没变，字号就不该跟着缩
const MOBILE_FONT_SIZE = 16

const COLOR = 'rgba(0, 0, 0, 0.08)'
const ROTATE = -24 // 度
// 单元四周的留白（总宽）。旋转之后是四个角最贴边，留一点免得字压着边界
const CELL_PAD = 28

// 方块字（CJK、全角标点）按一个字宽算，其余（字母数字冒号）按 0.55 估。
// 只求装得下不求精确：估宽一点只是水印稀疏些，估窄了会裁字（见 makeSvg）
const FULL_WIDTH = /[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef]/

function textWidthEm(text) {
  let em = 0
  for (const ch of text) em += FULL_WIDTH.test(ch) ? 1 : 0.55
  return em
}

// 把文字渲染成一个 SVG 单元，转 data URI 当背景图
//
// **单元的宽高按文字长度算，不写死。** SVG 根元素的 overflow 默认是 hidden，
// 装不下的部分直接看不见 —— 写死 260×140 时，长名字盖出来会前后各缺一截：
// 姓名很长时会被裁成前后各缺一截，恰恰把「谁在看」裁掉。
// 所以这里先把文字转成旋转后的外接矩形，单元按它来定。
function makeSvg(text, fontSize) {
  const rad = (ROTATE * Math.PI) / 180
  const textW = textWidthEm(text) * fontSize
  const textH = fontSize * 1.2 // 给上下伸出的笔画留点余量
  const cellW = Math.ceil(textW * Math.cos(rad) + textH * Math.abs(Math.sin(rad))) + CELL_PAD
  const cellH = Math.ceil(textW * Math.abs(Math.sin(rad)) + textH * Math.cos(rad)) + CELL_PAD
  const cx = cellW / 2
  const cy = cellH / 2
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${cellW}" height="${cellH}">` +
    `<text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="middle" ` +
    `font-size="${fontSize}" fill="${COLOR}" ` +
    `font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif" ` +
    `transform="rotate(${ROTATE} ${cx} ${cy})">${escapeXml(text)}</text>` +
    `</svg>`
  return `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`
}

function escapeXml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

const svgDataUrl = computed(() => makeSvg(props.text, FONT_SIZE))
const svgDataUrlMobile = computed(() => makeSvg(props.text, MOBILE_FONT_SIZE))
</script>

<style scoped>
.watermark {
  position: absolute;
  inset: 0;
  z-index: 9;
  pointer-events: none;
  user-select: none;
  background-image: var(--wm-svg);
  background-repeat: repeat;
}

/* 手机上换更小的单元 + 更小字号 */
@media (max-width: 768px) {
  .watermark {
    background-image: var(--wm-svg-mobile);
  }
}

/* 深色模式：整层反转。水印颜色写在 SVG 里（黑 8%），背景一变深就看不见了，
   反转正好得到白 8% —— 和浅色下的对比度一模一样，不用再维护一套深色图。
   keepDark 的例外：PDF 画布不管什么主题都是白的（见 PdfViewer 的 .pdf-canvas），
   反转过去反而看不见。 */
@media (prefers-color-scheme: dark) {
  .watermark:not(.keep-dark) {
    filter: invert(1);
  }
}
</style>
