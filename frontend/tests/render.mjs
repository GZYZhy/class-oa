// 前端渲染回归：用 vite 自己的 SSR 管道真渲染 SFC，断言用户看得见的文案。
//
//     cd frontend && npm test
//
// 几条 SSR 语义必须先知道，否则会白写一堆断言：
//   - onMounted 不执行（组件自己那次请求不会发生，所以下面用「灌数据」的办法）；
//   - el-dialog 的正文不渲染（弹窗里的文案断不到，只能断源码）；
//   - el-table 的数据行和表头都不渲染（行补了桩，表头没有 —— 见下面的 ElTableStub）；
//   - 没有 window、也没有 vue-router（两边都给了最小的桩，见下面）。
import { readFileSync, readdirSync, unlinkSync, writeFileSync } from 'node:fs'
import { createServer } from 'vite'
import { createSSRApp, h, inject } from 'vue'
import { renderToString } from 'vue/server-renderer'
import ElementPlus, { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import * as Icons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import { routeLocationKey, routerKey } from 'vue-router'
import { registerHooks } from 'node:module'

// Node 原生不认 .css 这个扩展名。Vite 的 SSR 会把 node_modules 里的依赖「外部化」，
// 交回给 Node 自己 import —— 而 element-plus 的按需样式入口
// （element-plus/es/components/*/style/css.mjs，由 vite.config.js 的按需插件注入）
// 正是一串 import '...css'，于是整条管道在这里断掉：
//   TypeError [ERR_UNKNOWN_FILE_EXTENSION]: Unknown file extension ".css"
// 样式在 SSR 里本来就没用（产出的是字符串，不带 <style>），统一吞掉即可。
// 用同步的 registerHooks（Node 22.15+）而不是异步的 register：不引入额外线程，
// 也不用额外写一个 loader 文件。
registerHooks({
  load(url, context, nextLoad) {
    if (/\.css(\?|$)/.test(url)) return { format: 'module', source: '', shortCircuit: true }
    return nextLoad(url, context)
  }
})

const ROOT = new URL('..', import.meta.url).pathname
let failed = 0

function check(cond, msg) {
  console.log(`  ${cond ? '✓' : '✗'} ${msg}`)
  if (!cond) failed++
}

/**
 * 掐掉模板注释。SSR 是带注释输出的（Vue 的 dev 编译保留了它们），而注释里常写着
 * 「签字图按钮」这类词 —— 裸 includes 会被注释命中，不管元素渲没渲都是真。
 * 通知公告那节的 `<!-- RSS 订阅弹窗 -->` 踩过一次，这里统一走这个函数。
 */
function stripComments(html) {
  return html.replace(/<!--[\s\S]*?-->/g, '')
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
  // mode: 'test' 让 vite.config.js 跳过 Element Plus 按需插件 —— 这个测试靠全局
  // 注册的桩组件让表格出内容，按需插件会让 SFC 直接 import 真组件、绕过全局注册。
  // 详见 vite.config.js 里 Components 那段注释。
  mode: 'test',
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

/**
 * 会渲染正文的 el-dialog。SSR 下弹窗正文本来是不渲染的（见文件头），要断里面的
 * 表单项就只能盖掉它。**按 modelValue 决定渲不渲染**：无条件渲染的话，页面里
 * 其它没打开的弹窗内容会一起混进断言（踩过一次）。
 * 只给需要的那一节传（render 的第二个参数），不进全局 —— 免得别的节跟着变。
 */
const ElDialogStub = {
  name: 'ElDialogStub',
  props: { modelValue: Boolean, title: String },
  setup(props, { slots }) {
    return () => (props.modelValue ? h('div', [slots.default?.(), slots.footer?.()]) : null)
  }
}

async function render(path, extraComponents = {}, props = {}) {
  // props 给根组件用（如 AccountEventTag 的 event）；页面级调用不传，仍是空对象
  const app = createSSRApp((await server.ssrLoadModule(path)).default, props)
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
    ElTableColumn: ElTableColumnStub,
    ...extraComponents
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
async function renderPatched(relPath, marker, replacement, extraComponents = {}) {
  return renderPatchedMany(relPath, [[marker, replacement]], extraComponents)
}

/**
 * 一次换好几处的 renderPatched。分两次调 renderPatched 是不行的：第二次又从原文件
 * 重读，第一处替换就丢了。要同时改「身份」和「弹窗初始状态」时用这个。
 *
 * 每处都必须是唯一的（String.replace 只换第一处），找不到就抛 —— 源码改了这段，
 * 报错是提醒，不是故障。
 */
async function renderPatchedMany(relPath, patches, extraComponents = {}) {
  let src = readFileSync(`${ROOT}${relPath}`, 'utf8')
  for (const [marker, replacement] of patches) {
    if (!src.includes(marker)) throw new Error(`${relPath} 里找不到要替换的那段：${marker}`)
    src = src.replace(marker, replacement)
  }
  const dir = relPath.slice(0, relPath.lastIndexOf('/'))
  const file = `__render_test_${++seq}.vue`
  const tmp = `${ROOT}${dir}/${file}`
  writeFileSync(tmp, src, 'utf8')
  try {
    return await render(`${dir}/${file}`, extraComponents)
  } finally {
    unlinkSync(tmp)
  }
}

/** SetupWizard 专用：把 onMounted(refresh) 换成灌状态 */
async function renderWith(stateCode) {
  return renderPatched('/src/components/SetupWizard.vue', 'onMounted(refresh)', stateCode)
}

/**
 * MyInfo 的 onMounted 整段。
 *
 * 里面又 fetchMe 又探 PWA（要 window），SSR 下本来就不跑，整段换成灌数据最省事。
 * 源码改了这段就跑不起来 —— renderPatched 里的 throw 是提醒，不是故障。
 */
const MYINFO_LOAD = `onMounted(async () => {
  // 确保登录状态已解析（路由守卫通常已经做了，但以防万一）
  if (!userStore.resolved) await userStore.fetchMe()

  // 安装 PWA 提示
  standalone.value = checkIsStandalone()
  canInstall.value = checkCanInstall()

  await fetchData()
})`

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
  check(/<template v-else>[\s\S]{0,200}?<router-view v-if="route\.meta\.bare" \/>/.test(src),
    '正常布局退到 v-else，两者不会同时渲染')
  check(src.includes('if (userStore.isBootstrap) return'), '登录态变化时的红点/推送刷新有守卫')
}

console.log('\n▶ 签到页首屏不下载整站布局（弱网也要快）')
{
  const app = readFileSync(`${ROOT}/src/App.vue`, 'utf8')
  const layout = readFileSync(`${ROOT}/src/components/AppLayout.vue`, 'utf8')
  check(/import\('@\/components\/AppLayout\.vue'\)/.test(app), '整站布局拆出去按需加载')
  check(!app.includes('<el-container'), '入口外壳里不再有菜单、对话框这一整套')
  check(layout.includes('<el-container') && layout.includes('MENU_GROUPS'),
    '布局内容完整搬到了 AppLayout')
  check(layout.includes('userStore.refreshTotal()') && layout.includes('if (!userStore.resolved)'),
    '登录态与班级人数改由布局挂载时拉取')
  // 公开页不再多问一次登录态：需要的 is_login / is_target 由公开接口一并返回
  const checkin = readFileSync(`${ROOT}/src/views/Checkin.vue`, 'utf8')
  check(!checkin.includes('fetchMe'), '签到页只发一个信息请求，弱网少一个来回')
  check(!/from '@\/store\/user'/.test(checkin), '公开页不依赖用户 store')
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
  // @done 上挂的必须是个真存在的函数：这条断言以前写的是 fetchList，
  // 而组件里只有 fetchData —— 测试等于把错字本身钉成了正确答案。
  check(list.includes('<StudentImportDialog ref="importDialogRef" @done="fetchData" />'), '模板里挂的是公共组件，导入完叫得应刷新')
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
  const { html, warns } = await renderPatched(
    '/src/views/MyInfo.vue',
    MYINFO_LOAD,
    `gradesList.value = ${JSON.stringify(grades)}`
  )
  const count = (s) => html.split(s).length - 1

  check(html.includes('搜索考试名称'), '我的成绩顶上有考试名称搜索框')
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

console.log('\n▶ 考勤情况：我的信息页新增 tab，只列自己的考勤')
{
  const my = readFileSync(`${ROOT}/src/views/MyInfo.vue`, 'utf8')
  check(my.includes('label="考勤情况"') && my.includes('name="attendance"'),
    '我的信息页有「考勤情况」tab')
  check(my.includes("const known = ['info', 'grades', 'attendance', 'account', 'workspace']"),
    'URL 参数认识 attendance')
  check(my.includes("if (val === 'attendance') fetchMyAttendance()"),
    '切到这个 tab 才拉数据')
  check(my.includes('getMyAttendance') && my.includes('attendanceLoading'),
    '接上了自己的考勤接口与加载状态')
  check(/label="考勤情况"[\s\S]{0,600}<Watermark :text="watermarkText"/.test(my),
    '考勤情况页盖水印')
  check(my.includes('label="考勤时间"') && my.includes('label="考勤标题"') &&
    my.includes('label="考勤类型"') && my.includes('label="参与范围"') &&
    my.includes('label="我的出勤"'), '五个字段都在表里')
  check(my.includes('attendanceTag(row.status)'), '出勤状态按颜色区分')
  const api = readFileSync(`${ROOT}/src/api/attendance.js`, 'utf8')
  check(api.includes("url: '/attendance/mine'"), '走自己的考勤接口')
}

console.log('\n▶ 我的档案：三张照片，自备证件照在里面')
{
  // records 留空 → pending 为空 → 「申请修改」那一格渲染表单而不是「有待审」的提示
  const me = {
    id: 1, student_no: '2024000002', name: '乙', dormitory: '3 号楼 502',
    gaokao_photo: 'gk.png', on_site_photo: '', id_photo: 'id.png'
  }
  const { html, warns } = await renderPatched(
    '/src/views/MyInfo.vue',
    MYINFO_LOAD,
    `me.value = ${JSON.stringify(me)}`
  )
  const count = (s) => html.split(s).length - 1

  // 标签和成分之间还夹着 scoped 的 data-v 属性，别把整个开标签写死
  const label = (text) => new RegExp(`<div class="photo-label"[^>]*>${text}</div>`).test(html)
  check(label('高考照片'), '高考照片那一格还在')
  check(label('实地采集'), '实地采集那一格还在')
  check(label('自备证件照'), '自备证件照这一格补上了（原先漏的就是它）')
  check(count('photo-label') === 3, '照片位正好三个，没有多也没有少')
  check(count('暂无照片') === 1, '只有没照片的那一格写「暂无照片」')
  // 取图要带鉴权（学生只能取自己的），所以断的是接口地址而不是文件名
  check(html.includes('/api/students/1/photo?type=id'), '自备证件照走带鉴权的接口取，不是裸文件名')

  // 身份证号只补不改：这份档案没有 id_card，补充入口要出现
  check(html.includes('身份证号') && html.includes('18 位身份证号'),
    '没身份证号的学生能看到补充入口')
  check(html.includes('补充生效后就不能再自行修改'), '写明了只是一次性补充')

  // 有值之后整格消失，不给「改一下试试」的机会
  const { html: hasIdCardHtml } = await renderPatched(
    '/src/views/MyInfo.vue',
    MYINFO_LOAD,
    `me.value = ${JSON.stringify({ ...me, id_card: '11010120000101001X' })}`
  )
  check(!hasIdCardHtml.includes('补充生效后就不能再自行修改'),
    '已有身份证号的学生看不到补充入口')

  // 「申请修改」的表单和档案在同一个 html 里（el-tab-pane 默认全渲染）
  check(html.includes('选择照片'), '申请表里有换照片的按钮')
  check(html.includes('不选就是不改'), '写明了只换照片也算一次申请')
  check(
    html.includes('accept=".jpg,.jpeg,.png,.gif,.bmp,.webp"'),
    '只收图片格式，和后面的后缀白名单对齐'
  )

  // 签字图：学生本人可以上传，但看不到、下不了、删不掉
  check(html.includes('签字图') && html.includes('上传签字图'), '「申请修改」里有签字图上传入口')
  check(html.includes('未上传'), '没传过时显示「未上传」')
  check(html.includes('上传即生效，无需审核'), '写明签字图不走审批，和上面的资料修改区分开')
  check(html.includes('文件不超过 10MB') && html.includes('1200×400'),
    '页面上写明了文件大小和尺寸建议')
  check(!html.includes('管理员会收到一条提醒') && !html.includes('不能查看、下载或删除'),
    '签字图说明不再写管理员提醒与本人不能查看 / 下载 / 删除')
  check(!html.includes('/api/sign-photos/image'),
    '学生页不出现取图地址 —— 上传接口同路径，但只该由 api 模块拼，不该出现在模板里')

  // 手写签名：和上传并列的第二个入口。弹窗正文在 SSR 下不渲染，所以这里断
  // 「入口按钮」和「确认后确实走上传那套 API」，画布本身靠真机验
  check(html.includes('手写签名'), '「申请修改」里有手写签名入口')
  check(html.includes('自动裁边') && html.includes('透明背景的 PNG'),
    '写明了手写签名的产出（自动裁边、透明底 PNG）')
  const myInfoSrc = readFileSync(`${ROOT}/src/views/MyInfo.vue`, 'utf8')
  const applyAt = myInfoSrc.indexOf('label="申请修改"')
  const cardAt = myInfoSrc.indexOf('class="sign-card"')
  const recordsAt = myInfoSrc.indexOf('label="申请记录"')
  check(applyAt > -1 && applyAt < cardAt && cardAt < recordsAt,
    '签字图卡片确实放在「申请修改」这一页，不在档案页')
  check(myInfoSrc.includes('<SignaturePadDialog') &&
    myInfoSrc.includes('@confirm="handleHandSignConfirm"'),
  '手写弹窗挂在页面上，并通过同一个上传接口保存')

  // 有申请在排队时上面的表单会收起来，但换签字图是当场生效的事，不该被挡住
  const { html: pendingHtml } = await renderPatched(
    '/src/views/MyInfo.vue',
    MYINFO_LOAD,
    `me.value = ${JSON.stringify(me)};
     records.value = [{ id: 1, status: 'pending', created_at: '2026-10-01T10:00:00', changes: {} }]`
  )
  check(!pendingHtml.includes('改动提交后需班委审核') && pendingHtml.includes('上传签字图'),
    '待审期间表单收起，签字图照常能换')
  check(/function handleHandSignConfirm\(blob\)[\s\S]{0,400}uploadSignImage\(me\.value\.id/.test(myInfoSrc),
    '手写签名的 Blob 复用 uploadSignImage，不另开接口')

  // 传过之后按钮变成「重新上传」，状态变「已上传」
  const { html: uploadedHtml } = await renderPatched(
    '/src/views/MyInfo.vue',
    MYINFO_LOAD,
    `me.value = ${JSON.stringify(me)}; mySign.uploaded = true`
  )
  check(uploadedHtml.includes('已上传') && uploadedHtml.includes('重新上传'),
    '已上传后按钮提示可以重新上传（替换原图）')

  const signApi = readFileSync(`${ROOT}/src/api/signPhoto.js`, 'utf8')
  check(signApi.includes("url: '/sign-photos/my-status'"),
    '学生状态走 /sign-photos/my-status，不复用班委那条带文件名的状态接口')
  check(readFileSync(`${ROOT}/src/views/MyInfo.vue`, 'utf8')
    .includes("import { getMySignStatus, uploadSignImage } from '@/api/signPhoto'"),
    '档案页复用签字图那套 API（学生传、管理员传同一接口）')

  // 照片交的是文件，混进 CHANGE_FIELDS 就会被 resetForm / buildChanges / el-input
  // 当成文本框消费（界面上会多出一个要人填文件名的输入框）
  const src = readFileSync(`${ROOT}/src/utils/changeFields.js`, 'utf8')
  const list = (src.match(/CHANGE_FIELDS = \[([\s\S]*?)\]/) || [])[1] || ''
  check(!list.includes('id_photo'), '照片没有混进 CHANGE_FIELDS')
  check(!list.includes('id_card'), '身份证号也没有混进 CHANGE_FIELDS（要按当前值决定显不显示）')
  check(list.includes("prop: 'dormitory'"), '宿舍进了 CHANGE_FIELDS')
  check(/PHOTO_FIELD = \{ prop: 'id_photo'/.test(src), '它单独是 PHOTO_FIELD')
  check(/ID_CARD_FIELD = \{/.test(src), '身份证号单独是 ID_CARD_FIELD')
  check(readFileSync(`${ROOT}/src/views/MyInfo.vue`, 'utf8')
    .includes('if (needsIdCard.value)'),
  '提交时再挡一次：已有身份证号就不带这一项')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')
}

console.log('\n▶ 审核页：照片给班委看新旧两张，不给文件名')
{
  // 形状照抄后端 ChangeRequestResponse。pending 那条有照片，approved 那条也留一个 ——
  // 处理完之后旧图已经删了、新图归到学生名下，那两个地址取到的已不是当时那两张，
  // 所以只有待审的才画图
  const rows = [
    {
      id: 7, student_no: '2024000002', student_name: '乙', status: 'pending',
      created_at: '2026-10-07T10:00:00',
      changes: { phone: '13900139000', id_photo: 'a1b2c3d4-新.png' },
      current: { phone: '13800138000', id_photo: 'e5f6a7b8-旧.png' }
    },
    {
      id: 8, student_no: '2024000003', student_name: '丙', status: 'approved',
      created_at: '2026-10-06T10:00:00',
      changes: { id_photo: 'c9d0e1f2-已过.png' },
      current: { id_photo: 'a3b4c5d6-更旧.png' }
    }
  ]
  const { html } = await renderPatched(
    '/src/views/Review.vue',
    'onMounted(handleTabChange)',
    `changeList.value = ${JSON.stringify(rows)}`
  )
  const count = (s) => html.split(s).length - 1

  check(html.includes('/api/change-requests/7/photo?side=old'), '左边那张取学生当前档案里的')
  check(html.includes('/api/change-requests/7/photo?side=new'), '右边那张取这条申请里传的')
  check((html.match(/<img[^>]*diff-photo/g) || []).length === 2, '待审那条正好两张缩略图')
  check(count('diff-photo-click') === 2 && count('title="点击放大预览"') === 2,
    '两张缩略图都提示可以点开预览')
  check(!/change-requests\/8\/photo/.test(html), '已处理那条一个图地址都不给')

  for (const name of ['a1b2c3d4-新.png', 'e5f6a7b8-旧.png', 'c9d0e1f2-已过.png', 'a3b4c5d6-更旧.png']) {
    check(!html.includes(name), `文件名 ${name} 没露出来`)
  }
  check(html.includes('已上传新照片'), '已处理那条给一句话，而不是空着')
  check(html.includes('自备证件照'), '这一行的字段名念得出来（FIELD_LABELS 认得它）')

  // 点击与弹框都只在源码里：SSR 不渲染事件监听，el-dialog 正文也不渲染
  const reviewSrc = readFileSync(`${ROOT}/src/views/Review.vue`, 'utf8')
  check(/@click="openChangePhoto\(row, 'old'\)"/.test(reviewSrc)
    && /@click="openChangePhoto\(row, 'new'\)"/.test(reviewSrc),
  '两张缩略图点开都走同一个预览入口')
  check(reviewSrc.includes(':file-url="changePhotoUrl"')
    && reviewSrc.includes('v-model="changePhotoViewerVisible"'),
  '预览用的是通用 FileViewer，而不是另写一个弹窗')
  check(reviewSrc.includes('${row.student_name}_自备证件照_${sideLabel}${ext}'),
    '下载名换成姓名 + 原/新照片，不落 uuid 文件名')
  check(reviewSrc.includes(".match(/\\.[^.]+$/)"),
    '文件后缀从 current / changes 里的真实文件名取，FileViewer 才判得出图片类型')

  // 文本字段照旧并排原值 → 新值，别被照片的特判带歪
  check(html.includes('13800138000') && html.includes('13900139000'), '手机号仍然是原值 → 新值')
}

console.log('\n▶ 编辑学生信息：实地采集那一格能调摄像头拍照')
{
  // 弹窗正文 SSR 下不渲染（见文件头），所以这一节只断源码。
  // 两个 input 都是静态属性：capture 得出现在初始 HTML 里，
  // 而且 photoPicking 是普通 let，动态改属性根本不参与渲染
  const list = readFileSync(`${ROOT}/src/views/StudentList.vue`, 'utf8')
  const photoInputs = (list.match(/<input\b[^>]*>/g) || []).filter((t) =>
    t.includes('handlePhotoPicked')
  )

  check(photoInputs.length === 2, '两个隐藏 input 都交给同一个 handlePhotoPicked')
  check(photoInputs.every((t) => t.includes('accept="image/*"')), '两个都还限制 image/*（收窄会关掉安卓的相机入口）')
  check(photoInputs.filter((t) => t.includes('capture')).length === 1, '只有拍照那个带 capture，选文件那个照旧')
  check(list.includes('capture="environment"'), '拍的是后置摄像头（管理员持机对着学生拍）')
  check(/const cameraInput = ref\(null\)/.test(list), '第二个 input 的 ref 声明了（漏了点「拍照」会直接抛错）')

  // 按钮：只有实地采集那一格多一个「拍照」，且上传中不可点
  const camBtn = list.match(/<el-button\b[^>]*pickPhoto\(p\.type, true\)[^>]*>[\s\S]{0,80}拍照/) || ['']
  check(camBtn[0] !== '', '「拍照」按钮：点的是 pickPhoto(p.type, true)，文案是「拍照」')
  check(camBtn[0].includes(':disabled'), '上传中拍照按钮禁用 —— 否则开相机会把页面切后台、挂起正在传的那张')
  check(/v-if="p\.camera"[\s\S]{0,300}pickPhoto\(p\.type, true\)/.test(list), '「拍照」只挂在实地采集那一项上（p.camera）')
  check((list.match(/pickPhoto\(p\.type, true\)/g) || []).length === 1, '「拍照」按钮只有一个')
  check(/label: '实地采集', camera: true/.test(list), '实地采集那一项标了 camera: true，模板里没新写 type === 字面量')

  // 原有链路一个字没动
  check(/function pickPhoto\(type,\s*useCamera = false\)/.test(list), 'pickPhoto 多一个开关，默认仍走文件框')
  check(/useCamera\s*\?\s*cameraInput\s*:\s*photoInput/.test(list), '按开关决定点哪个 input')
  check(/pickPhoto\(p\.type\)/.test(list), '原来的「选择图片」还是不带第二个参数')
  check(/photoUploading === p\.type/.test(list), '上传进度/loading 还挂在「选择图片」上')
}

console.log('\n▶ 我的日程：按类型涂色，全天事件排一行按格子铺开')
{
  // 整段 onMounted 换成灌数据（onMounted 在 SSR 里不跑，见文件头）。
  // 同时钉住 currentMonday，周次才是可复现的：2026-10-05 那周，基准 09-14
  // → 第 4 周。用户报的就是这一条（表名「第4周」的课，页面显示成第 6 周）
  // [标题, 类型, 该落到的主题]。最后两行是「认不出来的类型」：手填的、
  // 老数据没填的 —— 都该走默认灰，而不是没颜色
  const CASES = [
    ['数学分析', '课程', 'theme-primary'],
    ['篮球', '体育', 'theme-success'],
    ['网课', '网络课', 'theme-warning'],
    ['班会', '会议', 'theme-danger'],
    ['迎新', '活动', 'theme-yellow'],
    ['值班', '工作', 'theme-purple'],
    ['社团', '社团', 'theme-info'],
    ['没类型', '', 'theme-info']
  ]
  const rows = CASES.map(([title, event_type], i) => ({
    id: i + 1, title, event_type, location: '', all_day: false,
    instance_date: '2026-10-08',
    start_time: `2026-10-08T${String(8 + i).padStart(2, '0')}:00:00`,
    end_time: `2026-10-08T${String(8 + i).padStart(2, '0')}:30:00`
  }))
  // 全天事件：一条单天的；再一条跨周四、周五 —— 导入的表里跨天会摊成
  // 一天一条（两条独立记录、同一个标题），页面得把它连回一条
  rows.push(
    { id: 99, title: '全天课', event_type: '课程', location: '', all_day: true,
      instance_date: '2026-10-08', start_time: '2026-10-08T00:00:00', end_time: '2026-10-08T23:59:00' },
    { id: 100, title: '国庆放假', event_type: '', location: '', all_day: true,
      instance_date: '2026-10-08', start_time: '2026-10-08T00:00:00', end_time: '2026-10-08T23:59:00' },
    { id: 101, title: '国庆放假', event_type: '', location: '', all_day: true,
      instance_date: '2026-10-09', start_time: '2026-10-09T00:00:00', end_time: '2026-10-09T23:59:00' }
  )
  const { html, warns } = await renderPatched(
    '/src/views/Schedule.vue',
    `onMounted(() => {
  loadSchedules()
  loadSemesterInfo()
  if (userStore.isCommittee) {
    loadStudents()
  }
  clockTimer = setInterval(() => { now.value = new Date() }, 30000)
})`,
    `schedules.value = ${JSON.stringify(rows)}
    currentMonday.value = new Date(2026, 9, 5)
    semesterPeriods.value = [{
      base: new Date(2026, 8, 14), first: new Date(2026, 8, 14), last: new Date(2027, 0, 3)
    }]`
  )
  // 按类名分词数，别拿全串 count()：all-day-date 里含 day-date、
  // cal-events-overlay 里含 cal-event，都会多算（踩过）。
  // 另外 :class 渲染在静态 class **前面**（class="theme-primary cal-event"），
  // 所以是按「同时含这几个类」找，不指望顺序
  const cls = (...names) =>
    (html.match(/class="([^"]*)"/g) || [])
      .map((a) => a.slice(7, -1).split(/\s+/))
      .filter((list) => names.every((n) => list.includes(n))).length

  // 数各主题各几个，和 CASES 里的分配比：映射改错（比如会议挪去 info）
  // 就会一边多一个一边少一个，跑不过
  const want = {}
  for (const [, , theme] of CASES) want[theme] = (want[theme] || 0) + 1
  for (const [theme, n] of Object.entries(want)) {
    check(cls('cal-event', theme) === n, `${theme} 正好 ${n} 个（${CASES.filter(c => c[2] === theme).map(c => c[1] || '没类型').join('、')}）`)
  }
  check(cls('cal-event') === CASES.length, `${CASES.length} 个定时事件都渲染了`)

  check(cls('all-day-item', 'theme-primary') === 1, '全天事件那块也跟着类型上色')

  // 「今天」「前往」必须包在同一个容器里：各自是独立项的话，窄屏换行时
  // 「今天」留在上一行、「前往」掉到下一行，两个同类操作就被拆散了
  check(cls('quick-jump') === 1, '「今天」「前往」包在同一个容器里')

  // 紫和黄是手写的色值（Element 的调色板里没有），深色模式得各写一份 ——
  // 只写浅色那份的话，深色下这两类会跟别的事件一样是浅底，字直接糊掉
  const schedSrc = readFileSync(`${ROOT}src/views/Schedule.vue`, 'utf-8')
  check(/\.theme-purple\s*\{/.test(schedSrc) && /\.dark \.theme-purple\s*\{/.test(schedSrc),
    '紫色有浅色和深色两份色值')

  // 日程搜索：同名日程可能很多，结果得在弹窗里一条条列出来让用户按日期挑。
  // 渲染时把弹窗打开、塞两条同名的进去，断言两个日期都出现在结果列表里
  check(schedSrc.includes('title="搜索日程"')
    && schedSrc.includes('v-for="item in searchDialog.results"'),
    '搜索结果在弹窗里以列表展示')
  const scheduleApi = readFileSync(`${ROOT}src/api/schedule.js`, 'utf8')
  check(/url: '\/schedules\/search'/.test(scheduleApi), '前端走 /schedules/search')
  const scheduleService = readFileSync(
    `${ROOT}../backend/app/services/schedule_service.py`, 'utf8')
  check(/keyword_like\(keyword, Schedule\.title\)/.test(scheduleService),
    '后端按日程标题模糊匹配')

  const searchRows = [
    {
      template_id: 1, title: '晚自习', instance_date: '2026-10-12', all_day: false,
      start_time: '2026-10-12T19:00:00', end_time: '2026-10-12T21:00:00',
      location: '教学楼D 301', repeat_type: 'weekly'
    },
    {
      template_id: 2, title: '晚自习', instance_date: '2026-10-13', all_day: false,
      start_time: '2026-10-13T19:00:00', end_time: '2026-10-13T21:00:00',
      location: '', repeat_type: 'none'
    }
  ]
  const searchHtml = (await renderPatched(
    '/src/views/Schedule.vue',
    "const searchDialog = ref({ open: false, keyword: '', loading: false, results: [] })",
    `const searchDialog = ref({ open: true, keyword: '晚自习', loading: false, results: ${JSON.stringify(searchRows)} })`,
    { ElDialog: ElDialogStub }
  )).html
  check(searchHtml.includes('2026-10-12') && searchHtml.includes('2026-10-13'),
    '两条同名日程在弹窗里各占一行，靠日期区分')
  check(/\.theme-yellow\s*\{/.test(schedSrc) && /\.dark \.theme-yellow\s*\{/.test(schedSrc),
    '黄色有浅色和深色两份色值')

  // 全天事件排在表头正下方那一行（在时间行之前），按格子跨列铺开
  check(html.indexOf('cal-allday') < html.indexOf('cal-body'), '全天行在时间行前面 —— 就是表头下面第一行')
  check(cls('all-day-item') === 2, '三条一天一条的合成两条：跨天的连回一条')

  // 把 style 里的 left/width 百分比换算回「第几列 / 跨几列」。周三=2、周四=3
  const bars = [...html.matchAll(/class="[^"]*all-day-item[^"]*"[^>]*style="([^"]*)"/g)].map((m) => ({
    col: Math.round((parseFloat(/left:calc\(([\d.]+)%/.exec(m[1])[1]) / 100) * 7),
    span: Math.round((parseFloat(/width:calc\(([\d.]+)%/.exec(m[1])[1]) / 100) * 7),
    top: parseInt(/top:(\d+)px/.exec(m[1])[1], 10)
  }))
  const spanning = bars.find((b) => b.span === 2)
  check(spanning && spanning.col === 3, '「国庆放假」从周四那格起，横跨周四+周五两格')
  const onThu = bars.filter((b) => b.col === 3)
  check(onThu.length === 2, '周四那格上正好两条')
  check(onThu[0].top !== onThu[1].top, '撞在同一格的两条分行摆，不叠在一起')

  // 表头：mm.dd 而不是拼出来的怪串
  check(cls('day-date') === 7, '表头七天都在')
  check(html.includes('>10.05<') && html.includes('>10.11<'), '表头日期是 mm.dd（10.05 / 10.11）')
  check(!html.includes('/2026-'), '没有「10/2026-10-08」那种拼接')

  // 周次跟后端给的区间走
  check(html.includes('10月5日 - 11日'), '本周区间念得出来')
  check(html.includes('（第4周）'), '这一周是第 4 周 —— 跟表名走，不是前端按 9 月估的')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')

  // 区间外不编号。课表只覆盖到 2027-01-03（16 周），翻到次年 5 月还按
  // 「距基准几周」算就会冒出「第 35 周」—— 用户报的就是这一条。
  // 负对照的另一半：区间**内**必须照常有（上面那条「（第4周）」）
  const far = await renderPatched(
    '/src/views/Schedule.vue',
    `onMounted(() => {
  loadSchedules()
  loadSemesterInfo()
  if (userStore.isCommittee) {
    loadStudents()
  }
  clockTimer = setInterval(() => { now.value = new Date() }, 30000)
})`,
    `schedules.value = []
    currentMonday.value = new Date(2027, 4, 3)
    semesterPeriods.value = [{
      base: new Date(2026, 8, 14), first: new Date(2026, 8, 14), last: new Date(2027, 0, 3)
    }]`
  )
  check(far.html.includes('5月3日 - 9日'), '翻到次年 5 月，日期区间照常念')
  check(!far.html.includes('（第'), '课表覆盖不到的周不编号（不再冒出「第 35 周」）')
}


console.log('\n▶ 我的日程：全天事件给「起止日期」，不给时刻')
{
  // 单测那段纯日期展开（跨月、含首尾最容易写错）
  const { daysInRange } = await server.ssrLoadModule('/src/utils/schedule.js')
  check(
    daysInRange('2026-10-05', '2026-10-07').join(' ') === '2026-10-05 2026-10-06 2026-10-07',
    '跨三天：首尾都算上，中间不落'
  )
  check(daysInRange('2026-10-30', '2026-11-02').join(' ') === '2026-10-30 2026-10-31 2026-11-01 2026-11-02',
    '跨月不差一天')
  check(daysInRange('2026-10-05').join(' ') === '2026-10-05', '只有开始日期时按单天算')
  check(daysInRange('2026-10-07', '2026-10-05').length === 0, '结束早于开始 → 空（提示交给调用方）')

  // 弹窗正文在 SSR 里本来不渲染（见文件头），这里配一个会渲染正文的桩。
  // 又因为 onMounted 不跑，「打开弹窗」得在 setup 里直接调 openEdit —— 替换点
  // 选在 editForm 声明那一行之后，放到 onMounted 的位置会撞上 const 的暂时性死区
  const MARKER = 'const editForm = ref(defaultForm())'
  const EVT = (o) => ({
    repeat_type: 'none', repeat_end_date: null, notify_enabled: false, notify_minutes_before: 10,
    location: '', description: '', event_type: '', ...o
  })
  // 一根条压着三天：库里是一天一条（导入摊的、自己建跨天的都是），点这根条要拿到整条
  const run = ['2026-10-05', '2026-10-06', '2026-10-07'].map((d, i) => EVT({
    id: i + 1, title: '国庆放假', all_day: true, instance_date: d,
    start_time: `${d}T00:00:00`, end_time: `${d}T23:59:00`
  }))
  const { html, warns } = await renderPatched('/src/views/Schedule.vue', MARKER,
    `${MARKER}
    schedules.value = ${JSON.stringify(run)}
    currentMonday.value = new Date(2026, 9, 5)
    openEdit(schedules.value[0], schedules.value)`, { ElDialog: ElDialogStub })

  // 取表单项的标签。别拿 includes('结束日期') 去断 —— 模板里的 HTML 注释也是 SSR
  // 输出的一部分，源码注释里就有这几个字，会假通过（踩过）
  const labels = (h) => [...h.matchAll(/class="el-form-item__label"[^>]*>(?:<!--\[-->)?([^<]+)/g)].map(m => m[1])
  check(labels(html).includes('结束日期'), '全天事件能设结束日期（跨天就是日历上连着的一条）')
  check(labels(html).includes('开始日期'), '日期那一栏改叫开始日期')
  check(!labels(html).includes('时间'), '全天事件没有「时间」那一栏')
  // 开关确实开着 —— 不然上面那条「没有时间」是假通过
  check(/全天(?:<!--\]-->)<\/div>[\s\S]{0,600}?role="switch" aria-checked="true"/.test(html),
    '「全天」开关是打开的')

  // 对照组：普通日程仍然要时间、不要结束日期。没这条的话，上面那句
  // 「没有时间」也可能是因为弹窗压根没渲染出来
  const timed = await renderPatched('/src/views/Schedule.vue', MARKER,
    `${MARKER}
    schedules.value = ${JSON.stringify([EVT({
      id: 9, title: '数学分析', all_day: false, instance_date: '2026-10-08',
      start_time: '2026-10-08T08:00:00', end_time: '2026-10-08T09:00:00',
      repeat_type: 'weekly', repeat_end_date: '2026-11-02'
    })])}
    currentMonday.value = new Date(2026, 9, 5)
    openEdit(schedules.value[0])`, { ElDialog: ElDialogStub })
  check(labels(timed.html).includes('时间'), '普通日程照旧有「时间」那一栏')
  check(!labels(timed.html).includes('结束日期'), '普通日程没有结束日期')
  // 重复那一栏本来也叫「结束日期」，会和全天这栏撞名 —— 现在叫「重复到」
  check(labels(timed.html).includes('重复到'), '重复到哪天那栏叫「重复到」，不会和全天的结束日期分不清')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')
}

console.log('\n▶ 我的日程：分配出去的日程能选改谁的表')
{
  const MARKER = 'const editForm = ref(defaultForm())'
  const EVT = (o) => ({
    repeat_type: 'none', repeat_end_date: null, notify_enabled: false, notify_minutes_before: 10,
    location: '', description: '', event_type: '', ...o
  })
  const labels = (h) => [...h.matchAll(/class="el-form-item__label"[^>]*>(?:<!--\[-->)?([^<]+)/g)].map(m => m[1])
  // 甲给三个人建的一条：三个人各有一行，share_count 记着「这条在几个人的表里」
  const shared = EVT({
    id: 1, title: '班会', all_day: false, instance_date: '2026-10-08',
    start_time: '2026-10-08T08:00:00', end_time: '2026-10-08T09:00:00',
    source_batch_id: 7, share_count: 3
  })
  const editWith = (evt) => `${MARKER}
    userStore.info = { role: 'committee' }
    schedules.value = ${JSON.stringify([evt])}
    currentMonday.value = new Date(2026, 9, 5)
    openEdit(schedules.value[0])`

  const { html, warns } = await renderPatched('/src/views/Schedule.vue', MARKER,
    editWith(shared), { ElDialog: ElDialogStub })

  check(labels(html).includes('改谁的表'), '自己分配出去的日程，编辑时有「改谁的表」')
  check(html.includes('所有人的（3 人）'), '人数按实际分享范围算（3 人）')
  check(html.includes('仅我自己的'), '另一档是「仅我自己的」')
  // 默认是「所有人的」。只认那一档自己的 input 上有没有 checked 属性：一开始写成
  // 「出现过 is-checked 类」是假的 —— 默认换成「仅我自己的」时，第二档自己会带上
  // 这个类，断言照样绿（试过）。value="true" 也就是「所有人的」这一档
  const shareBlock = html.slice(html.indexOf('改谁的表'), html.indexOf('改谁的表') + 600)
  check(/value="true"[^>]*\schecked[\s>]/.test(shareBlock), '默认选中「所有人的」')

  // 对照组：个人日程（share_count 缺省为 1）没有这一栏 —— 没有它的话上面那几条
  // 也可能只是「弹窗渲染出来了」而已
  const alone = EVT({
    id: 2, title: '自习', all_day: false, instance_date: '2026-10-08',
    start_time: '2026-10-08T19:00:00', end_time: '2026-10-08T21:00:00'
  })
  const { html: own } = await renderPatched('/src/views/Schedule.vue', MARKER,
    editWith(alone), { ElDialog: ElDialogStub })
  // 钉一个编辑态里必定存在的表单项：没有它，下面那条「没有改谁的表」也可能只是
  // 弹窗压根没渲染出来（「修改范围」只对重复日程才出，当锚点会不稳）
  check(labels(own).includes('开启通知'), '对照组确实渲染出了编辑弹窗')
  check(!labels(own).includes('改谁的表'), '个人日程没有「改谁的表」')

  // 编辑时不能留两个「谁」的控制项：影响范围是新建时的概念
  check(!labels(html).includes('影响范围'), '编辑态不再显示「影响范围」')
  const { html: creating } = await renderPatched('/src/views/Schedule.vue', MARKER,
    `${MARKER}
    userStore.info = { role: 'committee' }
    currentMonday.value = new Date(2026, 9, 5)
    openCreate()`, { ElDialog: ElDialogStub })
  check(labels(creating).includes('影响范围'), '新建时照旧有「影响范围」')
  check(!labels(creating).includes('改谁的表'), '新建时没有「改谁的表」（还没分配出去）')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')
}

console.log('\n▶ 我的日程：点卡片先看详情，详情里才能改')
{
  const MARKER = 'const editForm = ref(defaultForm())'
  const EVT = (o) => ({
    repeat_type: 'none', repeat_end_date: null, notify_enabled: false, notify_minutes_before: 10,
    location: '', description: '', event_type: '', ...o
  })
  const detailWith = (evt, records = null) => `${MARKER}
    userStore.info = { role: 'student' }
    currentMonday.value = new Date(2026, 9, 5)
    openDetail(${JSON.stringify(evt)}${records ? `, ${JSON.stringify(records)}` : ''})`
  // 详情是 el-descriptions、不是 el-form-item，上面那个 labels(h) 断不到，按单元格断
  const hasCell = (h, t) => h.includes(`>${t}<`)

  // 入口：点卡片开的是详情。直接开编辑的话，只想看一眼教室在哪也得先进到表单里
  const src = readFileSync(`${ROOT}/src/views/Schedule.vue`, 'utf8')
  check((src.match(/@click\.stop="openDetail\(/g) || []).length === 2,
    '全天条和定时块两处点击都开详情')
  check(!src.includes('@click.stop="openEdit('),
    '没有哪一处还直接弹编辑表单')
  // 跨天全天条是靠 records 认出来的，详情里带没了它就退化成单天
  check(/function editFromDetail\(\)[\s\S]{0,300}?openEdit\(evt, records\)/.test(src),
    '详情里点「编辑」把整条的 records 带过去')
  check(/function deleteFromDetail\(\)[\s\S]{0,400}?fillEditState\(evt, records\)[\s\S]{0,80}?handleDelete\(true\)/.test(src),
    '详情里点「删除」先借编辑那套状态，再走 handleDelete')

  const course = EVT({
    id: 1, title: '高等数学', all_day: false, instance_date: '2026-10-08',
    start_time: '2026-10-08T08:00:00', end_time: '2026-10-08T09:40:00',
    event_type: '课程', location: '教学楼D 301', description: '带教材',
    repeat_type: 'weekly', repeat_end_date: '2026-12-25',
    notify_enabled: true, notify_minutes_before: 15
  })
  const { html, warns } = await renderPatched('/src/views/Schedule.vue', MARKER,
    detailWith(course), { ElDialog: ElDialogStub })

  check(html.includes('高等数学'), '详情弹窗里是日程标题')
  check(hasCell(html, '日期') && html.includes('2026-10-08'), '有日期')
  check(html.includes('08:00 ~ 09:40'), '非全天给起止时刻')
  check(html.includes('教学楼D 301'), '有地点')
  check(html.includes('课程'), '有类型')
  check(html.includes('带教材'), '有描述')
  check(html.includes('每周（到 2026-12-25）'), '重复写明重复到哪天')
  check(html.includes('提前 15 分钟'), '有提醒')
  for (const t of ['编辑', '删除', '关闭']) {
    check(html.includes(t), `详情弹窗底部有「${t}」`)
  }
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')

  // 没填的字段不占行：弹出来是张干净的卡片，不是一个排满「-」的表
  const bare = EVT({
    id: 2, title: '自习', all_day: false, instance_date: '2026-10-09',
    start_time: '2026-10-09T19:00:00', end_time: '2026-10-09T21:00:00'
  })
  const { html: plain } = await renderPatched('/src/views/Schedule.vue', MARKER,
    detailWith(bare), { ElDialog: ElDialogStub })
  check(plain.includes('自习'), '对照组确实渲染出了详情弹窗')
  for (const t of ['地点', '类型', '描述', '提醒', '重复', '分配']) {
    check(!hasCell(plain, t), `没填${t}就不占一行`)
  }

  // 跨天的全天条：一条日程在日历上是一根连着几天的条，详情里要有起止
  const day = (d) => EVT({
    id: 3, title: '运动会', all_day: true, instance_date: d,
    start_time: `${d}T00:00:00`, end_time: `${d}T23:59:00`
  })
  const { html: span } = await renderPatched('/src/views/Schedule.vue', MARKER,
    detailWith(day('2026-10-08'), [day('2026-10-08'), day('2026-10-09'), day('2026-10-10')]),
    { ElDialog: ElDialogStub })
  check(span.includes('2026-10-08 至 2026-10-10'), '跨天的全天条给「起 至 止」')
  check(!hasCell(span, '时间'), '全天的不给时刻')
  check(!span.includes('00:00'), '全天的不显示库里那对 00:00 / 23:59')

  // 分配出去的那条：详情里先说清删它会不会动别人的表
  const { html: shared } = await renderPatched('/src/views/Schedule.vue', MARKER,
    detailWith(EVT({ ...course, share_count: 3 })), { ElDialog: ElDialogStub })
  check(shared.includes('已分配给 3 人（含你）'), '自己分配出去的在详情里点明人数')

  // 负对照：没点卡片时详情弹窗压根不渲染 —— 没有它，上面那些断言也可能只是
  // 「页面里本来就有这几个字」
  const { html: none } = await renderPatched('/src/views/Schedule.vue', MARKER,
    `${MARKER}
    userStore.info = { role: 'student' }
    currentMonday.value = new Date(2026, 9, 5)`, { ElDialog: ElDialogStub })
  check(!hasCell(none, '日期'), '没点卡片时没有详情弹窗')
}

console.log('\n▶ 系统管理：日程批次面板')
{
  // 表桩对每行跑 default 插槽，所以这里能真断到行里的内容（见文件头）
  const BATCHES = `batches.value = [
    { id: 1, name: '秋季课表', target_count: 36, schedule_count: 42, created_at: '2026-10-07T10:00:00' },
    { id: 2, name: '运动会安排', target_count: 3, schedule_count: 2, created_at: '2026-10-08T09:30:00' }
  ]`
  const { html, warns } = await renderPatched(
    '/src/components/ScheduleBatchPanel.vue',
    `onMounted(() => {
  if (!userStore.isExternal) load()
})`, BATCHES)

  check(html.includes('秋季课表') && html.includes('运动会安排'), '两条批次名都渲出来了')
  check(html.includes('>36<') && html.includes('>42<'), '目标人数 / 每人日程数各自成列')
  // 合计 = 目标人数 × 每人日程数（36×42=1512、3×2=6）。少了这一列，36 人的
  // 生日批次显示成「36 / 4」看着就像只有 4 条（用户报的就是这个）
  check(html.includes('>1512<') && html.includes('>6<'), '「合计」列把总量算出来了')
  const panelSrc = readFileSync(`${ROOT}src/components/ScheduleBatchPanel.vue`, 'utf-8')
  check(panelSrc.includes('label="每人日程数"') && !panelSrc.includes('label="日程数"'),
    '「日程数」改叫「每人日程数」—— 它是每人几条，不是这一批一共几条')
  check(html.split(/撤销(?:<!--\]-->)?<\/span>/).length - 1 === 2, '两行各有一个「撤销」按钮')
  check(html.includes('撤销一个批次'), '说明写清了撤销的后果')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')
}

console.log('\n▶ 裸挂在 @事件 上的处理器：名字要真有，带默认参数的还得加括号')
{
  // 裸挂（@click="openCreate"）时 Vue 会把 MouseEvent 当第一个实参传进去。openCreate(date = null)
  // 就是这么把事件对象写进 editForm.date / end_date 的：点「新建日程」→ 选个开始日期（结束日期
  // 没动，还是那个事件对象）→ 保存全天事件，daysInRange 里 (endStr || startStr).split 直接炸。
  // 单看 `@click="xxx"` 分不出对错（@row-click / @change 本来就该收到各自的载荷），所以判据是
  // 「这个名字在本文件里的声明，第一个参数带默认值」—— 带默认值就等于「可以不给」。
  //
  // 同一个正则还顺带管另一件事：**裸挂的名字在本文件里得真有**。
  // StudentList.vue 的 @done="fetchList" 就是这么坏掉很久没人发现的 —— 组件里根本没这个名字
  // （真名 fetchData），页面不报错、控制台也只留一句提示，结果导入学生/照片后列表一直是旧的。
  const files = []
  const walk = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.isDirectory()) walk(`${dir}/${e.name}`)
      else if (e.name.endsWith('.vue')) files.push(`${dir}/${e.name}`)
    }
  }
  walk(`${ROOT}src`)

  const bad = []
  const undeclared = []
  for (const f of files) {
    const src = readFileSync(f, 'utf-8')
    for (const m of src.matchAll(/@[a-z:.-]+="([A-Za-z_$][\w$]*)"/g)) {
      const name = m[1]
      // 同名函数在本文件里声明过、且第一个参数有默认值 → 裸挂必然把事件对象喂进去
      if (new RegExp(`function\\s+${name}\\(\\s*\\w+\\s*=`).test(src)) {
        bad.push(`${f.slice(ROOT.length)} @…="${name}"`)
      }
      // 声明可能是 function / const / let / var / import，也可能是解构赋值
      const declared = new RegExp(
        `(?:function\\s+${name}\\b)|(?:\\b(?:const|let|var)\\s+${name}\\b)|(?:import\\s[^;]*\\b${name}\\b)|(?:\\{[^}]*\\b${name}\\b[^}]*\\}\\s*=)`
      ).test(src)
      if (!declared) undeclared.push(`${f.slice(ROOT.length)} @…="${name}"`)
    }
  }
  check(bad.length === 0, `没有裸挂的处理器${bad.length ? `（${bad.join('；')}）` : ''}`)
  check(undeclared.length === 0, `裸挂的名字都能在本文件里找到声明${undeclared.length ? `（找不到：${undeclared.join('；')}）` : ''}`)

  const src = readFileSync(`${ROOT}src/views/Schedule.vue`, 'utf-8')
  check(src.includes('@click="openCreate()"'), '「新建日程」写的是 openCreate()，不是裸挂')

  // 导入和批量签字都会改数据，做完都得叫调用方刷新列表
  const listSrc = readFileSync(`${ROOT}src/views/StudentList.vue`, 'utf-8')
  check(['StudentImportDialog', 'PhotoImportDialog', 'BatchSignDialog'].every((name) =>
    new RegExp(`<${name}[^>]*@done="fetchData"`).test(listSrc)),
  '学生导入、照片导入、批量签字三个弹窗，做完都去刷新列表')
}

console.log('\n▶ 我的日程：全天条的范围选择与几处「点了没反应」')
{
  const MARKER = 'const editForm = ref(defaultForm())'
  const EVT = (o) => ({
    repeat_type: 'none', repeat_end_date: null, notify_enabled: false, notify_minutes_before: 10,
    location: '', description: '', event_type: '', share_count: 1, ...o
  })
  const labels = (h) => [...h.matchAll(/class="el-form-item__label"[^>]*>(?:<!--\[-->)?([^<]+)/g)].map(m => m[1])
  const editWith = (evts, records) => `${MARKER}
    userStore.info = { role: 'committee' }
    schedules.value = ${JSON.stringify(evts)}
    currentMonday.value = new Date(2026, 9, 5)
    openEdit(schedules.value[0]${records ? ', schedules.value' : ''})`

  // 单条的全天重复日程（比如「每周三值日」）：改范围必须能选，且只有它能选
  const single = EVT({
    id: 1, title: '值日', all_day: true, instance_date: '2026-10-07',
    start_time: '2026-10-07T00:00:00', end_time: '2026-10-07T23:59:00',
    repeat_type: 'weekly', repeat_end_date: '2026-12-31'
  })
  const { html, warns } = await renderPatched('/src/views/Schedule.vue', MARKER,
    editWith([single]), { ElDialog: ElDialogStub })
  check(labels(html).includes('修改范围'), '全天 + 重复：能选「修改范围」（单条时）')

  // 跨天的全天条（一天一条，日历上是一根）：整条一起改，那就别摆出「仅本次」骗人
  const run = ['2026-10-05', '2026-10-06', '2026-10-07'].map((d, i) => EVT({
    id: i + 10, title: '国庆放假', all_day: true, instance_date: d,
    start_time: `${d}T00:00:00`, end_time: `${d}T23:59:00`,
    repeat_type: 'weekly', repeat_end_date: '2026-12-31'
  }))
  const { html: bar } = await renderPatched('/src/views/Schedule.vue', MARKER,
    editWith(run, true), { ElDialog: ElDialogStub })
  check(labels(bar).includes('开启通知'), '对照组：跨天的那根条确实渲染出了编辑弹窗')
  check(labels(bar).includes('结束日期'), '跨天的条能改起止日期')
  check(!labels(bar).includes('修改范围'), '跨天的整条不显示「修改范围」（保存/删除都是整条走，摆出来就是骗人）')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')

  // 左上角那格显示当前时间（hh:mm）：表头本来空着，正好放
  const clock = html.match(/class="now-clock"[^>]*>([^<]*)</)
  check(clock && /^\d{2}:\d{2}$/.test(clock[1]), `表头角上是 hh:mm 的当前时间（实际：${clock && clock[1]}）`)
  check(html.includes('当前时间'), '时钟上方写着「当前时间」')

  // 表头两处可点：周几把自己那列居中，左上角「当前时间」跳到当前时间所在行
  check((html.match(/title="点击把这一天移到中间"/g) || []).length === 7,
    '七个周几表头都能点')
  check(/title="点击跳到当前时间"/.test(html), '左上角「当前时间」那格也能点')

  const src = readFileSync(`${ROOT}src/views/Schedule.vue`, 'utf-8')
  check(/@click="centerDay\(day\.date, true\)"/.test(src), '点周几把那一列移到中间')
  check(/function centerDay\(date, smooth = false\)[\s\S]{0,500}?box\.scrollTo\(\{ left, behavior: 'smooth' \}\)/.test(src),
    '表头点击用平滑滚动（首次进页面仍瞬间定位，不在眼前自己滑一下）')
  check(/@click="scrollToNow"/.test(src), '点「当前时间」跳到当前时间附近')
  check(/function scrollToNow\(\) \{[\s\S]{0,400}?scrollIntoView\(\{ block: 'center'[\s\S]{0,80}?behavior: 'smooth' \}\)/.test(src),
    '按当前时间找到那一行，滚到屏幕中间')
  check(/function nowSlotIndex\(\) \{[\s\S]{0,300}?Math\.min\(Math\.max\(idx, 0\), timeSlots\.value\.length - 1\)/.test(src),
    '7:00 前 / 22:00 后夹到首尾两格，不越界')
  // 时钟靠定时器走，离开页面必须停掉，否则每进一次日程页就多一个永不回收的定时器
  check(/onUnmounted\(\(\) => \{[\s\S]{0,200}?clearInterval\(clockTimer\)/.test(src), '离开页面时停掉时钟定时器')
  // 窄窗口（半屏、手机）下工具栏一行放不下，「新建日程」会被挤出可见区域点不到
  const toolbar = src.slice(src.indexOf('.toolbar {'), src.indexOf('.week-nav {'))
  check(/flex-wrap:\s*wrap/.test(toolbar), '顶部工具栏允许换行，窄屏按钮不会被挤出去')
  // 搜索/导入/订阅/新建日程必须同一行：Element 给相邻按钮的 margin-left
  // 加上默认内边距，375px 上正好把「新建日程」顶到下一行
  check(/\.actions \{\s*flex-wrap: nowrap;[\s\S]{0,120}?width: 100%;[\s\S]{0,120}?gap: 6px;/.test(src),
    '手机上四个操作按钮强制同一行')
  check(/\.actions :deep\(\.el-button \+ \.el-button\) \{\s*margin-left: 0;/.test(src),
    '去掉相邻按钮自带的 margin-left（否则还是会换行）')

  // 全天条保存时把「修改范围」照用户选的传（写死 'all' 时，选「仅本次」会改掉整个序列）
  check(/scope:\s*form\.scope/.test(src), 'saveAllDay 用的是用户选的 scope')
  // 清空「结束日期」会缩小范围 → 先确认再删，不能悄悄把其余几天抹掉
  check(src.includes("'确认缩小范围'"), '缩小日期范围会先确认，再删多余的天数')
  // 关掉「全天」时整条一起转，别只转点中的那一天
  check(/isMultiDayBar\.value\)\s*\{/.test(src), '跨天的条关掉「全天」时整条一起转')

  // 请求失败不能是「点了没反应」：request.js 的拦截器只打 console
  for (const fn of ['runImportPreview', 'handleImportConfirm']) {
    const body = src.slice(src.indexOf(`function ${fn}`) || src.indexOf(`async function ${fn}`))
    check(/catch \(e\)/.test(body.slice(0, 1600)), `${fn} 接住了失败并给了提示`)
  }
  // 关掉导入弹窗要把 el-upload 一起销毁：它的文件列表留着，配上 :limit="1"
  // 会把下次选的文件直接吞掉，「下一步」永远是灰的
  check(/destroy-on-close/.test(src) && /@closed="resetImport"/.test(src),
    '导入弹窗关掉即复位（否则再选的文件会被 :limit="1" 吞掉）')
  check(/importTouched/.test(src), '反选到一条不剩时不当成「全选」')
}

console.log('\n▶ 我的日程：窄屏不把 7 天挤扁，今天默认居中')
{
  // 把某一列摆到正中间的换算（两端要夹住：滑到最右的周日不能滚出内容外）
  const { centerScrollLeft } = await server.ssrLoadModule('/src/utils/schedule.js')
  check(centerScrollLeft(410, 140, 1100, 0) === 0, '桌面上放得下 → 不滚')
  check(centerScrollLeft(324, 132, 375, 609) === 202.5, '手机上把周三那列摆到正中间')
  check(centerScrollLeft(60, 132, 375, 609) === 0, '周一本来就靠左，不往回滚')
  check(centerScrollLeft(852, 132, 375, 609) === 609, '周日靠右 → 夹到最右，不滚出内容外')

  // 「今天」钉在当周显示的那一周的周三：不然这条断言会随真实日期一起过期
  const TODAY = `const today = new Date()
  today.setHours(0, 0, 0, 0)`
  const { html } = await renderPatched('/src/views/Schedule.vue', TODAY,
    `${TODAY}
  today.setTime(new Date(
    currentMonday.value.getFullYear(), currentMonday.value.getMonth(),
    currentMonday.value.getDate() + 2
  ).getTime())`)

  // 居中就是靠这个类找列的（.cal-header .cal-day-col.today），表头里必须正好一个。
  // 按类名分词找、别按顺序：:class 渲染在静态 class 前面（「today cal-day-col」）
  const head = html.slice(html.indexOf('cal-header'), html.indexOf('cal-allday'))
  const cols = [...head.matchAll(/class="([^"]*)"/g)]
    .map((m) => m[1].split(/\s+/))
    .filter((list) => list.includes('cal-day-col'))
    .map((list) => list.includes('today'))
  check(cols.length === 7, '表头还是 7 列')
  check(cols.filter(Boolean).length === 1 && cols[2] === true,
    '正好一列带 today，就是当天那一列（滚动居中的钩子）')

  const src = readFileSync(`${ROOT}src/views/Schedule.vue`, 'utf-8')
  check(/\.calendar-wrapper\s*\{[^}]*overflow-x:\s*auto/.test(src), '表格能横向滚（不再 overflow: hidden 裁掉）')
  check(/\.calendar-grid\s*\{[^}]*min-width:\s*calc\(60px \+ 7 \* 132px\)/.test(src),
    '列宽有底线：时间列 + 7 × 132px —— 窄屏照电脑上的宽来，不挤窄')
  check(/\.cal-time-col\s*\{[^}]*position:\s*sticky[^}]*left:\s*0/.test(src),
    '时间刻度钉在左边（滑到今天那列还看得见几点）')
  check(/ref="calendarWrapper"/.test(src) && /const calendarWrapper = ref\(null\)/.test(src),
    '模板上的滚动容器 = 居中逻辑用的那个 ref')
  check((src.match(/nextTick\(centerToday\)/g) || []).length === 2,
    '居中接在「首次加载完」和「点今天」两处')
}

console.log('\n▶ 我的日程：「前往」跳到某一天')
{
  // 弹窗正文在 el-dialog 里，SSR 默认不渲染 —— 盖个会渲染正文的桩。
  // 标记取整个两行声明块：只换第一行的话，后面那句 const goDate 会留下来撞名字
  const MARKER = `const goDialog = ref({ open: false })
const goDate = ref('')`
  const openWith = (date, call = '') => `const goDialog = ref({ open: true })
const goDate = ref('${date}')${call}`

  // 跳完停在目标那一周：换周是靠 currentMonday，周标签跟着 weekDays 一起重算。
  // 两个不同的日子各跳一次 —— 只跳一次的话，万一那天正好落在本周，断言会假通过
  const { html: nov, warns } = await renderPatched('/src/views/Schedule.vue', MARKER,
    openWith('2026-11-05', '\ngoToDate()'), { ElDialog: ElDialogStub })
  check(nov.includes('11月2日 - 8日'), '选 11-05（周四）→ 停在它那一周（11/02–11/08）')
  check(nov.includes('11.05'), '目标那一天就在表里（列跟着一起翻过去了）')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)),
    '没有未解析的组件/指令')

  const { html: dec } = await renderPatched('/src/views/Schedule.vue', MARKER,
    openWith('2026-12-25', '\ngoToDate()'), { ElDialog: ElDialogStub })
  check(dec.includes('12月21日 - 27日'), '换成 12-25 就停到 12/21–12/27 那一周（真在按日期跳）')
  check(!dec.includes('11月2日 - 8日'), '不留下上一次跳的那一周')

  // 负对照：没点「前往」时那两周一个都不该出现（今天在 10 月）
  const { html: plain } = await render('/src/views/Schedule.vue', { ElDialog: ElDialogStub })
  check(!plain.includes('11月2日 - 8日') && !plain.includes('12月21日 - 27日'),
    '负对照：不点就不换周')

  // 弹窗正文：默认填眼前的周一，正文里说清跳的是「那一天所在的那一周」
  const { html: dialog } = await renderPatched('/src/views/Schedule.vue', MARKER,
    openWith('2026-11-05'), { ElDialog: ElDialogStub })
  // el-dialog 的标题走 props（桩只渲染正文和 footer），所以标题只能断源码
  check(dialog.includes('跳到这一天所在的那一周'), '正文说清跳的是那一天所在的那一周')
  check(dialog.includes('el-date-editor'), '是个日期选择器')
  check(!plain.includes('跳到这一天所在的那一周'), '负对照：弹窗没打开时不出现')

  // 工具栏那个按钮（弹窗关着也看得见）
  check(/<button\b[^>]*>(?:(?!<\/button>)[\s\S])*?前往/.test(plain), '工具栏上有「前往」按钮')

  const src = readFileSync(`${ROOT}src/views/Schedule.vue`, 'utf-8')
  check(/title="前往某一天"/.test(src), '弹窗标题是「前往某一天」')
  check(/currentMonday\.value = getMonday\(d\)/.test(src), '换成所选日期那一周的周一')
  check(/nextTick\(\(\) => centerDay\(goDate\.value\)\)/.test(src),
    '跳完把目标那一列滚到中间')
  check(/weekDays\.value\.findIndex\(d => d\.date === date\)/.test(src),
    '居中按日期找列（不是只认「今天」那一列）')
  check(/function centerToday\(\) \{\s*centerDay\(formatDate\(new Date\(\)\)\)/.test(src),
    '「今天」居中走的还是同一条路，两处不会各算一套')
}

console.log('\n▶ 我的日程：导入的周次锚点')
{
  // 导入弹窗的正文在 el-dialog 里，得盖个会渲染正文的桩；预览表和「下一步」
  // 也一样（footer 由桩一起渲染出来）。
  // 灌的是「文件里最小是第 8 周、锚点已定在 11/02」这一档 —— 日期列要能核对锚点
  const MARKER = 'const importForm = ref({'
  const openWith = (extra = '') => `importDialog.value = { open: true }
  importStep.value = 1
  importPreview.value = {
    items: [{
      title: '高等数学', weekday: 1, start_date: '2026-11-02',
      start_time: '08:00', end_time: '09:50',
      all_day: false, repeat_type: 'none', location: '教学楼C101',
    }],
    week_count: 3, week_first: 8, week_last: 10, anchor_monday: '2026-11-02',
    schedule_count: 1, all_day_count: 0, warnings: [],
  }
  ${extra}
${MARKER}`

  const { html, warns } = await renderPatched('/src/views/Schedule.vue', MARKER,
    openWith(), { ElDialog: ElDialogStub })

  check(html.includes('周次锚点'), '确认这一步摆着「周次锚点」')
  check(html.includes('最小是') && html.includes('第 8 周'),
    '提示里带上文件里最小的周次（第 8 周），用户才知道该指认哪一周')
  check(html.includes('由它推算'), '说明了所有日期都由锚点推算')
  check(html.includes('2026-11-02 周一'),
    '日程表按日期列核对：锚点选错时日期一眼就能看出来（原来只显示「周一」）')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)),
    '没有未解析的组件/指令')
  check(html.includes('el-date-editor'), '锚点是个日期选择器')

  // 负对照：弹窗没打开时上面这些一个字都不该有，否则「压根没渲染」也能假通过
  const { html: closed } = await render('/src/views/Schedule.vue', { ElDialog: ElDialogStub })
  check(!closed.includes('周次锚点') && !closed.includes('2026-11-02 周一'),
    '负对照：弹窗没打开时不出现')

  // 锚点没定下来就不让往下走：日期全靠它算，空着进了「选择目标」等于导出一堆错日期
  const src = readFileSync(`${ROOT}src/views/Schedule.vue`, 'utf-8')
  check(src.includes('importStep === 1 && !importAnchor'),
    '锚点为空时「下一步」是灰的')
  check(/@change="runImportPreview"/.test(src),
    '改锚点拿同一份文件重新解析（日期全部重算）')
  check(/:disabled-date="notMonday"/.test(src),
    '只让选周一 —— 锚点按定义就是某一周的周一')
  // 解析失败（后端 400）时不能往下走：会跳进一个「第 0 周、0 条」的空预览，
  // 勾不了任何东西也回不去，用户只会以为文件读进去了
  check(/if \(await runImportPreview\(\)\) importStep\.value = 1/.test(src),
    '「下一步」看解析结果决定要不要进第 2 步')
  check(/errText\(e, '解析文件失败'\)\)\s*return false/.test(src),
    '解析失败返回 false（catch 里吞掉就永远不知道失败了）')
  check(/if \(anchorMonday\) formData\.append\('anchor_monday', anchorMonday\)/.test(
    readFileSync(`${ROOT}src/api/schedule.js`, 'utf-8')),
    '锚点以表单字段发给后端')
}

console.log('\n▶ 通知公告：RSS 订阅（需要登录）')
{
  const NOTICES = '/src/views/Notices.vue'

  // 判「订阅按钮在不在」不能直接找 'RSS 订阅' 这几个字：模板里的
  // `<!-- RSS 订阅弹窗 -->` 也是 SSR 输出的一部分，裸 includes 会被它命中，
  // 不管按钮渲没渲都是真。所以要求这几个字确实落在某个 <button> 里
  const hasSubscribeButton = (html) =>
    /<button\b[^>]*>(?:(?!<\/button>)[\s\S])*?RSS 订阅/.test(html)

  // 订阅按钮的可见性。pinia 的 info 是 state，直接赋值就能让 isLogin / isExternal
  // 这两个 getter 跟着变，不用真去登录
  const AS_MEMBER = `const userStore = useUserStore()
  userStore.info = { student_no: '2024000001', name: '甲', role: 'admin', is_external: false }`
  const { html: asMember } = await renderPatched(
    NOTICES, 'const userStore = useUserStore()', AS_MEMBER)
  check(hasSubscribeButton(asMember), '登录后能看到订阅按钮')

  const AS_EXTERNAL = `const userStore = useUserStore()
  userStore.info = { student_no: 'x', name: '李老师', role: 'guest', is_external: true }`
  const { html: asExternal } = await renderPatched(
    NOTICES, 'const userStore = useUserStore()', AS_EXTERNAL)
  check(!hasSubscribeButton(asExternal),
    '域外账号看不到（后端给这个身份签订阅令牌是 403）')

  // 弹窗正文：把三个状态量的声明整段换掉，让弹窗「已经打开、链接已取到」
  const { html } = await renderPatched(
    NOTICES,
    `const subscribeDialog = ref({ open: false })
const subscribeLoading = ref(false)
const subscribeUrl = ref('')`,
    `const subscribeDialog = ref({ open: true })
const subscribeLoading = ref(false)
const subscribeUrl = ref('http://oa.example.com/api/notices/rss/cafebabe.xml')`,
    { ElDialog: ElDialogStub })

  check(html.includes('你的私有订阅链接'), '弹窗里有订阅链接这一块')
  check(html.includes('cafebabe.xml'), '链接原样显示在输入框里')
  check(html.includes('请勿分享给他人'), '写明链接里是私人令牌')
  check(html.includes('Feedly'), '说明是给 RSS 阅读器用的')
  check(html.includes('共用同一个订阅令牌'), '写明了和「我的日程」共用令牌')
  check(!html.includes('重置订阅令牌'),
    '没有重置按钮 —— 重置的是日程那条共用令牌，只在日程页做')

  // 负对照：弹窗没打开时上面那些文案一个都不该出现。
  // 少了这一步，「弹窗压根没渲染」也能让上面的断言全部假通过
  const { html: closed } = await render(NOTICES, { ElDialog: ElDialogStub })
  check(!closed.includes('你的私有订阅链接') && !closed.includes('Feedly'),
    '负对照：弹窗没打开时这些文案不出现')

  // ---------- ?id=123 定位 ----------
  const { noticeIdFromQuery } = await server.ssrLoadModule('/src/utils/notice.js')
  check(noticeIdFromQuery({ id: '123' }) === 123,
    'query 里是字符串，转成数字（不转的话 :name 是数字，面板不展开）')
  check(noticeIdFromQuery({ id: ['7', '8'] }) === 7, '?id=1&id=2 成了数组时取第一个')
  for (const bad of [undefined, {}, { id: '' }, { id: 'abc' }, { id: '0' },
                     { id: '-1' }, { id: '1.5' }, { id: '  ' }]) {
    check(noticeIdFromQuery(bad) === null, `取不到 id 时给 null：${JSON.stringify(bad)}`)
  }
  check(noticeIdFromQuery({ id: ' 12 ' }) === 12, '两头带空格也认')

  const src = readFileSync(`${ROOT}src/views/Notices.vue`, 'utf-8')
  check(src.includes('v-if="userStore.isLogin && !userStore.isExternal"'),
    '模板上的可见性条件就是这一条')
  check(src.includes('copyText(subscribeUrl.value)'),
    '复制走公共的 copyText（带 execCommand 降级）')
  check(!/navigator\.clipboard/.test(src),
    '这一页不出现裸的 navigator.clipboard（内网 http 下它拿不到）')
  check(/:id="'notice-item-' \+ item\.id"/.test(src),
    '每个面板挂上定位用的 id')

  // 定位必须绕开 fetchList 结尾那句「展开第一条」，否则每次搜索/发布都会跳回第一条
  const fetchBody = src.slice(
    src.indexOf('async function fetchList'),
    src.indexOf('/** 按 ?id= 定位'))
  check(fetchBody.indexOf('if (target)') < fetchBody.indexOf('activeNames.value = list.value.length'),
    '有目标时提前 return，不被下面那句「展开第一条」覆盖')
  check(fetchBody.indexOf('markRead([target])') < fetchBody.indexOf('markRead(list.value.slice(0, 1))'),
    '从链接进来只标目标那条已读，不顺手把最新那条也标了')
  check(src.includes('onMounted(focusFromQuery)'), '首屏走 focusFromQuery（没有 ?id= 就是普通加载）')
  check(src.includes('watch(() => route.query.id, focusFromQuery)'),
    '同标签内换到另一条时跟着切（组件不会重建）')
}

console.log('\n▶ 学生信息页：低频操作收进「更多」，年龄排序的方向没反')
{
  const src = readFileSync(`${ROOT}/src/views/StudentList.vue`, 'utf8')

  // 「更多」原来挂着 v-if="isAdmin"：近期生日（所有人都能看）和导出（班委及以上）
  // 塞进去就不能再整块只给管理员。改成整块都显示、可见性逐项跟着原来那个按钮走
  check(!/el-dropdown v-if="userStore\.isAdmin" @command="handleMore"/.test(src),
    '「更多」不再整块只给管理员看（否则班委点不到导出、学生点不到近期生日）')
  const more = src.slice(src.indexOf('<el-dropdown @command="handleMore">'))
  const menu = more.slice(0, more.indexOf('</el-dropdown>'))
  check(menu.includes('command="birthday"'), '「近期生日」收进了「更多」')
  check(menu.includes('command="export"'), '「导出」收进了「更多」')
  check(/<el-dropdown-item v-if="userStore\.isCommittee" command="export">/.test(menu),
    '导出那一项跟着班委及以上走（和原来那个按钮的权限一致）')
  check((menu.match(/<el-dropdown-item v-if="userStore\.isAdmin" command="(import|photo-import|create)">/g) || []).length === 3,
    '管理员那三项仍只给管理员')

  // 批量签字：同样是管理员工具，把表格的勾选状态一并传过去（勾了人默认覆盖）
  check(/<el-dropdown-item v-if="userStore\.isAdmin" command="batch-sign">/.test(menu) &&
    menu.includes('批量签字'), '「批量签字」收进「更多」，只给管理员')
  check(src.includes('<BatchSignDialog ref="batchSignRef" @done="fetchData" />'),
    '批量签字弹窗挂在页面上，签完刷新列表')
  check(/command === 'batch-sign'\) batchSignRef\.value\?\.open\(selectedStudents\.value\)/.test(src),
    '打开时把当前勾选的人交给弹窗')

  // 近期生日改成了弹窗：下拉项里再套一层 popover 的话，点一下两层浮层一起关，
  // 天数根本填不进去
  check(!src.includes('<el-popover'), '近期生日不再是个挂在工具栏上的 popover')
  check(src.includes('<el-dialog v-model="birthdayDialogVisible"') &&
    src.includes('const birthdayDialogVisible = ref(false)'), '它改成一个弹窗')
  check(/command === 'birthday'\) birthdayDialogVisible\.value = true/.test(src),
    '「更多」里那一项打开这个弹窗')
  check(/function applyBirthday\(\) \{[\s\S]{0,120}birthdayDialogVisible\.value = false/.test(src) &&
    /function clearBirthday\(\) \{[\s\S]{0,120}birthdayDialogVisible\.value = false/.test(src),
    '点「筛选」和「清除筛选」都把弹窗关掉（不然筛完还杵在那儿）')

  // 排的是 birth_date 这个生日列，方向和年龄相反：生日升序（早的在前）才是年龄大的在前。
  // 这两行原先正好标反了
  const age = src.match(/<el-dropdown-item command="birth_date_(?:asc|desc)">按年龄[^<]*<\/el-dropdown-item>/g) || []
  check(age.length === 2 && age[0].includes('birth_date_asc') && age[0].includes('从大到小') &&
    age[1].includes('birth_date_desc') && age[1].includes('从小到大'),
    '「按年龄从大到小」挂在 birth_date_asc 上（生日早 = 年龄大）')

  // 筛选区的控件宽度都是写死的（关键词 240px、下拉 100~130px），窄屏上放不下两个，
  // 一行一个把半屏占满 —— 媒体查询里得把宽度交回容器
  check(/@media \(max-width: 768px\)[\s\S]{0,1200}\.page-card :deep\(\.el-form--inline \.el-form-item\)/.test(src) &&
    src.includes('width: 100% !important'), '窄屏下筛选区两列自适应，控件不再写死宽度')

  // 前两列只留够放内容的宽度：窄屏横向滚动时先露出来的就是这几列，省下几十像素
  // 正好把「姓名」带进可视区（断上限而不钉死数值，以后微调宽度不该红）
  const selW = Number((src.match(/type="selection"[\s\S]{0,160}?width="(\d+)"/) || [])[1])
  // 属性之间允许换行：序号列带上 class-name 之后是多行写法
  const idxW = Number((src.match(/type="index"[\s\S]{0,160}?width="(\d+)"/) || [])[1])
  check(selW > 0 && selW <= 40 && idxW > 0 && idxW <= 45,
    `复选框列（${selW}）和序号列（${idxW}）都收窄了`)
}

console.log('\n▶ 学生信息页：抽签入口还在工具栏上（点名已挪去考勤页）')
{
  const src = readFileSync(`${ROOT}/src/views/StudentList.vue`, 'utf8')

  // 1.11.4 收低频操作进「更多」时，顺手把按钮删了却没放进下拉：弹窗组件还挂在
  // 模板里、ref 也还声明着，**只是没有任何地方调 open()**，于是从界面上整个消失。
  // 抽签是天天要按的，得留在工具栏上。光断言「文案在不在」抓不住这个 ——
  // 组件名和 ref 声明里也有这个词，所以断言直接钉在调用点上
  check(/<el-button v-if="userStore\.isCommittee" @click="drawRef\?\.open\(\)">/.test(src),
    '「抽签」按钮在，权限与原来一致（班委及以上）')
  check(/<DrawDialog ref="drawRef"/.test(src), '抽签弹窗组件仍挂在模板里')

  // 点名挪到考勤页：这边连按钮、弹窗和 ref 都不该留，免得点出来的记录
  // 落在学生信息页却看不到结果
  check(!src.includes('rollCallRef') && !src.includes('RollCallDialog'),
    '学生信息页不再有点名的按钮、弹窗和 ref')

  const more = src.slice(src.indexOf('<el-dropdown @command="handleMore">'))
  const moreMenu = more.slice(0, more.indexOf('</el-dropdown>'))
  check(!/点名|抽签/.test(moreMenu), '抽签没被塞进「更多」下拉（它不是低频操作）')
}

console.log('\n▶ 学生信息页：列表缩略图进视口才下载（别把点名/抽签挤在后面）')
{
  const src = readFileSync(`${ROOT}/src/views/StudentList.vue`, 'utf8')
  const thumb = src.slice(src.indexOf('class="thumb-photo"'))
  // 从 <img 开始切：它上面那几行注释里也写着 loading="lazy"（说明为什么不用它）
  const imgStart = thumb.indexOf('<img')
  const thumbImg = thumb.slice(imgStart, thumb.indexOf('/>', imgStart))

  // 一页 20 行，原生 loading="lazy" 的预加载距离有好几屏，等于 20 张原图同时开跑，
  // 把浏览器对本站的并发连接占满 —— 这时候点「点名」，要拉的名单就排在图片后面，
  // 看起来像按钮坏了
  check(thumbImg.includes('v-photo-src='), '列表缩略图走 v-photo-src（进视口才下载）')
  check(!/loading=/.test(thumbImg), '缩略图身上没有留着原来的 loading="lazy"')

  // 指令只写在模板上、忘了在 script 里定义的话，Vue 只会警告一句就跳过，
  // <img> 连 src 都不会有 —— 照片全空，而且不是报错
  check(src.includes('const vPhotoSrc = {'), 'v-photo-src 指令有定义（只写模板等于照片全空）')
  const dir = src.slice(src.indexOf('const vPhotoSrc = {'))
  const dirBody = dir.slice(0, dir.indexOf('\n}'))
  check(dirBody.includes('IntersectionObserver'), '靠 IntersectionObserver 判定是否可见')

  // 缩略图和详情大头照不再固定用高考照片：与顶栏头像同一优先级
  check(src.includes("const PRIMARY_PHOTO_ORDER = ['id', 'gaokao', 'on_site']"),
    '名单照片的优先级：自备证件照 > 高考照片 > 实地采集')
  check(thumb.includes('primaryPhoto(row).type'),
    '列表缩略图挑优先级最高的那张')
  check(src.includes('primaryPhoto(currentStudent).type'),
    '详情大头照和缩略图用同一张，不会点开就换人似的')
  check(/function openRowPhotos\(row\) \{\s*openPhotoViewer\(row, primaryPhoto\(row\)\?\.type/.test(src),
    '点缩略图从当前显示的那张开始看')
  check(dirBody.includes('el.src = binding.value'), '没有 IntersectionObserver 时退回直接加载，不至于不显示')
}

console.log('\n▶ 学生信息页：序号列不折行（两位数挤在 40px 里会断成两截）')
{
  const src = readFileSync(`${ROOT}/src/views/StudentList.vue`, 'utf8')

  // 40px 减掉 Element 默认左右各 12px 的内边距只剩 16px，两位数就折行了。
  // 靠 class-name 把这一列挑出来单独收内边距 —— Element 的列属性写错了不报错，
  // 只是样式落不到格子上，页面上看起来就像没改过
  check(/type="index"[\s\S]{0,120}class-name="col-index"/.test(src), '序号列带 col-index')
  check(/label-class-name="col-index"/.test(src), '表头的「序号」两个字同样收窄（它也会折）')

  check(src.includes(':deep(.col-index .cell)'), '样式里有 .col-index 这一条')
  const css = src.slice(src.indexOf(':deep(.col-index .cell)'))
  const rule = css.slice(0, css.indexOf('}'))
  check(rule.includes('white-space: nowrap'), '这一列不换行')
  check(/padding:\s*0 2px/.test(rule), '内边距收窄，40px 里放得下两位数')
}

console.log('\n▶ 点名：自动记的请假也得带上姓名（取错字段会静默写成空名）')
{
  const src = readFileSync(`${ROOT}/src/components/RollCallDialog.vue`, 'utf8')

  // 自动记 leave 的那组人是从 roster 里筛出来的学生对象（字段叫 name），
  // 不是请假记录（那套才叫 student_name）。取错字段不报错，只是往库里
  // 塞一条没有姓名的请假记录 —— 页面上那行就只剩学号
  check(!/name:\s*s\.student_name/.test(src), '没把学生对象当请假记录取姓名')
  check((src.match(/name:\s*s\.name/g) || []).length === 2,
    '点到的人和请假的人，两个分支都从学生对象取 name')
}

console.log('\n▶ 学生详情：考勤情况 / 办件记录默认收起，展开后分页')
{
  const src = readFileSync(`${ROOT}/src/views/StudentList.vue`, 'utf8')
  check(src.includes('<el-collapse') && src.includes('name="attendance"') &&
    src.includes('name="cases"'), '详情卡片里有「考勤情况」「办件记录」两个折叠节')
  check(src.includes('const attendanceOpen = ref([])') &&
    src.includes('const caseOpen = ref([])'), '两节都默认收起')
  check(src.includes('@change="handleAttendanceChange"') &&
    src.includes('if (open) loadStudentAttendance()') &&
    src.includes('@change="handleCaseChange"') &&
    src.includes('if (open) loadStudentCases()'), '展开时才拉数据')
  check(src.includes('getStudentAttendance') && src.includes('getStudentSubmitted'),
    '接上班委查看某学生考勤 / 办件记录的接口')
  check(src.includes('ATTENDANCE_PAGE_SIZE') && src.includes('CASE_PAGE_SIZE') &&
    (src.match(/<el-pagination/g) || []).length >= 2, '两节展开后都分页')
  check(src.includes('label="考勤时间"') && src.includes('label="考勤标题"') &&
    src.includes('label="考勤类型"') && src.includes('label="参与范围"') &&
    src.includes('label="出勤情况"'), '考勤字段与学生端一致')
  check(src.includes('prop="type_name" label="类型"') &&
    src.includes('prop="title" label="事项"') &&
    src.includes('row.status_label'), '办件记录按一行一条展示')
  check(src.includes('function goReviewTab(row)') &&
    src.includes("router.push({ path: '/review', query: { tab } })") &&
    src.includes('@click="goReviewTab(row)"'), '办件记录的「详情」跳到审核审批对应 tab')
  check(src.includes('attendanceTag(row.status)'), '出勤状态同样按颜色区分')
  const attApi = readFileSync(`${ROOT}/src/api/attendance.js`, 'utf8')
  check(attApi.includes('url: `/attendance/student/${studentId}`'),
    '考勤走单独的按学生查询接口')
  const wsApi = readFileSync(`${ROOT}/src/api/workspace.js`, 'utf8')
  check(wsApi.includes('`/workspace/student/${studentId}/submitted`'),
    '办件记录走单独的按学生查询接口')
}

console.log('\n▶ 学生名单：签字图（管理员传、班委申请、学生看不见）')
{
  const LIST = '/src/views/StudentList.vue'
  const who = (role, name) => `const userStore = useUserStore()
  userStore.info = { student_no: '2024000009', name: '${name}', role: '${role}', is_external: false }`
  // 详情弹窗打开、且后端把「有图 + 已批准」的状态都给全了 —— 数据这边挑最坏的情况，
  // 断言的才是「按角色该不该渲染」，而不是「碰巧没数据所以没渲染」
  const DETAIL_OPEN = `const detailVisible = ref(true)
const currentStudent = ref({ id: 7, student_no: '2024000004', name: '丁' })`
  const signState = (status, downloadName) =>
    `const signStatus = ref({ status: '${status}', expires_at: null, download_name: '${downloadName}' })`

  // 取每个按钮里的纯文本。判「按钮在不在」必须这么取：页面上别处（标签、tips）也可能
  // 出现同样的字，只有落到 <button> 里才说明真渲染了按钮。文案那一层再掐掉模板注释
  // （`<!-- 签字图按钮：… -->` 里就写着「签字」两个字）
  const buttonTexts = (html) =>
    [...stripComments(html).matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)]
      .map((m) => m[1].replace(/<[^>]+>/g, '').trim())

  // 1. 学生：连「签字」两个字都不该出现在他眼前（用户明确要求的「无文案」）
  const { html: asStudent } = await renderPatchedMany(
    LIST,
    [['const userStore = useUserStore()', who('student', '戊')],
     ['const detailVisible = ref(false)\nconst currentStudent = ref(null)', DETAIL_OPEN],
     ["const signStatus = ref({ status: 'none', expires_at: null, download_name: '' })",
      signState('approved', '丁_签字.png')]],
    { ElDialog: ElDialogStub })
  const studentButtons = buttonTexts(asStudent)
  check(!studentButtons.some((t) => t.includes('签字') || t.includes('申请')),
    '学生角色的详情弹窗上没有「申请签署」这类按钮')
  check(!stripComments(asStudent).includes('签字'),
    '学生角色的整页里不出现「签字」二字（状态接口他压根不会去调）')

  // 2. 班委：四态各渲一次，文案跟着 status 走
  const STATES = [
    ['none', '丁_签字.png', '申请签署'],
    ['pending', '丁_签字.png', '申请待审核'],
    ['approved', '丁_签字.png', '查看签字'],
    ['expired', '丁_签字.png', '重新申请']
  ]
  for (const [status, name, text] of STATES) {
    const { html } = await renderPatchedMany(
      LIST,
      [['const userStore = useUserStore()', who('committee', '乙')],
       ['const detailVisible = ref(false)\nconst currentStudent = ref(null)', DETAIL_OPEN],
       ["const signStatus = ref({ status: 'none', expires_at: null, download_name: '' })",
        signState(status, name)]],
      { ElDialog: ElDialogStub })
    check(buttonTexts(html).includes(text), `班委在 ${status} 状态下看到「${text}」`)
  }

  // 3. 该生没有签字图：后端不给 download_name，按钮整个不出现（不解释「为什么没有」）
  const { html: noPhoto } = await renderPatchedMany(
    LIST,
    [['const userStore = useUserStore()', who('committee', '乙')],
     ['const detailVisible = ref(false)\nconst currentStudent = ref(null)', DETAIL_OPEN],
     ["const signStatus = ref({ status: 'none', expires_at: null, download_name: '' })",
      signState('none', '')]],
    { ElDialog: ElDialogStub })
  check(!buttonTexts(noPhoto).some((t) => t.includes('签字') || t.includes('申请')),
    '该生没有签字图时按钮不渲染（判据是 download_name 空不空，不是状态字符串）')

  // 4. 编辑弹窗那一格：管理员看得见图（用户后来放宽的），班委看不到
  const EDIT_OPEN = `const editVisible = ref(true)
const editForm = reactive({ id: 7 })`
  const HAS_SIGN = "const signEdit = ref({ has: true, uploading: false, fileName: '丁_签字.png' })"
  const EDIT_PATCHES = [
    ['const editVisible = ref(false)\nconst editForm = reactive({})', EDIT_OPEN],
    ['const signEdit = ref({ has: false, uploading: false, fileName: \'\' })', HAS_SIGN],
    ['const detailVisible = ref(false)\nconst currentStudent = ref(null)', DETAIL_OPEN],
    ["const signStatus = ref({ status: 'none', expires_at: null, download_name: '' })", signState('none', '')]
  ]
  const signImg = (html) => /<img[^>]*src="[^"]*\/api\/sign-photos\/image\//.test(html)

  const { html: adminEdit } = await renderPatchedMany(
    LIST,
    [['const userStore = useUserStore()', who('admin', '甲')], ...EDIT_PATCHES],
    { ElDialog: ElDialogStub })
  check(signImg(adminEdit), '管理员在编辑弹窗里能看到签字图（改成真 <img> 的前提就是它）')
  check(buttonTexts(adminEdit).some((t) => t.includes('选择图片')),
    '管理员那一格有传图入口')

  const { html: cmEdit } = await renderPatchedMany(
    LIST,
    [['const userStore = useUserStore()', who('committee', '乙')], ...EDIT_PATCHES],
    { ElDialog: ElDialogStub })
  check(!signImg(cmEdit), '班委的编辑弹窗里没有签字图这一格（要看只能走申请）')

  // 5. 出网的地址只带学生 id，不带库里的文件名 —— 库里存的是 uuid4().hex.jpg，
  //    前端一旦自己拼过文件名就等于把内部命名泄露出去
  const listSrc = readFileSync(`${ROOT}${LIST}`, 'utf8')
  check(!listSrc.includes('sign_photo'), '前端不碰 sign_photo 这个列（连字段名都拿不到）')
  check(/signImageUrl\(editForm\.id/.test(listSrc),
    '取图地址由 signImageUrl() 拼，只带学生 id')
  check(/signImageUrl\(row\.student_id/.test(
    readFileSync(`${ROOT}/src/views/Review.vue`, 'utf8')),
    '审核页取图同样只带学生 id')
}

console.log('\n▶ 审核页：签字查看申请这个 tab')
{
  const REVIEW = '/src/views/Review.vue'
  const src = readFileSync(`${ROOT}${REVIEW}`, 'utf8')

  check(src.includes("'signphoto'"), "TABS 里有 signphoto（?tab=signphoto 才认得出来）")
  check(/<template #label>签字查看申请<span v-if="tabBadge\('signphoto'\)"/.test(src),
    'tab 上写着「签字查看申请」，并挂上待办红点')
  check(/<el-tab-pane v-if="userStore\.isAdmin" name="signphoto">/.test(src),
    '这个 tab 只给管理员（列表接口本身是 admin_required，班委进来只会看到一个红叉）')
  check(src.includes("activeTab.value === 'signphoto' && userStore.isAdmin"),
    '切到这个 tab 拉列表前先判管理员（通知里的 ?tab=signphoto 谁都可能点进来）')
  const fetchSign = src.slice(src.indexOf('async function fetchSignList'),
    src.indexOf('/** 管理员看一眼这条申请'))
  check(fetchSign.includes('badgeStore.refresh()'),
    '拉完列表刷红点（红点清了才说明这批待办真的处理完了）')

  // 管理员看签字图得现问文件名：列表里只有学号姓名，库里那个 uuid 名不能给前端
  const viewSign = src.slice(src.indexOf('async function viewSignImage'),
    src.indexOf('function handleApproveSign'))
  check(viewSign.includes('getSignStatus(row.student_id)') &&
    viewSign.includes('signFileName.value = s.download_name'),
    '预览用的文件名是后端拼的下载名，不是库里的裸文件名')
  check(viewSign.includes('没有签字图片'),
    '没有签字图时给一句提示，而不是打开一个必 404 的预览框')

  // tab 页签是 el-tabs 按每个 pane 的 label 插槽渲的，得真给管理员身份才出得来
  const { html } = await renderPatched(REVIEW, 'const userStore = useUserStore()',
    `const userStore = useUserStore()
  userStore.info = { student_no: '2024000001', name: '甲', role: 'admin', is_external: false }`)
  check(stripComments(html).includes('签字查看申请'),
    '管理员渲出来的 tab 页签上真有这四个字（label 插槽在 SSR 下是渲染的）')

  const { html: asCm } = await renderPatched(REVIEW, 'const userStore = useUserStore()',
    `const userStore = useUserStore()
  userStore.info = { student_no: '2024000002', name: '乙', role: 'committee', is_external: false }`)
  check(!stripComments(asCm).includes('签字查看申请'), '班委的审核页里没有这个 tab')
}

console.log('\n▶ 系统管理：域外账号的签字图（管理员传、只有管理员能取）')
{
  // Admin.vue 的弹窗正文在 SSR 下根本不渲染（el-dialog 的行为），所以这一节
  // 全是**源码断言** —— 和上面「前端不碰 sign_photo 这个列」同一个路子
  const ADMIN = '/src/views/Admin.vue'
  const src = readFileSync(`${ROOT}${ADMIN}`, 'utf8')

  // 这块与头像同构：只显示状态文字、不渲染预览。签字是敏感物，管理界面里不必
  // 把图摊在屏幕上 —— 连拼取图地址的代码都没有，想泄露也没有出口
  check(!src.includes('sign-photo'),
    'Admin.vue 里不出现取图地址（签字只给状态文字，不预览）')

  // 上限得按照片那套 10MB 拦：签字走的是 save_photo，不是头像的 2MB。
  // 复制粘贴头像那块忘了改阈值的话，用户会碰到「前端放行、后端 400」
  const pickSign = src.slice(src.indexOf('function handleExtSignPicked'),
    src.indexOf('function handleExtSignClear'))
  check(pickSign.includes('10 * 1024 * 1024'),
    '签字图的上限按照片那套 10MB 拦')
  check(!pickSign.includes('2 * 1024 * 1024'),
    '不是头像那个 2MB（阈值和提示文案都要跟着改）')
  // 选了新图就把「清除」标志复位：两个信号同时为真时后端按哪条走没有定论
  check(pickSign.includes('extForm.removeSignPhoto = false'),
    '选了新签字图就清掉「清除」标志')

  // 「清了」和「没动」必须回回都发 —— 不带 sign_photo 时后端分不清这两种，
  // 分不清就会把已有的签字图当成「没动」
  check(/fd\.append\('remove_sign_photo', extForm\.removeSignPhoto \? 'true' : 'false'\)/.test(src),
    '编辑时明确回传 remove_sign_photo')
  check(/if \(extForm\.signPhotoFile\) fd\.append\('sign_photo', extForm\.signPhotoFile\)/.test(src),
    '签字图跟着同一个 FormData 提交（与头像并列，不另开接口）')

  // 弹窗的「已有签字图」状态吃的是列表接口回传的 has_sign_photo
  check(src.includes('extForm.hasSignPhoto = !!row.has_sign_photo'),
    '弹窗按 has_sign_photo 显示「已有签字图」')
  check(/extForm\.hasSignPhoto = false/.test(src),
    '重置表单时一起清掉（否则新建时会显示上一个账号的状态）')

  // 头像与签字各有一个隐藏的 file input，各按各的按钮
  check(/ref="extSignInput"\s+type="file"/.test(src),
    '签字图有自己那个隐藏 file input')
  check(src.includes('ref="extAvatarInput"'),
    '头像那个还在（两块同构、互不影响）')
}

console.log('\n▶ 请假审批表：学生端下到的是 PDF，班导师意见跟着显示')
{
  const APPLY = '/src/views/LeaveApply.vue'
  const src = readFileSync(`${ROOT}${APPLY}`, 'utf8')

  // 旧入口是 admin_required 的 docx —— 学生点那个按钮必定 403，是个死按钮。
  // 这次把它连同地址一起换掉，残留一处就又是一条死路
  check(!/downloadLeaveDocx|downloadDocx/i.test(src), '学生端不再碰 docx（连名字都不留）')
  check(src.includes('downloadLeavePdf'), '下载走 downloadLeavePdf')
  check(/a\.download = `\$\{row\.student_name\}_请假审批表_[\s\S]{0,80}\.pdf`/.test(src),
    '下载下来的文件名是 .pdf')

  const api = readFileSync(`${ROOT}/src/api/leave.js`, 'utf8')
  check(api.includes('url: `/leaves/${id}/pdf`'), '接口地址是 /leaves/{id}/pdf')
  check(api.includes("url: '/leaves/advisor-signers'") &&
    api.includes('url: `/leaves/${id}/advisor-sign`'),
    '签字人列表与补签字各有自己的接口（补签字不是「再批一次」）')

  // 真渲染：班导师意见是批准时填的，学生要在「我的记录」里看得到。
  // onMounted 在 SSR 下不跑，直接把行灌进 leaves
  const row = (o) => ({
    id: 1, leave_type: '事假', start_at: '2026-10-15 08:00', end_at: '2026-10-17 18:00',
    reason: '家里有事', status: 'approved', reviewer_name: '甲', reject_reason: '',
    advisor_opinion: '', created_at: '2026-10-12 09:00', ...o
  })
  const history = (r) => [
    ["const activeTab = ref('apply')", "const activeTab = ref('history')"],
    ['const leaves = ref([])', `const leaves = ref(${JSON.stringify([r])})`]
  ]

  const { html } = await renderPatchedMany(APPLY, history(row({ advisor_opinion: '同意，注意安全' })))
  check(stripComments(html).includes('班导师意见：同意，注意安全'),
    '已通过的单子上能看到班导师意见')

  const { html: blank } = await renderPatchedMany(APPLY, history(row({})))
  check(!stripComments(blank).includes('班导师意见'),
    '没填意见就不占地方（意见是选填的）')
}

console.log('\n▶ 审核页：批准时填班导师意见、选谁的签字')
{
  const REVIEW = '/src/views/Review.vue'
  const src = readFileSync(`${ROOT}${REVIEW}`, 'utf8')

  const row = (o) => ({
    id: 1, student_name: '丙', student_no: '2024000003', leave_type: '事假',
    start_at: '2026-10-15 08:00', end_at: '2026-10-17 18:00', reason: '家里有事',
    status: 'pending', has_advisor_sign: false, advisor_sign_name: '', advisor_opinion: '',
    created_at: '2026-10-12 09:00', ...o
  })
  const who = (role) => `const userStore = useUserStore()
  userStore.info = { student_no: '2024000001', name: '甲', role: '${role}', is_external: false }`
  // 表桩对每行跑 default 插槽，所以行里的按钮和签字状态都能真断到
  const buttonTexts = (html) =>
    [...stripComments(html).matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)]
      .map((m) => m[1].replace(/<[^>]+>/g, '').trim())
  // 默认停在「信息修改申请」那个 tab，钉到请假那个 tab 上去（?tab=leave 的效果）
  const leaveTab = (r) => [
    ["const activeTab = ref(TABS.includes(route.query.tab) ? route.query.tab : 'change')",
      "const activeTab = ref('leave')"],
    ['const leaveList = ref([])', `const leaveList = ref(${JSON.stringify([r])})`]
  ]

  const { html: pending } = await renderPatchedMany(REVIEW,
    [['const userStore = useUserStore()', who('admin')], ...leaveTab(row({}))])
  const pb = buttonTexts(pending)
  check(pb.includes('通过') && pb.includes('驳回'), '待审核：管理员有「通过」「驳回」')
  check(!pb.includes('补签字'), '还没批准的单子没有「补签字」')
  check(stripComments(pending).includes('—'), '待审核的签字列是一横（还没到签字这一步）')

  const { html: signed } = await renderPatchedMany(REVIEW,
    [['const userStore = useUserStore()', who('admin')],
     ...leaveTab(row({ status: 'approved', has_advisor_sign: true, advisor_sign_name: '甲' }))])
  const sb = buttonTexts(signed)
  check(sb.includes('下载请假表'), '已批准：有「下载请假表」')
  check(!sb.includes('补签字'), '签过的没有「补签字」（后端也会 400）')
  check(stripComments(signed).includes('甲 已签'), '签字状态那列写着是谁签的')

  const { html: deferred } = await renderPatchedMany(REVIEW,
    [['const userStore = useUserStore()', who('admin')], ...leaveTab(row({ status: 'approved' }))])
  check(buttonTexts(deferred).includes('补签字'), '「暂不签字」的才给「补签字」')
  check(stripComments(deferred).includes('暂不签字'), '那一列写着「暂不签字」')

  // 班委：列表能看，但下载（别人的表）和签字都轮不到他
  const { html: asCm } = await renderPatchedMany(REVIEW,
    [['const userStore = useUserStore()', who('committee')], ...leaveTab(row({ status: 'approved' }))])
  const cb = buttonTexts(asCm)
  check(!cb.includes('下载请假表'), '班委的列表里没有「下载请假表」')
  check(!cb.includes('补签字'), '班委也没有「补签字」')
  check(stripComments(asCm).includes('暂不签字'), '但那列状态他看得到（不是整列藏起来）')

  // 批准 / 补签字共用同一个弹窗，两个入口分别调各自的接口
  check(/label="班导师签字"/.test(src), '请假列表加了一列「班导师签字」')
  check(src.includes("openLeaveDialog('approve', row)") && src.includes("openLeaveDialog('sign', row)"),
    '「通过」和「补签字」都走同一个弹窗')
  check(/await approveLeave\(row\.id, payload\)/.test(src), '通过时把意见和签字人一起提交')
  check(/await advisorSign\(row\.id, payload\)/.test(src), '补签字走单独那个接口')

  // 弹窗正文在 SSR 下不渲染，得盖掉 el-dialog；顺便把候选人也灌进去
  const R = row({})
  const { html: dialog } = await renderPatchedMany(REVIEW, [
    ['const userStore = useUserStore()', who('admin')],
    ...leaveTab(R),
    ['const leaveDialogVisible = ref(false)', 'const leaveDialogVisible = ref(true)'],
    ['const leaveDialogRow = ref(null)', `const leaveDialogRow = ref(${JSON.stringify(R)})`],
    // 候选人由后端按「是管理员 + 签字图文件还在盘上」筛出来，这里照实灌一份：
    // 一个学生管理员（甲）加一个域外管理员（李俊刚）
    ['const advisorSigners = ref([])', `const advisorSigners = ref([
  { student_no: '2024000001', name: '甲', is_external: false },
  { student_no: 'teacher_li', name: '李俊刚', is_external: true }
])`]
  ], { ElDialog: ElDialogStub })
  const dlg = stripComments(dialog)
  check(dlg.includes('班导师意见') && dlg.includes('班导师签字'), '意见和签字两个表单项都在')
  check(/maxlength="200"/.test(dialog), '意见卡 200 字（上限是排版算出来的，改这里要重跑版式测试）')
  check(dlg.includes('签的是批准当时这张图'), '写明了签的是快照')

  // 下面三条只能看源码：标题是 :title 传进去的 prop（桩不渲染 prop），
  // 两个 option 在一段没展开的下拉里（SSR 下连真 Element 都不渲染它的正文）。
  check(/\? '补班导师签字' : '通过请假申请'/.test(src), '弹窗标题按两种用途分')
  check(/<el-option label="暂不签字" value="" \/>/.test(src),
    '签字人那栏第一项固定是「暂不签字」（默认值就是它）')
  check(/s\.is_external \? `\$\{s\.name\}（域外账号）` : s\.name/.test(src),
    '域外账号在后缀里标出来（域外同等权限，靠后缀让他自己知道）')

  // 弹窗里选的是空串（= 暂不签字）时，两个字段都要原样提交：漏掉 advisor_sign_no 的话
  // 后端拿不到「暂不签字」，会当成没选签字人
  check(/advisor_sign_no: leaveDialogForm\.value\.advisor_sign_no/.test(src),
    '提交时 advisor_sign_no 原样带上（空串就是「暂不签字」）')
  check(/advisor_opinion: leaveDialogForm\.value\.advisor_opinion/.test(src), '意见同样原样带上')
}

console.log('\n▶ 撤销：三个办件都能撤，撤完是终态')
{
  const REVIEW = '/src/views/Review.vue'
  const src = readFileSync(`${ROOT}${REVIEW}`, 'utf8')

  const who = (role) => `const userStore = useUserStore()
  userStore.info = { student_no: '2024000001', name: '甲', role: '${role}', is_external: false }`
  const buttons = (html) =>
    [...stripComments(html).matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)]
      .map((m) => m[1].replace(/<[^>]+>/g, '').trim())

  // 三个 tab 的行长得不一样，但「管理员能看到撤销按钮、撤完就没了」是同一套语义
  const PAGES = [
    {
      name: '请假', tab: 'leave', list: 'leaveList',
      row: (o) => ({
        id: 1, student_name: '丙', leave_type: '事假', reason: '家里有事',
        start_at: '2026-10-15 08:00', end_at: '2026-10-17 18:00',
        status: 'approved', has_advisor_sign: true, advisor_sign_name: '甲',
        created_at: '2026-10-12 09:00', ...o
      }),
      download: '下载请假表'
    },
    {
      name: '电动车', tab: 'evpass', list: 'evPassList',
      row: (o) => ({
        id: 1, student_name: '戊', brand: '雅迪', plate_number: '京A1234567',
        status: 'approved', has_sign: true, sign_name: '甲',
        created_at: '2026-10-12 09:00', ...o
      }),
      download: '申请表'
    },
    {
      name: '证明', tab: 'certificate', list: 'certificateList',
      row: (o) => ({
        id: 1, student_name: '丙', title: '在读证明', recipient: '某某公司',
        status: 'approved', attachments: [], result_original_name: '在读证明.pdf',
        created_at: '2026-10-12 09:00', ...o
      }),
      download: '成品 PDF'
    }
  ]

  const show = async (p, role, r) => {
    const { html } = await renderPatchedMany(REVIEW, [
      ['const userStore = useUserStore()', who(role)],
      ["const activeTab = ref(TABS.includes(route.query.tab) ? route.query.tab : 'change')",
        `const activeTab = ref('${p.tab}')`],
      [`const ${p.list} = ref([])`, `const ${p.list} = ref(${JSON.stringify([r])})`]
    ])
    return { text: stripComments(html), labels: buttons(html) }
  }

  for (const p of PAGES) {
    const approved = await show(p, 'admin', p.row({}))
    check(approved.labels.includes('撤销'), `${p.name}：管理员对已通过的单子有「撤销」`)
    check(approved.labels.includes(p.download), `${p.name}：撤销之前下载入口还在`)

    const revoked = await show(p, 'admin', p.row({ status: 'revoked' }))
    check(revoked.text.includes('已撤销'), `${p.name}：状态 tag 写着「已撤销」`)
    check(!revoked.labels.includes('撤销') && !revoked.labels.includes(p.download),
      `${p.name}：撤完之后没有「撤销」，也没有下载入口`)
    check(!revoked.labels.includes('补签字'), `${p.name}：撤完之后不能再补签字`)

    const asCm = await show(p, 'committee', p.row({}))
    check(!asCm.labels.includes('撤销'), `${p.name}：班委没有「撤销」（后端也是 admin_required）`)
  }

  // 撤销是终态，确认框得把后果说清楚
  check(/撤销后这条申请会变成「已撤销」[\s\S]{0,80}不能恢复/.test(src),
    '二次确认写明了「已撤销」「不能恢复」')
  check(src.includes('revokeLeave') && src.includes('revokeEvPass') &&
    src.includes('revokeCertificate'), '三个办件的接口都接上了')

  for (const [p, url] of [
    ['/src/api/leave.js', '/leaves/${id}/revoke'],
    ['/src/api/evPass.js', '/ev-passes/${id}/revoke'],
    ['/src/api/certificate.js', '/certificates/${id}/revoke']
  ]) {
    check(readFileSync(`${ROOT}${p}`, 'utf8').includes(url), `${p} 的撤销地址是 ${url}`)
  }
}

console.log('\n▶ 电动车：两份都改成 PDF，批准时选经办班委签字')
{
  const REVIEW = '/src/views/Review.vue'
  const src = readFileSync(`${ROOT}${REVIEW}`, 'utf8')
  const api = readFileSync(`${ROOT}/src/api/evPass.js`, 'utf8')

  // 旧的两个下载地址是 admin_required 的 docx —— 学生点那个必然 403，是死按钮。
  // 地址连同 docx 这三个字母一起清掉，残留一处就又是一条死路
  check(api.includes('url: `/ev-passes/${id}/pass-pdf`') &&
    api.includes('url: `/ev-passes/${id}/promise-pdf`'), '申请表与承诺书各有一个 PDF 地址')
  check(!/docx/i.test(api), '接口层不再留 docx 的痕迹')
  check(/export function approveEvPass\(id, payload\)/.test(api) && /data: payload/.test(api),
    '通过时把签字人一起提交（payload 可省，老调用点照样能用）')
  check(api.includes('url: `/ev-passes/${id}/sign`'), '补签字走单独那个接口（不是「再批一次」）')
  check(api.includes("url: '/ev-passes/signers'"), '签字人列表单独一个接口')

  // 学生端：文件名从写死的 .docx 改成 .pdf，两个按钮都走 api 函数拿 blob
  const stu = readFileSync(`${ROOT}/src/views/EvPass.vue`, 'utf8')
  check(!/docx/i.test(stu), '学生端不再碰 docx')
  check(/a\.download = `\$\{row\.student_name\}_\$\{label\}_[\s\S]{0,80}\.pdf`/.test(stu),
    '下载下来的文件名是 .pdf')
  check(stu.includes('downloadEvPassPdf') && stu.includes('downloadEvPromisePdf'),
    '两个按钮都走 api 函数（不再裸拼 URL 下载）')

  // --- 审核页那一列与那几个按钮，真渲染 ---
  const row = (o) => ({
    id: 1, student_name: '戊', student_no: '2024000005', brand: '雅迪',
    plate_number: '京A1234567', status: 'pending', sign_name: '', has_sign: false,
    created_at: '2026-10-12 09:00', ...o
  })
  const who = (role) => `const userStore = useUserStore()
  userStore.info = { student_no: '2024000001', name: '甲', role: '${role}', is_external: false }`
  // 表桩对每行跑 default 插槽，所以行里的按钮和签字状态都能真断到
  const buttonTexts = (html) =>
    [...stripComments(html).matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)]
      .map((m) => m[1].replace(/<[^>]+>/g, '').trim())
  // 默认停在「信息修改申请」那个 tab，钉到电动车那个 tab 上去（?tab=evpass 的效果）
  const evTab = (r) => [
    ["const activeTab = ref(TABS.includes(route.query.tab) ? route.query.tab : 'change')",
      "const activeTab = ref('evpass')"],
    ['const evPassList = ref([])', `const evPassList = ref(${JSON.stringify([r])})`]
  ]

  const { html: pending } = await renderPatchedMany(REVIEW,
    [['const userStore = useUserStore()', who('admin')], ...evTab(row({}))])
  const pb = buttonTexts(pending)
  check(pb.includes('通过') && pb.includes('驳回'), '待审核：管理员有「通过」「驳回」')
  check(!pb.includes('补签字'), '还没批准的单子没有「补签字」')
  check(!pb.includes('申请表') && !pb.includes('承诺书'), '没批准就没得下载（后端也会 400）')
  check(stripComments(pending).includes('—'), '待审核的签字列是一横（还没到签字这一步）')

  const { html: signed } = await renderPatchedMany(REVIEW,
    [['const userStore = useUserStore()', who('admin')],
     ...evTab(row({ status: 'approved', has_sign: true, sign_name: '甲' }))])
  const sb = buttonTexts(signed)
  check(sb.includes('申请表') && sb.includes('承诺书'), '已批准：两份文档都能下')
  check(!sb.includes('补签字'), '签过的没有「补签字」（后端也会 400）')
  check(stripComments(signed).includes('甲 已签'), '签字状态那列写着是谁签的')

  const { html: deferred } = await renderPatchedMany(REVIEW,
    [['const userStore = useUserStore()', who('admin')], ...evTab(row({ status: 'approved' }))])
  check(buttonTexts(deferred).includes('补签字'), '「暂不签署」的才给「补签字」')
  check(stripComments(deferred).includes('暂不签署'), '那一列写着「暂不签署」')

  // 班委：两份文档他也能下（留档、报学院盖章用），但签字轮不到他
  const { html: asCm } = await renderPatchedMany(REVIEW,
    [['const userStore = useUserStore()', who('committee')], ...evTab(row({ status: 'approved' }))])
  const cb = buttonTexts(asCm)
  check(cb.includes('申请表') && cb.includes('承诺书'), '班委的列表里两份文档照样能下')
  check(!cb.includes('补签字') && !cb.includes('通过'), '班委没有「补签字」，也没有「通过」')
  check(stripComments(asCm).includes('暂不签署'), '但那列状态他看得到（不是整列藏起来）')

  // 批准 / 补签字共用同一个弹窗，两个入口分别调各自的接口
  check(/label="经办班委签字"/.test(src), '电动车列表加了一列「经办班委签字」')
  check(src.includes("openEvPassDialog('approve', row)") &&
    src.includes("openEvPassDialog('sign', row)"), '「通过」和「补签字」都走同一个弹窗')
  check(/await approveEvPass\(row\.id, payload\)/.test(src), '通过时把签字人一起提交')
  check(/await signEvPass\(row\.id, payload\)/.test(src), '补签字走单独那个接口')
  check(/\? '补经办班委签字' : '通过电动车通行证申请'/.test(src), '弹窗标题按两种用途分')
  check(/<el-option label="暂不签署" value="" \/>/.test(src),
    '签字人那栏第一项固定是「暂不签署」（默认值就是它）')

  // 弹窗正文在 SSR 下不渲染，得盖掉 el-dialog；顺便把候选人也灌进去
  const R = row({})
  const { html: dialog } = await renderPatchedMany(REVIEW, [
    ['const userStore = useUserStore()', who('admin')],
    ...evTab(R),
    ['const evPassDialogVisible = ref(false)', 'const evPassDialogVisible = ref(true)'],
    ['const evPassDialogRow = ref(null)', `const evPassDialogRow = ref(${JSON.stringify(R)})`],
    ['const evPassSigners = ref([])', `const evPassSigners = ref([
  { student_no: '2024000001', name: '甲', is_external: false },
  { student_no: 'teacher_li', name: '李俊刚', is_external: true }
])`]
  ], { ElDialog: ElDialogStub })
  const dlg = stripComments(dialog)
  check(dlg.includes('经办班委签字'), '弹窗里有「经办班委签字」那一栏')
  check(dlg.includes('签的是批准当时这张图'), '写明了签的是快照')
  check(dlg.includes('申请表落款处不会出现「经办班委」这一行'),
    '说明「暂不签署」的后果（那一行整行不出现）')
  // 这一条得切源码来看：整页里别的弹窗（请假那个）本来就有「班导师意见」
  const dialogAt = src.indexOf('v-model="evPassDialogVisible"')
  check(!src.slice(dialogAt, dialogAt + 1500).includes('意见'),
    '弹窗里没有意见输入框 —— 这份表上没有意见栏')
}

console.log('\n▶ 办件下载按钮：慢网络下显示百分比，与其他下载按钮一致')
{
  // 直接跑 composable：ref 在组件外也能用，不必为了三个断言去搭一个组件
  const { useDownloadProgress } = await server.ssrLoadModule('/src/composables/useDownloadProgress.js')
  const d = useDownloadProgress()
  let midPercent = 0
  const ret = await d.run('leave-1', async (onProgress) => {
    onProgress(30, 100)
    midPercent = d.percent.value
    return 'ok'
  })
  check(ret === 'ok', 'run 把 task 的返回值交回调用方')
  check(midPercent === 30, '进度按 loaded / total 算成百分比')
  check(d.isDownloading('leave-1') === false && d.percent.value === 0,
    '下载完清掉 key 和百分比（按钮回到原文案）')

  // total 为 0 = 后端没给 Content-Length，这时只能显示原文案，不能除以 0
  let zeroPercent = -1
  await d.run('a', async (onProgress) => {
    onProgress(500, 0)
    zeroPercent = d.percent.value
  })
  check(zeroPercent === 0, '拿不到总大小时百分比保持 0（不除以 0、也不显示 NaN）')

  // 同一时间只跑一个：第二个按钮点了也不发请求，免得两份一起下
  let secondRan = false
  let release
  const first = d.run('a', () => new Promise((resolve) => { release = resolve }))
  const second = await d.run('b', async () => { secondRan = true })
  check(second === undefined && !secondRan, '下载中的第二次点击直接被忽略')
  release()
  await first

  // 出错也要复位，否则按钮会永远转圈
  try {
    await d.run('x', async () => { throw new Error('boom') })
  } catch (e) { /* 预期内 */ }
  check(!d.isDownloading('x') && d.percent.value === 0, '下载失败也复位')

  // 接口层：onProgress 一律经 progressHandler 交给 axios，没传回调时是 undefined
  const reads = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const apis = {
    '/src/api/leave.js': ['export function downloadLeavePdf(id, onProgress)'],
    '/src/api/certificate.js': ['export function downloadCertificateResult(id, admin = false, onProgress)'],
    '/src/api/feedback.js': ['export function downloadFeedbackAttachment(feedbackId, index, onProgress)']
  }
  for (const [p, sigs] of Object.entries(apis)) {
    const src = reads(p)
    for (const sig of sigs) check(src.includes(sig), `${p} 的下载函数收 onProgress`)
    check(src.includes('onDownloadProgress: progressHandler(onProgress)'),
      `${p} 把进度回调挂到 onDownloadProgress`)
  }
  const evApi = reads('/src/api/evPass.js')
  check(evApi.includes('export function downloadEvPassPdf(id, onProgress)') &&
    evApi.includes('export function downloadEvPromisePdf(id, onProgress)'),
    '申请表、承诺书两个下载函数都收 onProgress')
  check((evApi.match(/onDownloadProgress: progressHandler\(onProgress\)/g) || []).length === 2,
    '两个地址都挂了进度回调')

  // 页面层：key 区分「哪一行、哪个按钮」，按钮 loading 与百分比都用同一个 key
  const keys = {
    '/src/views/LeaveApply.vue': ['leave'],
    '/src/views/Certificate.vue': ['cert'],
    '/src/views/Feedback.vue': ['feedback']
  }
  for (const [p, list] of Object.entries(keys)) {
    const src = reads(p)
    for (const k of list) {
      check(src.includes(`isDownloading(\`${k}-\${`) && src.includes(`runDownload(\`${k}-\${`),
        `${p}：「${k}」这个下载入口接了进度`)
    }
    check(src.includes("import { useDownloadProgress } from '@/composables/useDownloadProgress'"),
      `${p} 用的是同一个下载进度实现（不是各写一套）`)
  }
  // 电动车两个入口的 key 是拼好后传进 savePdf / downloadEvPassDoc 的，
  // 断言 key 的拼法，再断言那个函数里确实走了 runDownload
  const evStu = reads('/src/views/EvPass.vue')
  check(evStu.includes('savePdf(downloadEvPassPdf, row,') &&
    evStu.includes('`pass-${row.id}`') && evStu.includes('savePdf(downloadEvPromisePdf, row,') &&
    evStu.includes('`promise-${row.id}`') && evStu.includes('await runDownload(key,'),
    '学生端：申请表、承诺书两个入口各自带 key 走进度')

  const review = reads('/src/views/Review.vue')
  for (const k of ['leave', 'cert', 'feedback']) {
    check(review.includes(`isDownloading(\`${k}-\${`) && review.includes(`runDownload(\`${k}-\${`),
      `审核页：「${k}」这个下载入口接了进度`)
  }
  check(review.includes('`evpass-pass-${row.id}`') && review.includes('`evpass-promise-${row.id}`') &&
    review.includes('await runDownload(key,'),
    '审核页：申请表、承诺书也各自带 key 走进度')
  // 百分比为 0（后端没给总大小）时保留原文案，别把按钮变成空白
  for (const p of ['/src/views/LeaveApply.vue', '/src/views/EvPass.vue',
    '/src/views/Certificate.vue', '/src/views/Review.vue']) {
    check(/isDownloading\([^)]*\) && downloadPercent\s*\n?\s*\? `\$\{downloadPercent\}%`/.test(reads(p)),
      `${p}：没有百分比时显示原文案`)
  }
}

console.log('\n▶ 请假与电动车：承诺语照抄表上原话，各加一条「确认签字」')
{
  // 两个页面默认就停在「提交申请」那个 tab，表单本来就在页面上，不用灌数据
  const { html: leave, warns: lw } = await render('/src/views/LeaveApply.vue')
  const lh = stripComments(leave)
  check(lh.includes('本人承诺：'), '请假表单上多了「本人承诺」')
  check(lh.includes('1、请假期间保持与班导师和辅导员的联系，请假期满按时返校并办理销假手续。'),
    '第一条与《请假审批表》上的一致（保持联系、期满销假）')
  check(lh.includes('2、请假期间个人人身安全及财产安全责任自负。'),
    '第二条与《请假审批表》上的一致（安全责任自负）')
  check(lh.includes('我确认在请假审批表上签字'), '有「确认在请假审批表上签字」这一项')

  const { html: ev, warns: ew } = await render('/src/views/EvPass.vue')
  const eh = stripComments(ev)
  check(eh.includes('本人承诺申请通行证所对应车辆为本人实际使用') &&
    eh.includes('绝不进行代办、伪造、线上买卖通行证等违反校规的行为'),
    '电动车那句换成了《承诺书》上的原话')
  check(!eh.includes('提交前已与班委联系'), '原来那句自拟措辞已经撤掉')
  check(eh.includes('我确认在承诺书上签字'), '有「确认在承诺书上签字」这一项')

  // 漏挂校验的勾选框等于白摆：不勾也能交上去
  const L = readFileSync(`${ROOT}/src/views/LeaveApply.vue`, 'utf8')
  const E = readFileSync(`${ROOT}/src/views/EvPass.vue`, 'utf8')
  for (const f of ['agreed', 'promised', 'signConfirmed']) {
    check(new RegExp(`${f}: mustCheck\\(`).test(L), `请假：${f} 挂了校验`)
  }
  for (const f of ['confirmed', 'signConfirmed']) {
    check(new RegExp(`${f}: \\[\\{ validator: validate`).test(E), `电动车：${f} 挂了校验`)
  }
  check(L.includes('请确认会在请假审批表上签字') && E.includes('请确认会在承诺书上签字'),
    '没勾时提示的是缺哪一项，不是笼统的「请勾选」')

  check(![...lw, ...ew].some((w) => /Failed to resolve (component|directive)/.test(w)),
    '没有未解析的组件/指令')

  // 这几句在手机上都超过一行，而 Element 的复选框默认 nowrap + 死高 32px：
  // 不带上放开折行的那套 class，第二行会被直接裁掉
  const hasWrap = (src, cls) => {
    const blocks = src.match(new RegExp(`\\.${cls}[^{]*\\{[^}]*\\}`, 'g')) || []
    return blocks.some((b) => /white-space:\s*normal/.test(b) && /height:\s*auto/.test(b))
  }
  check((L.match(/class="agree-checkbox"/g) || []).length === 3,
    '请假三个勾选项都挂着 agree-checkbox')
  check(hasWrap(L, 'agree-checkbox'), 'agree-checkbox 放开了 nowrap 和固定高度')
  check((E.match(/class="confirm-item"/g) || []).length === 2,
    '电动车两个勾选项都挂着 confirm-item')
  check(hasWrap(E, 'confirm-item'), 'confirm-item 放开了 nowrap 和固定高度')

  // 没有签字图时先手写：勾上「我确认签字」那一刻就弹，不用等点提交
  for (const [name, src] of [['请假', L], ['电动车', E]]) {
    check(src.includes('<QuickSignDialog ref="signGuard" />'),
      `${name}：页面上挂了签字弹窗`)
    check(/prop="signConfirmed"[\s\S]{0,220}@change="handleSignConfirmedChange"/.test(src),
      `${name}：「我确认签字」的勾选框触发签名检查`)
    check(/async function handleSignConfirmedChange\(value\)[\s\S]{0,180}form\.signConfirmed = false/.test(src),
      `${name}：手写被取消时把勾去掉，不能留下一个假确认`)
    check(src.includes('await signGuard.value?.ensure()'),
      `${name}：提交前再兜底检查一次签字图`)
    const guardAt = src.indexOf('signGuard.value?.ensure()')
    check(guardAt > -1 && guardAt < src.indexOf('submitting.value = true'),
      `${name}：先签完再开始上传材料`)
  }

  const quick = readFileSync(`${ROOT}/src/components/QuickSignDialog.vue`, 'utf8')
  check(quick.includes('getMySignStatus') && quick.includes('if (uploaded) return true'),
    '快捷手签先查 /my-status，已经有图就直接放行')
  check(quick.includes('uploadSignImage') && quick.includes('if (!value) settle(false)'),
    '签完走同一个上传接口；取消则中止提交')
  check(quick.includes('还没有签名，请先手写一张'), '弹窗标题说清楚为什么要签')

  // 真渲染一次：弹窗打开时确实是一块能写的签名板，签名人不是空的
  const { html: quickHtml, warns: qw } = await renderPatched(
    '/src/components/QuickSignDialog.vue',
    'const visible = ref(false)',
    `const visible = ref(true)
  userStore.info = { name: '测试同学', student_no: '2026001' }`,
    { ElDialog: ElDialogStub }
  )
  const qh = stripComments(quickHtml)
  check(qh.includes('请在此处签名') && qh.includes('测试同学') &&
    qh.includes('2026001'), '弹窗打开就是签名板，签名人和学号都对')
  check(!qw.some((w) => /Failed to resolve (component|directive)/.test(w)),
    '快捷手签没有未解析的组件/指令')
}

console.log('\n▶ 三个办件的顶部说明：办件详情、提交材料、办结材料一套写法')
{
  const PAGES = [
    {
      path: '/src/views/LeaveApply.vue',
      name: '请假',
      intro: '因病因事无法参加课程或集体活动时',
      deadline: '3 个工作日（仅供参考）',
      notice: '本网办事项仅用于简化流程、避免材料递交繁琐，请假审批是否通过由学校决定。',
      submitted: '请假辅助证明',
      finished: '请假审批表（PDF）'
    },
    {
      path: '/src/views/EvPass.vue',
      name: '电动车',
      intro: '为在校内使用的电动自行车办理通行证',
      deadline: '7 个工作日（仅供参考）',
      notice: '本网络办件仅提供信息表生成',
      submitted: '行驶证（图片或 PDF）',
      finished: '电动车通行证申请表'
    },
    {
      path: '/src/views/Certificate.vue',
      name: '证明开具',
      intro: '开具在读证明、实习介绍信等由班委出具的文书',
      deadline: '7 个工作日（仅供参考）',
      notice: '班委会开具的介绍信公信力有限',
      submitted: '申请依据材料',
      finished: '证明成品（PDF）'
    }
  ]

  for (const p of PAGES) {
    const { html, warns } = await render(p.path)
    const h = stripComments(html)
    check(h.includes('办件详情') && h.includes('提交材料') && h.includes('办结材料'),
      `${p.name}：三段名目都在`)
    check(h.includes(p.notice), `${p.name}：原来那条提示语搬进了「注意事项」—— 没丢`)
    check(h.includes(p.submitted) && h.includes(p.finished),
      `${p.name}：提交材料、办结材料都按实际流程写上了`)
    check(h.includes(p.intro) && h.includes(p.deadline),
      `${p.name}：办件介绍与办结时限都写上了`)
    // 办结时限是承诺不是规矩（实际快慢看班委什么时候看到），三处都得带这四个字
    check(p.deadline.endsWith('（仅供参考）'), `${p.name}：办结时限标了「仅供参考」`)
    // 五项都填齐了，页面上就不该再落占位
    check(!h.includes('未指定'), `${p.name}：办件详情三项 + 两份材料都填齐，无占位`)
    check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)),
      `${p.name}：没有未解析的组件/指令`)
  }

  // 三页共用同一个组件：各写一份的话，改一次措辞得动三处、还容易漏
  for (const p of PAGES) {
    const src = readFileSync(`${ROOT}${p.path}`, 'utf8')
    check(src.includes("import ServiceIntro from '@/components/ServiceIntro.vue'") &&
      src.includes('<ServiceIntro'),
      `${p.name}：用的是公共组件，不是自己再写一份`)
    check(!/el-alert/.test(src), `${p.name}：原先那条 alert 已经撤干净`)
  }

  // 组件本身：什么都不传时五项全是「未指定」
  const { html: bare } = await render('/src/components/ServiceIntro.vue')
  check((stripComments(bare).match(/未指定/g) || []).length === 5,
    '组件什么都不传时，五个位置都落「未指定」')
}

console.log('\n▶ 页面铺满工作区：不套定宽的壳，宽屏不留空')
{
  // 早先几个页面各自在根节点上套了一层 max-width（请假 860、意见反馈 800、
  // 办事中心 720），后来加的页面都是裸 <div> 直接放 page-card —— 同一个工作区，
  // 点进去有的铺满、有的两边空一大块。根节点上挂类，十有八九就是想给这一页
  // 单独定宽，这里一并钉住。
  const PAGES = ['LeaveApply', 'EvPass', 'Certificate', 'Feedback', 'ServiceCenter']
  for (const name of PAGES) {
    const lines = readFileSync(`${ROOT}/src/views/${name}.vue`, 'utf8').split('\n')
    // <template> 的下一行就是根节点
    check(lines[1].trim() === '<div>',
      `${name}：根节点是裸 <div>，不给这一页单独套定宽的壳`)
    check(lines[2].includes('<div class="page-card"'),
      `${name}：page-card 直接铺在根节点里，宽度跟着工作区走`)
  }

  // 办事中心那四张服务卡：铺满之后若还是 flex 竖着排，宽屏上每张都拉成一条横幅
  //（左边图标、右边箭头，中间一片空白）。得用 auto-fit 的网格，宽屏分列、窄屏一列
  const sc = readFileSync(`${ROOT}/src/views/ServiceCenter.vue`, 'utf8')
  const grid = /\.service-grid\s*\{[^}]*\}/.exec(sc)?.[0] || ''
  check(/display:\s*grid/.test(grid) && /repeat\(auto-fit, minmax\(/.test(grid),
    '办事中心：服务卡是自适应网格，宽屏自动分列')
  check(/@media \(max-width: 768px\)[\s\S]*?\.service-grid\s*\{[^}]*grid-template-columns:\s*1fr/.test(sc),
    '办事中心：手机上定死一列，不挤成两列')
}

console.log('\n▶ 系统管理：水印溯源认得电动车申请表与承诺书')
{
  // 同上一节：这块在 tab 正文里，SSR 下不渲染，走源码断言
  const src = readFileSync(`${ROOT}/src/views/Admin.vue`, 'utf8')

  const at = src.indexOf("watermarkResult.source_type === 'evpass'")
  check(at > 0, '水印结果有电动车这一支')
  const branch = src.slice(at, at + 900)
  // 两份共用一个 source_type，到底是哪一份靠后端写好的 file_title 分
  check(branch.includes('watermarkResult.file_title'),
    '这一支直接显示后端写好的标题（「某某的电动车通行证申请表（日期）」）')
  check(branch.includes('电动车申请表与承诺书不写文件访问日志'),
    '顺带说明「不写日志是按设计的」，免得当成日志丢了')
  check(branch.includes('下载'), '说的是「谁于何时下载的」')

  // 顺序要紧：这一支必须排在那个通用 v-else 之前，排后面就永远轮不到它
  const fallback = src.indexOf('watermarkResult.log_matched', at)
  check(fallback > at, '通用那一支（带 log_matched 的）排在它后面')
}

console.log('\n▶ 系统管理：水印溯源认得请假审批表')
{
  // 这块在「文件访问日志」那个 tab 的正文里，SSR 下 tab 正文不渲染 —— 照本节
  // 其它几条的老路子走源码断言
  const src = readFileSync(`${ROOT}/src/views/Admin.vue`, 'utf8')

  const leaveBranch = src.slice(src.indexOf("watermarkResult.source_type === 'leave'"))
  check(leaveBranch.length > 0, '水印结果有请假审批表这一支')
  check(leaveBranch.slice(0, 1200).includes('检测到水印：请假审批表'),
    '这一支的措辞是「请假审批表」，不是笼统的「文件」')
  // 请假表的水印时间戳是**下载那一刻**现打的（不像导出是生成时间），措辞必须跟着分
  check(leaveBranch.slice(0, 1200).includes('下载'), '说的是「谁于何时下载的」')
  check(leaveBranch.slice(0, 1200).includes('不写文件访问日志'),
    '顺带说明「不写日志是按设计的」，免得当成日志丢了')

  // 顺序要紧：这一支必须排在那个通用 v-else 之前，排后面就永远轮不到它
  const at = src.indexOf("watermarkResult.source_type === 'leave'")
  const fallback = src.indexOf('watermarkResult.log_matched', at)
  check(at > 0 && fallback > at, '通用那一支（带 log_matched 的）排在它后面')
}

console.log('\n▶ 文件公开：删掉的文件，水印溯源要说得出「它已经没了」')
{
  // 文件公开里的文件被删时，它的查看/下载记录也一并清了。这时再拿一份流出去的
  // PDF 溯源，公告表里查不到那一行、日志里也核不到 —— 若还照旧显示成
  // 「动作未知 + 文件#5」，那个编号此刻已经指不回任何东西了，得换个说法。
  const admin = readFileSync(`${ROOT}/src/views/Admin.vue`, 'utf8')

  const generic = admin.indexOf('动作未知')
  check(generic > 0, '通用那一支还在（「动作未知」那个兜底）')
  // 通用分支那一段（到这一支收尾为止，够长就行）
  const branch = admin.slice(generic, generic + 1200)
  check(admin.includes('watermarkResult.file_deleted'), '通用那一支里分了「文件已删除」')
  check(branch.includes('已从「文件公开」里删除'),
    '明说这份文件是从「文件公开」删掉的，不是「查无此人」')
  check(branch.includes('一并清理'),
    '顺带说明记录也一并清了 —— 否则会被当成「日志丢了」')

  // 顺序要紧：这一支得排在「动作未知」**之后**，也就是落在通用分支内部。
  // 提到前面（比如做成 leave / evpass 那几支的兄弟节点）不会报错，
  // 但会把正常文件也拦下来，连标题都不显示了
  check(admin.indexOf('watermarkResult.file_deleted') > generic,
    '「已删除」这一支落在通用分支里，没拦在正常文件前面')

  // 通用分支里那句「核不到」的解释也要跟上新的保留期口径
  check(branch.includes('只保留最近一个月'),
    '把「记录只留一个月」写出来，管理员才知道为什么更早的核不到')

  // 删确认框：删完之后「文件访问日志」里再也查不到这份文件，管理员溯源时只会看到
  // 「已删除」—— 先说清楚，免得事后翻旧账
  const ann = readFileSync(`${ROOT}/src/views/Announcements.vue`, 'utf8')
  const handle = ann.slice(ann.indexOf('async function handleDelete'))
  check(handle.slice(0, 600).includes('查看/下载记录也会一并清理'),
    '删确认框里写明「查看/下载记录也会一并清理」')
}

console.log('\n▶ 首页统计卡：iPad 竖屏下两位数不折行')
{
  // 折行是布局算出来的，SSR 出来的 HTML 里没有宽度 —— 所以这一节断的是**样式表**：
  // 把 <style> 里每条 @media 的条件解析出来，算出某宽度会命中哪几条，再断言命中的
  // 那条确实把卡里的图标和数字收小了。
  //
  // 为什么盯 820：iPad 竖屏（810 / 820 / 834）在 768 之上，拿不到「手机」那套尺寸，
  // 而四张卡已经按 1/4 宽排好了，桌面尺寸（图标 60px、数字 28px、内边距 20px）挤不下 ——
  // 「36」当场被压成上下两个数字，标签「总人数」也竖成三行。
  const src = readFileSync(`${ROOT}/src/views/Dashboard.vue`, 'utf8')
  const style = src.slice(src.indexOf('<style'), src.lastIndexOf('</style>'))

  /** 从 s[open]（'{' 的位置）起找配对的那个 '}'，返回里面那段文本 */
  const inside = (s, open) => {
    let depth = 0
    for (let i = open; i < s.length; i++) {
      if (s[i] === '{') depth++
      else if (s[i] === '}' && --depth === 0) return s.slice(open + 1, i)
    }
    return ''
  }
  const media = [...style.matchAll(/@media\s*([^{]+)\{/g)].map((m) => {
    const open = m.index + m[0].length - 1
    const body = inside(style, open)
    return { cond: m[1].trim(), start: m.index, end: open + body.length + 2, body }
  })
  check(media.length > 0, '样式表里有 @media')

  /** 一条 @media 的条件把宽度 w 圈在里面吗（只认 min-width / max-width，够用了） */
  const covers = (cond, w) => {
    const min = cond.match(/min-width:\s*([\d.]+)px/)
    const max = cond.match(/max-width:\s*([\d.]+)px/)
    return !(min && w < +min[1]) && !(max && w > +max[1])
  }
  /** 样式文本里某个选择器的声明块（`[^}]` 收尾即可：这几条规则里没有嵌套） */
  const decls = (text, sel) =>
    (text.match(new RegExp(sel.replace(/\./g, '\\.') + '\\s*\\{([^}]*)\\}')) || ['', ''])[1]
  /** 一条声明里的某个 px 值 */
  const px = (decl, prop) => {
    const m = decl.match(new RegExp(`${prop}:\\s*([\\d.]+)px`))
    return m ? +m[1] : null
  }

  const W = 820
  const hit = media.filter((b) => covers(b.cond, W))
  const icons = hit.map((b) => px(decls(b.body, '.stat-icon'), 'width')).filter((v) => v !== null)
  const values = hit.map((b) => px(decls(b.body, '.stat-value'), 'font-size')).filter((v) => v !== null)

  check(icons.length > 0 && Math.min(...icons) <= 50,
    `${W}px 会命中一条把图标收到 50px 以内的媒体查询（现在是 ${icons.length ? Math.min(...icons) + 'px' : '没命中'}）`)
  check(values.length > 0 && Math.min(...values) <= 24,
    `${W}px 会把数字收到 24px 以内（现在是 ${values.length ? Math.min(...values) + 'px' : '没命中'}）`)

  // 兜底：数字任何宽度下都不许换行 —— 上面那条媒体查询哪天被删了，两位数也不该折成两行。
  // 先把它那几条 @media 整块挖掉，才是各行其是的「基础样式」（倒着挖，下标才还准）
  let base = style
  for (const b of [...media].reverse()) base = base.slice(0, b.start) + base.slice(b.end)
  check(/white-space:\s*nowrap/.test(decls(base, '.stat-value')),
    '基础样式里 .stat-value 写着 white-space: nowrap')

  // 这一页**渲染不了**（顶部 import echarts，而 zrender 在模块顶层就摸 document），
  // 四张卡还在不在只能断源码
  const cards = ['总人数', '女生', '男生', '班委']
  check(cards.every((label) => src.includes(`<div class="stat-label">${label}</div>`)),
    `四张统计卡都还在（${cards.join(' / ')}）`)
  // 标签一律短词：四字短语（「女生人数」）在窄屏上会被卡片宽度挤成两行，
  // 而那是卡片里唯一不会自己收窄的东西
  check(cards.every((label) => label.length <= 3),
    `标签都不超过三个字（${cards.join(' / ')}）`)
}

console.log('\n▶ 首页：品牌标签、快捷入口、最新通知')
{
  const src = readFileSync(`${ROOT}/src/views/Dashboard.vue`, 'utf8')

  // 学院 / 专业两个品牌标签各自判空。**不是拼成一句话再过滤**：SITE 里没配就是空字符串
  // （utils/site.js 明确不做兜底），拼的话两个都空会渲染出一句孤零零的「 · 」
  check(/<span v-if="SITE\.college" class="brand-chip">/.test(src), '学院配了才渲染那个标签')
  check(/<span v-if="SITE\.major" class="brand-chip">/.test(src), '专业配了才渲染那个标签')

  // 快捷入口：从源码里解析出这份清单，然后两件事都用它来断 ——
  // 一是每项的可见性和路由 meta 对不对得上，二是那份判据本身跑起来对不对
  const shortcuts = [...src.matchAll(
    /\{ path: '(\/[^']+)', title: '([^']+)', icon: '[^']+', theme: '[^']+'([^}]*)\}/g
  )].map(([, path, title, tail]) => ({
    path,
    title,
    public: /public: true/.test(tail),
    studentOnly: /studentOnly: true/.test(tail),
    role: (tail.match(/role: '(\w+)'/) || [])[1]
  }))
  check(shortcuts.length >= 6, `从首页源码里解析出 ${shortcuts.length} 个快捷入口`)

  // 首页摆得出来、点进去被路由守卫弹回首页，是最难发现的那种错（界面上只是「点了没反应」）。
  // 所以逐项比着 router/index.js 的 meta 断：可见性条件必须**一模一样**，多一条少一条都不行
  const router = readFileSync(`${ROOT}/src/router/index.js`, 'utf8')
  const flags = (text) => ({
    public: /public: true/.test(text),
    studentOnly: /studentOnly: true/.test(text),
    role: (text.match(/role: '(\w+)'/) || [])[1] || null
  })
  for (const item of shortcuts) {
    const at = router.indexOf(`path: '${item.path}'`)
    check(at >= 0, `${item.path}（${item.title}）在路由表里`)
    if (at < 0) continue
    const meta = (router.slice(at).match(/meta: \{([^}]*)\}/) || ['', ''])[1]
    const own = { public: item.public, studentOnly: item.studentOnly, role: item.role || null }
    const want = flags(meta)
    check(JSON.stringify(own) === JSON.stringify(want),
      `${item.path} 的可见性和路由 meta 一致（首页 ${JSON.stringify(own)} / 路由 ${JSON.stringify(want)}）`)
  }

  // 判据本体真跑一遍 —— 首页渲染不出来，但这份纯函数能。同一份 canSee 侧边菜单也在用
  const { canSee } = await server.ssrLoadModule('/src/utils/roles.js')
  const seen = (user) => shortcuts.filter((i) => canSee(i, user)).map((i) => i.path)
  const guy = (role, extra = {}) => ({ isLogin: true, isExternal: false, info: { role }, ...extra })

  check(seen({ isLogin: false, isExternal: false, info: null }).join() === '/notices',
    '游客只剩「通知公告」（它本来就是公开页）')
  check(seen(guy('student')).join() === '/notices,/service,/leave,/schedule,/downloads',
    `普通学生看得见那五项（实际 ${seen(guy('student')).join(' / ')}）`)
  check(!seen(guy('student', { isExternal: true })).includes('/service'),
    '域外账号看不见学生用的那几项（域外账号没有学生记录，点进去也会被弹回）')
  check(!seen(guy('student')).includes('/students'),
    '普通学生看不见「学生信息」（那是班委及以上才有的页）')
  check(seen(guy('committee')).length === shortcuts.length,
    '班委/管理员八项全看得见')

  // 整块只给登录用户：游客看得见的那一项在侧边菜单里已经有了，
  // 为它单摆一块卡片没意义
  check(/v-if="userStore\.resolved && userStore\.isLogin" class="page-card quick-card"/.test(src),
    '快捷入口整块只给登录用户（且等 resolved，别闪一下）')

  // 最新通知
  check(/getNotices\(\{ limit: NOTICE_COUNT \}\)/.test(src),
    '通知按条数取，不是取回来再切片（每条都带整篇 Markdown 正文）')
  check(/v-if="notices\.length"/.test(src), '没有通知就整块不显示')
  check(/v-if="userStore\.isLogin && !item\.is_read"/.test(src),
    '未读圆点只在登录时渲染 —— 后端对游客恒返回未读，不判断就是整列红点')
  check(src.includes('/notices?id=${item.id}'),
    '点一条直接定位到那一篇（通知页认 ?id=，见 utils/notice.js）')
  check(/Promise\.allSettled\(/.test(src),
    '生日和通知两路一起发、各自兜异常，不串着等也不连累首页统计')

  // 判据只有一份：侧边菜单改成 import 了，不许再抄回去一份
  // （布局已从 App.vue 拆到 AppLayout.vue，菜单在那里）
  const app = readFileSync(`${ROOT}/src/components/AppLayout.vue`, 'utf8')
  check(/import \{ canSee \} from '@\/utils\/roles'/.test(app), '菜单用的是公共那份 canSee')
  check(!/function canSee\(/.test(app), 'AppLayout 里没有第二份 canSee 实现')
}

console.log('\n▶ 分类统计：概览卡点开是哪些人')
{
  // 这一页渲染不了，原因和上一节的 Dashboard.vue 一样：顶层 import echarts，而 zrender
  // 在模块加载时就摸 document（render.mjs 只补了 window，没补 document）。
  // 所以：分组规则抽在 utils/statGroups.js 里**真跑**，页面那点接线只能断源码。
  const { buildRoster, countMinority } = await server.ssrLoadModule('/src/utils/statGroups.js')

  // 边界值都塞进来：职务有 真职务/「无」/空串/null 四种写法，民族有汉族、少数民族和空串。
  // 学号等长，字符串升序排出来就是人眼看的顺序
  const s = (no, name, extra) => ({ id: Number(no), student_no: no, name, ...extra })
  const students = [
    s('001', '甲', { gender: '男', ethnicity: '汉族', political_status: '共青团员', class_position: '班长', league_position: '学研部', is_poor: '否' }),
    s('002', '乙', { gender: '女', ethnicity: '满族', political_status: '群众', class_position: '无', league_position: '无', is_poor: '是' }),
    s('003', '丙', { gender: '男', ethnicity: '回族', political_status: '共青团员', class_position: '', league_position: '', is_poor: '否' }),
    s('004', '丁', { gender: '女', ethnicity: '汉族', political_status: '群众', class_position: null, league_position: null, is_poor: '是' }),
    s('005', '戊', { gender: '男', ethnicity: '回族', political_status: '中共预备党员', class_position: '学习委员', league_position: '学研部', is_poor: '否' }),
    s('006', '己', { gender: '女', ethnicity: '汉族', political_status: '共青团员', class_position: '生活委员', league_position: '文体部', is_poor: '否' }),
    s('007', '庚', { gender: '男', ethnicity: '汉族', political_status: '群众', class_position: null, league_position: '文体部', is_poor: '是' }),
    s('008', '辛', { gender: '女', ethnicity: '满族', political_status: '群众', class_position: '', league_position: '学研部', is_poor: '否' }),
  ]
  /** 名单里的学号按顺序连起来：一次断言「恰好是这些人、就这个顺序」 */
  const nos = (key) => buildRoster(key, students).rows.map((x) => x.student_no).join(',')

  check(nos('male') === '001,003,005,007', '男生名单：只有男生')
  check(nos('female') === '002,004,006,008', '女生名单：只有女生')
  check(nos('league') === '001,003,006', '共青团员名单：只认「共青团员」，预备党员不算团员')

  // 班委/团学会是「有职务」的三张写法里排掉「无」和空串 —— 组名按码点排：
  // 学(5b66) < 班(73ed) < 生(751f)、学(5b66) < 文(6587)
  check(nos('committee') === '005,001,006', '班委任职表：按职务分组，排掉「无」/空串/null')
  check(nos('leagueMember') === '001,005,008,006,007', '团学会名单：按部门分组，同一部门的人挨在一起')
  check(buildRoster('committee', students).rows[0].group === '学习委员', '班委那张的 group 是职务本身')

  check(nos('poor') === '002,004,007', '贫困生名单：只认「是」，「否」不进')
  check(nos('minority') === '003,005,002,008', '少数民族名单：按民族分组，汉族不进，空民族也不进')

  check(buildRoster('committee', students).column === '职务'
    && buildRoster('leagueMember', students).column === '部门'
    && buildRoster('minority', students).column === '民族', '分组卡各自的分组列名')
  check(buildRoster('male', students).column === ''
    && buildRoster('male', students).rows.every((r) => !('group' in r)), '平铺的卡没有分组列')
  check(buildRoster('male', students).rows.every((r) => r.id === Number(r.student_no)),
    '每行都带 id（名单里的「详情」靠它跳学生详情）')
  check(buildRoster('committee', students).title === '班委任职表'
    && buildRoster('minority', students).title === '少数民族名单', '弹窗标题按名单取')

  check(buildRoster(null, students) === null && buildRoster('total', students) === null
    && buildRoster(undefined, students) === null, '没有 key 的卡（总人数）不返回名单 —— 点了不弹窗')
  check(buildRoster('male', [])?.rows.length === 0 && buildRoster('male')?.rows.length === 0,
    '空名单/没给名单也不炸')

  // 卡片上的数字点开必须和弹窗里的条数相等：这里刻意造一份「有两个少数民族、但民族种类
  // 比少数民族人数少」的字典（汉族 4 + 满族 2 + 回族 2），种类数是 3、人数是 4
  const ethDict = {}
  for (const st of students) ethDict[st.ethnicity] = (ethDict[st.ethnicity] || 0) + 1
  const minorityRows = buildRoster('minority', students).rows.length
  check(countMinority(ethDict) === minorityRows && minorityRows === 4,
    `「少数民族人数」卡与弹窗行数相等（${countMinority(ethDict)} = ${minorityRows}，而民族种类数是 ${Object.keys(ethDict).length}）`)
  check(countMinority({ 汉族: 30 }) === 0 && countMinority({}) === 0 && countMinority(undefined) === 0,
    '只有汉族 / 空字典 / 没数据时是 0')

  // 页面接线：这一页渲染不了，只能断源码
  const src = readFileSync(`${ROOT}/src/views/Statistics.vue`, 'utf8')
  const cards = ['总人数', '男生', '女生', '共青团员', '班委', '团学会成员', '贫困生', '少数民族人数']
  check(cards.every((label) => src.includes(`label: '${label}'`)), `八张概览卡都在（${cards.join(' / ')}）`)
  check(!src.includes("label: '民族数'"), '原来那张「民族数」已改名为「少数民族人数」')

  // 「总人数」那张不许有 key：有 key 就会弹出一个没有名单的空弹窗
  const totalLine = src.split('\n').find((l) => l.includes("label: '总人数'")) || ''
  check(!!totalLine && !/key:/.test(totalLine), '「总人数」卡没有 key（保持不可点）')
  const keyed = [['男生', 'male'], ['女生', 'female'], ['共青团员', 'league'], ['班委', 'committee'],
    ['团学会成员', 'leagueMember'], ['贫困生', 'poor'], ['少数民族人数', 'minority']]
  check(keyed.every(([label, key]) => new RegExp(`label: '${label}'[^}]*key: '${key}'`).test(src)),
    '另外七张卡各自指向对的名单（' + keyed.map(([, k]) => k).join(' / ') + '）')

  check(/@click="openRoster\(item\.key\)"/.test(src), '点卡片走 openRoster（key 为空时它自己 return）')
  check(/class="mini-card"[\s\S]{0,200}clickable/.test(src)
    && /\.mini-card\.clickable\s*\{[\s\S]{0,120}cursor:\s*pointer/.test(src),
    '可点的卡有手型光标，看得出能点')
  check(/<el-dialog v-model="rosterVisible"[\s\S]{0,400}<Watermark :text="watermarkText" \/>/.test(src),
    '名单弹窗里盖了水印（同「学生详情」那个弹窗）')
  check(/<el-table-column v-if="roster\?\.column" prop="group"/.test(src), '分组卡多一列，平铺的卡没有')
  check(/prop="name" label="姓名"/.test(src) && /prop="student_no" label="学号"/.test(src),
    '名单里是姓名 + 学号')
  check(/max-height="420px"/.test(src), '长名单（团员近三十人）用 max-height 管住弹窗高度')
  check(/goStudentDetail[\s\S]{0,200}path: '\/students', query: \{ open: row\.id \}/.test(src),
    '「详情」跳学生信息页并弹开这个人（那边认 ?open=<id>）')
  check(/studentStore\.fetchAllStudents\(\)/.test(src), '名单走 store 的 fetchAllStudents（一次拉全班，本地分组）')
}

console.log('\n▶ 点名与抽签：台上只留姓名学号，不再显示头像')
{
  // 两个弹窗的正文都在 el-dialog 里（SSR 下不渲染），所以给它盖上会渲染正文的桩，
  // 再把弹窗拨到「台上正好有人」的那一步，真渲染一遍看输出里有什么。
  //
  // 夹具里的人**特意带 gaokao_photo**：有照片却不出图，才证明是头像被拿掉了，
  // 而不是照片字段恰好为空 —— 后者用空字段测会假通过。
  const WHO = "{ id: 1, name: '张三', student_no: '20260000001', gaokao_photo: 'gk.png' }"
  const DIALOG = { ElDialog: ElDialogStub }

  const roll = await renderPatchedMany('/src/components/RollCallDialog.vue', [
    ['const visible = ref(false)', 'const visible = ref(true)'],
    ["const step = ref('scope')", "const step = ref('calling')"],
    ['const queue = ref([])', `const queue = ref([${WHO}])`]
  ], DIALOG)
  const rollHtml = stripComments(roll.html)
  check(rollHtml.includes('张三') && rollHtml.includes('20260000001'),
    '点名第二步真渲染出来了（台上的姓名学号都在）')
  check(!rollHtml.includes('<img'), '点名台上没有头像')

  const draw = await renderPatchedMany('/src/components/DrawDialog.vue', [
    ['const visible = ref(false)', 'const visible = ref(true)'],
    ["const step = ref('setup')", "const step = ref('drawing')"],
    ["const mode = ref('batch')", "const mode = ref('one')"],
    ['const latest = ref(null)', `const latest = ref(${WHO})`]
  ], DIALOG)
  const drawHtml = stripComments(draw.html)
  check(drawHtml.includes('张三') && drawHtml.includes('20260000001'),
    '抽签「点一回取一个」真渲染出来了（台上的姓名学号都在）')
  check(!drawHtml.includes('<img'), '抽签台上没有头像')

  // 源码兜底：把上面两条断言的范围从「这两个状态」放大到「整个文件」——
  // 比如哪天给「一次抽取」模式也补个头像，或者把头像块从别处搬回来，这两条会红
  for (const [file, cls] of [['RollCallDialog', 'rc'], ['DrawDialog', 'dr']]) {
    const src = readFileSync(`${ROOT}/src/components/${file}.vue`, 'utf8')
    check(!src.includes('<img') && !src.includes('gaokao_photo') && !src.includes('/photo')
      && !src.includes(`.${cls}-photo`) && !src.includes(`.${cls}-img`)
      && !src.includes(`.${cls}-placeholder`),
      `${file}.vue 里没有图片、照片接口和头像块的样式`)
  }
}

console.log('\n▶ 共青团员：点名能选、出卷能筛，判据只有一份')
{
  const { pickByScope, isLeagueMember } = await server.ssrLoadModule('/src/utils/roster.js')

  // 边界值都塞进来：空串、整个字段缺失，还有「中共预备党员」—— 它带「党员」二字，
  // 写成 includes('团员') 之类会把「预备党员」也算进去，这条就是拦那种写法
  const st = (no, ps) => ({
    id: Number(no),
    student_no: no,
    name: no,
    ...(ps === undefined ? {} : { political_status: ps })
  })
  const roster = [
    st('001', '共青团员'),
    st('002', '群众'),
    st('003', '共青团员'),
    st('004', '中共预备党员'),
    st('005', ''),
    st('006', undefined)
  ]
  const nos = (list) => list.map((s) => s.student_no).join(',')

  check(nos(pickByScope(roster, '共青团员')) === '001,003',
    '点名选「共青团员」只出团员：群众 / 预备党员 / 空 / 整个字段没有的都不进')
  check(isLeagueMember(null) === false && isLeagueMember(undefined) === false,
    '判据对 null / undefined 不炸（名单里字段可能是空的）')
  check(nos(pickByScope(roster, '全班')) === '001,002,003,004,005,006'
    && nos(pickByScope(roster, '男生')) === '',
    '加了这一条没有影响原有的「全班」和按性别的两个范围')

  // 统计页那张团员卡必须和点名、出卷是同一批人 —— 哪边单独重写一遍判据，这条会红
  const { buildRoster } = await server.ssrLoadModule('/src/utils/statGroups.js')
  check(nos(buildRoster('league', roster).rows) === '001,003',
    '分类统计的共青团员名单与点名/出卷共用同一个判据')

  // 点名第一步真渲染：按钮上的人数按政治面貌现算
  const DIALOG = { ElDialog: ElDialogStub }
  const TWO = '{ id: 1, student_no: "001", name: "甲", political_status: "共青团员" },'
    + '{ id: 2, student_no: "002", name: "乙", political_status: "群众" }'
  const roll = await renderPatchedMany('/src/components/RollCallDialog.vue', [
    ['const visible = ref(false)', 'const visible = ref(true)'],
    ['const roster = ref([])', `const roster = ref([${TWO}])`]
  ], DIALOG)
  const rollHtml = stripComments(roll.html)
  check(rollHtml.includes('共青团员（1）'),
    '点名第一步真渲染出团员按钮，人数只算团员（两个人里一个）')
  check(rollHtml.includes('全班（2）'), '同一次渲染里「全班」还是两个人，没被带偏')

  // 点了会发生什么 SSR 测不到（事件不进 HTML），只能断源码
  const rollSrc = readFileSync(`${ROOT}/src/components/RollCallDialog.vue`, 'utf8')
  check(/@click="startCall\('共青团员'\)"/.test(rollSrc),
    '这个按钮按「共青团员」这个范围点名 —— 范围名会原样写进考勤记录')

  // 出卷弹窗的「仅团员」：和「仅班委」并排，用的是同一份判据
  const pollSrc = readFileSync(`${ROOT}/src/components/PollCreateDialog.vue`, 'utf8')
  check(pollSrc.includes('>仅团员<'), '出卷「有权表决的人」多了一枚「仅团员」')
  check(/roster\.value\.filter\(isLeagueMember\)/.test(pollSrc),
    '「仅团员」调的是共用判据，不是在这儿再比一遍「共青团员」四个字')
  check(/import \{ isLeagueMember \} from '@\/utils\/roster'/.test(pollSrc),
    '判据是从 utils/roster.js 引进来的，不是本地又定义了一个')

  // 后端得把政治面貌带出来，否则上面这个判据没有数据可判
  const pollsApi = readFileSync(`${ROOT}/../backend/app/api/polls.py`, 'utf8')
  check(/"political_status": student\.political_status/.test(pollsApi),
    '出卷名单接口回填每个人的政治面貌')
  const pollSchema = readFileSync(`${ROOT}/../backend/app/schemas/poll.py`, 'utf8')
  check(/class PollRosterItem[\s\S]{0,500}political_status/.test(pollSchema),
    'PollRosterItem 里有 political_status 字段')
}

console.log('\n▶ 投票页盖水印：整页 + 两个弹窗')
{
  const voteSrc = readFileSync(`${ROOT}/src/views/Vote.vue`, 'utf8')
  const { html } = await render('/src/views/Vote.vue')
  const { SITE } = await server.ssrLoadModule('/src/utils/site.js')

  // 水印字样是 encodeURIComponent 塞进 SVG 再当背景图的，中文在 HTML 里是 %XX，
  // 所以断言也得编码后再比 —— 直接 includes('示例班') 永远为假
  check(html.includes(encodeURIComponent(SITE.shortName)),
    '整页真渲染出一层水印（字样「当前登录人@班级」，SSR 里没登录态所以是「未知用户」）')
  check((html.match(/class="watermark"/g) || []).length === 1,
    '页面上只铺一层：弹窗没打开，水印不该跟着混进来')

  check(/<div class="vote">[\s\S]{0,300}?<Watermark/.test(voteSrc), '水印放在根容器第一行')
  check(/\.vote \{[\s\S]{0,120}?position: relative/.test(voteSrc),
    '根容器是 position: relative —— 水印是 absolute，没有定位基准会铺到整页之外')

  // 两个弹窗：SSR 渲不出弹窗正文（见文件头），只能断源码。两处的字样必须同一份
  check(/<Watermark :text="watermarkText" \/>\s*<div v-loading="voteLoading"/.test(voteSrc),
    '投票弹窗盖了水印（投过之后这里会回显「我投了什么」）')
  check(/<Watermark :text="watermarkText" \/>\s*<div v-loading="resultLoading"/.test(voteSrc),
    '结果/名单弹窗盖了水印（名单里是「谁投了、谁还没投」）')
  check(/import \{ useWatermark \} from '@\/composables\/useWatermark'/.test(voteSrc),
    '水印字样用的还是那份共用的 composable，没有在页面里另写一套')
}

console.log('\n▶ 投票能编辑：标题描述随时改，题目只在没开始时能改')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const pollSrc = src('/src/components/PollCreateDialog.vue')

  // 「详情填进表单」那一段映射（formFromPoll）是纯函数，**真跑它**。
  // 不能在渲染结果里断：SSR 下 el-input 只输出 placeholder、不输出 value（实测过），
  // 所以「标题填回来了没有」在 HTML 里根本看不见 —— 断它只会断到假的东西
  const { formFromPoll, blankForm, blankQuestion } =
    await server.ssrLoadModule('/src/utils/poll.js')

  const DETAIL = (status) => ({
    id: 7, title: '关于班服的表决', description: '先看看款式', anonymous: false,
    status, start_at: '2026-11-01T08:00:00', end_at: '2026-11-02T20:00:00', target_count: 38,
    questions: [
      { id: 11, sort: 0, title: '你赞成哪一款？', multiple: false, max_choices: 1,
        options: ['A 款', 'B 款'], my_choices: [], tallies: null }
    ]
  })

  // ---------- 详情 → 表单（真跑） ----------
  const f = formFromPoll(DETAIL('pending'))
  check(f.title === '关于班服的表决', '标题填回来了')
  check(f.description === '先看看款式', '描述填回来了')
  // 这条是这一节最该钉住的：详情回的是 ISO 串，picker 的 value-format 是
  // 'YYYY-MM-DD HH:mm'，中间那步格式化一旦没了，两个时间栏就都是空的
  check(f.start_at === '2026-11-01 08:00' && f.end_at === '2026-11-02 20:00',
    '起止时间转成了 picker 认的格式（ISO 串原样塞进去这一栏会是空的）')
  check(f.questions.length === 1 && f.questions[0].title === '你赞成哪一款？',
    '题干填回来了')
  check(JSON.stringify(f.questions[0].options) === JSON.stringify(['A 款', 'B 款']),
    '选项填回来了，而且原顺序不动')
  check(f.questions[0].multiple === false && f.questions[0].max_choices === 1,
    '单选题的「最多选几项」固定是 1')
  check(f.targets.length === 0, '不带表决范围（范围改不了，选中的名单也不该被回填）')

  // 填空题、脏数据和兜底
  const multi = formFromPoll({ questions: [{ title: 'q', multiple: true, max_choices: 9, options: ['a', 'b'] }] })
    .questions[0]
  check(multi.multiple && multi.max_choices === 2,
    '「最多选几项」超过选项数就夹回选项数（照抄组件里 removeOption 的口径）')
  check(formFromPoll({ questions: [{ title: 'q', multiple: true, options: ['a', 'b', 'c'] }] })
    .questions[0].max_choices === 2, '多选没给 max_choices 时默认 2')
  check(formFromPoll({ questions: [{ title: 'q', multiple: false, max_choices: 3, options: ['a', 'b'] }] })
    .questions[0].max_choices === 1, '单选就算库里存着别的数，也一律按 1 来')
  check(JSON.stringify(formFromPoll({ questions: [{ title: 'q', options: [] }] })
    .questions[0].options) === JSON.stringify(['', '']), '选项为空时补两个空框，不然没法输入')
  check(formFromPoll({ questions: [] }).questions.length === 1,
    '详情里一道题都没有时补一道空题，弹窗不能是空的')
  check(formFromPoll({ start_at: null, end_at: '' }).start_at === '',
    '时间缺失给空串，不能是 formatDateTime 那个「-」（picker 里会显示成一个破折号）')

  // blankForm / blankQuestion：出卷和编辑共用同一份「空表单」定义
  check(blankForm().questions.length === 1, '空表单自带一道题')
  check(blankQuestion().max_choices === 1 && blankQuestion(true).max_choices === 2,
    '空题的选项数跟着单选/多选走')
  check(/Object\.assign\(form, blankForm\(\), formFromPoll\(poll\)\)/.test(pollSrc),
    'openForEdit 用的是这段纯函数（拿详情拼表单只有这一处实现）')

  // ---------- 未开始：题目能改（这一半是渲染接线） ----------
  // 通用的 ElDialogStub 不渲染 title 这个 prop，而这节要断「标题切没切」——
  // 就地补一个把它渲出来的，比去 grep 源码 :title 那句结实
  const DialogWithTitle = {
    name: 'DialogWithTitle',
    props: { modelValue: Boolean, title: String },
    setup(props, { slots }) {
      return () => (props.modelValue
        ? h('div', [h('div', props.title), slots.default?.(), slots.footer?.()])
        : null)
    }
  }
  /** 打开编辑态：openForEdit 是父组件调用的，SSR 里没人调，干脆在 setup 里补一句 */
  async function editMode(status) {
    const r = await renderPatchedMany('/src/components/PollCreateDialog.vue', [
      ['defineExpose({ open, openForEdit })',
        `openForEdit(${JSON.stringify(DETAIL(status))})\n` + 'defineExpose({ open, openForEdit })']
    ], { ElDialog: DialogWithTitle })
    return stripComments(r.html)
  }

  /** 某个 placeholder 的输入框那一整个标签（要按属性名判 disabled 就只能看整条） */
  function inputTag(html, placeholder) {
    return (html.match(/<input[^>]*>/g) || [])
      .find((t) => t.includes(`placeholder="${placeholder}"`)) || ''
  }

  const draft = await editMode('pending')
  check(draft.includes('编辑投票'), '弹窗标题切成「编辑投票」')
  check(draft.includes('保存修改'), '按钮切成「保存修改」')
  check(!/\sdisabled/.test(inputTag(draft, '题干，例如：你赞成哪一款班服？')),
    '没开始：题干能改')
  check(!draft.includes('已开始，题目不能改了'), '没开始：不挂「题目不能改」的说明')
  check(draft.includes('共 38 人 · 不能改'), '表决范围只显示人数')
  check(!draft.includes('仅团员'), '编辑时整块名单不渲染（范围本来就改不了，也不用拉）')

  // ---------- 已开始：题目锁住，标题描述还能改 ----------
  const started = await editMode('open')
  check(/\sdisabled/.test(inputTag(started, '题干，例如：你赞成哪一款班服？')),
    '已开始：题干是只读的')
  check(/\sdisabled/.test(inputTag(started, '选项 1')), '已开始：选项也是只读的')
  check(started.includes('已开始，题目不能改了'), '已开始：挂出为什么不能改')
  check(!/\sdisabled/.test(inputTag(started, '例如：关于班服款式的表决')),
    '已开始：**标题照样能改**（封的是题目，不是整场投票）')
  check(!/\sdisabled/.test(inputTag(started, '选填。写清背景或注意事项')),
    '已开始：描述照样能改')

  // ---------- 提交那一下 ----------
  check(/if \(!startedLocked\.value\) payload\.questions = buildQuestions\(\)/.test(pollSrc),
    '题目锁着时**一个字都不传 questions** —— 后端只在收到它时才替换，已开始带了会被 400')
  check(/await updatePoll\(editingId\.value, payload\)/.test(pollSrc), '编辑走 updatePoll')
  check(/defineExpose\(\{ open, openForEdit \}\)/.test(pollSrc), 'openForEdit 暴露给父组件')
  check(/const emit = defineEmits\(\['saved'\]\)/.test(pollSrc),
    '出卷和编辑发同一个 saved：父组件一律重拉列表')

  // ---------- 入口 ----------
  const voteSrc = src('/src/views/Vote.vue')
  check(/<el-dropdown-item command="edit">编辑<\/el-dropdown-item>/.test(voteSrc),
    '管理下拉里多了「编辑」')
  check(/command === 'edit'[\s\S]{0,80}?handleEdit\(row\)/.test(voteSrc), '「编辑」分发到 handleEdit')
  check(/async function handleEdit[\s\S]{0,300}?openForEdit\(await getPoll\(row\.id\)\)/.test(voteSrc),
    '编辑前先拉一次详情（列表行里没有题目）')
  check(/@saved="handleSaved"/.test(voteSrc), '保存后父组件重拉列表')

  const voteApi = src('/src/api/vote.js')
  check(/export function updatePoll[\s\S]{0,400}?method: 'patch'/.test(voteApi),
    'updatePoll 走 PATCH')

  // ---------- 后端 ----------
  const pollsPy = src('/../backend/app/api/polls.py')
  check(/@router\.patch\("\/\{poll_id\}"/.test(pollsPy), '后端有 PATCH /api/polls/{poll_id}')
  // 状态是上面算好一次的 `status`（记名那段也用它），不再在题目这里现算一遍
  check(/status != STATUS_PENDING[\s\S]{0,400}?题目改不了/.test(pollsPy),
    '题目只在未开始时能换，否则回一句中文原因（不是 422 的数组）')
  // 窗口 800：update_poll 光是 docstring 就五百来字，卡太紧会因为「注释写长了」而红
  check(/def update_poll[\s\S]{0,800}?_load_manageable\(db, poll_id, user, is_admin\(user\)\)/
    .test(pollsPy), '编辑走的是「我能管」那道闸，越权一律 404')
  check(/_check_questions\(data\.questions\)/.test(pollsPy),
    '替换题目复用出卷那份校验，没有另写一套')
}

console.log('\n▶ 出卷能复用旧卷子：只搬题目，其余重新填')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const pollSrc = src('/src/components/PollCreateDialog.vue')

  // 映射和「编辑填回表单」共用一段，真跑它
  const { questionsFromPoll, formFromPoll, hasQuestionContent, blankQuestion } =
    await server.ssrLoadModule('/src/utils/poll.js')

  const OLD = () => ({
    id: 9, title: '上一场表决', status: 'closed', anonymous: true,
    start_at: '2026-10-01T08:00:00', end_at: '2026-10-02T20:00:00',
    questions: [
      { id: 1, title: '旧题一', multiple: false, max_choices: 1, options: ['甲', '乙'] },
      { id: 2, title: '旧题二', multiple: true, max_choices: 9, options: ['A', 'B', 'C'] }
    ]
  })

  const old = OLD()
  const qs = questionsFromPoll(old)
  check(qs.length === 2 && qs[0].title === '旧题一' && qs[1].title === '旧题二',
    '旧卷子里的题一道道搬过来')
  check(qs[1].multiple && qs[1].max_choices === 3,
    '「最多选几项」超过选项数就夹回选项数，和编辑走同一段映射')
  check(JSON.stringify(qs[0].options) === JSON.stringify(['甲', '乙']),
    '选项原样照抄，顺序不动')
  qs[0].options[0] = '改过'
  check(old.questions[0].options[0] === '甲',
    '复制出来的是深拷贝：复用后接着改，不会动到原来那场投票')
  check(questionsFromPoll({ questions: [] }).length === 1,
    '旧卷子一道题都没有时回一道空题，弹窗不会空着')

  check(JSON.stringify(formFromPoll(OLD()).questions) === JSON.stringify(questionsFromPoll(OLD())),
    '「编辑」和「复用」用的是同一段映射，没有各写一套')
  check(formFromPoll(OLD()).title === '上一场表决',
    '复用不影响编辑：formFromPoll 照旧把标题带回来（复用时只取它的 questions）')

  // 要不要先确认覆盖：空题不算填过
  check(!hasQuestionContent([blankQuestion()]), '刚打开时的空题不算填过，直接复制不打扰')
  check(hasQuestionContent([{ ...blankQuestion(), title: '敲了一半' }]),
    '题干填过就要先确认')
  check(hasQuestionContent([{ ...blankQuestion(), options: ['甲', ''] }]),
    '只填了选项也算填过')
  check(hasQuestionContent([blankQuestion(), blankQuestion()]),
    '多加了一道题也算填过')

  // ---------- 组件接线（SSR 渲不到弹窗正文，只能断源码） ----------
  check(/<div v-if="!isEdit" class="pc-reuse">/.test(pollSrc),
    '复用入口只在出卷时出现 —— 编辑时题目本来就在表单里')
  check(pollSrc.includes('从之前的投票复制题目（可选）'), '下拉框写明了这是干什么的')
  check(pollSrc.includes('只复制题目') && pollSrc.includes('标题、时间、表决范围和记名方式'),
    '旁边说清楚只搬题目，免得以为整场都沿用了')
  check(/getPolls\(\{ page: 1, page_size: 100 \}\)/.test(pollSrc),
    '拉可见的投票列表（100 是列表接口的上限）')
  check(/filter\(\(p\) => p\.question_count > 0\)/.test(pollSrc),
    '一道题都没有的投票不列出来')
  check(/await getPoll\(id\)[\s\S]{0,120}?form\.questions = questionsFromPoll\(detail\)/.test(pollSrc),
    '列表行里没有题目，选中后拉详情，只替换 questions')

  const reuseFn = (pollSrc.match(/async function reuseQuestions[\s\S]*?\n}/) || [''])[0]
  check(/hasQuestionContent\(form\.questions\)/.test(reuseFn) && /ElMessageBox\.confirm/.test(reuseFn),
    '当前题目有内容时先确认，覆盖不可撤销')
  check(!/form\.(title|description|start_at|end_at|targets|anonymous)\s*=/.test(reuseFn),
    '复用只换题目：标题、时间、范围、记名方式一律不碰')

  check(/function open\(\)[\s\S]{0,200}?fetchReusePolls\(\)/.test(pollSrc),
    '每次打开出卷弹窗都重拉一遍，刚建的那场也能马上复用')
}

console.log('\n▶ 投票能暂停：暂停不是结束')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')

  // ---------- 判定规则：真跑 utils/poll.js ----------
  const { statusLabel, statusTag, myStateText, canToggleLock, voteBlockReason } =
    await server.ssrLoadModule('/src/utils/poll.js')

  check(statusLabel('locked') === '已暂停', '第四种状态的标签是「已暂停」')
  check(statusTag('locked') === 'danger', '暂停用红色 —— 它看着像进行中，其实投不了')
  check(new Set(['pending', 'open', 'closed', 'locked'].map(statusTag)).size === 4,
    '四种状态四种颜色，互不撞：撞了暂停就和别的状态分不出来')

  // 我的状态那一列：暂停只影响「还能不能投」，改不了另两种处境
  const row = (o) => ({ has_voted: false, is_target: true, status: 'open', ...o })
  check(myStateText(row({ status: 'locked' })) === '已暂停',
    '进行中没投的人，暂停后显示「已暂停」')
  check(myStateText(row({ status: 'locked', has_voted: true })) === '已投',
    '投过的人照样显示「已投」—— 暂停不是把票退回来')
  check(myStateText(row({ status: 'locked', is_target: false })) === '无需投票',
    '范围外的人也不该被暂停影响（那两条判据排在前面）')
  check(myStateText(row({})) === '待投票', '原样的进行中还是「待投票」，没被带偏')

  check(canToggleLock(row({ status: 'open' })) && canToggleLock(row({ status: 'locked' })),
    '只有进行中和已暂停的能来回切')
  check(!canToggleLock(row({ status: 'pending' })) && !canToggleLock(row({ status: 'closed' })),
    '没开始、已结束的都不给点（菜单项是禁用的）')

  // **顺序是这一段最该钉的**：「不在范围内」排在「已暂停」前面
  check(voteBlockReason({ status: 'locked', is_target: true })
    === '投票已暂停，等发起人解锁后才能继续投', '锁定时给的是「暂停」那句')
  check(voteBlockReason({ status: 'locked', is_target: false })
    === '你不在本次投票的表决范围内，只能看题目',
    '范围外的人先看范围：跟他说「已暂停」是误导 —— 等解锁他也投不了')
  check(voteBlockReason({ status: 'closed', is_target: false }) === '投票已结束',
    '已结束排在范围前面（结束这件事对谁都一样）')
  check(voteBlockReason({ status: 'open', is_target: true }) === '现在不能投票',
    '兜底那句话说得出话')
  check(typeof voteBlockReason() === 'string' && voteBlockReason() !== '',
    '弹窗没开时传进来的是空对象，不能抛异常、也不能返回空白')

  // ---------- 列表状态列真渲染 ----------
  // 表格数据行在 SSR 下不渲染（见文件头），把 rows 灌进去才看得到那一列
  const LIST_ROW = (status) => JSON.stringify([{
    id: 1, title: '要不要聚餐', description: '', anonymous: false, status,
    question_count: 1, target_count: 3, voted_count: 1, end_at: '2026-10-13 18:00',
    closed_at: null, is_target: true, has_voted: true, results_visible: true,
    can_manage: true, can_vote: false
  }])
  const listHtml = async (status) => stripComments(
    (await renderPatchedMany('/src/views/Vote.vue',
      [['const rows = ref([])', `const rows = ref(${LIST_ROW(status)})`]])).html
  )

  const paused = await listHtml('locked')
  check(paused.includes('已暂停'), '列表状态列真渲染出「已暂停」')
  // 不记名那一枚没渲染时，页面上就这一个 el-tag，所以断颜色是准的
  check(paused.includes('el-tag--danger'),
    '暂停的标签是红的（别和进行中的绿混了，两者一眼看上去都是「还没结束」）')
  check((await listHtml('open')).includes('el-tag--success'),
    '进行中照旧是绿的 —— 暂停没有把原有那一档也染红')

  // ---------- 接线：入口、分发、轮询 ----------
  const voteSrc = src('/src/views/Vote.vue')
  check(/<el-dropdown-item command="toggleLock"/.test(voteSrc), '管理下拉里多了这一项')
  check(/:disabled="!canToggleLock\(row\)"/.test(voteSrc),
    '没开始 / 已结束的那两行是禁用的')
  check(/row\.status === 'locked' \? '恢复投票' : '暂停投票'/.test(voteSrc),
    '一个入口两用，文案跟着状态走')
  check(/command === 'toggleLock'[\s\S]{0,80}?handleToggleLock\(row\)/.test(voteSrc),
    '「暂停投票」分发到 handleToggleLock')
  check(/async function handleToggleLock[\s\S]{0,1200}?\(locking \? lockPoll : unlockPoll\)\(row\.id\)/
    .test(voteSrc), '按当前状态决定调 lock 还是 unlock（不是两个函数各写一遍）')
  check(/if \(locking\) stopPolling\(\)[\s\S]{0,80}?else startPolling\(\)/.test(voteSrc),
    '暂停时停掉轮询、恢复时开回来 —— startPolling 不在 refreshResult 里，'
    + '不自己管这一次，解锁之后票数就再也不会自动刷新了')
  check(/voteBlockReason as blockReasonOf/.test(voteSrc),
    '「不能投的原因」挪去了 utils/poll.js，页面里不再重写一份判据')
  check(/const voteBlockReason = computed\(\(\) => blockReasonOf\(votePoll\.value\)\)/.test(voteSrc),
    'computed 转调那个纯函数，模板一个字不用改')

  // 筛选项仍是三档：暂停归在「进行中」里（用户口径），不新增选项
  check((voteSrc.match(/<el-option\b/g) || []).length === 4
    && !/value="locked"/.test(voteSrc), '筛选下拉还是「全部 + 三档」，没多出「已暂停」')

  const voteApi = src('/src/api/vote.js')
  check(/export function lockPoll[\s\S]{0,200}?\/lock`[\s\S]{0,60}?method: 'post'/.test(voteApi)
    && /export function unlockPoll[\s\S]{0,200}?\/unlock`[\s\S]{0,60}?method: 'post'/.test(voteApi),
    'lockPoll / unlockPoll 都是 POST')

  // ---------- 后端 ----------
  const pollsPy = src('/../backend/app/api/polls.py')
  check(/@router\.post\(\s*"\/\{poll_id\}\/lock"/.test(pollsPy)
    && /@router\.post\(\s*"\/\{poll_id\}\/unlock"/.test(pollsPy), '后端有这两个接口')
  check(/if status == STATUS_LOCKED:[\s\S]{0,300}?return detail\(db, poll, user\.student_no, admin\)[\s\S]{0,200}?if status != STATUS_OPEN/.test(pollsPy),
    '锁定的幂等分支排在「不是进行中」前面 —— 反了的话再点一次会收到 400')
  check(voteSrc && /"投票已暂停，等发起人解锁后才能继续投"/.test(pollsPy),
    '暂停期间投票回的是「暂停」那句，不是「还没开始或已经结束」')

  const serviceSrc = src('/../backend/app/services/poll_service.py')
  check(/if now > poll\.end_at:\s*\n\s*return STATUS_CLOSED\s*\n\s*if poll\.locked_at is not None:/
    .test(serviceSrc),
    '**判断截止时间那条排在暂停之前** —— 顺序反了，被暂停过的投票到点也结束不了，'
    + '永远挂在「已暂停」上没人能收尾')

  const migrateSrc = src('/../backend/app/database_migrate.py')
  check(/\("polls", "locked_at", "DATETIME"\)/.test(migrateSrc),
    '老库启动时会补出 polls.locked_at（create_all 不给已存在的表补列）')

  const schemaSrc = src('/../backend/app/schemas/poll.py')
  check(/status: str = Field[\s\S]{0,220}?locked 已暂停/.test(schemaSrc),
    '接口文档里的 status 说明补上了第四种取值')
}

console.log('\n▶ 投票能改时间：没开始的都能改，开始了只能改截止时间')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const { canEditTimes } = await server.ssrLoadModule('/src/utils/poll.js')

  // ---------- 分档规则（真跑） ----------
  check(JSON.stringify(canEditTimes('pending')) === '{"start_at":true,"end_at":true}',
    '未开始：两个都能改（把开场时间往后推 = 推迟开场）')
  check(JSON.stringify(canEditTimes('open')) === '{"start_at":false,"end_at":true}',
    '进行中：只能改截止时间')
  check(JSON.stringify(canEditTimes('locked')) === '{"start_at":false,"end_at":true}',
    '已暂停也是只能改截止时间 —— 暂停只是不收票，不等于回到未开始')
  check(JSON.stringify(canEditTimes('closed')) === '{"start_at":false,"end_at":false}',
    '已结束：一个都不给改（closed_at 优先，改了也不生效，允许就是骗人）')
  check(canEditTimes('').end_at === true && canEditTimes().end_at === true,
    '状态取不到时按「还能改」兜底 —— 宁可让后端去拒，也别把框锁死让人干瞪眼')

  // ---------- 接线：两个 picker 各绑各的字段 ----------
  const dlgSrc = src('/src/components/PollCreateDialog.vue')
  check(!/时间不能改/.test(dlgSrc),
    '那句「时间不能改：投票进行中改截止时间…要改就删了重发」删干净了')
  check(/const timeEdit = computed\(\(\) => canEditTimes\(editingStatus\.value\)\)/.test(dlgSrc),
    '能不能改时间来自那个纯函数，组件里不另写一份判据')
  check(/editingStatus\.value = poll\.status \|\| 'pending'/.test(dlgSrc),
    'openForEdit 把这场投票的状态记下来 —— 忘了记，进行中的开始时间就会被当成未开始放开')
  check(/editingStatus\.value = 'pending'/.test(dlgSrc),
    '出卷 / 重置时状态回到 pending（不然上一次编辑留下的状态会串到下一次）')

  // 两个 disabled 绑反了会怎样：开始时间那一栏跟着 end_at 走，「进行中还能改截止时间」
  // 就变成了「还能改开始时间」，看着能编辑、提交却被后端 400
  const startPicker = dlgSrc.slice(dlgSrc.indexOf('form.start_at'), dlgSrc.indexOf('form.end_at'))
  const endPicker = dlgSrc.slice(dlgSrc.indexOf('form.end_at'), dlgSrc.indexOf('是否记名'))
  check(/:disabled="!timeEdit\.start_at"/.test(startPicker), '开始时间那个框绑的是 start_at')
  check(/:disabled="!timeEdit\.end_at"/.test(endPicker), '截止时间那个框绑的是 end_at')

  // ---------- 接线：校验与提交 ----------
  check(/if \(timeEdit\.value\.end_at\) \{[\s\S]{0,600}?投票跨度不能超过一年'/.test(dlgSrc),
    '编辑时也走同一套时间校验 —— 原先整块包在「只有出卷才填」里，编辑改的时间没人管')
  check(/if \(timeEdit\.value\.start_at\) payload\.start_at = form\.start_at/.test(dlgSrc)
    && /if \(timeEdit\.value\.end_at\) payload\.end_at = form\.end_at/.test(dlgSrc),
    '不能改的字段一个字都不往上传（灰着的框还传，读代码的人会以为它真能改）')

  // ---------- 后端 ----------
  const pollsPy = src('/../backend/app/api/polls.py')
  check(/if status == STATUS_CLOSED:\s*\n\s*raise HTTPException\(status_code=400, detail="投票已经结束，时间改不了了"\)/
    .test(pollsPy), '已结束的投票改时间直接 400')
  check(/if data\.start_at is not None and status != STATUS_PENDING:/.test(pollsPy),
    '已经开始的改不了开始时间（它已经过去了）')
  // **顺序即口径**：时间先校验、题目在中间、赋值放最后。反过来先赋值的话，「把开场提早
  // 到现在」会当场把这场变成进行中，同一份表单里刚填好的题目就莫名改不了了
  const checkTimeAt = pollsPy.indexOf('_check_time(data.start_at or poll.start_at')
  const questionsAt = pollsPy.indexOf('if data.questions is not None:')
  const assignAt = pollsPy.indexOf('poll.start_at = data.start_at')
  check(checkTimeAt > 0 && checkTimeAt < questionsAt && questionsAt < assignAt,
    '顺序：先校验时间 → 再处理题目 → 最后落库（题目那段要按改时间之前的状态判）')
  check(/poll\.end_at = data\.end_at\s*\n\s*changed\.append\("截止时间"\)/.test(pollsPy),
    '值真变了才写、才记一笔 —— 「原样回传」和「真改了」在操作日志上得分得开')

  const schemaSrc = src('/../backend/app/schemas/poll.py')
  check(/start_at: datetime \| None = Field\(/.test(schemaSrc)
    && /end_at: datetime \| None = Field\(/.test(schemaSrc),
    'PollUpdate 里多了这两个可选字段（不传 = 不改）')
  check(!/匿名与否、起止时间、表决范围这三样一个都不在这里/.test(schemaSrc),
    'schema 的说明里不再写着「起止时间不在可编辑之列」')

  const voteApi = src('/src/api/vote.js')
  check(/start_at\?: string, end_at\?: string/.test(voteApi),
    'api 的 JSDoc 里也标出了这两个字段')
}

console.log('\n▶ 投票能改记名：开始前随便改，开始了不许')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const { canEditBeforeStart } = await server.ssrLoadModule('/src/utils/poll.js')

  // ---------- 判据（真跑） ----------
  check(canEditBeforeStart('pending') === true, '未开始：能改')
  check(canEditBeforeStart('open') === false, '进行中：不许改 —— 那会儿已经有票了')
  check(canEditBeforeStart('locked') === false,
    '已暂停也不许改：暂停只是不收票，票还挂在那儿，不等于回到未开始')
  check(canEditBeforeStart('closed') === false, '已结束：更不用说了')
  check(canEditBeforeStart() === false, '状态取不到时按「不许改」兜底 —— 后端说了算')

  // ---------- 接线 ----------
  const dlgSrc = src('/src/components/PollCreateDialog.vue')
  check(/const startedLocked = computed\(\(\) => !canEditBeforeStart\(editingStatus\.value\)\)/
    .test(dlgSrc), '题目和记名共用同一个判据（都是「只有没开始才改得动」），不另写一份')
  check(!/questionsLocked/.test(dlgSrc),
    '原来那个 questionsLocked 已改名 —— 留着会让人以为它只管题目，记名就能绕过去')

  // 记名那一整块：开关绑的是状态，不是「在不在编辑」——绑 isEdit 的话，
  // 编辑一场还没开始的投票时，记名会被无端锁死（明明还能改）
  const anonAt = dlgSrc.indexOf('<el-form-item label="是否记名">')
  const anonBlock = dlgSrc.slice(anonAt, dlgSrc.indexOf('二、有权表决的人'))
  check(/:disabled="startedLocked"/.test(anonBlock), '记名开关绑的是「已经开始了没有」')
  check(!/isEdit/.test(anonBlock), '它不再绑 isEdit —— 未开始的投票编辑时记名照样能改')
  check(/投票已经开始，记名方式改不了了/.test(anonBlock),
    '灰掉时说清为什么，不然看着像坏了')
  check(/if \(!startedLocked\.value\) payload\.anonymous = form\.anonymous/.test(dlgSrc),
    '没开始的才把记名往上传')

  // ---------- 那句「表决范围不能改」按用户要求删掉了 ----------
  check(!/表决范围不能改/.test(dlgSrc), '那句「要换人请删了重发」删干净了')
  check(/共 \{\{ editTargetCount \}\} 人 · 不能改/.test(dlgSrc),
    '但范围本身还是改不了：编辑时只显示一个人数，整块名单都不渲染')

  // ---------- 后端 ----------
  const pollsPy = src('/../backend/app/api/polls.py')
  check(/if data\.anonymous is not None:\s*\n\s*if status != STATUS_PENDING:\s*\n\s*raise HTTPException\(status_code=400, detail="投票已经开始，记名方式改不了了"\)/
    .test(pollsPy), '已经开始的改记名直接 400')
  const statusAt = pollsPy.indexOf('status = poll_status(poll)')
  const anonAt2 = pollsPy.indexOf('if data.anonymous is not None:')
  const assignAt2 = pollsPy.indexOf('poll.anonymous = data.anonymous')
  check(statusAt > 0 && statusAt < anonAt2 && anonAt2 < assignAt2,
    '状态在任何改动之前算一次，记名段用的就是它（一次请求里的改动是原子的）')
  check(/if data\.anonymous != bool\(poll\.anonymous\):\s*\n\s*poll\.anonymous = data\.anonymous/
    .test(pollsPy), '值真变了才写、才记一笔（「原样回传」和「真改了」得分得开）')
  check(/题目和记名与否都只在这张卷子还没开始时能改/.test(pollsPy),
    '接口注释里的口径跟着改了（题目和记名同一条理由：改了都是「换一张票」）')

  const schemaSrc = src('/../backend/app/schemas/poll.py')
  check(/anonymous: bool \| None = Field\(/.test(schemaSrc),
    'PollUpdate 里多了 anonymous（不传 = 不改）')
  check(/记名与否只有还没开始时能改/.test(schemaSrc), 'schema 的说明跟着换成新口径')

  const voteApi = src('/src/api/vote.js')
  check(/anonymous\?: boolean/.test(voteApi), 'api 的 JSDoc 里标出了这个字段')
  check(!/记名与否还是改不了/.test(voteApi), '那句过期的话删了')
}

console.log('\n▶ 日程选人：仅班委 / 仅团员 / 仅团学成员，判据与分类统计共用一份')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const { hasPosition, isLeagueMember, COMMITTEE_FIELD, LEAGUE_OFFICER_FIELD } =
    await server.ssrLoadModule('/src/utils/roster.js')

  // ---------- 判据（真跑） ----------
  // 「有职务」的坑都在这一份名单里：字面量「无」、空串、null、字段整个没填
  const st = (id, o = {}) => ({ id, student_no: String(id), name: String(id), ...o })
  const roster = [
    st(1, { class_position: '班长' }),                        // 只是班委
    st(2, { class_position: '无', league_position: '部长' }),  // 只是团学（「无」不算职务）
    st(3, { class_position: '团支书', league_position: '副部长' }), // 两个都是
    st(4, {}),                                                // 什么都没有
    st(5, { class_position: '', league_position: null }),     // 空串 / null
    st(6, { political_status: '共青团员' }),                   // 只是团员、没有职务
    st(7, { political_status: '群众', league_position: '干事' }) // 团学但不是团员
  ]
  // 顺带排一下序：统计那边是按职务分组重排过的，比集合而不是比顺序
  const idSet = (list) => list.map((s) => s.id).sort((a, b) => a - b).join(',')

  check(idSet(roster.filter(hasPosition(COMMITTEE_FIELD))) === '1,3',
    '仅班委：填了班级职务的才是，「无」/ 空串 / null / 没填的都不进')
  check(idSet(roster.filter(hasPosition(LEAGUE_OFFICER_FIELD))) === '2,3,7',
    '仅团学成员：看的是团学会职务，与性别、政治面貌无关')
  check(roster.filter(isLeagueMember).length === 1 && isLeagueMember(roster[5]),
    '仅团员：仍用点名/出卷那份判据（这 7 个人里只有 6 号是）')
  check(hasPosition(COMMITTEE_FIELD)(null) === false
    && hasPosition('league_position')(undefined) === false,
    '判据对 null / undefined 不炸（学生的职务字段可能是空的）')

  // 统计页那两张卡必须和日程选人是同一批人 —— 谁单独重写一份判据，这条会红
  const { buildRoster } = await server.ssrLoadModule('/src/utils/statGroups.js')
  check(idSet(buildRoster('committee', roster).rows) === '1,3',
    '分类统计的班委名单与日程「仅班委」共用同一个判据')
  check(idSet(buildRoster('leagueMember', roster).rows) === '2,3,7',
    '分类统计的团学会名单与日程「仅团学成员」共用同一个判据')

  // statGroups 那份是本地的还是引来的：留着本地定义迟早和 roster 那份漂开
  const statSrc = src('/src/utils/statGroups.js')
  check(/import \{ hasPosition, isLeagueMember \} from '\.\/roster'/.test(statSrc),
    '分类统计的职务判据是从 utils/roster.js 引的')
  check(!/function hasPosition/.test(statSrc), '本地那份 hasPosition 已经删干净了')

  // ---------- 接线 ----------
  const schedSrc = src('/src/views/Schedule.vue')
  check(/import \{ COMMITTEE_FIELD, LEAGUE_OFFICER_FIELD, hasPosition, isLeagueMember \} from '@\/utils\/roster'/
    .test(schedSrc), '日程页的判据同样引自 utils/roster.js')
  check(/const studentScopes = scopePickers\(selectedStudents\)/.test(schedSrc)
    && /const importScopes = scopePickers\(importSelectedStudents\)/.test(schedSrc),
    '两个选人弹窗（新建日程、导入日程）各挂一份快捷范围')
  check(/target\.value = allStudents\.value\.filter\(predicate\)\.map\(\(s\) => s\.id\)/.test(schedSrc),
    '点一次是整份替换（选中的是学生 id，和复选框绑的是同一个东西），不是往上加')
  check(/committee: pick\(hasPosition\(COMMITTEE_FIELD\)\)/.test(schedSrc)
    && /league: pick\(isLeagueMember\)/.test(schedSrc)
    && /officer: pick\(hasPosition\(LEAGUE_OFFICER_FIELD\)\)/.test(schedSrc),
    '三枚按钮各自接的是共用判据，不是就地再比一遍字符串')

  // 三枚按钮要在两个弹窗里都渲染出来（少了哪边，那边就只能靠手点几十下）
  for (const [name, scope] of [['新建日程', 'studentScopes'], ['导入日程', 'importScopes']]) {
    for (const [label, fn] of [['仅班委', 'committee'], ['仅团员', 'league'], ['仅团学成员', 'officer']]) {
      check(schedSrc.includes(`@click="${scope}.${fn}">${label}</el-button>`),
        `${name}的选人弹窗里有「${label}」`)
    }
  }
  // 范围说的始终是「全班里哪些人」，不能被搜索框里剩下的那几个左右
  check(/function scopePickers\(target\) \{\s*\n\s*const pick = \(predicate\) => \(\) => \{\s*\n\s*target\.value = allStudents\.value\.filter/
    .test(schedSrc), '快捷范围从全班名单里取人，不受搜索框影响')

  // 学生列表接口得把两个职务字段带出来，否则上面这些判据没有数据可判
  const stuSchema = src('/../backend/app/schemas/student.py')
  check(/class_position: Optional\[str\]/.test(stuSchema) && /league_position: Optional\[str\]/.test(stuSchema),
    '学生列表返回的字段里有班级职务和团学会职务')
}

console.log('\n▶ 日程重叠：同一时段撞在一起的要并排，不再一条压住一条')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const { columnizeDay } = await server.ssrLoadModule('/src/utils/schedule.js')

  // startIdx / endIdx 是 10 分钟一格的格子下标（28px 一格）：0 = 07:00，6 = 08:00
  const ev = (id, startIdx, endIdx) => ({ id, startIdx, endIdx })
  // 按 id 排序再比：结果本身与入参同序，直接比字符串会被「谁先传进来」带着走
  const cols = (list) => {
    const laid = columnizeDay(list)
    return list
      .map((e, i) => ({ id: e.id, ...laid[i] }))
      .sort((a, b) => a.id - b.id)
      .map((x) => `${x.id}:${x.col}/${x.cols}`)
      .join(' ')
  }

  check(cols([ev(1, 0, 6)]) === '1:0/1', '一天只有一条：独占整列（宽度和从前一样）')
  check(cols([ev(1, 0, 6), ev(2, 3, 9)]) === '1:0/2 2:1/2', '两条重叠：并成两列，各占半列')
  check(cols([ev(2, 3, 9), ev(1, 0, 6)]) === '1:0/2 2:1/2',
    '换个传进来的顺序，谁在第几列不变（内部按开始时间重排）')
  check(cols([ev(1, 0, 6), ev(2, 6, 12)]) === '1:0/1 2:0/1',
    '首尾相接（8:00-9:00 接 9:00-10:00）不算重叠，各自独占整列')
  check(cols([ev(1, 0, 6), ev(2, 0, 6), ev(3, 0, 6)]) === '1:0/3 2:1/3 3:2/3',
    '三条同一时刻：并成三列')
  check(cols([ev(1, 0, 12), ev(2, 3, 6)]) === '1:0/2 2:1/2', '长会压短：照样两列')
  check(cols([ev(1, 0, 6), ev(2, 0, 6), ev(3, 8, 12), ev(4, 8, 12)]) === '1:0/2 2:1/2 3:0/2 4:1/2',
    '上午两条、下午两条：各分各的列，下午那两条不会被拖成 1/4 宽')
  // 链式重叠：1 压 2、2 压 3，可 1 和 3 自己并不重叠。断开得看「簇里最晚的结尾」，
  // 拿上一条的结尾比的话 3 会另起一簇、独占整列，画出来正好盖住 1
  check(cols([ev(1, 0, 6), ev(2, 3, 9), ev(3, 6, 12)]) === '1:0/2 2:1/2 3:0/2',
    '链式重叠的三条同一簇，第 3 条接着第 1 条腾出来的那列排 —— 只用两列，不是三列')
  check(columnizeDay([]).length === 0, '这天没有定时日程：返回空数组')
  check(cols([ev(1, 0, 6)]) === cols([ev(1, 0, 6)]), '同样的输入算两次结果一样（排序不飘）')

  // ---------- 接线 ----------
  const schedSrc = src('/src/views/Schedule.vue')
  check(/import \{ daysInRange, centerScrollLeft, columnizeDay \} from '@\/utils\/schedule'/
    .test(schedSrc), '并排的算法是从 utils/schedule.js 引的纯函数')
  check(/const laid = columnizeDay\(list\)/.test(schedSrc)
    && /const \{ col, cols \} = laid\[k\]/.test(schedSrc),
    '按天分组后真调了它，并且用的是「第几列、共几列」')
  check(/const colWidth = 100 \/ 7 \/ cols/.test(schedSrc)
    && /left: `calc\(\$\{dayIndex \* \(100 \/ 7\) \+ col \* colWidth\}%/.test(schedSrc)
    && /width: `calc\(\$\{colWidth\}% - \$\{gap \* 2\}px\)`/.test(schedSrc),
    '宽度按列数平分、位置按列号偏移')
  check(/const gap = cols === 1 \? 4 : 2/.test(schedSrc),
    '一条独占时留白还是 4px/8px —— 没有重叠的日子观感分毫不变')
  check(!/\$\{100 \/ 7\}% - 8px/.test(schedSrc),
    '原来那条「整列宽、后画的盖住先画的」的写法定死了，改不回去')

  // 窄块上那颗铃铛正好压在标题的字上，藏掉
  check(/'evt-narrow': evt\.narrow/.test(schedSrc), '并排出来的窄块带上了 evt-narrow')
  check(/\.evt-narrow \.evt-bell \{\s*\n\s*display: none;/.test(schedSrc),
    '窄块里藏着那颗铃铛（点开卡片还有提醒那一栏）')

  // ---------- 真渲染：量一下两种块实际的宽和位置 ----------
  // 灌数据的手段同上面几节（onMounted 在 SSR 里不跑，只能在 setup 里直接赋值）
  const MARKER = 'const editForm = ref(defaultForm())'
  const EVT = (o) => ({
    repeat_type: 'none', repeat_end_date: null, notify_enabled: false, notify_minutes_before: 10,
    location: '', description: '', event_type: '', ...o
  })
  const at = (id, title, start, end) => EVT({
    id, title, all_day: false, instance_date: '2026-10-06',
    start_time: `2026-10-06T${start}:00`, end_time: `2026-10-06T${end}:00`
  })
  // 08:00-09:00 和 08:30-09:30：重叠半小时
  const [班, 团] = [at(21, '班会', '08:00', '09:00'), at(22, '团学会例会', '08:30', '09:30')]
  const render2 = (evts) => renderPatched('/src/views/Schedule.vue', MARKER,
    `${MARKER}
    schedules.value = ${JSON.stringify(evts)}
    currentMonday.value = new Date(2026, 9, 5)`, { ElDialog: ElDialogStub })

  // 从渲染结果里量：left / width 都被写成 calc(百分比 + 像素)
  const pcts = (h, prop) => [...h.matchAll(new RegExp(`${prop}:calc\\(([\\d.]+)% ([+-]) (\\d+)px\\)`, 'g'))]
    .map((m) => [Number(m[1]), m[2] === '+' ? Number(m[3]) : -Number(m[3])])

  const both = await render2([班, 团])
  const bothLeft = pcts(both.html, 'left')
  const bothWidth = pcts(both.html, 'width')
  const colPct = 100 / 7
  check(bothLeft.length === 2 && bothWidth.length === 2, '重叠的两个块都真渲染出来了')
  check(new Set(bothLeft.map(([p]) => p)).size === 2,
    '两个块的横向位置不同 —— 真是并排，不是一上一下压着')
  check(bothWidth.every(([p]) => Math.abs(p - colPct / 2) < 1e-9),
    `每个块占整列的一半（${colPct.toFixed(2)}% → ${(colPct / 2).toFixed(2)}%）`)
  check(bothLeft.every(([, px]) => px === 2) && bothWidth.every(([, px]) => px === -4),
    '并排时留白收成 2px/4px（原来是 4px/8px），两条之间才不会空出大半条缝')

  // 对照：同样这一天只留一条，得和从前一模一样
  const alone = await render2([班])
  const aloneLeft = pcts(alone.html, 'left')
  const aloneWidth = pcts(alone.html, 'width')
  check(aloneLeft.length === 1 && Math.abs(aloneWidth[0][0] - colPct) < 1e-9,
    '没有重叠的日子照样占满整列 —— 宽度、位置分毫未动')
  check(aloneLeft[0][1] === 4 && aloneWidth[0][1] === -8,
    '没有重叠时留白仍是原来的 4px/8px')
  check(!/evt-narrow/.test(alone.html) && /evt-narrow/.test(both.html),
    '只有并排出来的块才带 evt-narrow')
}

console.log('\n▶ 结果页的「按得票排序」：只是换个看的顺序，票数一分不动')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const { tallyOrder } = await server.ssrLoadModule('/src/utils/poll.js')

  const q = { options: ['甲', '乙', '丙', '丁'], tallies: [3, 11, 5, 1] }
  check(tallyOrder(q, false).join('') === '0123', '开关没开：还是原来的选项顺序（A/B/C/D 原样）')
  check(tallyOrder(q, true).join('') === '1203', '开了就按票数从多到少：乙(11) 丙(5) 甲(3) 丁(1)')
  check(tallyOrder(q, true).map((j) => q.options[j]).join('') === '乙丙甲丁',
    '排的是行不是选项本身：下标仍指着原来那个选项')

  // 同票必须稳住。结果页轮到新票会重渲染（5 秒一次），同票的两项来回换的话，
  // 每次刷新位置都在跳，看着像自己看错了
  check(tallyOrder({ options: ['甲', '乙', '丙'], tallies: [2, 5, 2] }, true).join('') === '102',
    '同票的按原顺序（甲和丙都是 2 票，甲还排在丙前面）')
  check(tallyOrder({ options: ['甲', '乙'], tallies: [0, 0] }, true).join('') === '01', '全是 0 票也不乱动')
  check(tallyOrder({ options: ['甲', '乙'] }, true).join('') === '01', 'tallies 整个缺了也不炸')
  check(tallyOrder({}, true).length === 0 && tallyOrder(null, false).length === 0,
    '没有题目 / 没有选项：返回空数组')

  // ---------- 接线 ----------
  const voteSrc = src('/src/views/Vote.vue')
  check(/v-for="j in tallyOrder\(q, tallySorted\)"/.test(voteSrc),
    '结果页的选项行照 tallyOrder 给的次序渲染')
  check(/class="vt-opt-letter">\{\{ letters\[j\] \}\}\.<\/span> \{\{ q\.options\[j\] \}\}/.test(voteSrc),
    '字母和选项名按同一个下标取 —— 排完序每一行还是原来那个选项')
  check(/:percentage="percentOf\(q, j\)"/.test(voteSrc) && /q\.tallies\?\.\[j\] \?\? 0/.test(voteSrc),
    '进度条和票数也仍按原下标算，排序没顺手把它们也换一遍')
  check(/@click="tallySorted = !tallySorted"/.test(voteSrc), '那枚按钮翻的就是这个开关')
  check(/\{\{ tallySorted \? '按选项顺序' : '按得票排序' \}\}/.test(voteSrc),
    '按钮上的字跟着当前状态变，按下去会变成什么一看就知道')
  check(/const tallySorted = ref\(false\)/.test(voteSrc), '开关默认关着，进页面不会无端重排')

  // ---------- 真渲染：两行的先后，以及字母跟不跟着走 ----------
  const RESULT = {
    id: 1, title: '入党推优选举（系统测试）', status: 'closed', anonymous: false,
    results_visible: true, can_manage: false, voted_count: 20, target_count: 20,
    start_at: '2026-10-01T08:00:00', end_at: '2026-10-02T08:00:00',
    questions: [{
      id: 1, title: '选谁', multiple: false,
      options: ['甲', '乙', '丙'], tallies: [3, 11, 5]
    }]
  }
  const renderResult = (sorted) => renderPatchedMany('/src/views/Vote.vue', [
    ['const resultVisible = ref(false)', 'const resultVisible = ref(true)'],
    ['const resultPoll = ref({})', `const resultPoll = ref(${JSON.stringify(RESULT)})`],
    ['const tallySorted = ref(false)', `const tallySorted = ref(${sorted})`]
  ], { ElDialog: ElDialogStub })
  // SSR 会在插值两边插注释记号（<!--[-->…<!--]-->），不剥掉就断不到那几个字；
  // 名字列里还套着字母格那一层（.vt-opt-letter），所以两头都要取上再剥标签。
  // 这条也顺带钉住了结构：字母格要是没了（退回「字母和名字一条行内文本」），
  // 这里一条都匹配不上，下面几条会当场全红。
  const rows = (h) => [
    ...h.matchAll(
      /class="vt-opt-name"[^>]*>\s*(<span class="vt-opt-letter"[^>]*>[\s\S]*?<\/span>)([\s\S]*?)<\/span>/g
    )
  ].map((m) =>
    (m[1] + m[2]).replace(/<!--[\s\S]*?-->/g, '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim()
  )

  const plain = rows((await renderResult(false)).html)
  check(plain.join(' | ') === 'A. 甲 | B. 乙 | C. 丙', '没开排序：A/B/C 按卷子上的顺序排')
  const sorted = rows((await renderResult(true)).html)
  check(sorted.join(' | ') === 'B. 乙 | C. 丙 | A. 甲',
    '开了排序：乙(11) 丙(5) 甲(3)，而且字母跟着选项走 —— 乙排到第一行也还叫 B')
  check((await renderResult(false)).warns.every((w) => !/Failed to resolve/.test(w)),
    '没有未解析的组件/指令')
}

console.log('\n▶ 选项字母单占一格：名字的起点才对得齐')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const voteSrc = src('/src/views/Vote.vue')

  // 字母和名字本来是**同一条行内文本**（「A. 名字」）。字母是比例字形：「I.」两三个像素宽、
  // 「M.」十几个 —— 于是每行名字的起点跟着这行的字母有多宽左右跳。截图里那十六行量过：
  // 全 0 票、进度条左端都钉在同一个 x 上，唯一参差的就是这一列名字。
  const CELL = /class="vt-opt-letter">\{\{ letters\[j\] \}\}\.<\/span> \{/g
  check((voteSrc.match(CELL) || []).length === 4,
    '四处都套上了字母格：结果页、单选、多选、只读回显（少拿一处，那处就还是歪的）')
  check(!/\{\{ letters\[j\] \}\}\. \{\{/.test(voteSrc),
    '没有漏网的：字母直接拼进文本的老写法一处都不剩')

  check(/\.vt-opt-letter\s*\{[^}]*display: inline-block/.test(voteSrc)
    && /\.vt-opt-letter\s*\{[^}]*min-width: 1\.5em/.test(voteSrc),
    '这一格是行内块 + 钉住宽度 —— 只包一层不钉宽度，宽度仍跟着字母走，等于没改')
  // 用 min-width 而不是 width：万一某套字体把「M.」撑得比这一格还宽，写死宽度会让它压到名字上
  check(!/\.vt-opt-letter\s*\{[^}]*[^-]width: /.test(voteSrc),
    '钉的是下限不是死宽度')
  check(/class="pc-opt-label"/.test(src('/src/components/PollCreateDialog.vue')),
    '和出卷弹窗早就有的定宽写法一个路子，不是另发明一种')

  // ---------- 真渲染：结果页和作答弹窗里字母都真进了那一格 ----------
  const RESULT = {
    id: 1, title: '选谁', status: 'closed', anonymous: false, can_vote: false,
    results_visible: true, can_manage: false, voted_count: 3, target_count: 3,
    questions: [{ id: 1, title: '选谁', multiple: false, options: ['甲', '乙'], tallies: [2, 1] }]
  }
  const resultsHtml = stripComments((await renderPatchedMany('/src/views/Vote.vue', [
    ['const resultVisible = ref(false)', 'const resultVisible = ref(true)'],
    ['const resultPoll = ref({})', `const resultPoll = ref(${JSON.stringify(RESULT)})`]
  ], { ElDialog: ElDialogStub })).html)
  check(/class="vt-opt-name"[^>]*>\s*<span class="vt-opt-letter"[^>]*>A\.<\/span> 甲/.test(resultsHtml),
    '结果页里字母归字母格、名字跟在后面（名字的起点由这一格决定，不再由字母的宽窄决定）')

  const VOTE = {
    id: 1, title: '要不要聚餐', status: 'open', anonymous: false, can_vote: true,
    has_voted: false, results_visible: false, can_manage: false, is_target: true,
    voted_count: 0, target_count: 3,
    questions: [
      { id: 1, title: '单选', multiple: false, max_choices: 1, options: ['甲', '乙'] },
      { id: 2, title: '多选', multiple: true, max_choices: 2, options: ['丙', '丁'] }
    ]
  }
  const voteHtml = stripComments((await renderPatchedMany('/src/views/Vote.vue', [
    ['const voteVisible = ref(false)', 'const voteVisible = ref(true)'],
    ['const votePoll = ref({})', `const votePoll = ref(${JSON.stringify(VOTE)})`]
  ], { ElDialog: ElDialogStub })).html)
  const cells = [...voteHtml.matchAll(/class="vt-opt-letter"[^>]*>([\s\S]*?)<\/span>/g)]
    .map((m) => m[1].replace(/<!--[\s\S]*?-->/g, '').trim())
  check(cells.join(' ') === 'A. B. A. B.',
    '作答弹窗里四个字母各占一格（单选两个、多选两个；每道题各自从 A 数起）')
  check(/vt-opt-letter"[^>]*>B\.<\/span> 丁/.test(voteHtml),
    '名字就跟在那一格后面（单选和多选共用这条写法）—— 学生作答时看见的也是齐的')
}

console.log('\n▶ 审核页：受理环节 —— 没受理审批按钮是灰的，受理过才敢批')
{
  const REVIEW = '/src/views/Review.vue'
  const src = readFileSync(`${ROOT}${REVIEW}`, 'utf8')

  // 筛选器就四档（待处理 / 待补正 / 已办结 / 全部），默认停在「全部」—— 进来先看见
  // 所有的，要收窄再自己点。待受理与已受理合在「待处理」里（都要同一个人动手），
  // 已通过和已驳回合在「已办结」里（谁都不用再动手）：具体是哪个状态看行上的 tag，
  // 不靠筛选按钮一个个摆出来（原来五个状态各占一个，一排按钮占掉半条工具栏）
  for (const v of ['leaveStatus', 'evPassStatus', 'certificateStatus']) {
    check(new RegExp(`const ${v} = ref\\(''\\)`).test(src), `${v} 默认停在「全部」档`)
  }
  // 逐块断，不整个文件数按钮：「已通过」「已驳回」这几个词在信息修改、导出申请那几个
  // tab 里也有（那些办件没有受理环节，该留的留着），整个文件数会数到别人身上
  for (const v of ['leaveStatus', 'evPassStatus', 'certificateStatus']) {
    const i = src.indexOf(`v-model="${v}"`)
    const block = src.slice(i, src.indexOf('</el-radio-group>', i))
    check(block.includes('value="open"') && block.includes('value="correcting"') &&
      block.includes('value="closed"') && block.includes('value=""'),
      `${v}：就四档 —— 待处理 / 待补正 / 已办结 / 全部`)
    check(!/value="(pending|accepted|approved|rejected)"/.test(block),
      `${v}：五个状态不再各占一个按钮（收进状态 tag 和这两档合称里了）`)
  }

  // 打开材料即受理：不 await（别让网络拖慢预览）、出错静默（管理员只是想看眼材料，
  // 不该因为已被别人审掉就弹红条）。显式的「受理」按钮是兜底
  const auto = src.match(
    /if \(userStore\.isAdmin\) accept\w+\(row\.id\)\.then\(fetch\w+List\)\.catch\(\(\) => \{\}\)/g) || []
  check(auto.length === 3, '三个预览函数各顺手受理一次，且不阻塞、出错静默')
  // 受理、撤回受理、退回补正这三件套收在一个工厂里：三个办件的动作逐字一样，
  // 抄三遍就是三次各写各的漂移机会（各自那个接口按办件传进去）
  check(src.includes('function makeReviewActions({ accept, unaccept, correct, reload })') &&
    (src.match(/= makeReviewActions\(\{/g) || []).length === 3,
    '受理三件套只有一份实现，三个办件各自调一次')
  for (const fn of ['accept', 'unaccept', 'correct']) {
    check((src.match(new RegExp(`\\b${fn}: ${fn}\\w+`, 'g')) || []).length === 3,
      `三个办件各自接下自己的 ${fn} 接口（接错一家就是给请假调证明的接口）`)
  }
  check((src.match(/correct\(row\.id, value\.trim\(\)\)/g) || []).length === 1 &&
    src.includes('请写清楚要补什么'),
    '退回补正带着理由提交（理由要通知给申请人，空的不让交）')

  // ---------- 真渲染：同一行在四种状态下长什么样 ----------
  const who = (role) => `const userStore = useUserStore()
  userStore.info = { student_no: '2024000001', name: '甲', role: '${role}', is_external: false }`
  // 表桩对每行跑 default 插槽，所以行里那几个按钮能真断到
  const buttons = (html) =>
    [...stripComments(html).matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map((m) => m[0])
  const label = (b) => b.replace(/<[^>]+>/g, '').trim()
  // ⚠️ 别拿 /disabled/ 直接扫整个标签：Element 渲出来的按钮里还有 class 的
  // is-disabled 和 aria-disabled="false"，两处都含「disabled」六个字母，
  // 于是「灰的」永远为真、「亮的」永远为假。只认那个真的布尔属性
  const isDisabled = (b) => /<button[^>]*\sdisabled(?=[\s>=])/.test(b)

  const WORKFLOWS = [
    {
      name: '请假', tab: 'leave', listRef: 'leaveList',
      row: (o) => ({
        id: 1, student_name: '丙', student_no: '2024000003', leave_type: '事假',
        start_at: '2026-10-15 08:00', end_at: '2026-10-17 18:00', reason: '家里有事',
        status: 'pending', has_advisor_sign: false, advisor_sign_name: '',
        advisor_opinion: '', correction_reason: '', created_at: '2026-10-12 09:00', ...o
      })
    },
    {
      name: '电动车', tab: 'evpass', listRef: 'evPassList',
      row: (o) => ({
        id: 1, student_name: '戊', student_no: '2024000005', brand: '雅迪',
        plate_number: '京A1234567', status: 'pending', sign_name: '', has_sign: false,
        correction_reason: '', created_at: '2026-10-12 09:00', ...o
      })
    },
    {
      name: '证明', tab: 'certificate', listRef: 'certificateList',
      row: (o) => ({
        id: 1, student_name: '己', student_no: '2024000006', title: '在读证明',
        recipient: '某某公司', status: 'pending', attachments: [{ name: 'basis.png' }],
        correction_reason: '', created_at: '2026-10-12 09:00', ...o
      })
    }
  ]

  /** 把一行灌进对应 tab 的列表，渲一遍，回那一行里的按钮与整页文字 */
  const renderRow = async (w, role, status) => {
    const { html } = await renderPatchedMany(REVIEW, [
      ['const userStore = useUserStore()', who(role)],
      ["const activeTab = ref(TABS.includes(route.query.tab) ? route.query.tab : 'change')",
        `const activeTab = ref('${w.tab}')`],
      [`const ${w.listRef} = ref([])`,
        `const ${w.listRef} = ref(${JSON.stringify([w.row({ status })])})`]
    ])
    const bs = buttons(html)
    return { text: stripComments(html), buttons: bs, labels: bs.map(label) }
  }

  for (const w of WORKFLOWS) {
    // 待受理：能受理，但审批按钮亮着点不动 —— 逼着人先看过材料
    const pending = await renderRow(w, 'admin', 'pending')
    check(pending.labels.includes('受理'), `${w.name}：待受理的单子有「受理」按钮`)
    check(!pending.labels.includes('撤回受理'), `${w.name}：还没受理就没有「撤回受理」`)
    const pass = pending.buttons.find((b) => label(b) === '通过')
    const reject = pending.buttons.find((b) => label(b) === '驳回')
    check(pass && isDisabled(pass) && reject && isDisabled(reject),
      `${w.name}：待受理时「通过」「驳回」是灰的`)
    check(pending.text.includes('需先受理'), `${w.name}：旁边写明了为什么点不动`)
    check(pending.text.includes('待受理'), `${w.name}：状态 tag 写着「待受理」`)

    // 已受理：按钮亮起来，并给出「撤回受理」「退回补正」两条回头路
    const accepted = await renderRow(w, 'admin', 'accepted')
    check(accepted.labels.includes('撤回受理') && accepted.labels.includes('退回补正'),
      `${w.name}：已受理的给了「撤回受理」和「退回补正」（点错了能回头）`)
    check(!accepted.labels.includes('受理'), `${w.name}：受理过的没有「受理」按钮`)
    const apass = accepted.buttons.find((b) => label(b) === '通过')
    check(apass && !isDisabled(apass), `${w.name}：已受理之后「通过」才点得动`)
    check(accepted.text.includes('已受理'), `${w.name}：状态 tag 写着「已受理」`)

    // 待补正：球在申请人那边，管理员这里不摆审批也不摆受理
    const correcting = await renderRow(w, 'admin', 'correcting')
    check(!correcting.labels.includes('通过') && !correcting.labels.includes('驳回') &&
      !correcting.labels.includes('受理'),
      `${w.name}：待补正时不摆审批和受理按钮（这时候在等申请人补齐材料）`)
    check(correcting.text.includes('待补正'), `${w.name}：状态 tag 写着「待补正」`)

    // 班委：列表看得到，受理和审批都轮不到他
    const asCm = await renderRow(w, 'committee', 'accepted')
    check(!asCm.labels.includes('受理') && !asCm.labels.includes('撤回受理') &&
      !asCm.labels.includes('通过'),
      `${w.name}：班委的列表里没有受理和审批按钮`)
  }
}

console.log('\n▶ 学生端三页：待受理/待补正能改，撤只有待受理能撤')
{
  // 三页的「我的记录」那个 tab 名和列表变量各不一样，其余断言逐字一样
  const PAGES = [
    {
      path: '/src/views/LeaveApply.vue', name: '请假',
      tabPatches: (rows) => [
        ["const activeTab = ref('apply')", "const activeTab = ref('history')"],
        ['const leaves = ref([])', `const leaves = ref(${JSON.stringify(rows)})`]
      ],
      row: (o) => ({
        id: 1, leave_type: '事假', start_at: '2026-10-15 08:00', end_at: '2026-10-17 18:00',
        reason: '家里有事', status: 'pending', reviewer_name: '', reject_reason: '',
        advisor_opinion: '', correction_reason: '', created_at: '2026-10-12 09:00', ...o
      })
    },
    {
      path: '/src/views/EvPass.vue', name: '电动车',
      tabPatches: (rows) => [
        ["const activeTab = ref('apply')", "const activeTab = ref('mine')"],
        ['const list = ref([])', `const list = ref(${JSON.stringify(rows)})`]
      ],
      row: (o) => ({
        id: 1, brand: '雅迪', plate_number: '京A1234567', status: 'pending',
        sign_name: '', reject_reason: '', correction_reason: '',
        created_at: '2026-10-12 09:00', ...o
      })
    },
    {
      path: '/src/views/Certificate.vue', name: '证明',
      tabPatches: (rows) => [
        ["const activeTab = ref('apply')", "const activeTab = ref('mine')"],
        ['const list = ref([])', `const list = ref(${JSON.stringify(rows)})`]
      ],
      row: (o) => ({
        id: 1, title: '在读证明', recipient: '某某公司', status: 'pending',
        attachments: [], result_original_name: '', reject_reason: '',
        correction_reason: '', created_at: '2026-10-12 09:00', ...o
      })
    }
  ]

  const buttons = (html) =>
    [...stripComments(html).matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)]
      .map((m) => m[1].replace(/<[^>]+>/g, '').trim())

  for (const p of PAGES) {
    const show = async (row) => {
      const { html } = await renderPatchedMany(p.path, p.tabPatches([row]))
      return { text: stripComments(html), labels: buttons(html) }
    }

    const pending = await show(p.row({}))
    check(pending.labels.includes('修改') && pending.labels.includes('撤销'),
      `${p.name}：待受理的单子能改也能撤`)
    check(pending.text.includes('待受理'), `${p.name}：状态 tag 写着「待受理」`)

    const accepted = await show(p.row({ status: 'accepted' }))
    check(!accepted.labels.includes('修改') && !accepted.labels.includes('撤销'),
      `${p.name}：受理之后改不了也撤不了（要改得先找管理员撤回受理）`)
    check(accepted.text.includes('已受理'), `${p.name}：状态 tag 写着「已受理」`)

    const correcting = await show(p.row({ status: 'correcting' }))
    check(correcting.labels.includes('修改') && !correcting.labels.includes('撤销'),
      `${p.name}：待补正能改，但撤不掉（撤掉就没人知道这条要补什么了）`)
    check(correcting.text.includes('待补正'), `${p.name}：状态 tag 写着「待补正」`)

    const approved = await show(p.row({ status: 'approved', reviewer_name: '甲' }))
    check(!approved.labels.includes('修改') && !approved.labels.includes('撤销'),
      `${p.name}：办结的单子改不了也撤不了`)

    // 管理员撤销后：状态变「已撤销」，和学生自己撤（记录删掉）不是一回事 ——
    // 这条记录还在，但改不了、下不了、也不再显示当初的驳回/补正说明
    const revoked = await show(p.row({ status: 'revoked', reviewer_name: '甲' }))
    check(revoked.text.includes('已撤销'), `${p.name}：状态 tag 写着「已撤销」`)
    check(!revoked.labels.includes('修改') && !revoked.labels.includes('撤销'),
      `${p.name}：已撤销的单子改不了（撤销是终态）`)
    check(!revoked.text.includes('驳回原因') && !revoked.text.includes('补正说明'),
      `${p.name}：已撤销的不再展示当初的审核说明`)
  }

  // 退回补正的理由是让申请人照办的话，得看得见才补得对。请假那页有一列「审核意见」
  // 直接摊开写；另两页挂在「补正说明」的悬浮提示上（提示内容是 prop，SSR 渲不出来，
  // 那两页只能断源码）
  const APPLY = '/src/views/LeaveApply.vue'
  const leaveRow = (o) => ({
    id: 1, leave_type: '事假', start_at: '2026-10-15 08:00', end_at: '2026-10-17 18:00',
    reason: '家里有事', status: 'correcting', reviewer_name: '', reject_reason: '',
    advisor_opinion: '', created_at: '2026-10-12 09:00', ...o
  })
  const history = (r) => [
    ["const activeTab = ref('apply')", "const activeTab = ref('history')"],
    ['const leaves = ref([])', `const leaves = ref(${JSON.stringify([r])})`]
  ]
  const { html: correcting } = await renderPatchedMany(APPLY,
    history(leaveRow({ correction_reason: '照片反光看不清车牌' })))
  check(stripComments(correcting).includes('需补正：照片反光看不清车牌'),
    '请假：退回补正的理由跟状态一起看得见')

  // ⚠️ 这条是修的一个自相矛盾：tag 写着「已受理」，旁边那列却还写「待审核」
  const { html: accepted } = await renderPatchedMany(APPLY, history(leaveRow({ status: 'accepted' })))
  check(stripComments(accepted).includes('已受理，等待审批'),
    '请假：已受理那一行的「审核意见」列不写「待审核」（同一行两句话得对得上）')

  for (const p of ['/src/views/EvPass.vue', '/src/views/Certificate.vue']) {
    const src = readFileSync(`${ROOT}${p}`, 'utf8')
    check(/:content="row\.correction_reason"/.test(src),
      `${p.slice(p.lastIndexOf('/') + 1)}：补正理由挂在悬浮提示上`)
    check(src.includes('补正说明'), `${p.slice(p.lastIndexOf('/') + 1)}：那一处有可点的说明`)
  }
}

console.log('\n▶ 待办口径：红点、删学生拦截、状态名与状态机同源')
{
  const be = (p) => readFileSync(`${ROOT}/../backend/app/${p}`, 'utf8')

  // 五个状态字面量散在三个 api、badges、students、workspace 里各写一遍的话，写错
  // 一处不报错、只会静默计数为 0 —— 所以口径统一由这一个模块出
  const flow = be('services/review_flow.py')
  check(/ADMIN_TODO = \(STATUS_PENDING, STATUS_ACCEPTED\)/.test(flow),
    '待办 = 待受理 + 已受理')
  check(/UNFINISHED = \(STATUS_PENDING, STATUS_ACCEPTED, STATUS_CORRECTING\)/.test(flow),
    '未办结比待办多一个待补正（那种单子在等申请人，管理端不催它）')

  const badges = be('api/badges.py')
  check((badges.match(/_count\(db, \w+, ADMIN_TODO\)/g) || []).length === 3,
    '三个办件的红点数的是 ADMIN_TODO（已受理未审批的也得进红点）')
  check(!/_count\(db, (LeaveRequest|EvPassRequest|CertificateRequest), "pending"\)/.test(badges),
    '没有哪个办件还在数裸 "pending" —— 那样写的红点会在受理那一刻凭空少一个')

  const students = be('api/students.py')
  const blockers = students.slice(students.indexOf('checks = ('),
    students.indexOf('for model, belongs, label, statuses'))
  const blocks = blockers.split(/\n(?=        \()/).map((s) => s.trim())
  const blockOf = (model) => blocks.find((s) => s.includes(`${model},`)) || ''
  for (const m of ['LeaveRequest', 'CertificateRequest', 'EvPassRequest']) {
    check(blockOf(m).endsWith('UNFINISHED),'),
      `删学生拦得住没办结的${m}（已受理、待补正的都算没办结，不然那些待办没人收尾）`)
  }
  // 信息修改和签字查看没有受理环节，只认 pending —— 整组套 UNFINISHED 会让这两类
  // 永远删不掉学生
  for (const m of ['ChangeRequest', 'SignPhotoRequest']) {
    check(blockOf(m).includes('(STATUS_PENDING,)'), `${m} 没有受理环节，仍只认 pending`)
  }

  const ws = be('api/workspace.py')
  for (const label of ['待受理', '已受理', '待补正']) {
    check((ws.match(new RegExp(`\\("${label}", "\\w+"\\)`, 'g')) || []).length === 3,
      `「我提交的」里三个办件都认得「${label}」（漏一档就把英文状态名直接显示给学生）`)
  }
}

console.log('\n▶ 材料预览小窗：慢网络下要看得见在加载，关了就别再传')
{
  const src = readFileSync(`${ROOT}/src/components/FileViewer.vue`, 'utf8')

  // 图片分支原来既不显示进度、也没有遮罩：点开请假证明材料是一整片空白，
  // 而这些材料常有几 MB 的扫描件，慢网络下要等好一会儿，看着像点坏了
  // 下载按钮上的百分比：progress 是 { loaded, total }，直接拼进模板会印成
  // 「[object Object]%」。慢网络下用户看到的就是这一串乱码
  check(src.includes('const downloadPercent = computed'),
    '下载按钮的百分比从 { loaded, total } 算出来')
  check(!/progress \+ '%'/.test(src),
    '按钮上不再直接把 progress 对象拼成 [object Object]%')

  check(src.includes('v-loading="loadingImage"'), '图片分支挂了加载遮罩')
  check(/:element-loading-text="loadingText"/.test(src.slice(0, src.indexOf('<!-- PDF -->'))),
    '遮罩上带进度文字（和 PDF 分支共用同一句）')

  const loadImage = src.slice(src.indexOf('async function loadImage()'))
  const body = loadImage.slice(0, loadImage.indexOf('\n}'))
  check(body.includes('progress.value = { loaded, total }'),
    '取图片时报进度 —— 不报的话遮罩上只能写「正在加载…」')
  check(body.includes('inFlight.signal'), '把取消信号递给请求')
  check(body.includes('isCanceled(e)'), '关窗掐掉的请求不弹「加载失败」')

  // 关掉小窗时在传的那份要停：不掐的话它会一直占着带宽传完没人要的字节，
  // 用户重开一次就是两份在下
  check(/if \(!val\) \{[\s\S]{0,160}abortInFlight\(\)/.test(src), '关窗就把还在传的那份停掉')

  // PDF 那条路同样处理（大 PDF 比图片更占带宽）
  const loadPdf = src.slice(src.indexOf('async function loadPdf()'))
  check(loadPdf.slice(0, loadPdf.indexOf('\n}')).includes('inFlight.signal'), 'PDF 也递了取消信号')
}

console.log('\n▶ 材料预览小窗：图片能转正（手机拍的证明经常是躺着的）')
{
  const src = readFileSync(`${ROOT}/src/components/FileViewer.vue`, 'utf8')

  check(
    src.includes('@click="rotateLeft"') && src.includes('@click="rotateRight"'),
    '图片工具条有向左 / 向右旋转两个按钮'
  )
  check(
    /rotate\.value \+ 270\) % 360/.test(src) && /rotate\.value \+ 90\) % 360/.test(src),
    '每次转 90°，角度归一化到 0~359'
  )
  check(src.includes('rotate(${rotate}deg)'), '旋转真的应用在图片的 transform 上')
  check(/watch\([\s\S]{0,400}rotate\.value = 0/.test(src), '每次打开都从正向开始')
  // PDF 不跟着转：那两个按钮只写在图片分支里，PDF 分支没有
  const pdfBranch = src.slice(src.indexOf('<!-- PDF -->'), src.indexOf('<!-- 不支持的类型 -->'))
  check(!pdfBranch.includes('rotateLeft'), 'PDF 工具条没有旋转按钮')

  // 真渲染一遍图片分支。SSR 下 el-dialog 正文不渲染，得套上会渲染的桩
  const { html } = await render(
    '/src/components/FileViewer.vue',
    { ElDialog: ElDialogStub },
    { modelValue: true, fileName: '证明.jpg', fileUrl: '/x.jpg' }
  )
  check(html.includes('向左旋转'), '向左旋转按钮带说明（图标按钮没有文字）')
  check(html.includes('向右旋转'), '向右旋转按钮带说明')
}

console.log('\n▶ 弱网首屏：图表库按需且不挡首页，图标不整包进产物')
{
  const iconNames = new Set(Object.keys(Icons))

  /** 遍历 src 下每个 .vue/.js（main.js 除外），把源码交给回调 */
  function eachSource(fn) {
    ;(function walk(dir) {
      for (const e of readdirSync(dir, { withFileTypes: true })) {
        const p = `${dir}/${e.name}`
        if (e.isDirectory()) { walk(p); continue }
        if (!/\.(vue|js)$/.test(e.name) || p.endsWith('/src/main.js')) continue
        fn(p, readFileSync(p, 'utf8'))
      }
    })(`${ROOT}/src`)
  }

  // ---- 图表库 ----
  // 全站体积最大的一件就是它：裸 `import * as echarts from 'echarts'` 会把整个图表库
  // 打进产物（实测 1.04MB / gzip 343KB）。首页是落地页、还非要画两张饼图，于是每个访客、
  // 每台新设备头一屏都得先下完这一份。这一节盯的就是「别再引全量」「首屏别等它」。
  const chartSrc = readFileSync(`${ROOT}/src/utils/chart.js`, 'utf8')
  check(/from 'echarts\/core'/.test(chartSrc), '按需入口用 echarts/core，不是全量 echarts')

  // 用到的图表类型和交互组件都得在 use() 里注册。**漏一个不会报错** ——
  // echarts.init 照常成功，只是那张图一片空白，属于最难查的那种
  const useBlock = chartSrc.slice(chartSrc.indexOf('echarts.use(['), chartSrc.indexOf('])'))
  const modules = ['PieChart', 'BarChart', 'TooltipComponent', 'LegendComponent', 'GridComponent', 'CanvasRenderer']
  check(modules.every((m) => useBlock.includes(m)),
    `图表类型与交互组件都注册了（缺：${modules.filter((m) => !useBlock.includes(m)).join(', ') || '无'}）`)

  const dashSrc = readFileSync(`${ROOT}/src/views/Dashboard.vue`, 'utf8')
  check(/await import\('@\/utils\/chart'\)/.test(dashSrc),
    '首页动态引入图表库 —— 人数、生日条幅、最新通知不必等它')
  check(!/^\s*import .*'echarts/m.test(dashSrc), '首页顶部没有静态引图表库（那样整页都得等它下完）')

  // 分类统计页是懒加载路由，静态引入没有代价；但也得从同一个按需模块拿
  const statSrc = readFileSync(`${ROOT}/src/views/Statistics.vue`, 'utf8')
  check(/^import echarts from '@\/utils\/chart'$/m.test(statSrc), '分类统计页也从 utils/chart 拿图表库')

  // 兜底：除了 utils/chart.js 自己，全站不许再有第二处直接引 echarts ——
  // 绕过去一处，上面那些按需注册就全白做了，而且体积要到发版看产物才发现
  const bypass = []
  eachSource((p, s) => {
    if (p.endsWith('/src/utils/chart.js')) return
    if (/from\s+'echarts(\/|')/.test(s)) bypass.push(p.replace(ROOT, ''))
  })
  check(bypass.length === 0, `没有别处绕过 utils/chart 直接引 echarts（现在：${bypass.join(', ') || '无'}）`)

  // ---- 图标 ----
  // 原来写的是 `import * as ElementPlusIconsVue` + 循环注册，那会让打包器的 tree-shaking
  // 完全失效：图标包 293 个图标整包进首屏，而全站真正用到的只有六十来个。
  const mainSrc = readFileSync(`${ROOT}/src/main.js`, 'utf8')
  // 锚在行首：main.js 的注释里也写着「原来写的是 import * as ...」，不锚的话自己把自己判红
  check(!/^import \* as/m.test(mainSrc), '图标不再整包 import *（那会废掉 tree-shaking）')
  check(/} from '@element-plus\/icons-vue'/.test(mainSrc), '图标改为具名引入')

  // 注册表就是 main.js 里那份 ICONS 对象。漏登记**不会报错**，Vue 只在控制台留一句
  // "Failed to resolve component"，页面上那个位置就是空的 —— 图标本来就小，很难发现。
  // 所以反向扫一遍全站：用到哪些图标名，必须都在清单里。
  const at = mainSrc.indexOf('const ICONS = {')
  const registry = new Set(
    [...mainSrc.slice(at, mainSrc.indexOf('}', at)).matchAll(/[A-Z][A-Za-z0-9]*/g)].map((m) => m[0])
  )
  check(registry.size >= 40, `main.js 里登记着 ${registry.size} 个图标`)

  // 两种写法都要覆盖：模板里的 <el-icon><Bell /></el-icon> 与 :icon="Bell"，
  // 以及 App.vue 侧边菜单、首页快捷入口那种 `icon: 'Bell'` 字符串（最后走 <component :is>）。
  // 串里的假阳性（'Service' 之类）靠 iconNames 过滤掉
  const referenced = new Map()
  eachSource((p, s) => {
    for (const re of [/<([A-Z][A-Za-z0-9]*)\s*\/>/g, /:icon="([A-Z][A-Za-z0-9]*)"/g, /'([A-Z][A-Za-z0-9]*)'/g]) {
      for (const m of s.matchAll(re)) if (iconNames.has(m[1])) referenced.set(m[1], p.replace(ROOT, ''))
    }
  })
  const missing = [...referenced].filter(([name]) => !registry.has(name))
  check(missing.length === 0,
    `用到的 ${referenced.size} 个图标都登记了（缺：${missing.map(([n, p]) => `${n}@${p}`).join(', ') || '无'}）`)

  // 首页顺势改成真渲染了：图表库动态引入之后，SSR 这条路上根本不会去加载它，
  // 于是这一页原先「只能断源码」的限制没了，能断到真渲染出来的文案
  const { html, warns } = await render('/src/views/Dashboard.vue')
  const body = stripComments(html)
  check(body.includes('class="dashboard"'), '首页真渲染出来了（图表库动态引入之前这一页渲染不了）')
  // 两个饼图容器：SSR 里当然是空的（数据要等接口，图要等图表库），
  // 但容器在不在决定了图有没有地方画 —— 容器被 v-if 掉的话客户端也补不回来
  check((body.match(/chart-container/g) || []).length === 2, '性别/政治面貌两个饼图容器都渲染出来了')
  // 只盯图标：这个桩环境没装 vue-router，router-link 解析不到是桩的事，和图标无关
  const unresolved = warns
    .map((w) => (w.match(/Failed to resolve component: (\w+)/) || [])[1])
    .filter((n) => n && iconNames.has(n))
  check(unresolved.length === 0, `首页没有解析不到的图标（现在：${unresolved.join(', ') || '无'}）`)
}

console.log('\n▶ 首屏瘦身：Element Plus 改按需，弹窗文案还得是中文')
{
  // 断「源码里不再有 X」时得先把行注释去掉：解释这件事为什么要改的注释里
  // 恰恰会写着原来那句 —— 不断的话，注释自己把自己判红（这份文件里踩过）。
  // 只管整行的 //，本文件要断的几句都写在整行注释里
  const noLineComments = (s) => s.replace(/^\s*\/\/.*$/gm, '')

  const viteSrc = readFileSync(`${ROOT}/vite.config.js`, 'utf8')
  const mainSrc = noLineComments(readFileSync(`${ROOT}/src/main.js`, 'utf8'))

  // 全量 app.use(ElementPlus) 会把八十来个组件连同样式整个塞进首屏 ——
  // 实测入口因此多出 838KB JS（gzip 267KB）和 354KB 样式。改成按需之后，
  // 走哪页带哪些组件，入口的 gzip 从 468.9KB 掉到 234.6KB。
  check(!/app\.use\(ElementPlus\b/.test(mainSrc), 'main.js 不再整包 app.use(ElementPlus)')
  check(!/element-plus\/dist\/index\.css/.test(mainSrc), '也不再整包引 dist 那份样式')
  check(/ElementPlusResolver\(\{\s*importStyle:\s*'css'\s*\}\)/.test(viteSrc),
    'vite.config.js 挂着 Element Plus 的按需解析器')
  // dirs 置空是刻意的：本项目的组件一律显式 import，少一层「这个名字从哪来」的谜题，
  // 代码跳转和全局搜索都还认。填上 src/components 会让插件替我们隐式注册
  check(/dirs:\s*\[\]/.test(viteSrc), '按需插件只管 Element Plus（dirs 置空）')

  // 深色主题变量挂在 .dark 类下，不属于任何一个组件，按需插件带不上它。
  // 删掉不会报错，只是切到深色模式时颜色全不对
  check(/element-plus\/theme-chalk\/dark\/css-vars\.css/.test(mainSrc),
    '深色主题的 css-vars 还留着（按需插件不管它）')

  // 这三样按需插件看不见：ElMessage / ElMessageBox 是当函数调出来的（模板里没有
  // 对应标签），ElLoading 是全局指令 v-loading 的本体（全站 49 处在用）。
  // 装它们不只是「能用」—— install 里那句 fn._context = app._context 是这些
  // 脱离组件树的弹窗/遮罩认出自己属于哪个应用、从而拿到全局配置的唯一途径
  for (const name of ['ElMessage', 'ElMessageBox', 'ElLoading']) {
    check(new RegExp(`app\\.use\\(${name}\\)`).test(mainSrc), `${name} 自己装了（按需插件看不见它）`)
  }

  // 中文文案。原来是 `app.use(ElementPlus, { locale: zhCn })` 顺手带的，
  // 现在靠 provideGlobalConfig 的第三个参数：它除了 provide 给整棵组件树，
  // 还把这配置写进模块级的**后备值** —— 函数调出来的弹窗并不在组件树上，
  // 拿不到 provide，走的正是这条后备路。少了那个 true，按钮会退回英文 OK / Cancel
  check(/provideGlobalConfig\(\s*\{\s*locale:\s*zhCn\s*\},\s*app,\s*true\s*\)/.test(mainSrc),
    'provideGlobalConfig 传了第三个参数 true（少了它弹窗按钮就是英文）')

  // SSR 回归测试靠全局注册的桩组件让表格出内容（本文件开头的 ElTableStub 那几件）。
  // 按需插件会让 SFC 直接 import 真组件、绕过全局注册，一百多条断言会一起红 ——
  // 所以测试态必须能把它关掉。这个口子没了，整个测试套件就废了
  check(/mode === 'test'/.test(viteSrc), "vite.config.js 留着 mode === 'test' 这个逃生口")
}

console.log('\n▶ 缓存：接口的默认值搬到了后端，压给上游的 Vary 不能少')
{
  /**
   * 取 `/api/` 那个 location 块的正文（到下一个 4 空格缩进的右花括号为止），
   * 并去掉 `#` 注释 —— 解释「这里原来有那句 add_header」的注释里正好写着那几个字，
   * 不去掉的话注释自己就把断言判红
   */
  function apiBlock(src) {
    const start = src.indexOf('location ^~ /api/')
    if (start < 0) return ''
    return src.slice(start, src.indexOf('\n    }', start)).replace(/^\s*#.*$/gm, '')
  }

  // 三份配置内容基本重合，改功能项三份都要改（这个仓库里踩过「只改一份、
  // 镜像里那份没动」的坑），所以这里三份一起断
  for (const file of ['nginx.conf', 'nginx.conf.template', 'docker-entrypoint.sh']) {
    const src = readFileSync(`${ROOT}/${file}`, 'utf8')

    // add_header 是**追加**不是覆盖：写在这儿会把后端特意给照片设的
    // 「private, max-age=31536000」顶成两个 Cache-Control，而 no-store 只要
    // 出现一个就生效 —— 学生名单页三十多张照片每进一次就重下一遍。
    // 那句默认值现在在后端 DefaultCacheControlMiddleware 里（它只补默认值、
    // 不覆盖已表态的），配套断言在 backend/tests/test_cache_control.py
    check(!/add_header\s+Cache-Control/.test(apiBlock(src)), `${file}: /api/ 里没有 add_header Cache-Control`)

    // 少这一句，中间任何一层共享缓存（宝塔反代的 proxy_cache、CDN）都可能把
    // 压缩过的响应发给不支持压缩的客户端 —— 那是乱码级的故障
    check(/gzip_vary on;/.test(src), `${file}: 开了 gzip_vary`)

    // 带哈希的产物名是唯一能安全长缓存的东西，这条规则本身别被删掉。
    // docker-entrypoint.sh 里那份包在 shell 双引号串里，引号是转义的（\"），
    // 所以引号位置得容许一个反斜杠
    check(/Cache-Control \\?"public, immutable\\?"/.test(src), `${file}: 带哈希的产物仍然长缓存`)
  }
}

console.log('\n▶ 改密地址：/.well-known/change-password')
{
  // 浏览器和密码管理器会探这个地址，标准做法是 302 到真正的改密页面。
  // 三份配置都查一遍：只改 nginx.conf、镜像里那份没动，线上就还是 404 页面。
  for (const file of ['nginx.conf', 'nginx.conf.template', 'docker-entrypoint.sh']) {
    const src = readFileSync(`${ROOT}/${file}`, 'utf8')
    check(
      src.includes('location = /.well-known/change-password'),
      `${file}: 响应密码管理器的探路地址`
    )
    // # 必须带引号（shell 那份是转义的 \"），否则 nginx 把它当注释开头
    check(
      /return 302 \\?"\/#\/my-info\?tab=account\\?";/.test(src),
      `${file}: 302 到账户设置里的改密表单`
    )
  }

  const myInfoSrc = readFileSync(`${ROOT}/src/views/MyInfo.vue`, 'utf8')
  check(
    myInfoSrc.includes("const accountTab = ref('security')"),
    '目标页默认落在「账号安全」子 tab（改密表单就在这里）'
  )
  check(myInfoSrc.includes('handleChangePassword'), '目标页确实有改密表单')
}

console.log('\n▶ 通行密钥：没有浏览器的环境要安静降级')
{
  // 后端发来的是 base64url，浏览器 API 要 ArrayBuffer，这一层掉了登录必失败
  const { _internal } = await server.ssrLoadModule('/src/utils/passkey.js')
  const bytes = new Uint8Array([0, 1, 2, 250, 255])
  const encoded = _internal.bytesToB64url(bytes.buffer)
  check(!/[+/=]/.test(encoded), 'base64url 里没有 + / = 这三个字符')
  check(
    _internal.b64urlToBytes(encoded).join(',') === bytes.join(','),
    '编码再解码还原出同样的字节'
  )
  check(
    _internal.b64urlToBytes('AQID-g').join(',') === '1,2,3,250',
    '解码时补回省略的 = 填充'
  )

  // SSR 里没有 window.PublicKeyCredential —— 登录页不能多出一个按了也登不了的按钮
  const off = await render('/src/views/Login.vue')
  check(off.html.includes('登 录'), '登录页照常渲染')
  check(!off.html.includes('使用通行密钥登录'), '不支持通行密钥的环境不显示那个按钮')

  // onMounted 在 SSR 不跑，直接改初始值模拟「支持」
  const on = await renderPatched(
    '/src/views/Login.vue',
    'const passkeyReady = ref(false)',
    'const passkeyReady = ref(true)'
  )
  check(on.html.includes('使用通行密钥登录'), '支持时登录页出现「使用通行密钥登录」')

  // 免账号：不再要求先填学号，按钮是和「登 录」同宽同高的白底次要按钮
  const loginSrc = readFileSync(`${ROOT}/src/views/Login.vue`, 'utf8')
  check(
    /class="login-btn passkey-btn"/.test(loginSrc),
    '通行密钥按钮与「登 录」同样式（白底、同宽）'
  )
  check(!loginSrc.includes('请先填写学号或账号'), '通行密钥登录不再要求先填学号')

  // 条件式 UI：登记过钥匙的人聚焦账号框就能从自动填充里选，不用先点按钮。
  // 没登记的人看到的仍是普通输入框 —— 这条路径失败时必须一声不吭
  check(
    on.html.includes('autocomplete="username webauthn"'),
    '账号框带 webauthn 自动填充标记'
  )
  check(loginSrc.includes("mediation: 'conditional'"), '登录页挂起条件式 UI')
  check(loginSrc.includes('new AbortController()'), '挂起的自动填充可以中止')
  check(
    /async function handlePasskeyLogin\(\) \{[\s\S]{0,400}?stopConditionalPasskey\(\)/.test(loginSrc),
    '点按钮前先中止自动填充，两条流程不会互相覆盖挑战'
  )
  const condBody = loginSrc.slice(
    loginSrc.indexOf('async function startConditionalPasskey'),
    loginSrc.indexOf('/** 中止挂起的自动填充')
  )
  check(!/ElMessage\.(error|warning|info)/.test(condBody), '自动填充失败时保持静默')

  const storeSrc = readFileSync(`${ROOT}/src/store/user.js`, 'utf8')
  check(
    /loginWithPasskey\(\{\s*remember, mediation, signal\s*\}\)/.test(storeSrc),
    '登录调用不再传学号，并透传自动填充参数'
  )

  check(
    !on.warns.some((w) => /Failed to resolve (component|directive)/.test(w)),
    '登录页没有未解析的组件/指令'
  )

  // 账户设置里的那一段：不支持添加，但已有钥匙的列表还在（换设备后还得能删）
  const plain = await render('/src/components/PasskeySetting.vue')
  check(plain.html.includes('当前浏览器不支持通行密钥'), '不支持的浏览器给出说明')
  check(plain.html.includes('我的通行密钥'), '已有钥匙的列表仍然渲染')
  check(plain.html.includes('还没有添加过通行密钥'), '空列表有提示')
  check(
    !plain.warns.some((w) => /Failed to resolve (component|directive)/.test(w)),
    '通行密钥组件没有未解析的组件/指令'
  )

  const usable = await renderPatched(
    '/src/components/PasskeySetting.vue',
    'const supported = ref(false)',
    'const supported = ref(true)'
  )
  check(usable.html.includes('添加通行密钥'), '支持时可以添加')
  check(usable.html.includes('登录密码'), '添加前要再确认一次密码')
  check(usable.html.includes('服务器只保存公钥'), '说明了私钥不离开设备')
}

console.log('\n▶ 账户设置：子 tab 栏末尾有退出登录')
{
  const { html, warns } = await render('/src/views/MyInfo.vue')
  const logsAt = html.indexOf('我的日志')
  const logoutAt = html.indexOf('退出登录')
  check(logsAt > 0 && logoutAt > logsAt, '退出登录排在「我的日志」之后')
  check(html.includes('el-tabs__new-tab'), '它挂在子 tab 栏上，不是另起一块')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')

  const src = readFileSync(`${ROOT}/src/views/MyInfo.vue`, 'utf8')
  check(
    /<el-tabs\s+v-model="accountTab"[\s\S]{0,100}@tab-add="handleLogout"/.test(src),
    '点它走的是退出登录，不是切换 tab'
  )
  check(src.includes('<template #add-icon>'), '按钮内容放在 add-icon 槽里')
  check(src.includes('await userStore.logout()'), '确认后真的清会话')
  check(src.includes("router.push('/dashboard')"), '退出后回首页（和左侧菜单一致）')
}

console.log('\n▶ 上传前压缩：证明材料、证件照、签字图与附件')
{
  const { fitSize, needsCompress, jpegName, COMPRESS_THRESHOLD, MAX_EDGE } =
    await server.ssrLoadModule('/src/utils/imageCompress.js')

  check(MAX_EDGE === 2000, '长边上限 2000px（纸面小字仍看得清）')
  check(COMPRESS_THRESHOLD === 1024 * 1024, '超过 1MB 才压')

  const wide = fitSize(4000, 3000)
  check(wide.width === 2000 && wide.height === 1500, '横图等比缩到长边 2000')
  const tall = fitSize(1200, 3000)
  check(tall.width === 800 && tall.height === 2000, '竖图也按长边缩')
  check(fitSize(800, 600).width === 800, '本来就不大的图不放大')

  check(needsCompress({ type: 'image/jpeg', size: 2 * 1024 * 1024 }), '大图要压')
  check(!needsCompress({ type: 'image/jpeg', size: 900 * 1024 }), '小于阈值不压')
  check(!needsCompress({ type: 'application/pdf', size: 9 * 1024 * 1024 }), 'PDF 原样放行')
  check(!needsCompress({ type: 'image/gif', size: 5 * 1024 * 1024 }), 'GIF 不压（转 JPEG 会只剩一帧）')
  check(jpegName('证明照片.PNG') === '证明照片.jpg', '压成 JPEG 后文件名跟着换后缀')

  const pages = [
    'LeaveApply.vue', 'EvPass.vue', 'MyInfo.vue',
    'StudentList.vue', 'Feedback.vue', 'Certificate.vue', 'Notices.vue'
  ]
  for (const page of pages) {
    const src = readFileSync(`${ROOT}/src/views/${page}`, 'utf8')
    check(src.includes("from '@/utils/imageCompress'"), `${page} 接上了压缩工具`)
  }

  // 单图 / 表单附件：选完当场 await，压完再校验、再上传
  for (const page of ['LeaveApply.vue', 'EvPass.vue', 'MyInfo.vue', 'StudentList.vue', 'Feedback.vue', 'Certificate.vue']) {
    const src = readFileSync(`${ROOT}/src/views/${page}`, 'utf8')
    check(/await compressImage\(/.test(src), `${page} 在上传前真的等它压完`)
  }

  // 公告附件一次能选多个：先登记全部压缩任务，提交时等齐
  const notices = readFileSync(`${ROOT}/src/views/Notices.vue`, 'utf8')
  check(notices.includes('const task = compressImage(raw)'), '公告图片走压缩')
  check(notices.includes('await Promise.all([...compressTasks])'), '发布前等压缩任务落地')

  // 学生照片、签字图、反馈、证明附件都各接了一处
  const student = readFileSync(`${ROOT}/src/views/StudentList.vue`, 'utf8')
  check(/async function handlePhotoPicked[\s\S]{0,300}await compressImage\(/.test(student),
    '学生照片（高考 / 实地 / 证件照）上传前压缩')
  check(/async function handleSignPicked[\s\S]{0,300}await compressImage\(/.test(student),
    '签字图上传前压缩')
  const feedback = readFileSync(`${ROOT}/src/views/Feedback.vue`, 'utf8')
  check(/file\.__compressTask[\s\S]{0,200}compressImage\(/.test(feedback), '反馈附件里的图片压缩')
  const certificate = readFileSync(`${ROOT}/src/views/Certificate.vue`, 'utf8')
  check(/file\.__compressTask[\s\S]{0,200}compressImage\(/.test(certificate), '证明附件里的图片压缩')
}

console.log('\n▶ 账号安全：三块折叠面板之间不再叠分割线')
{
  const src = readFileSync(`${ROOT}/src/views/MyInfo.vue`, 'utf8')
  const start = src.indexOf('<!-- 访问令牌')
  const end = src.indexOf('</el-tab-pane>', start)
  check(start > 0 && end > start, '找得到账号安全那一段')
  const account = src.slice(start, end)
  check(!account.includes('<el-divider'),
    '访问令牌 / 通行密钥 / 二次验证之间没有 el-divider（折叠项自带边框）')
  check(src.includes('.channel-block + .channel-block :deep(.el-collapse)'),
    '相邻折叠面板去掉后一块的上边框，避免两条线并排')

  // 通知设置：渠道顺序改为 邮件 → Bark → Webhook，且不再叠 el-divider
  const notify = src.slice(src.indexOf('后加的渠道'), src.indexOf('我的日志'))
  const iEmail = notify.indexOf('EmailNotifySetting')
  const iBark = notify.indexOf('Bark 推送')
  const iHook = notify.indexOf('WebhookSetting')
  check(iEmail > 0 && iBark > iEmail && iHook > iBark,
    '通知渠道顺序：电子邮件 → Bark → Webhook')
  check(notify.includes('<el-divider'), '渠道之间保留一条分割线')
  check(src.includes('.notify-channel :deep(.el-collapse)'),
    '折叠块自带的外边框在通知设置里关掉，避免和分割线并排成双线')
}

console.log('\n▶ 登录与账号操作：事件都映射成中文')
{
  // 我的日志与管理员「按账号查日志」共用这一份映射，两边不再各写一长串 v-if
  const labels = {
    login: '登录',
    change_password: '修改密码',
    token_create: '创建令牌',
    token_revoke: '吊销令牌',
    passkey_add: '添加通行密钥',
    passkey_delete: '删除通行密钥',
    two_factor_enable: '开启二次验证',
    two_factor_disable: '关闭二次验证',
    recovery_regenerate: '重新生成恢复码'
  }
  for (const [event, label] of Object.entries(labels)) {
    const { html, warns } = await render(
      '/src/components/AccountEventTag.vue', {}, { event }
    )
    check(stripComments(html).includes(label), `${event} 显示为「${label}」`)
    check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)),
      `${event}：没有未解析的组件/指令`)
  }

  // 后端将来加新事件类型时退回原始事件名，不会变成一片空白
  const unknown = await render('/src/components/AccountEventTag.vue', {}, { event: 'future_event' })
  check(unknown.html.includes('future_event'), '未知事件显示原始名')

  for (const page of ['/src/views/MyInfo.vue', '/src/views/Admin.vue']) {
    const src = readFileSync(`${ROOT}${page}`, 'utf8')
    check(src.includes('<AccountEventTag :event="row.event" />'),
      `${page} 用共享组件渲染事件标签`)
  }
}

console.log('\n▶ 二次验证：登录第二步与账户设置')
{
  // 登录页默认还是密码表单，不会凭空多出验证码框
  const login = await render('/src/views/Login.vue')
  check(login.html.includes('登 录'), '没触发二次验证时仍是密码登录')

  // SSR 里 onMounted 不跑，直接改初始值模拟「密码已通过、等邮箱验证码」
  const email = await renderPatched(
    '/src/views/Login.vue',
    'const twoFactor = ref(null)',
    "const twoFactor = ref({ method: 'email', masked_email: 'a***@example.com', email_sent: true })"
  )
  check(email.html.includes('验证码已发送到'), '邮箱方式显示收件地址')
  check(email.html.includes('a***@example.com'), '地址是打码后的')
  check(email.html.includes('twofa-validity'), '有效期单独一行，不跟着邮箱地址折行')
  check(email.html.includes('10 分钟内有效'), '有效期文案还在')
  check(!email.html.includes('XXXX-XXXX'), '不再提示恢复码的格式')
  check(email.html.includes('一次性恢复码'), '提示可以改用恢复码')
  check(email.html.includes('twofa-sub'), '恢复码提示单独一行')
  check(email.html.includes('重新发送验证码'), '邮箱方式有重发入口')
  check(email.html.includes('返回重新登录'), '可以退回密码登录')
  check(!email.html.includes('登 录'), '第二步不再显示密码登录按钮')
  check(
    !email.warns.some((w) => /Failed to resolve (component|directive)/.test(w)),
    '第二步没有未解析的组件/指令'
  )

  const totp = await renderPatched(
    '/src/views/Login.vue',
    'const twoFactor = ref(null)',
    "const twoFactor = ref({ method: 'totp', masked_email: '', email_sent: false })"
  )
  check(totp.html.includes('身份验证器 App'), 'TOTP 方式提示去 App 里看码')
  check(totp.html.includes('twofa-sub'), 'TOTP 方式的恢复码提示也在')
  check(!totp.html.includes('XXXX-XXXX'), 'TOTP 方式也不提恢复码格式')
  check(!totp.html.includes('重新发送验证码'), 'TOTP 方式没有重发按钮')

  // 两种方式共用同一套居中样式，不再按方式各写一份
  const loginSrc = readFileSync(`${ROOT}/src/views/Login.vue`, 'utf8')
  check(
    /\.twofa-tip\s*\{[^}]*text-align:\s*center/s.test(loginSrc),
    '第二步提示语整体居中'
  )
  check(!loginSrc.includes('twofa-tip--totp'), '不再按验证方式单独加居中样式')

  // 身份验证器要能扫码：otpauth 链接在浏览器里不一定点得动，二维码是主入口
  const tfSrc = readFileSync(`${ROOT}/src/components/TwoFactorSetting.vue`, 'utf8')
  check(tfSrc.includes("import('qrcode')"), '二维码库按需加载，不进首屏')
  check(tfSrc.includes('QRCode.toDataURL'), '用 otpauth 链接在本地画二维码')
  check(/class="totp-qr"/.test(tfSrc), '设置页把二维码显示出来')
  check(tfSrc.includes("qrDataUrl.value = ''"), '取消设置时清掉上一张二维码')

  // 账户设置里的那段：默认未开启，两种方式都摆出来
  const off = await render('/src/components/TwoFactorSetting.vue')
  check(off.html.includes('未开启'), '默认显示未开启')
  check(off.html.includes('电子邮件验证码'), '提供邮箱方式')
  check(off.html.includes('身份验证器（TOTP）'), '提供身份验证器方式')
  check(off.html.includes('开始设置'), '身份验证器有开始设置入口')
  check(off.html.includes('管理员还没配置发信服务'), '没配 SMTP 时说明原因')
  check(
    !off.warns.some((w) => /Failed to resolve (component|directive)/.test(w)),
    '二次验证组件没有未解析的组件/指令'
  )

  // 灌一个「已开启、恢复码用完」的状态
  const on = await renderPatched(
    '/src/components/TwoFactorSetting.vue',
    `  enabled: false,
  method: '',
  email: '',
  masked_email: '',
  smtp_enabled: false,
  recovery_codes_left: 0`,
    `  enabled: true,
  method: 'email',
  email: 'admin@example.com',
  masked_email: 'ad***@example.com',
  smtp_enabled: true,
  recovery_codes_left: 0`
  )
  check(on.html.includes('已开启'), '已开启时有标记')
  check(on.html.includes('当前方式：电子邮件验证码'), '显示当前方式')
  check(on.html.includes('验证码发到 ad***@example.com'), '已开启时邮箱是打码后的')
  check(!on.html.includes('admin@example.com'), '不显示完整邮箱')
  check(on.html.includes('剩余恢复码 0 个'), '显示剩余恢复码数量')
  check(on.html.includes('重新生成恢复码'), '提供重生成恢复码入口')
  check(on.html.includes('关闭二次验证'), '提供关闭入口')
  check(on.html.includes('恢复码已经用完'), '用完后提醒重新生成')
  check(!on.html.includes('开始设置'), '已开启时不再显示开启入口')
}

console.log('\n▶ 线上真实的 404：部署后的旧 chunk、通知里的已删投票')
{
  // 部署换包后，开着的旧页面点菜单会请求已删掉的旧哈希 chunk，页面毫无反应。
  // 路由层要接住这类错误自动刷新，而不是把错误丢在控制台
  const routerSrc = readFileSync(`${ROOT}/src/router/index.js`, 'utf8')
  check(/router\.onError\(/.test(routerSrc), '接住了动态 import 失败')
  check(/dynamically imported module/.test(routerSrc), '只认旧 chunk 这一类错误')
  check(/navigator\.onLine/.test(routerSrc), '断网时先提示，不白白刷新')
  check(
    /sessionStorage\.setItem\(RELOAD_KEY/.test(routerSrc) && /Date\.now\(\) - last < 10000/.test(routerSrc),
    '10 秒内不重复刷新，断网也不会刷成死循环'
  )
  check(
    /window\.location\.hash = to\.fullPath/.test(routerSrc) && /window\.location\.reload\(\)/.test(routerSrc),
    '刷新后落在用户本来想去的页面'
  )

  // 通知跳到一场已被删除的投票时，后端回 404。完全静默会让用户以为点错了通知
  const voteSrc = readFileSync(`${ROOT}/src/views/Vote.vue`, 'utf8')
  const at = voteSrc.indexOf('async function openFromQuery')
  const block = at >= 0 ? voteSrc.slice(at, voteSrc.indexOf('onMounted', at)) : ''
  check(
    /status === 404/.test(block) && block.includes('这场投票不存在或你无权查看'),
    '通知点进已删除的投票：给提示而不是静默'
  )
}

console.log('\n▶ 输错地址：给一张「页面不存在」的卡片，而不是空白')
{
  // 哈希路由下服务端永远是 200（nginx 兜底回 index.html），能给的只有前端这张卡片。
  // 没有 catch-all 的话 router-view 什么都不渲染，正文区一片空白
  const routerSrc = readFileSync(`${ROOT}/src/router/index.js`, 'utf8')
  check(/path: '\/:pathMatch\(\.\*\)\*'/.test(routerSrc), '路由表有 catch-all')
  check(
    routerSrc.indexOf("path: '/:pathMatch") > routerSrc.indexOf("path: '/about'"),
    'catch-all 排在所有具名路由之后'
  )
  check(/meta: \{ title: '页面不存在' \}/.test(routerSrc), '标签页标题是「页面不存在」')

  const { html } = await render('/src/views/NotFound.vue')
  const text = stripComments(html)
  check(text.includes('页面不存在'), '卡片上写着页面不存在')
  check(text.includes('地址可能输错了'), '说明了可能的原因')
  check(text.includes('返回首页'), '给了回首页的出口')

  const src = readFileSync(`${ROOT}/src/views/NotFound.vue`, 'utf8')
  check(src.includes("router.push('/dashboard')"), '「返回首页」真跳首页')
}

console.log('\n▶ 站内信：分页之外，还能一把删掉已读')
{
  // onMounted 在 SSR 里不跑，灌一个「25 条里 20 条未读」的状态
  const SEED = `
items.value = [
  { id: 1, title: '新消息', body: '正文', level: 'active', page: null,
    created_at: '2026-10-17T08:00:00', read_at: null },
  { id: 2, title: '旧消息', body: '正文', level: 'active', page: null,
    created_at: '2026-10-16T08:00:00', read_at: '2026-10-16T09:00:00' }
]
total.value = 25
unread.value = 20
`
  const { html } = await renderPatched('/src/views/Inbox.vue', 'onMounted(load)', SEED)
  const text = stripComments(html)
  check(text.includes('删除已读（5）'), '按钮上写着要删几条（total - unread）')
  check(text.includes('全部标为已读（20）'), '两个操作按钮并排出现')
  check(/class="inbox-pager"/.test(html), '超过 20 条时出分页器')

  // 全部已读：没有未读可标，但已读都能删；条数不够一页时不显示分页器
  const allRead = await renderPatched(
    '/src/views/Inbox.vue',
    'onMounted(load)',
    `
items.value = []
total.value = 3
unread.value = 0
`
  )
  check(allRead.html.includes('删除已读（3）'), '全是已读时删除按钮仍在')
  check(!allRead.html.includes('全部标为已读'), '没有未读时不显示「全部标为已读」')
  check(!/class="inbox-pager"/.test(allRead.html), '不超过一页时不出分页器')

  const apiSrc = readFileSync(`${ROOT}/src/api/inbox.js`, 'utf8')
  check(
    /url: '\/inbox\/read', method: 'delete'/.test(apiSrc),
    '删除走 DELETE /inbox/read（不是逐条删）'
  )

  const src = readFileSync(`${ROOT}/src/views/Inbox.vue`, 'utf8')
  check(!src.includes('所有推送给你的消息都在这里'), '消息页不再挂那句推送说明')
  check(src.includes('未读消息保留') && src.includes('删除后不可恢复'), '确认框说清了删什么、能不能反悔')
  check(src.includes('res.deleted'), '成功提示用的是后端真实删掉的条数')
  check(src.includes('page.value = 1'), '删完回到第一页（已读散在各页）')
}

console.log('\n▶ 标题行与搜索：投票、学生、考勤、成绩、审核')
{
  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')

  // ---------- 四个页面顶上都有标题行 ----------
  for (const [path, title] of [
    ['/src/views/Vote.vue', '投票表决'],
    ['/src/views/StudentList.vue', '学生信息'],
    ['/src/views/Attendance.vue', '考勤记录'],
    ['/src/views/Grade.vue', '成绩管理']
  ]) {
    const { html } = await render(path)
    check(
      new RegExp(`class="page-title"[^>]*>\\s*${title}\\s*<`).test(stripComments(html)),
      `${title}页有标题行`
    )
  }

  // ---------- 四页整页一张卡片（和审核审批一致） ----------
  for (const [path, title] of [
    ['/src/views/Vote.vue', '投票表决'],
    ['/src/views/StudentList.vue', '学生信息'],
    ['/src/views/Attendance.vue', '考勤记录'],
    ['/src/views/Grade.vue', '成绩管理']
  ]) {
    const pageSrc = src(path)
    check((pageSrc.match(/class="page-card/g) || []).length === 1,
      `${title}页只有一张卡片：操作区和信息区合在一起`)
  }
  const studentSrc = src('/src/views/StudentList.vue')
  check(!studentSrc.includes('>学生名单<'), '学生信息页不再出现「学生名单」')
  check(!studentSrc.includes('filter-card'), '临时的 filter-card 类名清干净了')

  // ---------- 投票：按标题搜 ----------
  const { html: voteHtml } = await render('/src/views/Vote.vue')
  check(stripComments(voteHtml).includes('搜索投票标题'), '投票页有标题搜索框')
  const voteSrc = src('/src/views/Vote.vue')
  check(/if \(keyword\.value\.trim\(\)\) params\.keyword = keyword\.value\.trim\(\)/.test(voteSrc),
    '投票列表把标题关键词带给后端')
  check(/function handleReset\(\) \{[\s\S]{0,80}?keyword\.value = ''/.test(voteSrc),
    '重置会清掉标题关键词')
  const pollsPy = src('/../backend/app/api/polls.py')
  check(/keyword: str \| None = Query\(None, description="按标题模糊搜索"\)/.test(pollsPy),
    '后端投票列表收 keyword')
  check(/keyword_like\(keyword, Poll\.title\)/.test(pollsPy), '投票按 Poll.title 过滤')

  // ---------- 考勤：全局搜索（两类记录都搜列表里的「标题」列） ----------
  const { html: attendanceHtml } = await render('/src/views/Attendance.vue')
  check(stripComments(attendanceHtml).includes('搜索标题'),
    '考勤页的搜索框搜两类记录的标题')
  const attendanceSrc = src('/src/views/Attendance.vue')
  check(attendanceSrc.includes('label="标题"') && !attendanceSrc.includes('label="备注"'),
    '列表那一列统一叫「标题」，不再出现「备注」')
  check(attendanceSrc.includes('class="at-filter"') && attendanceSrc.includes('class="at-search"')
    && !/el-form-item label="搜索"/.test(attendanceSrc),
    '筛选栏不再用表单项标签，搜索、日期和按钮收进同一条')
  check(/formatDateTime\(row\.start_at \|\| row\.time\)/.test(attendanceSrc)
    && !attendanceSrc.includes("row.status === 'ongoing' ? '截止' : '结束'"),
    '时间列显示签到的开始时间，不再标「截止 / 结束」')
  check(/if \(keyword\.value\.trim\(\)\) params\.keyword = keyword\.value\.trim\(\)/
    .test(attendanceSrc), '考勤列表把关键词带给后端')
  check(/function handleReset\(\) \{[\s\S]{0,80}?keyword\.value = ''/.test(attendanceSrc),
    '重置会清掉关键词')
  const attendancePy = src('/../backend/app/api/attendance.py')
  check(/keyword: str \| None = Query\(None, description="按点名备注或签到标题模糊搜索"\)/
    .test(attendancePy), '后端汇总与导出都收同一个 keyword')
  check(/att_match = keyword_like\(keyword, AttendanceRecord\.remark\)/.test(attendancePy),
    '点名按 AttendanceRecord.remark 过滤')
  check(/chk_match = keyword_like\(keyword, Checkin\.title\)/.test(attendancePy),
    '签到按 Checkin.title 过滤')

  // ---------- 成绩：按考试名搜 ----------
  const { html: gradeHtml } = await render('/src/views/Grade.vue')
  check(stripComments(gradeHtml).includes('搜索考试名称'), '成绩页有考试名称搜索框')
  const gradeSrc = src('/src/views/Grade.vue')
  check(/if \(keyword\.value\.trim\(\)\) params\.keyword = keyword\.value\.trim\(\)/.test(gradeSrc),
    '成绩列表把关键词带给后端')
  check(/function handleReset\(\) \{[\s\S]{0,80}?keyword\.value = ''/.test(gradeSrc),
    '重置会清掉考试名称关键词')
  const gradesPy = src('/../backend/app/api/grades.py')
  check(/keyword: str \| None = Query\(None, description="按考试名称模糊搜索"\)/.test(gradesPy),
    '后端成绩列表收 keyword')
  check(/keyword_like\(keyword, GradeTest\.name\)/.test(gradesPy), '成绩按 GradeTest.name 过滤')

  // ---------- 审核审批：七个 tab 都能按提交人 / 提交时间搜 ----------
  // 懒加载的 tab 在 SSR 下只渲第一个，所以「七处都在」从源码断言，渲染只验证
  // 当前这个 tab 的搜索栏真的长出来了
  const reviewHtml = stripComments((await render('/src/views/Review.vue')).html)
  check(reviewHtml.includes('提交人姓名或学号'), '审核页渲染出了提交人搜索框')
  check(reviewHtml.includes('提交开始'), '审核页渲染出了提交日期范围')

  const reviewSrc = src('/src/views/Review.vue')
  check((reviewSrc.match(/<ReviewSearch/g) || []).length === 7,
    '七个 tab 各挂一个搜索栏')
  const fetchFns = [
    'fetchChangeList', 'fetchLeaveList', 'fetchEvPassList', 'fetchCertificateList',
    'fetchSignList', 'fetchExportList', 'fetchFeedbackList'
  ]
  for (const fn of fetchFns) {
    const at = reviewSrc.indexOf(`async function ${fn}`)
    const block = reviewSrc.slice(at, reviewSrc.indexOf('\n}', at))
    check(at >= 0 && block.includes('reviewParams('), `${fn} 带上提交人 / 提交日期筛选`)
  }
  check(/if \(range\?\.length === 2\) \{\s*params\.start = range\[0\]\s*params\.end = range\[1\]/
    .test(reviewSrc), '日期范围拆成 start / end 两个参数')
  check(/params\.keyword = kw/.test(reviewSrc), '关键词去空白后才发给后端')

  const searchSrc = src('/src/components/ReviewSearch.vue')
  check(searchSrc.includes('value-format="YYYY-MM-DD"'), '搜索栏的日期是 YYYY-MM-DD')
  check(searchSrc.includes('@clear="emit(\'search\')"'), '清空关键词立即重查')
  check(/<span class="review-search-actions">[\s\S]*?查询[\s\S]*?重置[\s\S]*?<\/span>/
    .test(searchSrc), '查询和重置包成一组，窄屏换行时不会被拆散')

  // ---------- 三个筛选区在手机上的布局 ----------
  // 全局 ≤768px 规则会把每个表单项变成整行（main.css），所以这几页要自己
  // 把表单/控件排紧凑；SSR 不带样式，只能断源码
  const mobileCss = (pageSrc) => {
    const at = pageSrc.indexOf('@media (max-width: 768px)')
    return at < 0 ? '' : pageSrc.slice(at)
  }

  const reviewMobile = mobileCss(searchSrc)
  check(/grid-template-columns: minmax\(0, 1fr\) auto/.test(reviewMobile),
    '审核搜索栏：关键词和按钮一行，日期范围另起一行')
  check(/\.review-search-actions \{\s*grid-area: 1 \/ 2;/.test(searchSrc),
    '查询/重置固定在第一行右侧')
  check(/\.review-search :deep\(\.el-date-editor\) \{\s*width: 100% !important;/.test(searchSrc),
    '日期范围在手机上撑满整宽，不再右侧空一片')

  const studentMobile = mobileCss(studentSrc)
  check(/\.el-form--inline\) \{\s*display: flex;\s*flex-wrap: wrap;/.test(studentMobile),
    '学生筛选：表单变成可换行的 flex 容器，两列才落得下来')
  check(/\.el-form-item__label\) \{\s*width: 68px;/.test(studentMobile),
    '学生筛选：标签收到控件左侧，不再各占一行')
  check(/width: calc\(50% - 5px\)/.test(studentMobile),
    '学生筛选：中间五个下拉两两一行')

  const voteMobile = mobileCss(voteSrc)
  check(/<div class="vt-head">[\s\S]{0,500}?投票表决[\s\S]{0,500}?发起投票[\s\S]{0,200}?<div class="vt-bar">/
    .test(voteSrc), '「发起投票」和标题同一行，不再悬在筛选区右侧')
  check(/\.vt-filter :deep\(\.el-form-item__label\) \{\s*width: 44px;/.test(voteMobile),
    '投票筛选：标签挪到控件左侧，控件占满整行')

  // 后端七个列表接口都得收下这三项，少一个那个 tab 就会「搜了没反应」
  for (const file of ['leaves', 'ev_passes', 'certificates', 'change_requests',
                      'sign_photos', 'exports', 'feedback']) {
    const py = src(`/../backend/app/api/${file}.py`)
    check(/keyword: str \| None = Query\(None, description="按提交人姓名或学号模糊搜索"\)/
      .test(py), `${file} 接收 keyword`)
    check(/created_between\((query|q), \w+\.created_at, start, end\)/.test(py),
      `${file} 按 created_at 与日期范围过滤`)
  }

  // ---------- 文件公开：一个关键词框（标题或文号片段） + 发布时间 ----------
  const annSrc = src('/src/views/Announcements.vue')
  check(/label="文号" width="220"/.test(annSrc), '文号列加宽到 220')
  check(!/label="发布人"/.test(annSrc), '发布人列已去掉')

  const searchArea = annSrc.slice(
    annSrc.indexOf('<!-- 搜索区'), annSrc.indexOf('<!-- 文件列表'))
  check((searchArea.match(/<el-input/g) || []).length === 1,
    '搜索区只有一个输入框，标题和文号共用一个')
  check(searchArea.includes('按标题或文号搜索'), '搜索框说清了标题和文号都能搜')
  check(searchArea.includes('type="daterange"'), '发布时间区间照旧留着')
  check(/keyword: searchForm\.keyword\.trim\(\) \|\| undefined/.test(annSrc),
    '关键词去空白后带给后端')
  const annApi = src('/src/api/announcement.js')
  check(/url: '\/announcements', method: 'get', params/.test(annApi),
    '列表接口把筛选参数真的发出去了（之前这里漏了参数）')
  const annService = src('/../backend/app/services/announcement_service.py')
  check(/keyword_like\(keyword, Announcement\.title, Announcement\.doc_number\)/
    .test(annService), '后端按标题或文号任一段模糊匹配')
}

console.log('\n▶ 资料下载：管理员能调整分类之间的顺序')
{
  const admin = readFileSync(`${ROOT}/src/views/Admin.vue`, 'utf8')
  // 分组循环得带下标，按钮才知道自己在第几组
  check(/v-for="\(group, gi\) in resourceGroups"/.test(admin),
    '分类遍历带下标，整组才能上移/下移')
  check(admin.includes('@click="moveResourceCategory(gi, -1)"')
    && admin.includes('@click="moveResourceCategory(gi, 1)"'),
    '每个分类标题旁有上移、下移按钮')
  // 第一组不能再上移、最后一组不能再下移
  check(admin.includes(':disabled="gi === 0"')
    && admin.includes(':disabled="gi === resourceGroups.length - 1"'),
    '到头的按钮置灰，不会发出越界请求')
  const move = admin.slice(admin.indexOf('async function moveResourceCategory'))
  check(move.includes('reorderResourceCategories(order)'),
    '换完位置后把整串分类名按新顺序发给后端')
  check(move.indexOf('reorderResourceCategories(order)') < move.indexOf('fetchResources()'),
    '先保存成功再重新拉列表，保存失败就别刷新')

  const api = readFileSync(`${ROOT}/src/api/admin.js`, 'utf8')
  check(api.includes("url: '/admin/resources/categories/order'"),
    '前端走专门的分类排序接口')

  // 后端：接口存在，且真的落库；只动分类之间
  const py = readFileSync(`${ROOT}/../backend/app/api/admin.py`, 'utf8')
  check(py.includes('"/resources/categories/order"'), '后端有调整分类顺序的接口')
  const svc = readFileSync(`${ROOT}/../backend/app/services/resource_service.py`, 'utf8')
  check(/def reorder_categories\(db: Session, order: list\[str\]\)/.test(svc),
    '服务层按传入顺序写 sort_order')
  check(svc.includes('def _ordered_categories('),
    '前台与后台共用同一套排序口径')
}

console.log('\n▶ 签到：点名与签到合成一张列表')
{
  const { html } = await render('/src/views/Attendance.vue')
  const text = stripComments(html)
  check(text.includes('发布签到'), '考勤页有「发布签到」按钮')
  check(text.includes('搜索标题'), '搜索框覆盖两种记录')

  const pageSrc = readFileSync(`${ROOT}/src/views/Attendance.vue`, 'utf8')
  // 点名从学生信息页挪过来，点完的记录就落在本页列表里
  check(pageSrc.includes('@click="rollCallRef?.open()"')
    && pageSrc.includes('<RollCallDialog ref="rollCallRef"'),
    '点名入口和弹窗都在考勤页')
  check(pageSrc.includes('@saved="() => fetchList()"'),
    '点名上报成功后刷新列表，新记录当场可见')
  check(readFileSync(`${ROOT}/src/components/RollCallDialog.vue`, 'utf8')
    .includes("emit('saved')"),
    '点名弹窗上报成功后发出 saved 事件')

  // 范围：点名是班级口径，签到按应到人数算
  check(pageSrc.includes('label="范围"'), '列表有「范围」列')
  check(pageSrc.includes("row.type === 'checkin' ? `${row.target_count}人` : row.title"),
    '签到的范围显示为应到 x 人')
  check(!pageSrc.includes('<el-tabs'), '去掉标签页，点名与签到同表')
  check(!pageSrc.includes('CheckinPanel'), '不再挂单独的签到面板')
  check(pageSrc.includes('type="selection"') && pageSrc.includes(':reserve-selection="true"'),
    '复选框跨页保留')
  check(pageSrc.includes(':row-key="rowKey"') && pageSrc.includes('`${row.type}-${row.id}`'),
    '两类记录的 row-key 不会撞车')
  check(pageSrc.includes('只导出选中的记录') && pageSrc.includes('导出当前筛选结果'),
    '导出时二选一：选中记录 / 当前筛选结果')
  check(pageSrc.includes('recordIds:') && pageSrc.includes('checkinIds:'),
    '勾选导出分别带点名和签到的 id')
  check(pageSrc.includes('${start || \'全部\'}_${end || \'全部\'}.xlsx')
    && pageSrc.includes('选中${selection.value.length}条.xlsx'),
    '两种导出的文件名分得清')
  check(pageSrc.includes('startAutoRefresh') && pageSrc.includes('30000'),
    '有进行中的签到时定时刷新实时人数')
  check(pageSrc.includes('批量删除') && pageSrc.includes('handleBatchDelete')
    && pageSrc.includes(':disabled="!selection.length"'),
    '勾选后才能批量删除')
  check(pageSrc.includes('batchDeleteAttendance') && pageSrc.includes('clearSelection'),
    '批量删除后清空勾选')
  check(pageSrc.includes('label="操作" width="220"'), '操作列收窄，按钮不折行')
  check(!pageSrc.includes('handleCheckinRemark'),
    '签到的改备注挪进明细，列表上少一个按钮')

  const src = (p) => readFileSync(`${ROOT}${p}`, 'utf8')
  const attendancePy = src('/../backend/app/api/attendance.py')
  check(attendancePy.includes('"/overview"'), '后端提供合并列表接口')
  check(/def overview_attendance\(/.test(attendancePy)
    && attendancePy.includes('type="checkin"') && attendancePy.includes('type="attendance"'),
    '汇总接口同时返回点名和签到两类行')
  // 结算生成的考勤不再单独成行，签到那一行自己换成标准格式
  check(attendancePy.includes('AttendanceRecord.id.notin_(settled_ids)'),
    '签到结算生成的那条考勤不单独出现在列表里')
  check(pageSrc.includes("row.type === 'attendance' || row.status === 'ended'")
    && pageSrc.includes('已签 {{ row.signed_count }} / {{ row.target_count }}'),
    '签到结算后本行显示应到/实到/请假/无应答，进行中才显示已签人数')
  check(/record_ids: list\[int\] = Query\(default=\[\]/.test(attendancePy)
    && /checkin_ids: list\[int\] = Query\(default=\[\]/.test(attendancePy),
    '导出接口接收勾选的记录 id')
  check(attendancePy.includes('"/batch-delete"') && /def batch_delete_attendance\(/.test(attendancePy),
    '后端提供批量删除接口')
  check(!attendancePy.includes('不能单独删除'),
    '签到生成的考勤不再被拒绝单独删除，而是连签到一起删')

  const attApi = src('/src/api/attendance.js')
  check(attApi.includes("url: '/attendance/batch-delete'")
    && attApi.includes('record_ids: recordIds') && attApi.includes('checkin_ids: checkinIds'),
    '批量删除把点名和签到的 id 分开传')

  // 签到被删后，公开链接不能只报「读取失败」，要明说链接已失效
  const checkinVue = src('/src/views/Checkin.vue')
  check(checkinVue.includes("'链接已失效'") && checkinVue.includes('status === 404')
    && checkinVue.includes('已被删除'),
    '签到删除后打开链接显示「链接已失效」')
}

console.log('\n▶ 签到：公开链接页（不登录也能看，登录后才能签）')
{
  const base = {
    code: 'abc123',
    title: '周六晚点名',
    remark: '宿舍区集合',
    status: 'ongoing',
    created_by_name: '班长',
    created_at: '2026-10-18T19:00:00',
    end_at: '2026-10-18T19:30:00',
    require_photo: false,
    location: null,
    target_count: 5,
    link: 'https://example.com/#/checkin?code=abc123',
    is_login: false,
    is_target: false,
    can_sign: false,
    grace_until: null,
    signed_at: null,
    my_distance_m: null,
    on_leave: false
  }
  const inject = (extra) =>
    `loading.value = false\ninfo.value = ${JSON.stringify({ ...base, ...extra })}`

  // 未登录：只读信息 + 一个回跳登录的按钮
  const { html: guest } = await renderPatched('/src/views/Checkin.vue', 'onMounted(load)', inject({}))
  const guestText = stripComments(guest)
  check(guestText.includes('周六晚点名') && guestText.includes('宿舍区集合'), '没登录也能看到标题和备注')
  check(guestText.includes('截止 2026-10-18 19:30'), '截止时间换了展示格式')
  check(guestText.includes('登录后签到'), '没登录时给的是「登录后签到」')
  check(guest.includes('class="ck-center"'), '「登录后签到」按钮居中（提示与按钮同一块）')
  check(guestText.includes('#/login?redirect='), '登录后会回到这个签到链接')

  // 有地点：只读显示地点名、半径和坐标（测试环境没有高德 Key，走降级那一路）
  const { html: located } = await renderPatched(
    '/src/views/Checkin.vue',
    'onMounted(load)',
    inject({ location: { lat: 39.9071, lng: 116.3972, radius_m: 100, name: '一公寓门口' } })
  )
  const locatedText = stripComments(located)
  check(locatedText.includes('在「一公寓门口」100 米范围内'), '公开页把签到地点与允许半径写进要求')
  check(/<ol class="ck-req"/.test(located) && /<li/.test(located),
    '签到要求按 1. 2. 编号列出')
  check(!locatedText.includes('签到地点：一公寓门口'), '地点只出现在要求里，不再重复一行标题')
  check(locatedText.includes('纬度 39.9071'), '没配地图时降级显示经纬度')

  // 能签时表单直接长在页面上（不再弹窗），并带上定位与照片入口
  const { html: form } = await renderPatched(
    '/src/views/Checkin.vue',
    'onMounted(load)',
    inject({
      is_login: true, is_target: true, can_sign: true, require_photo: true,
      location: { lat: 39.9071, lng: 116.3972, radius_m: 100, name: '一公寓门口' }
    })
  )
  const formText = stripComments(form)
  check(formText.includes('确认签到'), '签到表单位于页面内，不用再弹窗')
  check(form.includes('class="ck-center"'), '确认签到按钮居中')
  check(form.includes('class="ck-line"') && !form.includes('ck-block'),
    '定位与照片各占一行，不再套一层分块')
  check(formText.includes('请拍照或从相册选一张'), '要求照片时页面内给出选择入口')

  // 还没到开始时间：只说几时开始，不给签到按钮
  const { html: pending } = await renderPatched(
    '/src/views/Checkin.vue',
    'onMounted(load)',
    inject({
      status: 'pending', start_at: '2026-10-18T19:00:00',
      is_login: true, is_target: true
    })
  )
  const pendingText = stripComments(pending)
  check(pendingText.includes('未开始'), '没到开始时间时标「未开始」')
  check(pendingText.includes('签到将于 2026-10-18 19:00 开始'), '没到开始时写明几时开始')
  check(!pendingText.includes('确认签到'), '没到开始时不给签到按钮')

  // 已签到
  const { html: signed } = await renderPatched(
    '/src/views/Checkin.vue',
    'onMounted(load)',
    inject({ is_login: true, is_target: true, signed_at: '2026-10-18T19:05:00' })
  )
  check(stripComments(signed).includes('你已于 2026-10-18 19:05 签到'), '签过了就显示签到时间')
  check(stripComments(signed).includes('查看考勤情况'), '签完后给一个去考勤情况的按钮')
  check(signed.includes('#/my-info?tab=attendance'), '「查看考勤情况」跳自己的考勤页')

  // 已结束 + 有有效请假 → 记为请假
  const { html: ended } = await renderPatched(
    '/src/views/Checkin.vue',
    'onMounted(load)',
    inject({ status: 'ended', is_login: true, is_target: true, on_leave: true })
  )
  check(stripComments(ended).includes('记为「请假」'), '结束了没签、有请假 → 记为请假')

  // 截止前打开过页面、登录花掉了一点时间：过了点仍给一段补签宽限
  const { html: graceGuest } = await renderPatched(
    '/src/views/Checkin.vue',
    'onMounted(load)',
    inject({ status: 'ended', grace_until: '2026-10-18T20:00:00' })
  )
  const graceGuestText = stripComments(graceGuest)
  check(!graceGuestText.includes('前补签'), '补签不再显示提示语')
  check(graceGuestText.includes('登录后签到'),
    '游客在宽限内仍然能走「登录后签到」，不会只剩一句已结束')

  const { html: graceForm } = await renderPatched(
    '/src/views/Checkin.vue',
    'onMounted(load)',
    inject({
      status: 'ended', is_login: true, is_target: true, can_sign: true,
      grace_until: '2026-10-18T20:00:00'
    })
  )
  const graceFormText = stripComments(graceForm)
  check(graceFormText.includes('确认签到'), '已结束但在宽限内，签到表单照样显示')
  check(!graceFormText.includes('前补签'), '补签表单上方也不再有提示语')

  // 截止之后链接仍能看：地点地图与要求对游客也公开
  const { html: endedInfo } = await renderPatched(
    '/src/views/Checkin.vue',
    'onMounted(load)',
    inject({
      status: 'ended',
      require_photo: true,
      location: { lat: 39.9071, lng: 116.3972, radius_m: 100, name: '一公寓门口' }
    })
  )
  const endedInfoText = stripComments(endedInfo)
  check(endedInfoText.includes('这次签到已经结束'), '截止后仍能打开链接看信息')
  check(/<ol class="ck-req"/.test(endedInfo), '签到要求逐条编号，对所有人公开')
  check(endedInfoText.includes('一公寓门口') && endedInfoText.includes('100 米范围内'),
    '未登录、已结束时也写明地点与允许半径')
  check(endedInfoText.includes('上传一张照片'), '要求照片对所有人公开')
  check(endedInfo.includes('class="ck-location"'), '已结束时地图照常展示')
  check(endedInfoText.includes('纬度 39.9071'), '已结束时没配地图也能看到坐标')

  // 结算后可在签到详情里逐人改出勤状态（读写结算生成的考勤明细）
  const detailSrc = readFileSync(`${ROOT}/src/components/CheckinDetailDialog.vue`, 'utf8')
  check(detailSrc.includes('updateAttendanceItem('), '结算后可在签到详情里直接改出勤状态')
  check(detailSrc.includes('label="出勤状态"'), '签到详情把状态列成可改的下拉框')
  check(detailSrc.includes('FileViewer'), '签到照片复用证明材料那个预览框')
  check(!detailSrc.includes('window.open'), '照片不再另开新窗口')
  check(detailSrc.includes('detail.attendance_record_id'), '改的是结算生成的那条考勤明细')
  check(detailSrc.includes('updateCheckinTitle(detail.value.id')
    && detailSrc.includes('>修改<'),
    '签到的标题在明细里改')
  // 修改按钮跟在弹窗标题行上，正文不再重复一行「标题 xxx」
  check(detailSrc.includes('<template #header>')
    && detailSrc.includes('cd-header-title')
    && /@click="editTitle">修改</.test(detailSrc),
    '「修改」按钮直接放在明细弹窗的标题行')
  check(!/class="cd-label">标题</.test(detailSrc), '正文里不再重复标题那一行')

  const createSrc = readFileSync(`${ROOT}/src/components/CheckinCreateDialog.vue`, 'utf8')
  check(createSrc.includes('label="说明"') && !createSrc.includes('label="备注"'),
    '发布签到表单里的补充文字叫「说明」，不再和标题混称备注')
  // 列表里结算后的签到行显示的就是这四个计数，改完标题或状态都要刷新列表
  check(detailSrc.match(/emit\('updated'\)/g)?.length >= 2,
    '改标题和改出勤状态之后都通知父组件刷新列表')

  // 公开页要暴露给没登录的人：路由必须是 public + bare
  const routerSrc = readFileSync(`${ROOT}/src/router/index.js`, 'utf8')
  check(/path: '\/checkin'[\s\S]{0,200}?meta: \{ title: '签到', public: true, bare: true \}/
    .test(routerSrc), '签到链接是公开页且不套侧边栏')

  // 后端只收公开 code，登录后由接口告诉前端能不能签
  const apiSrc = readFileSync(`${ROOT}/src/api/checkin.js`, 'utf8')
  check(apiSrc.includes("url: `/checkins/public/${code}/sign`"), '签到走公开 code + 登录态接口')
  check(apiSrc.includes("url: `/checkins/public/${code}/photo`"), '照片先单独上传，换到凭证再签到')
  check(/export function uploadCheckinPhoto\(code, photo, \{ onProgress \}/.test(apiSrc),
    '照片上传接口带进度回调')
  check(apiSrc.includes("form.append('photo_token', photoToken)"), '签到只回传照片凭证，不再带文件')

  // 选中就上传：大照片传得慢，等到点「签到」再传容易正好错过截止
  const checkinVueSrc = readFileSync(`${ROOT}/src/views/Checkin.vue`, 'utf8')
  check(/photoFile\.value = await compressImage\(picked\)[\s\S]{0,300}await uploadPhoto\(\)/.test(checkinVueSrc),
    '照片压缩完立即上传，不等点签到')
  check(checkinVueSrc.includes(':indeterminate="uploadPercent === null"'),
    '拿不到总大小时进度条走不确定态，不是卡在 0%')
  check(checkinVueSrc.includes(':disabled="compressing || uploading"'),
    '照片还在压缩或上传时「确认签到」点不了')
  check(checkinVueSrc.includes('重试上传'), '上传失败保留照片，可以重试')
  check(/if \(info\.value\?\.require_photo && !photoToken\.value\)/.test(checkinVueSrc),
    '要求照片时以拿到凭证为准，不是选过文件就行')
  // 登录耗时不能把人挡在门外，但宽限由服务端给（grace_until），前端不自己算
  check(checkinVueSrc.includes("info.status === 'ongoing' || info.grace_until"),
    '已结束但服务端给了补签宽限时，表单照常显示')
  check(!checkinVueSrc.includes('前补签'), '补签不再显示提示语')
  check(!/OPEN_GRACE|30 \* 60|30分钟宽限/.test(checkinVueSrc),
    '宽限时长只在后端定义，前端不另写一份')

  // 进行中的签到，明细里可以延长截止时间、催还没签的人
  check(apiSrc.includes('url: `/checkins/${id}/extend`')
    && apiSrc.includes('url: `/checkins/${id}/remind`'),
    '延长截止时间与提醒未签到都有接口')
  check(detailSrc.includes('延长5分钟') && detailSrc.includes('提醒未签到')
    && /v-if="detail\.status === 'ongoing'"/.test(detailSrc),
    '只有进行中的签到才显示「延长5分钟」和「提醒未签到」')
  check(/@click="extend"/.test(detailSrc)
    && detailSrc.includes("emit('updated')")
    && detailSrc.includes('已延长5分钟'),
    '延长后列表里的截止时间跟着刷新')
}

console.log('\n▶ 签到：发布端默认用发布人定位，地图上画出允许范围')
{
  const picker = readFileSync(`${ROOT}/src/components/MapPicker.vue`, 'utf8')
  check(picker.includes('autoLocate()'), '打开地图就自动定位发布人（默认地点）')
  check(/if \(!props\.readonly\) autoLocate\(\)/.test(picker), '只读地图不自动定位（公开页不该要访问者位置）')
  check(picker.includes('getCurrentLocation'), '默认位置来自浏览器定位')
  check(picker.includes('new AMapRef.Circle'), '地图上画出允许签到的范围圆')
  check(picker.includes('circle.setRadius(props.radius || 0)'), '半径改了圆跟着变')
  check(/map\.on\('click'/.test(picker), '可以在地图上点选改变地点')
  check(picker.includes("marker.on('dragend'"), '也可以拖动标记微调')
  check(picker.includes("'地图加载失败，可直接填写经纬度'"),
    '配了 Key 但地图加载失败时，提示与「未配置」区分开')

  // 发布端可以按名字搜地点（地图上点点找太费劲）；只读页不出现搜索
  check(picker.includes('new AMapRef.PlaceSearch'), '发布端用高德 PlaceSearch 搜地点')
  check(/placeSearch\.search\(text/.test(picker), '输入关键词真的去搜（Enter 与按钮都走它）')
  check(/v-if="!readonly && useMap"/.test(picker), '搜索框只在可编辑的地图上出现')
  check(picker.includes("emit('place', poi.name)"), '选中搜索结果后把地点名交给发布人')
  check(picker.includes('centerOn(poi)'), '选中后地图移到该地点')
  const amapSrc = readFileSync(`${ROOT}/src/utils/amap.js`, 'utf8')
  check(amapSrc.includes('plugin=AMap.Geocoder,AMap.PlaceSearch,AMap.Scale'),
    '搜地点与比例尺插件跟主脚本一起加载，不在点击时再等')
  check(picker.includes('zoomControl: true'), '缩放按钮在公开页也显示（只读也留着）')
  check(picker.includes('new AMapRef.Scale'), '比例尺一直显示，方便看半径圈多大')

  // CSP 不放行高德，地图脚本会被浏览器拦掉、静默降级成手填
  const cspFile = readFileSync(`${ROOT}/security-headers.conf`, 'utf8')
  // 只看真正下发的那一行，注释里的示例不算
  const csp = cspFile.match(/add_header Content-Security-Policy "([^"]+)"/)?.[1] || ''
  const directive = (name) => csp.match(new RegExp(`${name} ([^;]+);`))?.[1] || ''
  // 只放行 webapi 不够：高德 2.0 运行时还会从 jsapi-service.amap.com 拉
  // WebGLRender 插件，脚本被 CSP 拦掉时地图就是一片白网格（2026-10-18 线上踩过）
  check(directive('script-src').includes('https://*.amap.com'), 'CSP 允许加载高德地图脚本与运行时插件')
  check(directive('script-src').includes("'unsafe-eval'"),
    'CSP 允许高德装配 WebGLRender（它用 eval，不加地图只剩白网格）')
  check(directive('connect-src').includes('https://*.amap.com'),
    'CSP 允许高德的逆地理编码与底图数据请求')

  const create = readFileSync(`${ROOT}/src/components/CheckinCreateDialog.vue`, 'utf8')
  check(create.includes(':radius="form.radius_m"'), '发布弹窗把半径传给地图')
  check(/if \(!point\.value\) return '已打开「要求定位」，请先选择签到地点'/.test(create),
    '打开定位却没选点时不让发布')
  check(create.includes('function defaultEnd()')
    && /function defaultEnd\(\) \{\s*return formatPicker\(new Date\(Date.now\(\) \+ 30 \* 60 \* 1000\)\)/
      .test(create), '截止时间默认 30 分钟后')
  check(/function defaultStart\(\) \{\s*return formatPicker\(new Date\(\)\)/.test(create),
    '开始时间默认现在')
  check(create.includes('label="开始时间"') && create.includes('v-model="form.start_at"')
    && create.includes('start_at: form.start_at'), '发布弹窗可以指定开始时间并随表单提交')
  check(create.includes('开始时间必须早于截止时间'), '开始时间晚于截止时间时前端先拦一道')
  check(create.includes('label="地点展示名"'), '地点名称那一项叫「地点展示名」')
}

console.log('\n▶ 签到：发布结果页带大二维码，列表「链接」重新打开它')
{
  const createSrc = readFileSync(`${ROOT}/src/components/CheckinCreateDialog.vue`, 'utf8')
  check(createSrc.includes('>复制</el-button>'), '结果页的按钮叫「复制」')
  check(!createSrc.includes('>链接</el-button>'), '结果页不再把按钮叫「链接」')
  check(/await import\('qrcode'\)/.test(createSrc), '二维码按需加载 qrcode，不进首屏')
  check(/class="cc-qr"/.test(createSrc) && /width:\s*340px/.test(createSrc),
    '结果页展示一个大号二维码，适合投屏')
  check(createSrc.includes('function openShare(row)') &&
    createSrc.includes('defineExpose({ open, openShare })'),
  '弹窗对外提供 openShare，用来重新打开已有签到的分享页')
  check(createSrc.includes('end_at: row.end_at || row.time'),
    '列表行的 time 映射成 end_at，重新打开时截止时间不会变横杠')
  check(createSrc.includes('QRCode.toDataURL(link') &&
    createSrc.includes('makeQr(created.value.link)'),
  '发布成功和重新打开都会生成二维码')

  const attendanceSrc = readFileSync(`${ROOT}/src/views/Attendance.vue`, 'utf8')
  check(attendanceSrc.includes('createRef?.openShare(row)'),
    '考勤列表的「链接」按钮重新打开分享弹窗')
  check(!attendanceSrc.includes('copyText(row.link)'),
    '列表里不再一点就只复制链接')

  // 真渲染一次结果页：二维码和「复制」都在
  const { html } = await renderPatched(
    '/src/components/CheckinCreateDialog.vue',
    "const qrDataUrl = ref('')",
    `const qrDataUrl = ref('data:image/png;base64,AAAA')
  visible.value = true
  justCreated.value = true
  created.value = {
    title: '周六晚点名', target_count: 5, link: 'https://example.com/share',
    start_at: null, end_at: '2026-10-19T19:30:00'
  }`,
    { ElDialog: ElDialogStub }
  )
  const text = stripComments(html)
  check(text.includes('签到已发布') && text.includes('复制'), '结果页有「签到已发布」和「复制」')
  check(/class="cc-qr"/.test(html), '结果页真渲染出二维码')
  check(!text.includes('投屏后让同学用微信扫一扫') &&
    !text.includes('把下面的链接或二维码发到群里') &&
    !text.includes('结算后会生成一条普通考勤记录'),
  '不再显示扫码提示、转发说明与结算说明')
}

console.log('\n▶ 水印：成绩页、成绩弹窗、办件空间都盖上')
{
  const grade = readFileSync(`${ROOT}/src/views/Grade.vue`, 'utf8')
  check(/<div class="grade">[\s\S]{0,200}?<Watermark :text="watermarkText"/.test(grade),
    '成绩管理页整页盖水印')
  check(grade.includes('const watermarkText = useWatermark()'), '成绩管理页用共用的水印字样')
  check(/\.grade,\s*\n\.wm-host\s*\{\s*position:\s*relative/.test(grade),
    '成绩管理页有定位基准')
  check(/el-dialog v-model="editVisible"[\s\S]{0,300}<Watermark/.test(grade),
    '「修改测试信息」弹窗也有水印')

  for (const file of ['GradeDetailDialog.vue', 'GradeStatsDialog.vue', 'GradeImportDialog.vue']) {
    const src = readFileSync(`${ROOT}/src/components/${file}`, 'utf8')
    check(src.includes('<Watermark :text="watermarkText"'), `${file} 盖了水印`)
    check(src.includes('const watermarkText = useWatermark()'), `${file} 用水印 composable`)
  }
  const detail = readFileSync(`${ROOT}/src/components/GradeDetailDialog.vue`, 'utf8')
  check(/settingVisible[\s\S]{0,400}<Watermark/.test(detail), '科目设置小弹窗也有水印')

  const my = readFileSync(`${ROOT}/src/views/MyInfo.vue`, 'utf8')
  check(/label="我的成绩"[\s\S]{0,400}<Watermark :text="watermarkText"/.test(my),
    '「我的成绩」页盖水印')
  check(/label="办件空间"[\s\S]{0,400}<Watermark :text="watermarkText"/.test(my),
    '「办件空间」页盖水印')
  check(/\.wm-host\s*\{\s*position:\s*relative/.test(my), '两处水印都有定位基准')
}

console.log('\n▶ 强制改密：签到深链也不能绕过，改完留在原页')
{
  const app = readFileSync(`${ROOT}/src/App.vue`, 'utf8')
  check(/<template v-else>[\s\S]*<ForcePasswordDialog \/>[\s\S]*<\/template>/.test(app),
    '强制改密浮层挂在布局外层，签到这种 bare 页也会弹')
  check(app.includes("if (!userStore.resolved && route.name !== 'Login') userStore.fetchMe()"),
    '公开页也恢复一次登录态（登录页除外，避免覆盖刚登录的状态）')

  const dlg = readFileSync(`${ROOT}/src/components/ForcePasswordDialog.vue`, 'utf8')
  check(dlg.includes(':show-close="false"') && dlg.includes(':close-on-click-modal="false"'),
    '改密弹窗不能关掉绕过')
  check(dlg.includes('setInitialPassword') && dlg.includes('markPasswordChanged'),
    '设置成功后清掉 must_change_password 标记')
  check(!dlg.includes('useRouter'), '改完不跳页 —— 从签到链接来的就留在签到页')
  const layout = readFileSync(`${ROOT}/src/components/AppLayout.vue`, 'utf8')
  check(!layout.includes('force-password') && !layout.includes('pwdVisible'),
    '布局里不再重复挂一份改密弹窗')
}

console.log('\n▶ 公开页缓存与分享卡片')
{
  const entry = readFileSync(`${ROOT}docker-entrypoint.sh`, 'utf8')
  check(entry.includes('logo-${LOGO_HASH}.png') && entry.includes('SITE_LOGO_URL'),
    '启动时按内容哈希生成校徽副本，供长期缓存')
  const tpl = readFileSync(`${ROOT}site-config.js.template`, 'utf8')
  check(tpl.includes("logoUrl: '${SITE_LOGO_URL}'"), 'site-config 里下发校徽缓存地址')
  const site = readFileSync(`${ROOT}src/utils/site.js`, 'utf8')
  check(site.includes('logoUrl: raw.logoUrl'), '前端从 SITE 读校徽地址')
  for (const p of ['src/views/Login.vue', 'src/views/Checkin.vue']) {
    check(readFileSync(`${ROOT}${p}`, 'utf8').includes(':src="SITE.logoUrl"'),
      `${p} 的校徽走缓存地址`)
  }
  const robots = readFileSync(`${ROOT}public/robots.txt`, 'utf8')
  check(robots.includes('Allow: /api/checkins/share/'),
    'robots 只对签到分享页放开抓取')

  const checkin = readFileSync(`${ROOT}src/views/Checkin.vue`, 'utf8')
  check(checkin.includes('function applyShareMeta') && checkin.includes("'og:title': title"),
    '签到页把签到标题写进 OG 标签')
  check(checkin.includes("robots.setAttribute('content', 'index,follow')"),
    '签到页把 robots 改成允许抓取')
  check(checkin.includes('document.title = title'), '签到页标题使用签到标题')
}

console.log('\n▶ 手写签名：裁边只框住墨迹，空画布不产图')
{
  const { findInkBounds } = await server.ssrLoadModule('/src/utils/signatureImage.js')
  const width = 8
  const height = 5
  const blank = new Uint8ClampedArray(width * height * 4)
  check(findInkBounds(blank, width, height) === null, '全透明的画布判成「没签」')

  // 在 (2,1) 到 (4,3) 之间画一块不透明墨迹
  const rgba = new Uint8ClampedArray(blank)
  for (let y = 1; y <= 3; y += 1) {
    for (let x = 2; x <= 4; x += 1) rgba[(y * width + x) * 4 + 3] = 255
  }
  const bounds = findInkBounds(rgba, width, height)
  check(bounds?.x === 2 && bounds?.y === 1 && bounds?.width === 3 && bounds?.height === 3,
    '包围盒正好框住落笔区域')

  // alpha 极低的抗锯齿噪点不算落笔，否则裁出来会大一圈、白白多占体积
  const faint = new Uint8ClampedArray(blank)
  faint[(0 * width + 0) * 4 + 3] = 8
  check(findInkBounds(faint, width, height) === null, '阈值以下的透明噪点不算落笔')

  const pkg = JSON.parse(readFileSync(`${ROOT}/package.json`, 'utf8'))
  check(!!pkg.dependencies.signature_pad, 'signature_pad 写进了正式依赖')

  const pad = readFileSync(`${ROOT}/src/components/SignaturePad.vue`, 'utf8')
  check(/penColor: '#000'/.test(pad), '墨迹固定是黑色')
  check(pad.includes('exportSignaturePng(canvasRef.value)'), '预览 / 确认前先走裁边导出')
  check(pad.includes('defineExpose({ init, reset })'), '对批量弹窗暴露 init / reset')
  check(pad.includes('签名人') && pad.includes('{{ signerName'), '签名板上写着当前签名人')
  check(!pad.includes('backgroundColor'), '没设背景色 —— 默认透明，PDF 里不会出现白底')

  const batch = readFileSync(`${ROOT}/src/components/BatchSignDialog.vue`, 'utf8')
  check(batch.includes("mode.value = selectedIds.value.length ? 'selected' : 'missing'"),
    '勾了人默认走覆盖，没勾人默认补缺')
  check(batch.includes('roster.value.filter((s) => !s.has_sign_photo)'),
    '「补充缺失」按 has_sign_photo 筛人')
  check(batch.includes('uploadSignImage(item.id, new File([blob]'),
    '每位同学签完立刻上传，复用签字图接口')
  check(batch.includes('skipCurrent') && batch.includes('跳过此人'), '可以跳过当前这位')
  check(/item\.status = 'done'[\s\S]{0,200}advance\(\)/.test(batch),
    '上传成功才换下一位，失败留在原地可重试')
}

await server.close()

console.log(`\n${'='.repeat(46)}`)
console.log(failed ? `失败 ${failed} 条` : '全部通过')
process.exit(failed ? 1 : 0)
