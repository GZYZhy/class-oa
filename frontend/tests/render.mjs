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

  // 紫和黄是手写的色值（Element 的调色板里没有），深色模式得各写一份 ——
  // 只写浅色那份的话，深色下这两类会跟别的事件一样是浅底，字直接糊掉
  const schedSrc = readFileSync(`${ROOT}src/views/Schedule.vue`, 'utf-8')
  check(/\.theme-purple\s*\{/.test(schedSrc) && /\.dark \.theme-purple\s*\{/.test(schedSrc),
    '紫色有浅色和深色两份色值')
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

await server.close()

console.log(`\n${'='.repeat(46)}`)
console.log(failed ? `失败 ${failed} 条` : '全部通过')
process.exit(failed ? 1 : 0)
