import request from '@/utils/request'

/**
 * 投票列表
 *
 * 只列我该看得见的：管理员和发起人看全部，其他人在表决名单里才看得见
 * （范围外的人压根看不到这场投票）。
 * params: { status, page, page_size }
 */
export function getPolls(params) {
  return request({ url: '/polls', method: 'get', params })
}

/** 出卷时可选的学生名单，带 committee 标记给「仅班委」快捷键（班委及以上） */
export function getRoster() {
  return request({ url: '/polls/roster', method: 'get' })
}

/**
 * 发起投票（班委及以上）
 *
 * @param {{title, description, anonymous, start_at, end_at,
 *          targets: string[], questions: object[]}} data
 *   start_at / end_at 用 'YYYY-MM-DD HH:mm'（不带时区，后端也是这么比的）
 *   questions 每项 { title, multiple, max_choices, options: string[] }
 */
export function createPoll(data) {
  return request({ url: '/polls', method: 'post', data })
}

/**
 * 投票详情
 *
 * 返回里 status / is_target / has_voted / results_visible / can_vote 都是后端
 * 算好的，**页面只认这些字段、不自己拿时间去比**（可见性只有后端一处口径）。
 * 看得到结果时每道题带 tallies（每个选项的票数），看不到时是 null。
 */
export function getPoll(id) {
  return request({ url: `/polls/${id}`, method: 'get' })
}

/**
 * 投票：整卷一次提交
 *
 * @param {number} id
 * @param {{answers: {question_id: number, choices: number[]}[]}} data
 *   choices 是选中选项的**下标**；每题必答。**投过就不能再投**（后端会 400）。
 */
export function votePoll(id, data) {
  return request({ url: `/polls/${id}/vote`, method: 'post', data })
}

/**
 * 谁投了谁没投（发起人和管理员）
 *
 * 记名投票每行带 choices（{题目 ID: 下标数组}）；**不记名的一律是 null** ——
 * 后端就不返回「谁投了什么」。未投的排在前面。
 */
export function getBallots(id) {
  return request({ url: `/polls/${id}/ballots`, method: 'get' })
}

/** 催还没投的人（发起人和管理员），返回 { reminded } */
export function remindPoll(id) {
  return request({ url: `/polls/${id}/remind`, method: 'post' })
}

/** 立即结束（发起人和管理员）。重复调用幂等，返回 { status, voted_count } */
export function closePoll(id) {
  return request({ url: `/polls/${id}/close`, method: 'post' })
}

/** 删除一场投票（发起人和管理员），已有人投过也允许 */
export function deletePoll(id) {
  return request({ url: `/polls/${id}`, method: 'delete' })
}
