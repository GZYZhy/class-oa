/**
 * 投票页面用到的纯展示规则
 *
 * 抽出来是因为这些规则要**在出卷和表决两个地方用同一套**（选项字母），
 * 而且「这人在这次投票里是什么处境」这类判断写错不会报错、只会显示成别的字，
 * 放在这儿能被单独跑起来验。
 *
 * 注意：**状态的判定不在前端**。一场投票是未开始 / 进行中 / 已暂停 / 已结束，由后端
 * 按开始、截止、手动结束、暂停四个时刻现算（services/poll_service.py），前端只把
 * 后端给的 status 翻成中文，不自己拿时间去比 —— 否则两处口径迟早走散。
 */

import { formatDateTime } from './format'

/** 选项前的字母：A B C…（选项最多 20 个，用不到后面） */
export const POLL_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')

// 进行中绿、未开始橙、已结束灰，暂停给红 —— 四色不撞，且暂停是件要留意的事：
// 它看着像「进行中」，实际上投不了
const STATUS_TEXT = { pending: '未开始', open: '进行中', closed: '已结束', locked: '已暂停', paused: '已暂停' }
const STATUS_TAG = { pending: 'warning', open: 'success', closed: 'info', locked: 'danger', paused: 'warning' }

export function statusLabel(status) {
  return STATUS_TEXT[status] || status || '—'
}

/** el-tag 的颜色 */
export function statusTag(status) {
  return STATUS_TAG[status] || 'info'
}

/** 我在这场投票里的处境：已投 / 无需投票 / 未开始 / 未投 / 已暂停 / 待投票 */
export function myStateText(row) {
  if (row.has_voted) return '已投'
  if (!row.is_target) return '无需投票'
  if (row.status === 'pending') return '未开始'
  if (row.status === 'closed') return '未投'
  // 已投的和范围外的那两条在前面：暂停只影响「还能不能投」，改不了这两件事
  if (row.status === 'locked') return '已暂停'
  return '待投票'
}

/** 能不能暂停 / 恢复这场投票：只有进行中和已暂停的能来回切 */
export function canToggleLock(row) {
  return row.status === 'open' || row.status === 'locked'
}

/**
 * 编辑一场投票时，两个时间各能不能改
 *
 * **不是「编辑时一概不能改」**，按状态分档（后端 api/polls.py 的 update_poll 按同一套判）：
 *   未开始 —— 两个都能改：把开始时间往后推 = 推迟开场，截止时间自然跟着挪
 *   进行中 / 已暂停 —— 只能改截止时间：开始时间已经过去了，改它没有任何意义
 *   已结束 —— 一个都不给改：closed_at 优先，改了也不会生效，允许就是骗人
 */
export function canEditTimes(status) {
  return { start_at: status === 'pending', end_at: status !== 'closed' }
}

/**
 * 只有还没开始的投票能改的那几样：**题目、记名与否**
 *
 * 两样的理由是同一条 —— 改了都会「换一张票」：题目换了下标就错位（作答存的是选项
 * 下标），记名方式换了等于把已经投出去的票重新定义一遍（不记名的票突然有了主）。
 * 没开始时库里不可能有作答（can_vote 要求状态是 open），所以那时怎么改都安全。
 *
 * 表决范围不在此列 —— 它**任何状态都改不了**，要换人只能删了重发。
 */
export function canEditBeforeStart(status) {
  return status === 'pending'
}

/**
 * 现在不能投的话，说清楚为什么（能投时这个函数根本不会被调用）
 *
 * **顺序即口径**：「不在表决范围内」排在「已暂停」前面 —— 范围外的人看到「已暂停」
 * 是误导，他等解锁也投不了。两条调换就反了，测试盯着这个顺序。
 */
export function voteBlockReason(p = {}) {
  if (p.status === 'pending') return '投票还没开始，到时间后才能作答'
  if (p.status === 'closed') return '投票已结束'
  if (!p.is_target) return '你不在本次投票的表决范围内，只能看题目'
  if (p.status === 'locked') return '投票已暂停，等发起人解锁后才能继续投'
  return '现在不能投票'
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

/**
 * 结果页里一道题的选项显示顺序（「按得票排序」那个开关）
 *
 * 返回的是**原始下标**数组，不是排好序的选项本身：字母（A/B/C）、票数、进度条
 * 全都按原下标去取，换的只是行的先后 —— 这样排序前后每一行还是同一个选项，
 * 字母也不会跟着挪（「A. 张三」排到第二个去的时候，它还得叫 A）。
 *
 * 票数相同的保持原顺序：不然同票的两项按 sort 的实现来回换，每次刷新位置都在
 * 跳，看着像自己看错了。sorted 为假时原样返回。
 */
export function tallyOrder(question, sorted) {
  const idx = (question?.options || []).map((_, j) => j)
  if (!sorted) return idx
  const tally = (j) => question.tallies?.[j] || 0
  return idx.sort((a, b) => tally(b) - tally(a) || a - b)
}

// ---------- 出卷 / 编辑的那张表单 ----------
//
// 这一段是纯数据搬运，**故意放在这儿而不是组件里**：SSR 下 el-input 不输出 value
// （只输出 placeholder），表单「填回来了没有」在渲染结果里根本断不到 —— 抽成纯函数
// 才真跑得起来。同 utils/roster.js、utils/statGroups.js 那个路子。

/** 表单里的一道空题。多选题的「最多选几项」默认 2 */
export function blankQuestion(multiple = false) {
  return {
    title: '',
    multiple,
    max_choices: multiple ? 2 : 1,
    options: ['', ''],
    // 切回多选时要恢复上次填的「最多选几项」，不然来回切一次就得重填
    lastMax: 2
  }
}

/** 出卷时的空表单 */
export function blankForm() {
  return {
    title: '',
    description: '',
    anonymous: false,
    start_at: '',
    end_at: '',
    notify_on_start: true,
    targets: [],
    questions: [blankQuestion()]
  }
}

/**
 * 表单里的题目是不是已经填过东西了
 *
 * 复用时拿它决定要不要先确认覆盖：刚打开的弹窗自带一道空题，这时直接填进去就行；
 * 用户已经敲了题干或选项，覆盖掉就找不回来了，得先问一句。多一道题也算填过。
 */
export function hasQuestionContent(questions = []) {
  if (questions.length > 1) return true
  const q = questions[0]
  if (!q) return false
  return !!(q.title || '').trim() || (q.options || []).some((o) => (o || '').trim())
}

/** 详情里的一道题 → 表单里的一道题 */
function toFormQuestion(q) {
  const options = (q.options || []).length ? [...q.options] : ['', '']
  // 单选在库里 max_choices 恒为 1；多选至少 2，越界就夹回选项数（与组件里 removeOption 同口径）
  const max = Math.min(Math.max(q.max_choices || 2, 2), options.length)
  return {
    title: q.title || '',
    multiple: !!q.multiple,
    max_choices: q.multiple ? max : 1,
    options,
    lastMax: max
  }
}

/**
 * 一场旧投票里的题目 → 表单题目（「复用之前的卷子」和「编辑」共用这一段）
 *
 * 只搬题目：标题、描述、起止时间、表决范围、记名方式都是这一场的新决定，
 * 照抄上一场只会让人以为「沿用」了其实没有。
 *
 * 返回的是新数组、新对象，选项也复制了一份 —— 复用之后接着改，
 * 不能改着改着把列表里那场投票的数据也动了。
 * 一道题都没有的旧卷子回一道空题，和 blankForm 的口径一致。
 */
export function questionsFromPoll(poll) {
  const questions = (poll.questions || []).map(toFormQuestion)
  return questions.length ? questions : [blankQuestion()]
}

/**
 * 投票详情 → 编辑表单的一份值（GET /api/polls/{id} 的返回拿进来）
 *
 * **时间必须过一遍 formatDateTime**：详情回的是 ISO 串（2026-11-01T08:00:00），而两个
 * picker 的 value-format 是 'YYYY-MM-DD HH:mm'，把 ISO 串直接塞进 v-model，那一栏
 * 会显示成空的 —— 看着像「这场投票没设时间」。
 *
 * **不带表决范围**：范围改不了（把已经投过的人挪出去，他那张票就算不清了），编辑时
 * 整块名单都不渲染，只显示一个从详情带过来的人数。
 */
export function formFromPoll(poll) {
  // formatDateTime 对空值回的是 '-'，直接塞给 picker 会显示成一个破折号；空就给空串
  const toPicker = (value) => (value ? formatDateTime(value) : '')
  return {
    title: poll.title || '',
    description: poll.description || '',
    anonymous: !!poll.anonymous,
    start_at: toPicker(poll.start_at),
    end_at: toPicker(poll.end_at),
    notify_on_start: poll.notify_on_start !== false,
    targets: [],
    questions: questionsFromPoll(poll)
  }
}
