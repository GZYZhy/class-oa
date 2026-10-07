// 前端渲染回归：用 vite 自己的 SSR 管道真渲染 SFC，断言用户看得见的文案。
//
//     cd frontend && npm test
//
// 几条 SSR 语义必须先知道，否则会白写一堆断言：
//   - onMounted 不执行（组件自己那次请求不会发生，所以下面用「灌数据」的办法）；
//   - el-dialog 的正文不渲染（弹窗里的文案断不到，只能断源码）；
//   - el-table 的数据行和表头都不渲染（行补了桩，表头没有 —— 见下面的 ElTableStub）；
//   - 没有 window、也没有 vue-router（两边都给了最小的桩，见下面）。
import { readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { createServer } from 'vite'
import { createSSRApp, h, inject } from 'vue'
import { renderToString } from 'vue/server-renderer'
import ElementPlus, { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import * as Icons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import { routeLocationKey, routerKey } from 'vue-router'

const ROOT = new URL('..', import.meta.url).pathname
let failed = 0

function check(cond, msg) {
  console.log(`  ${cond ? '✓' : '✗'} ${msg}`)
  if (!cond) failed++
}

// SSR 里没有 window，可 useIsMobile 这类 composable 在 setup 阶段就摸它
// （matchMedia 是同步调的，不像 onMounted 那样能躲过去），所以得补个最小桩。
// 只满足「读到不是窄屏」这一个判断：matches 恒 false，监听器空实现
globalThis.window = {
  matchMedia: () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {}
  })
}

const server = await createServer({
  root: ROOT,
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'silent'
})

/**
 * el-table 在 SSR 下**一个数据行都不渲染**：行要等客户端算完布局才建，SSR 里只有
 * hidden-columns 里的一串空 div（表头同理）。所以「成绩格里学生能看见什么」这类
 * 断言必须给它写桩 —— ElTable 把 data 放进 provide，ElTableColumn 拿它对每一行
 * 渲染一次自己的 default 插槽。**表头不在覆盖范围内**，要验列标题请断源码。
 *
 * 桩挂在 ElementPlus 之后注册，所以会盖掉真的实现。装在这里而不是只给某一节用：
 * 真表在 SSR 下本来就不出内容，有桩只会多内容不会少。
 */
const TABLE_DATA = Symbol('render-test-table-data')

const ElTableStub = {
  name: 'ElTableStub',
  props: { data: { type: Array, default: () => [] } },
  provide() {
    return { [TABLE_DATA]: this.data }
  },
  setup(props, { slots }) {
    return () => slots.default?.() ?? null
  }
}

const ElTableColumnStub = {
  name: 'ElTableColumnStub',
  props: { prop: String },
  setup(props, { slots }) {
    const rows = inject(TABLE_DATA, [])
    return () =>
      rows.map((row) =>
        // 只写了 prop 的列（如 prop="subject"）没有 default 插槽，回落到这个值
        h('div', slots.default ? slots.default({ row }) : String(row[props.prop] ?? ''))
      )
  }
}

async function render(path) {
  const app = createSSRApp((await server.ssrLoadModule(path)).default)
  app.use(ElementPlus)
  app.use(createPinia()) // 组件里那句 useUserStore() 得有活的 pinia
  app.provide(ID_INJECTION_KEY, { prefix: 1000, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  // 模板里写的是 <Upload /> <Plus /> 这类裸图标，真实应用靠 main.js 全局注册。
  // 桩环境不照做就会渲染成空标签，且只在警告里体现 —— 很容易漏过去
  for (const [name, icon] of Object.entries(Icons)) app.component(name, icon)
  // 直接写 components 表，不走 app.component()：Element Plus 已经注册过这两个名字，
  // 再注册一次 Vue 会打一条 "already been registered" 的 warn，而那条 warn 走的是
  // 全局 console（不受 config.warnHandler 管），只能从注册这一步本身绕开
  Object.assign(app._context.components, {
    ElTable: ElTableStub,
    ElTableColumn: ElTableColumnStub
  })
  // 页面组件会 useRoute() / useRouter()，而这里没装 vue-router。给两个够用的替身，
  // 省得为了"渲染一个页面"去搭一整套路由。真跨页跳转的逻辑本来也不该在这儿验
  app.provide(routeLocationKey, { path: '/', fullPath: '/', hash: '', query: {}, params: {}, meta: {} })
  app.provide(routerKey, { push() {}, replace() {}, back() {}, resolve: () => ({ href: '/' }) })
  const warns = []
  app.config.warnHandler = (msg) => warns.push(msg)
  return { html: await renderToString(app), warns }
}

/**
 * 把某个 SFC 源码里的一段换成别的，再真渲染一遍。
 *
 * 换掉 onMounted 那一句是为了「灌数据」：onMounted 在 SSR 里不执行，组件自己那次
 * load() 永远不发生。所以要做的是**把 onMounted(reload) 整个换成直接赋值** ——
 * 赋值语句在 setup 作用域里生效，不依赖挂载。
 *
 * 每次都得换一个新文件名：vite 的模块图按路径缓存，同名文件复用同一个模块，
 * 第二次灌的数据根本不会生效 —— 渲染出来的还是上一次的样子。
 * 临时文件写在**原组件同一个目录**，它里面的 `@/` 别名和相对导入才照旧解析。
 */
let seq = 0
async function renderPatched(relPath, marker, replacement) {
  const src = readFileSync(`${ROOT}${relPath}`, 'utf8')
  if (!src.includes(marker)) throw new Error(`${relPath} 里找不到要替换的那段：${marker}`)
  const dir = relPath.slice(0, relPath.lastIndexOf('/'))
  const file = `__render_test_${++seq}.vue`
  const tmp = `${ROOT}${dir}/${file}`
  writeFileSync(tmp, src.replace(marker, replacement), 'utf8')
  try {
    return await render(`${dir}/${file}`)
  } finally {
    unlinkSync(tmp)
  }
}

/** SetupWizard 专用：把 onMounted(refresh) 换成灌状态 */
async function renderWith(stateCode) {
  return renderPatched('/src/components/SetupWizard.vue', 'onMounted(refresh)', stateCode)
}

/**
 * 「完成初始化」按钮此刻是不是禁用的
 *
 * 必须严格匹配布尔属性：el-button 无论禁用与否都会渲染 aria-disabled="false"，
 * 用 includes('disabled') 去判会一路为真 —— 断言看着在跑，其实什么都没测。
 */
function submitDisabled(html) {
  const tag = html.match(/<button[^>]*setup-submit[^>]*>/)?.[0] ?? ''
  return /\sdisabled(?![\w-])/.test(tag)
}

console.log('\n▶ 初始化浮层：还没有学生')
{
  const { html, warns } = await render('/src/components/SetupWizard.vue')
  check(html.includes('首次初始化'), '标题在')
  check(html.includes('你现在用的是初始化临时账号'), '警示语在')
  check(html.includes('导入 Excel 名单'), '导入按钮在')
  check(html.includes('手工新增一名学生'), '手工新增按钮在')
  check(html.includes('先把上面那步做完'), '没学生时不让选人，并说清原因')
  check(submitDisabled(html), '提交按钮是禁用的')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')
}

console.log('\n▶ 初始化浮层：已有学生')
{
  const hasStudents = `Object.assign(state, { has_students: true,
      students: [{ student_no: '26990000001', name: '张三' }] })`
  const { html } = await renderWith(hasStudents)
  check(html.includes('已有 1 名学生'), '第一步显示已有几名')
  check(!html.includes('先把上面那步做完'), '有学生后不再拦着选人')
  check(html.includes('输入姓名或学号搜索'), '选人的下拉出来了')
  check(submitDisabled(html), '还没选人 → 提交仍然禁用')

  const { html: picked } = await renderWith(`${hasStudents}\n    adminStudentNo.value = '26990000001'`)
  check(!submitDisabled(picked), '选好人之后提交可点')
}

console.log('\n▶ 初始化浮层必须整屏换掉外壳（不是盖一层弹窗）')
{
  const src = readFileSync(`${ROOT}/src/App.vue`, 'utf8')
  check(/<SetupWizard v-if="userStore\.isBootstrap" \/>/.test(src), '浮层挂在 isBootstrap 上')
  check(/<router-view v-else-if="route\.meta\.bare" \/>/.test(src), '正常布局退到 v-else-if，两者不会同时渲染')
  check(src.includes('if (userStore.isBootstrap) return'), '登录态变化时的红点/推送刷新有守卫')
}

console.log('\n▶ 身份只认 is_bootstrap 列，不认登录名')
{
  const src = readFileSync(`${ROOT}/src/store/user.js`, 'utf8')
  check(/isBootstrap: \(state\) => !!state\.info\?\.is_bootstrap/.test(src), 'isBootstrap 取的是 info.is_bootstrap')
  check(!/isBootstrap[\s\S]{0,120}student_no === 'admin'/.test(src), '没有「登录名是不是 admin」这种判断')
}

console.log('\n▶ 学生名单页的导入弹窗已抽成公共组件')
{
  const list = readFileSync(`${ROOT}/src/views/StudentList.vue`, 'utf8')
  check(list.includes('<StudentImportDialog ref="importDialogRef" @done="fetchList" />'), '模板里挂的是公共组件')
  check(list.includes('importDialogRef.value?.open()'), '「更多 → 导入 Excel」走组件的 open()')
  check(!/importPreview|importConfirm/.test(list), '旧的 api 直接调用已清干净')

  const dialog = readFileSync(`${ROOT}/src/components/StudentImportDialog.vue`, 'utf8')
  check(/defineExpose\(\{ open \}\)/.test(dialog), '组件对外暴露 open()')
  check(/emit\('done'\)/.test(dialog), '导入成功后 emit done（调用方据此刷新）')
}

console.log('\n▶ 我的成绩：位次、通过制、标记词、未录入')
{
  // 形状照抄后端 MyGradeEntry（backend/app/schemas/grade.py）。顺手埋两个陷阱：
  // scored_count 是后端**刻意不再返回**的分母，位次给通过制科目也没意义 ——
  // 就算接口哪天漏回来，界面上也不该出现
  const grades = [
    {
      test_id: 1, name: '高数期中考', tested_at: '2026-04-01', remark: '',
      scores: [
        { subject: '数学', value: '120', mode: 'score', rank_percent: 25, scored_count: 40 },
        { subject: '体育', value: '通过', mode: 'pass_fail', rank_percent: 12 },
        { subject: '英语', value: '缺考', mode: 'score', rank_percent: null },
        { subject: '物理', value: '', mode: 'score', rank_percent: null }
      ]
    },
    {
      test_id: 2, name: '补考', tested_at: '2026-05-01', remark: '',
      scores: [
        { subject: '数学', value: '0', mode: 'score', rank_percent: 88.9 },
        { subject: '体育', value: '不通过', mode: 'pass_fail', rank_percent: null }
      ]
    }
  ]
  // MyInfo 的 onMounted 整段：里面又 fetchMe 又探 PWA（要 window），SSR 下本来就不跑，
  // 整段换成灌数据最省事。改了这段源码就跑不起来 —— 这里的 throw 是提醒，不是故障
  const LOAD = `onMounted(async () => {
  // 确保登录状态已解析（路由守卫通常已经做了，但以防万一）
  if (!userStore.resolved) await userStore.fetchMe()

  // 安装 PWA 提示
  standalone.value = checkIsStandalone()
  canInstall.value = checkCanInstall()

  await fetchData()
})`
  const { html, warns } = await renderPatched(
    '/src/views/MyInfo.vue',
    LOAD,
    `gradesList.value = ${JSON.stringify(grades)}`
  )
  const count = (s) => html.split(s).length - 1

  check(html.includes('排在前 25%'), '计分科目带位次小字')
  check(html.includes('排在前 88.9%'), '第二张测试卡片各渲染各的')
  check(!html.includes('排在前 12%'), '通过制科目不给位次（后端漏了也不显示）')
  check(count('grade-rank') === 2, '位次小字正好两处')

  check(count('grade-pass') === 1, '「通过」是绿的那个')
  check(count('grade-fail') === 1, '「不通过」是红的那个')
  check(count('grade-mark') === 1, '缺考走橙色标记，没落进通过/不通过')

  check(count('grade-none') === 1 && count('未录入') === 1, '只有空着的那格写「未录入」')
  check(!html.includes('人有成绩'), '不显示「N 人有成绩」——分母不返回给学生')
  check(!/排在前[^<]*人/.test(html), '位次小字里也不跟着人数')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')
}

await server.close()

console.log(`\n${'='.repeat(46)}`)
console.log(failed ? `失败 ${failed} 条` : '全部通过')
process.exit(failed ? 1 : 0)
