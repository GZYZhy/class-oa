/**
 * 日程的日期展开
 *
 * 全天事件的「起止日期」要摊成一天一条：库里没有「跨天日程」这个概念（后端
 * schedule_import_service 导入跨天事件时也是这么摊的），日历上那根连着的条
 * 是前端按相邻同标题合出来的（见 Schedule.vue 的 allDayBars）。
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

/** Date → 'YYYY-MM-DD'（本地时区，和 daysInRange 的输入同一个口径） */
function formatDay(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
