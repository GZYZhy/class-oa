/**
 * 日程的日期展开与排布
 *
 * 全天事件的「起止日期」要摊成一天一条：库里没有「跨天日程」这个概念（后端
 * schedule_import_service 导入跨天事件时也是这么摊的），日历上那根连着的条
 * 是前端按相邻同标题合出来的（见 Schedule.vue 的 allDayBars）。
 *
 * 定时日程的重叠并排（columnizeDay）也放这儿：重叠怎么算、并成几列是能真跑的
 * 纯逻辑，写在组件的 computed 里就断不到了。
 */

/**
 * 起止日期 → 逐日展开（含首尾），返回 'YYYY-MM-DD' 数组
 *
 * 用 new Date(y, m-1, d) 构造而不是 new Date('2026-10-05')：后者按 UTC 解析，
 * 在东八区会差出一天（这个坑在周次那处也踩过）。
 * 结束日期早于开始日期时返回空数组 —— 由调用方去提示，这里不抛错。
 * 结束日期省略时按单天算。
 */
export function daysInRange(startStr, endStr) {
  const [y1, m1, d1] = startStr.split('-').map(Number)
  const [y2, m2, d2] = (endStr || startStr).split('-').map(Number)
  const cur = new Date(y1, m1 - 1, d1)
  const end = new Date(y2, m2 - 1, d2)
  const days = []
  while (cur <= end) {
    days.push(formatDay(cur))
    cur.setDate(cur.getDate() + 1)
  }
  return days
}

/**
 * 把日历里的某一列滚到可视区正中间，返回该赋给 scrollLeft 的值
 *
 * 窄屏（手机）上日程表比屏幕宽、得横向滚（见 Schedule.vue 里 .calendar-grid 的
 * min-width），一进页面要把「今天」那一列摆到眼睛正前方 —— 否则手机上先看到
 * 周一，容易以为今天没课。两端夹住，免得滚到内容外面去（桌面上放得下时永远
 * 返回 0，等于不滚）。
 *
 * @param {number} colLeft   目标列左边缘（相对滚动容器的内容区）
 * @param {number} colWidth  目标列宽
 * @param {number} viewWidth 可视区宽（clientWidth）
 * @param {number} maxScroll 最多能滚多远（scrollWidth - clientWidth）
 */
export function centerScrollLeft(colLeft, colWidth, viewWidth, maxScroll) {
  const target = colLeft + colWidth / 2 - viewWidth / 2
  return Math.max(0, Math.min(target, maxScroll))
}

/**
 * 同一天里时间重叠的日程并成几列
 *
 * 日历上的日程块是绝对定位、宽度固定 1/7 的。同一时段有两条时，后画的把先画的
 * 整个盖住 —— 看着只有一条，谁也不知道还另有安排。让它们并排就得知道「各占第
 * 几列、这一片共几列」。
 *
 * 两趟：先把时间上连成一片的聚成一簇，簇内再按「最早已空出来的那列」逐个落位。
 * 判断断开用的是**簇里最晚的那个结尾**（不是上一条的结尾）：1 压着 2、2 压着 3
 * 的时候 1 和 3 并不重叠，但它俩必须同簇，否则 3 会被排到第 0 列、盖在 1 上面。
 *
 * 整簇共用一个列数：每条宽度一致、边界对齐，看着才像一栏一栏的。代价是簇里明明
 * 不跟别人重叠的那条也只占 1/n 宽 —— 换来结果可预期（宽度只跟「这一簇有几列」
 * 有关，跟谁压着谁无关），值。
 *
 * @param {{startIdx: number, endIdx: number}[]} events 同一天的日程（10 分钟为单位
 *   的格子下标），顺序随便
 * @returns {{col: number, cols: number}[]} 与入参**同序**：落在第几列（0 起）、
 *   这一簇共几列。首尾相接（8:00-9:00 接 9:00-10:00）不算重叠，各自独占整列
 */
export function columnizeDay(events) {
  // 早开始的在前；同一刻开始的，长的先放（长的那条占左边那列，短的靠右，
  // 顺序固定下来画面才不会跳）；最后按原下标兜底，保证排序结果唯一
  const order = events.map((_, i) => i).sort((a, b) =>
    events[a].startIdx - events[b].startIdx
    || events[b].endIdx - events[a].endIdx
    || a - b)

  const out = new Array(events.length)
  let cluster = []       // 当前这一簇里的下标
  let clusterEnd = -1    // 簇里最晚的结尾

  // 簇内分列：「最早已空出来的那列」，一列都腾不出来就新开一列
  const flush = () => {
    const colEnds = []   // 第 i 列上最后一条的结尾
    const placed = cluster.map((i) => {
      let col = colEnds.findIndex((end) => end <= events[i].startIdx)
      if (col === -1) {
        col = colEnds.length
        colEnds.push(events[i].endIdx)
      } else {
        colEnds[col] = events[i].endIdx
      }
      return { i, col }
    })
    // 列数要等整簇落完位才知道，这时才能把 cols 补上
    for (const { i, col } of placed) out[i] = { col, cols: colEnds.length }
    cluster = []
  }

  for (const i of order) {
    if (cluster.length && events[i].startIdx >= clusterEnd) flush()
    cluster.push(i)
    clusterEnd = cluster.length === 1
      ? events[i].endIdx
      : Math.max(clusterEnd, events[i].endIdx)
  }
  if (cluster.length) flush()

  return out
}

/** Date → 'YYYY-MM-DD'（本地时区，和 daysInRange 的输入同一个口径） */
function formatDay(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
