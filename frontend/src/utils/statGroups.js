/**
 * 分类统计页的概览卡点开之后是哪些人
 *
 * 这一页（views/Statistics.vue）顶上的卡片原来只有一个数字，想知道「都是谁」得切到学生名单页
 * 逐个筛。规则抽在这里而不是写在组件里，**原因是那个组件测不了**：它顶层
 * `import * as echarts`，而 zrender 在模块加载时就摸 document（见 tests/render.mjs 里写明的
 * 结论），SSR 渲染不了。放成纯函数才断得到真东西 —— 同 utils/roster.js 那个路子。
 *
 * 判定口径与后端统计保持一致（backend/app/services/student_service.py 的 get_statistics）：
 * 班委/团学会 = 非空且不是「无」，贫困生取中文「是」。
 */

/** 少数民族：民族填了、而且不是汉族。
    空值不算 —— 字段没填的人不该被凭空划成少数民族 */
export function isMinority(student) {
  return isMinorityName(student.ethnicity)
}

function isMinorityName(name) {
  return !!name && name !== '汉族'
}

/**
 * 少数民族人数：统计接口里的 ethnicity 是 `{民族: 人数}`，把非汉族的**人数**加起来。
 *
 * 刻意不数「有几种民族」：种类数只在每个少数民族恰好一个人时才等于名单的行数（演示库
 * 正好是这种巧合），换成人数才保证卡片上的数字点开永远和名单条数相等。两者的判据共用
 * 上面那个 isMinorityName，不会各算各的。
 */
export function countMinority(ethnicity) {
  return Object.entries(ethnicity || {}).reduce(
    (n, [name, count]) => n + (isMinorityName(name) ? count : 0),
    0
  )
}

/** 「有没有职务」：空串、null 和字面量「无」都算没有 */
function hasPosition(field) {
  return (s) => !!s[field] && s[field] !== '无'
}

/**
 * 卡片 key → 名单规则。key 与 Statistics.vue 里 overviewCards 的 key 一一对应。
 *
 *   pick   ：谁进这份名单
 *   field  ：有它就是**分组**展示（班委任职表、团学会按部门、民族按民族），
 *            group 取这个字段的值，column 是那一列的表头
 *
 * 「总人数」那种点了不出名单的卡不在这里 —— buildRoster 收到空 key 直接返回 null。
 */
const SPECS = {
  male: { title: '男生名单', pick: (s) => s.gender === '男' },
  female: { title: '女生名单', pick: (s) => s.gender === '女' },
  league: { title: '共青团员名单', pick: (s) => s.political_status === '共青团员' },
  poor: { title: '贫困生名单', pick: (s) => s.is_poor === '是' },
  committee: {
    title: '班委任职表',
    pick: hasPosition('class_position'),
    field: 'class_position',
    column: '职务'
  },
  leagueMember: {
    title: '团学会成员名单',
    pick: hasPosition('league_position'),
    field: 'league_position',
    column: '部门'
  },
  minority: {
    title: '少数民族名单',
    pick: isMinority,
    field: 'ethnicity',
    column: '民族'
  }
}

/**
 * 字符串升序。
 *
 * 用码点比而不用 localeCompare：后者依赖运行时的 locale 与 ICU 数据，同一份数据在不同
 * 机器上可能排出不同顺序（职务、民族这些词本来也没有公认的先后），测试会飘。
 */
function asc(a, b) {
  const x = String(a ?? '')
  const y = String(b ?? '')
  return x < y ? -1 : x > y ? 1 : 0
}

/**
 * 生成某张概览卡点开后的名单。
 *
 * @param {string} key 卡片标识（male / female / league / poor / committee / leagueMember / minority）
 * @param {object[]} students GET /api/students 返回的 items
 * @returns {null | {title: string, column: string, rows: {id: number, name?: string, student_no?: string, group?: string}[]}}
 *   返回 null = 这张卡不弹窗（key 为空或认不出来），调用方据此决定开不开弹窗
 */
export function buildRoster(key, students) {
  const spec = SPECS[key]
  if (!spec) return null

  const picked = (students || []).filter(spec.pick)
  // id 一路带出去：名单里的「详情」按钮要靠它跳到学生详情（/students?open=<id>）
  const baseRows = picked.map((s) => {
    const row = { id: s.id, name: s.name, student_no: s.student_no }
    if (spec.field) row.group = s[spec.field]
    return row
  })
  // 顺序显式排定：跟着列表里谁先出现走的话，同样的数据能排出不同结果
  const rows = spec.field
    ? baseRows.sort((a, b) => asc(a.group, b.group) || asc(a.student_no, b.student_no))
    : baseRows.sort((a, b) => asc(a.student_no, b.student_no))

  return { title: spec.title, column: spec.column || '', rows }
}
