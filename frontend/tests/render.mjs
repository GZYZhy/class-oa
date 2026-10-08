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

async function render(path, extraComponents = {}) {
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
  const src = readFileSync(`${ROOT}${relPath}`, 'utf8')
  if (!src.includes(marker)) throw new Error(`${relPath} 里找不到要替换的那段：${marker}`)
  const dir = relPath.slice(0, relPath.lastIndexOf('/'))
  const file = `__render_test_${++seq}.vue`
  const tmp = `${ROOT}${dir}/${file}`
  writeFileSync(tmp, src.replace(marker, replacement), 'utf8')
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
  const { html, warns } = await renderPatched(
    '/src/views/MyInfo.vue',
    MYINFO_LOAD,
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

  // 「申请修改」的表单和档案在同一个 html 里（el-tab-pane 默认全渲染）
  check(html.includes('选择照片'), '申请表里有换照片的按钮')
  check(html.includes('不选就是不改'), '写明了只换照片也算一次申请')
  check(
    html.includes('accept=".jpg,.jpeg,.png,.gif,.bmp,.webp"'),
    '只收图片格式，和后面的后缀白名单对齐'
  )

  // 照片交的是文件，混进 CHANGE_FIELDS 就会被 resetForm / buildChanges / el-input
  // 当成文本框消费（界面上会多出一个要人填文件名的输入框）
  const src = readFileSync(`${ROOT}/src/utils/changeFields.js`, 'utf8')
  const list = (src.match(/CHANGE_FIELDS = \[([\s\S]*?)\]/) || [])[1] || ''
  check(!list.includes('id_photo'), '照片没有混进 CHANGE_FIELDS')
  check(list.includes("prop: 'dormitory'"), '宿舍进了 CHANGE_FIELDS')
  check(/PHOTO_FIELD = \{ prop: 'id_photo'/.test(src), '它单独是 PHOTO_FIELD')
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
  check(count('diff-photo') === 2, '待审那条正好两张缩略图')
  check(!/change-requests\/8\/photo/.test(html), '已处理那条一个图地址都不给')

  for (const name of ['a1b2c3d4-新.png', 'e5f6a7b8-旧.png', 'c9d0e1f2-已过.png', 'a3b4c5d6-更旧.png']) {
    check(!html.includes(name), `文件名 ${name} 没露出来`)
  }
  check(html.includes('已上传新照片'), '已处理那条给一句话，而不是空着')
  check(html.includes('自备证件照'), '这一行的字段名念得出来（FIELD_LABELS 认得它）')

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
    ['迎新', '活动', 'theme-info'],
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
    semesterFirstMonday.value = new Date(2026, 8, 14)`
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

  // 周次跟后端给的基准走
  check(html.includes('10月5日 - 11日'), '本周区间念得出来')
  check(html.includes('（第4周）'), '这一周是第 4 周 —— 跟表名走，不是前端按 9 月估的')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')
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
  check(html.includes('>36<') && html.includes('>42<'), '目标人数 / 日程数各自成列')
  check(html.split(/撤销(?:<!--\]-->)?<\/span>/).length - 1 === 2, '两行各有一个「撤销」按钮')
  check(html.includes('撤销一个批次'), '说明写清了撤销的后果')
  check(!warns.some((w) => /Failed to resolve (component|directive)/.test(w)), '没有未解析的组件/指令')
}

console.log('\n▶ 带默认参数的处理器不能裸挂在 @事件 上')
{
  // 裸挂（@click="openCreate"）时 Vue 会把 MouseEvent 当第一个实参传进去。openCreate(date = null)
  // 就是这么把事件对象写进 editForm.date / end_date 的：点「新建日程」→ 选个开始日期（结束日期
  // 没动，还是那个事件对象）→ 保存全天事件，daysInRange 里 (endStr || startStr).split 直接炸。
  // 单看 `@click="xxx"` 分不出对错（@row-click / @change 本来就该收到各自的载荷），所以判据是
  // 「这个名字在本文件里的声明，第一个参数带默认值」—— 带默认值就等于「可以不给」。
  const files = []
  const walk = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.isDirectory()) walk(`${dir}/${e.name}`)
      else if (e.name.endsWith('.vue')) files.push(`${dir}/${e.name}`)
    }
  }
  walk(`${ROOT}src`)

  const bad = []
  for (const f of files) {
    const src = readFileSync(f, 'utf-8')
    for (const m of src.matchAll(/@[a-z:.-]+="([A-Za-z_$][\w$]*)"/g)) {
      // 同名函数在本文件里声明过、且第一个参数有默认值 → 裸挂必然把事件对象喂进去
      if (new RegExp(`function\\s+${m[1]}\\(\\s*\\w+\\s*=`).test(src)) {
        bad.push(`${f.slice(ROOT.length)} @…="${m[1]}"`)
      }
    }
  }
  check(bad.length === 0, `没有裸挂的处理器${bad.length ? `（${bad.join('；')}）` : ''}`)

  const src = readFileSync(`${ROOT}src/views/Schedule.vue`, 'utf-8')
  check(src.includes('@click="openCreate()"'), '「新建日程」写的是 openCreate()，不是裸挂')
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

  const src = readFileSync(`${ROOT}src/views/Schedule.vue`, 'utf-8')
  // 时钟靠定时器走，离开页面必须停掉，否则每进一次日程页就多一个永不回收的定时器
  check(/onUnmounted\(\(\) => clearInterval\(clockTimer\)\)/.test(src), '离开页面时停掉时钟定时器')
  // 窄窗口（半屏、手机）下工具栏一行放不下，「新建日程」会被挤出可见区域点不到
  const toolbar = src.slice(src.indexOf('.toolbar {'), src.indexOf('.week-nav {'))
  check(/flex-wrap:\s*wrap/.test(toolbar), '顶部工具栏允许换行，窄屏按钮不会被挤出去')

  // 全天条保存时把「修改范围」照用户选的传（写死 'all' 时，选「仅本次」会改掉整个序列）
  check(/scope:\s*form\.scope/.test(src), 'saveAllDay 用的是用户选的 scope')
  // 清空「结束日期」会缩小范围 → 先确认再删，不能悄悄把其余几天抹掉
  check(src.includes("'确认缩小范围'"), '缩小日期范围会先确认，再删多余的天数')
  // 关掉「全天」时整条一起转，别只转点中的那一天
  check(/isMultiDayBar\.value\)\s*\{/.test(src), '跨天的条关掉「全天」时整条一起转')

  // 请求失败不能是「点了没反应」：request.js 的拦截器只打 console
  for (const fn of ['importNextStep', 'handleImportConfirm']) {
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

await server.close()

console.log(`\n${'='.repeat(46)}`)
console.log(failed ? `失败 ${failed} 条` : '全部通过')
process.exit(failed ? 1 : 0)
