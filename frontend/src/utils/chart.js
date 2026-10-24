/**
 * ECharts 的按需引入。全站要用图表的地方都从这里拿 `echarts`，别直接引 'echarts'。
 *
 * 为什么要这么绕一圈：裸写 `import * as echarts from 'echarts'` 会把整个图表库
 * 打进产物，实测 1.04MB（gzip 343KB）。而首屏落地页 views/Dashboard.vue 也要画图，
 * 于是每个访客、每台新设备，头一屏都得先把这 343KB 下完才开始看得见东西 ——
 * 弱网下这就是首页卡住的主因。
 *
 * 换成 echarts/core + 按需注册之后只剩实际用到的那些，实测 gap **见下方注释**。
 *
 * ⚠️ 新增图表类型时**记得在下面 use() 里补一项**（饼图之外的图、以及用到的
 * 交互组件）。漏了不会报错：`echarts.init` 照常成功，只是那张图一片空白。
 * tests/render.mjs 有一节盯着这份清单，用法对不上的新 API 会被它拦下。
 */

// 图表本体：目前只有环形饼图（性别/政治面貌/宿舍楼…）和柱状图（成绩分布、人数分布）
import * as echarts from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
// 交互与布局：tooltip 是鼠标悬停的那个浮层，legend 是图例，
// grid 是直角坐标系的内边距 —— 只有柱状图用得到，但一共才几 KB
// title 用来在环形图中心写总数（不用 graphic，那件更重）
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
// 渲染后端。SVG 版在多饼图的统计页上更省内存，但 canvas 版更小也更通用
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer
])

export default echarts

/* ============ 共用图表主题 ============
   首页那两张环和统计页的九张图原来是各写一份配置、各配一套颜色，
   于是同是「人数占比」的图在不同页面长得不像一家的。这里收成公共实现：
   配色、圆角、间隙、tooltip、深浅模式取值，两处共用。 */

/* 色板按「相邻色相拉开」排：第 1 和第 2 片放靛蓝/玫粉这种对角色，
   两片挨着也能一眼分开（上一版男女两片都是紫蓝，几乎糊成一片） */
export const CHART_PALETTE = [
  '#6a73f3', // 靛蓝（主色）
  '#f472b6', // 玫粉
  '#38bdf8', // 天青（副色）
  '#fbbf24', // 琥珀
  '#34d399', // 薄荷
  '#a78bfa', // 薰衣草
  '#fb7185', // 珊瑚
  '#22d3ee'  // 青
]

/** 当前主题下的文字/线条颜色：直接读 CSS 变量，深浅模式各拿各的 */
export function chartColors() {
  const css = getComputedStyle(document.documentElement)
  const v = (n, f = '') => css.getPropertyValue(n).trim() || f
  return {
    text: v('--el-text-color-primary', '#1f2430'),
    text2: v('--el-text-color-secondary', '#5c6373'),
    line: v('--app-outline', 'rgba(0, 0, 0, 0.08)'),
    track: v('--el-fill-color-light', 'rgba(0, 0, 0, 0.04)'),
    surface: v('--app-surface-solid', '#ffffff')
  }
}

function tooltipTheme(t) {
  return {
    backgroundColor: t.surface,
    borderColor: t.line,
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: t.text, fontSize: 12 },
    extraCssText: 'border-radius:10px;box-shadow:0 8px 24px rgba(17,20,45,.14);'
  }
}

/**
 * 环形图：细环 + 分片间隙 + 圆心总数 + 带人数的图例。
 * 圆心文字用 title 的 middle 对齐（不是给个百分比 top）——
 * 上一版按 27% 估位置，字就浮在环心偏上；radius 也收到 72%，
 * 之前 84% 的外沿会顶到容器上下边缘被切掉。
 * @param {HTMLElement} dom
 * @param {{name:string,value:number}[]} list
 */
export function renderDonut(dom, list) {
  const t = chartColors()
  const sum = list.reduce((s, d) => s + d.value, 0)
  const inst = echarts.init(dom)
  inst.setOption({
    color: CHART_PALETTE,
    tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 人 · {d}%', ...tooltipTheme(t) },
    title: {
      text: String(sum),
      subtext: '总计',
      left: 'center',
      top: 'middle',
      textAlign: 'center',
      textStyle: { color: t.text, fontSize: 26, fontWeight: 700 },
      subtextStyle: { color: t.text2, fontSize: 11 }
    },
    legend: {
      bottom: 0,
      left: 'center',
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 14,
      textStyle: { color: t.text2, fontSize: 12 },
      // 图例直接带人数：省掉图下方那张「同样的数据再列一遍」的表格
      formatter: (name) => {
        const it = list.find((d) => d.name === name)
        return `${name}  ${it ? it.value : 0}`
      }
    },
    series: [{
      type: 'pie',
      radius: ['50%', '70%'],
      /* 环心必须和 title 的 middle 对齐（都是画布 50%），
         否则「总计」会浮在环心偏上；70% 的外沿给底部图例留出空间，不会上下被切 */
      center: ['50%', '50%'],
      // padAngle 直接把相邻分片「掰开」一道缝，比给每片描一圈底色边更干净
      padAngle: 2,
      itemStyle: { borderRadius: 8 },
      label: { show: false },
      labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 6 },
      data: list
    }]
  })
  return inst
}

/**
 * 条形图（可横向）：圆角 + 浅色底槽 + 虚线网格 + 条尾数值。
 * 隐藏数值轴刻度 —— 需要精确值时悬停看 tooltip，画面上只留对比关系。
 */
export function renderBar(dom, list, { horizontal = false, color = CHART_PALETTE[0] } = {}) {
  const t = chartColors()
  const inst = echarts.init(dom)
  const cat = {
    type: 'category',
    data: list.map((d) => d.name),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: t.text2, fontSize: 11, hideOverlap: true }
  }
  const val = {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: t.line, type: 'dashed' } },
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { show: false }
  }
  inst.setOption({
    grid: horizontal
      ? { left: 4, right: 34, top: 6, bottom: 4, containLabel: true }
      : { left: 4, right: 8, top: 26, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: '{b}<br/>{c} 人', ...tooltipTheme(t) },
    xAxis: horizontal ? val : cat,
    yAxis: horizontal ? cat : val,
    series: [{
      type: 'bar',
      barMaxWidth: horizontal ? 12 : 26,
      data: list.map((d) => d.value),
      showBackground: true,
      backgroundStyle: {
        color: t.track,
        borderRadius: horizontal ? 6 : [8, 8, 0, 0]
      },
      itemStyle: {
        color,
        borderRadius: horizontal ? 6 : [8, 8, 0, 0]
      },
      label: {
        show: true,
        position: horizontal ? 'right' : 'top',
        color: t.text2,
        fontSize: 11,
        formatter: '{c}'
      }
    }]
  })
  return inst
}
