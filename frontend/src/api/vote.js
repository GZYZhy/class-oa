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

/** 出卷时可选的学生名单，带 committee / political_status 给「仅班委」「仅团员」快捷键（班委及以上） */
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
 * 编辑一场投票（发起人和管理员）
 *
 * @param {number} id
 * @param {{title: string, description: string, start_at?: string, end_at?: string,
 *          anonymous?: boolean, questions?: object[]}} data
 *   时间**不传 = 不动**；传了按状态分档，后端说了算（api/polls.py 的 update_poll）：
 *   未开始的两个都能改，已开始的只能改 end_at，已结束的都不给改。判据在
 *   utils/poll.js 的 canEditTimes —— 调用方按它决定哪个框能编辑、哪个字段要带。
 *   anonymous **不传 = 不动**；只在**未开始**时改得动，判据是 utils/poll.js 的
 *   canEditBeforeStart（和题目同一条：开始之后改，等于把投出去的票重新定义一遍）。
 *   **表决范围改不了**（把已投的人挪出去，他那张票就算不清了），要换人请删了重发。
 *   questions **不传 = 不动题目**；传了 = 整卷替换，而且只在**未开始**时有效 ——
 *   已经开始的那场传了会被后端 400（作答存的是选项下标，换题目会让历史作答错位）。
 *   所以编辑一个已开始的投票时，调用方别带 questions。
 */
export function updatePoll(id, data) {
  return request({ url: `/polls/${id}`, method: 'patch', data })
}

/**
 * 投票详情
 *
 * 返回里 status / is_target / has_voted / results_visible / can_vote 都是后端
 * 算好的，**页面只认这些字段、不自己拿时间去比**（可见性只有后端一处口径）。
 * 看得到结果时每道题带 tallies（每个选项的票数），看不到时是 null。
 *
 * 编辑弹窗要用它拿题目：列表行里没有 questions。
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

/**
 * 暂停收票（发起人和管理员）。**暂停不是结束**：解锁后照样能投
 *
 * 只认「进行中」的投票；已经结束或还没开始的会被 400。重复调用幂等（返回详情）。
 * 到点没解开的话，状态会自己变成已结束，不需要谁去收拾。
 */
export function lockPoll(id) {
  return request({ url: `/polls/${id}/lock`, method: 'post' })
}

/** 恢复收票（发起人和管理员）。重复调用幂等，返回详情 */
export function unlockPoll(id) {
  return request({ url: `/polls/${id}/unlock`, method: 'post' })
}

/** 删除一场投票（发起人和管理员），已有人投过也允许 */
export function deletePoll(id) {
  return request({ url: `/polls/${id}`, method: 'delete' })
}
