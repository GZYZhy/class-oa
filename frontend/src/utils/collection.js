/**
 * 投票收集的纯展示/表单规则
 *
 * 和 utils/poll.js 分开：投票只有单选/多选，收集有六种题型、每人多份、竞争名额。
 * 这里只放能被单独测试的纯函数，接口调用在 api/collection.js。
 */

import { statusLabel, statusTag } from './poll'

export const QUESTION_TYPES = [
  { value: 'single', label: '单选' },
  { value: 'multiple', label: '多选' },
  { value: 'short_text', label: '短文本' },
  { value: 'long_text', label: '长文本' },
  { value: 'image', label: '图片' },
  { value: 'rating', label: '评分（1–5）' }
]

export const QUESTION_TYPE_LABEL = Object.fromEntries(
  QUESTION_TYPES.map((item) => [item.value, item.label])
)

export const CHOICE_TYPES = new Set(['single', 'multiple'])
export const TEXT_TYPES = new Set(['short_text', 'long_text'])
export const TEXT_LIMITS = { short_text: 200, long_text: 2000 }
export const RATING_MIN = 1
export const RATING_MAX = 5
export const IMAGE_MAX_FILES = 3

/** 出卷时的一道空题 */
export function blankQuestion(type = 'single') {
  return {
    title: '',
    qtype: type,
    required: true,
    options: ['', ''],
    max_choices: 2
  }
}

/** 出卷时的空表单 */
export function blankForm() {
  return {
    title: '',
    description: '',
    anonymous: false,
    allow_withdraw: false,
    start_at: '',
    end_at: '',
    notify_on_start: true,
    submit_quota: 1,
    max_responses: 0,
    targets: [],
    questions: [blankQuestion()]
  }
}

/** 一份旧收集里的题目 → 表单题目（复用旧卷和编辑共用这一段） */
export function questionsFromCollection(collection) {
  const questions = (collection?.questions || []).map((question) => ({
    title: question.title || '',
    qtype: question.qtype || 'single',
    required: question.required !== false,
    options: CHOICE_TYPES.has(question.qtype)
      ? [...(question.options || [])]
      : ['', ''],
    max_choices: question.max_choices || 2
  }))
  return questions.length ? questions : [blankQuestion()]
}

/**
 * 详情 → 编辑表单
 *
 * 题目深拷贝；范围不回填（范围不能改，编辑时整块名单不渲染，只显示人数）。
 */
export function formFromCollection(collection) {
  const toPicker = (value) => {
    if (!value) return ''
    return String(value).slice(0, 16).replace('T', ' ')
  }
  return {
    title: collection?.title || '',
    description: collection?.description || '',
    anonymous: !!collection?.anonymous,
    allow_withdraw: !!collection?.allow_withdraw,
    start_at: toPicker(collection?.start_at),
    end_at: toPicker(collection?.end_at),
    notify_on_start: collection?.notify_on_start !== false,
    submit_quota: collection?.submit_quota || 1,
    max_responses: collection?.max_responses || 0,
    targets: [],
    questions: questionsFromCollection(collection)
  }
}

/** 题目有没有填过东西（切换题型/复用旧卷时决定要不要确认覆盖） */
export function hasQuestionContent(question) {
  if (!question) return false
  if ((question.title || '').trim()) return true
  if (CHOICE_TYPES.has(question.qtype) && (question.options || []).some((o) => (o || '').trim())) {
    return true
  }
  return false
}

/** 答卷里一道题的初始值 */
export function blankAnswer(question) {
  if (CHOICE_TYPES.has(question.qtype)) return []
  if (TEXT_TYPES.has(question.qtype)) return ''
  if (question.qtype === 'rating') return null
  if (question.qtype === 'image') return []
  return ''
}

/** 列表里的主按钮文案 */
export function collectionActionText(row) {
  if (row?.can_submit) {
    return row.my_submitted_count > 0 ? '继续填写' : '填写'
  }
  if (row?.quota_reached) {
    // 填满后主按钮仍然点得动：进去看自己的答卷（允许时还能撤回）
    return row.my_submitted_count > 0 ? '查看答卷' : '已填完'
  }
  return '查看'
}

/** 「我的状态」列 */
export function collectionMyState(row) {
  if (!row?.is_target) return '无需填写'
  if (row.quota_reached) return '已完成'
  if (row.my_submitted_count > 0) return `已填 ${row.my_submitted_count}/${row.submit_quota}`
  if (row.status === 'pending') return '未开始'
  if (row.status === 'closed') return '未填写'
  // 已经填过一部分的，进度比「暂停」更值得看（上面那条已经返回了）
  if (row.status === 'paused') return '已暂停'
  if (row.cap_reached) return '名额已满'
  return '待填写'
}

export { statusLabel, statusTag }

/**
 * 列表/卡片用的 Markdown 纯文本摘要
 *
 * 只做最常见的清理（代码块、图片、链接、标题符号、强调符号），不追求完整
 * Markdown 解析 —— 列表里只需要一眼看懂，详情/分享页才用 renderMarkdown。
 */
export function markdownPreview(text, limit = 80) {
  const plain = String(text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/[*_~>#]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return plain.length > limit ? `${plain.slice(0, limit)}…` : plain
}
