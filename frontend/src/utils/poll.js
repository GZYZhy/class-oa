/**
 * 投票页面用到的纯展示规则
 *
 * 抽出来是因为这些规则要**在出卷和表决两个地方用同一套**（选项字母），
 * 而且「这人在这次投票里是什么处境」这类判断写错不会报错、只会显示成别的字，
 * 放在这儿能被单独跑起来验。
 *
 * 注意：**状态的判定不在前端**。一场投票是未开始 / 进行中 / 已结束，由后端按
 * 开始、截止、手动结束三个时刻现算（services/poll_service.py），前端只把后端给的
 * status 翻成中文，不自己拿时间去比 —— 否则两处口径迟早走散。
 */

/** 选项前的字母：A B C…（选项最多 20 个，用不到后面） */
export const POLL_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')

const STATUS_TEXT = { pending: '未开始', open: '进行中', closed: '已结束' }
const STATUS_TAG = { pending: 'warning', open: 'success', closed: 'info' }

export function statusLabel(status) {
  return STATUS_TEXT[status] || status || '—'
}

/** el-tag 的颜色 */
export function statusTag(status) {
  return STATUS_TAG[status] || 'info'
}

/** 我在这场投票里的处境：已投 / 无需投票 / 未开始 / 未投 / 待投票 */
export function myStateText(row) {
  if (row.has_voted) return '已投'
  if (!row.is_target) return '无需投票'
  if (row.status === 'pending') return '未开始'
  if (row.status === 'closed') return '未投'
  return '待投票'
}

/** 列表里那个主按钮该叫什么：能投就叫「投票」，否则按看不看得到结果区分 */
export function actionText(row) {
  if (row.can_vote) return '投票'
  return row.results_visible ? '查看结果' : '查看'
}

/** 一道题的票数之和。多选题每人选多项，所以它会大于人数 */
export function sumOf(question) {
  return (question.tallies || []).reduce((a, b) => a + b, 0)
}

/**
 * 某个选项的进度条百分比：**占本题所有选择的比例**
 *
 * 分母不用「已投人数」：多选题一个人能选好几项，用人数当分母会算出超过 100% 的数。
 * 单选时本题所有选项的票数之和恰好等于已投人数，所以这时它就是得票率。
 */
export function percentOf(question, index) {
  const sum = sumOf(question)
  if (!sum) return 0
  return Math.round(((question.tallies?.[index] || 0) / sum) * 100)
}
