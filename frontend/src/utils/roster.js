/**
 * 学生名单的共用规则与抽样
 *
 * 点名和抽签用的是同一套规则：谁算「能参与的人」、「男生/女生/共青团员/全班」各
 * 对应库里哪个字段值。放这里是为了只写一份 —— 点名当初把筛选逻辑在 counts 和
 * startCall 里各写了一份，counts 用了单字、startCall 却拿按钮上的「男生」直接比，
 * 于是选男生/女生永远是空名单，只有不筛选的「全班」正常。
 *
 * 「是不是共青团员」也放这儿：投票出卷的「仅团员」快捷键、分类统计的共青团员卡
 * 都要用同一个判据，三处各写一遍迟早漂成不一样的。
 *
 * 「有没有职务」（班委、团学成员）同理：分类统计的班委/团学会卡片、日程选人的
 * 快捷范围共用它。
 */

/** 在校状态为这个值才参与点名/抽签。
    休学/退学/保留学籍这些叫到了也没意义 —— 人不在校，答不上来等于天天误报。
    比对的是「不等于它就不参与」，所以字段为空也按不参与处理 */
export const NORMAL_SCHOOL_STATUS = '正常'

/** 范围名 → 学生表 gender 字段里的实际取值。
    界面上和日志里都写「男生」，但库里存的是「男」，这两个必须对上 */
export const GENDER_BY_SCOPE = { 男生: '男', 女生: '女' }

/** 政治面貌填这个值才算共青团员。空着、填「群众」或「中共预备党员」的都不算 */
export const LEAGUE_STATUS = '共青团员'

/** 是不是共青团员。判据只此一份：点名、投票出卷、分类统计共用它 */
export function isLeagueMember(student) {
  return student?.political_status === LEAGUE_STATUS
}

/** 班委看这个字段，团学成员看 league_position。字段名散在各处就会写错一个字母
    （写错的表现是「一个有职务的人都没筛出来」，不是报错） */
export const COMMITTEE_FIELD = 'class_position'
export const LEAGUE_OFFICER_FIELD = 'league_position'

/** 「有没有职务」：空串、null 和字面量「无」都算没有。口径与后端统计一致
    （backend/app/services/student_service.py 的 get_statistics）。
    返回的是判据函数本身、不是一个布尔 —— 它的用处就是丢给 filter */
export function hasPosition(field) {
  return (s) => !!s?.[field] && s[field] !== '无'
}

/** 按范围取人。显示人数和实际取人共用它，就不会再各写一套比法 */
export function pickByScope(list, scopeName) {
  if (scopeName === '全班') return [...list]
  // 团员看的是政治面貌、不是性别，得在下面那条按性别比的之前单独分出来
  if (scopeName === LEAGUE_STATUS) return list.filter(isLeagueMember)
  return list.filter((s) => s.gender === GENDER_BY_SCOPE[scopeName])
}

/** 拆成「能参与的」和「被滤掉的」两份，后者只用来在界面上提示一句 */
export function splitBySchoolStatus(list) {
  return {
    active: list.filter((s) => s.school_status === NORMAL_SCHOOL_STATUS),
    excluded: list.filter((s) => s.school_status !== NORMAL_SCHOOL_STATUS)
  }
}

/**
 * 从已批准的请假里挑出「此刻正落在请假区间内」的人。
 *
 * 请假精确到小时、点名发生在某一时刻，所以直接用时刻比较，不引入「按天」的
 * 第二套语义。一个人可能有多条记录（续假），只留第一条，免得占两个名额。
 *
 * @param {object[]} students 参与点名的名单，不在里面的忽略
 * @param {object[]} leaves GET /api/leaves?status=approved 的结果
 * @param {number} now 比较用的时刻（传 Date.now()）
 * @returns {Map<string, object>} 学号 → 那条请假记录
 */
export function onLeaveNow(students, leaves, now) {
  const inRoster = new Set(students.map((s) => s.student_no))
  const byNo = new Map()
  for (const leave of leaves || []) {
    // 一个人只留一条，续假会有多条重叠
    if (!inRoster.has(leave.student_no) || byNo.has(leave.student_no)) continue
    if (new Date(leave.start_at).getTime() > now) continue
    if (now > new Date(leave.end_at).getTime()) continue
    byNo.set(leave.student_no, leave)
  }
  return byNo
}

/**
 * 把某个范围里的人拆成「要逐个点名的」和「自动记为请假的」两份。
 *
 * **必须和范围求交集**：请假名册是全班范围的，直接拿去用的话，选「男生」点名时
 * 一个请假的女生也会被算进这次记录，应到人数当场多一个。
 */
export function splitByLeave(list, leaveByNo) {
  return {
    calling: list.filter((s) => !leaveByNo.has(s.student_no)),
    onLeave: list.filter((s) => leaveByNo.has(s.student_no))
  }
}

/**
 * 洗牌后取前 n 个：取出的 n 个人互不重复，且每种组合等概率。
 * Fisher-Yates 洗到第 n 位就停，不必把整副牌洗一遍。
 */
export function sample(list, n) {
  const arr = [...list]
  const take = Math.min(n, arr.length)
  for (let i = 0; i < take; i++) {
    const j = i + Math.floor(Math.random() * (arr.length - i))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr.slice(0, take)
}
