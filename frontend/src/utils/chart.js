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
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
// 渲染后端。SVG 版在多饼图的统计页上更省内存，但 canvas 版更小也更通用
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer
])

export default echarts
