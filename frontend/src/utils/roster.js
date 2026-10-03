/**
 * 学生名单的共用规则与抽样
 *
 * 点名和抽签用的是同一套规则：谁算「能参与的人」、「男生/女生/全班」各对应
 * 库里哪个 gender 值。放这里是为了只写一份 —— 点名当初把筛选逻辑在 counts 和
 * startCall 里各写了一份，counts 用了单字、startCall 却拿按钮上的「男生」直接比，
 * 于是选男生/女生永远是空名单，只有不筛选的「全班」正常。
 */

/** 在校状态为这个值才参与点名/抽签。
    休学/退学/保留学籍这些叫到了也没意义 —— 人不在校，答不上来等于天天误报。
    比对的是「不等于它就不参与」，所以字段为空也按不参与处理 */
export const NORMAL_SCHOOL_STATUS = '正常'

/** 范围名 → 学生表 gender 字段里的实际取值。
    界面上和日志里都写「男生」，但库里存的是「男」，这两个必须对上 */
export const GENDER_BY_SCOPE = { 男生: '男', 女生: '女' }

/** 按范围取人。显示人数和实际取人共用它，就不会再各写一套比法 */
export function pickByScope(list, scopeName) {
  if (scopeName === '全班') return [...list]
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
