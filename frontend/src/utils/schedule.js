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

/** Date → 'YYYY-MM-DD'（本地时区，和 daysInRange 的输入同一个口径） */
function formatDay(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
