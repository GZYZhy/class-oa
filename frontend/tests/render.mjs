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
}

console.log('\n▶ 三个办件的顶部说明：办件详情、提交材料、办结材料一套写法')
{
  const PAGES = [
    {
      path: '/src/views/LeaveApply.vue',
      name: '请假',
      notice: '本网办事项仅用于简化流程、避免材料递交繁琐，请假审批是否通过由学校决定。',
      submitted: '请假辅助证明',
      finished: '请假审批表（PDF）'
    },
    {
      path: '/src/views/EvPass.vue',
      name: '电动车',
      notice: '本网络办件仅提供信息表生成',
      submitted: '行驶证（图片或 PDF）',
      finished: '电动车通行证申请表'
    },
    {
      path: '/src/views/Certificate.vue',
      name: '证明开具',
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
    // 办件介绍和办结时限眼下没内容，占位正好两处；多一处少一处都说明哪里写漏了
    check((h.match(/未指定/g) || []).length === 2,
      `${p.name}：只有办件介绍、办结时限两项是「未指定」`)
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
  const cards = ['总人数', '女生人数', '男生人数', '班委人数']
  check(cards.every((label) => src.includes(`<div class="stat-label">${label}</div>`)),
    `四张统计卡都还在（${cards.join(' / ')}）`)
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

await server.close()

console.log(`\n${'='.repeat(46)}`)
console.log(failed ? `失败 ${failed} 条` : '全部通过')
process.exit(failed ? 1 : 0)
