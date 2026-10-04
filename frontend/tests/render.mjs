// 前端渲染回归：用 vite 自己的 SSR 管道真渲染 SFC，断言用户看得见的文案。
//
//     cd frontend && npm test
//
// 两条 SSR 语义必须先知道，否则会白写一堆断言：
//   - onMounted 不执行（组件自己那次请求不会发生，所以下面用「灌数据」的办法）；
//   - el-dialog 的正文不渲染（弹窗里的文案断不到，只能断源码）。
import { readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import ElementPlus, { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import * as Icons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'

const ROOT = new URL('..', import.meta.url).pathname
let failed = 0

function check(cond, msg) {
  console.log(`  ${cond ? '✓' : '✗'} ${msg}`)
  if (!cond) failed++
}

const server = await createServer({
  root: ROOT,
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'silent'
})

async function render(path) {
  const app = createSSRApp((await server.ssrLoadModule(path)).default)
  app.use(ElementPlus)
  app.use(createPinia()) // 组件里那句 useUserStore() 得有活的 pinia
  app.provide(ID_INJECTION_KEY, { prefix: 1000, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  // 模板里写的是 <Upload /> <Plus /> 这类裸图标，真实应用靠 main.js 全局注册。
  // 桩环境不照做就会渲染成空标签，且只在警告里体现 —— 很容易漏过去
  for (const [name, icon] of Object.entries(Icons)) app.component(name, icon)
  const warns = []
  app.config.warnHandler = (msg) => warns.push(msg)
  return { html: await renderToString(app), warns }
}

/**
 * 把组件源码里的 onMounted(refresh) 换成直接灌数据，再看渲染结果
 *
 * 每次都得换一个新文件名：vite 的模块图按路径缓存，同名文件复用同一个模块，
 * 第二次灌的数据根本不会生效 —— 渲染出来的还是上一次的样子。
 */
let seq = 0
async function renderWith(stateCode) {
  const src = readFileSync(`${ROOT}/src/components/SetupWizard.vue`, 'utf8')
  if (!src.includes('onMounted(refresh)')) throw new Error('SetupWizard 里找不到 onMounted(refresh)')
  const file = `__render_test_${++seq}.vue`
  const tmp = `${ROOT}/src/components/${file}`
  writeFileSync(tmp, src.replace('onMounted(refresh)', stateCode), 'utf8')
  try {
    return await render(`/src/components/${file}`)
  } finally {
    unlinkSync(tmp)
  }
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

await server.close()

console.log(`\n${'='.repeat(46)}`)
console.log(failed ? `失败 ${failed} 条` : '全部通过')
process.exit(failed ? 1 : 0)
