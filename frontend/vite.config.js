import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'

/** 项目根目录（frontend/ 的上一层）。根 .env 就在这里，后端也读它 */
const PROJECT_ROOT = fileURLToPath(new URL('..', import.meta.url))
/** 品牌配置模板，生产和开发共用这一份形态 */
const SITE_TEMPLATE = fileURLToPath(new URL('./site-config.js.template', import.meta.url))

/** 模板里出现过的、需要替换的键。名字必须和 docker-entrypoint.sh 的白名单一致 */
const SITE_KEYS = [
  'SITE_NAME',
  'SITE_SHORT_NAME',
  'SITE_SUBTITLE',
  'SITE_COLLEGE',
  'SITE_MAJOR',
  'SITE_FOOTER',
  'SITE_DESCRIPTION'
]

/**
 * 把文本里的 ${SITE_X} 换成 .env 里的值
 *
 * 认不出来的键保持原样不动，和生产的 envsubst 白名单行为一致 ——
 * 名字拼错了就该一眼看见 ${SITE_XXX}，而不是悄悄变成空。
 */
function renderSite(text, env) {
  const values = Object.fromEntries(SITE_KEYS.map((key) => [key, env[key] || '']))
  // SEO 描述留空时取站名，和 entrypoint 里的处理保持一致
  values.SITE_DESCRIPTION = values.SITE_DESCRIPTION || values.SITE_NAME

  return text.replace(/\$\{(SITE_[A-Z_]+)\}/g, (whole, key) =>
    key in values ? values[key] : whole
  )
}

/**
 * 本地开发时的品牌注入插件
 *
 * 生产环境是容器启动时由 frontend/docker-entrypoint.sh 用 envsubst 注入的
 * （前端镜像是 CI 预构建的，Vite 的构建期变量在部署侧不存在，品牌只能运行时注入）。
 * 本地没有 nginx，所以这里读**同一份** site-config.js.template 和**同一个**根 .env，
 * 在内存里替换一遍 —— 这样仓库里不需要再存一份带值的副本。
 *
 * 只在 `vite dev` 生效（apply: 'serve'）：构建产物里必须保留 ${SITE_*} 占位符，
 * 容器启动时才有可替换的目标。
 */
function siteBrand() {
  let env = {}

  return {
    name: 'site-brand',
    apply: 'serve',

    configResolved(config) {
      // loadEnv 的第三个参数传 '' = 不过滤前缀，把 .env 里的键都读进来。
      // 但下面只取 SITE_* 用：其余键（含 MASTER_PASSWORD 等机密）既不会
      // 进 HTML，也不会进客户端产物。
      env = loadEnv(config.mode, PROJECT_ROOT, '')
      console.log(
        `[品牌] 已从 ${PROJECT_ROOT}.env 注入：` +
          SITE_KEYS.map((k) => `${k}=${env[k] || '(空)'}`).join('  ')
      )
    },

    transformIndexHtml(html) {
      return renderSite(html, env)
    },

    configureServer(server) {
      // 本地没有 public/site-config.js（那份是容器里现渲染的），这里补一个，
      // 否则页面会一直 404、window.__SITE__ 拿不到值。
      server.middlewares.use('/site-config.js', (req, res) => {
        res.setHeader('Content-Type', 'application/javascript; charset=utf-8')
        res.setHeader('Cache-Control', 'no-store')
        res.end(renderSite(readFileSync(SITE_TEMPLATE, 'utf8'), env))
      })
    }
  }
}

// https://vitejs.dev/config/
// 用函数形式是为了能看 mode：tests/render.mjs 起服务时传 mode: 'test'，
// 那时要跳过下面的 Element Plus 按需插件（理由写在 plugins 里）。
export default defineConfig(({ mode }) => ({
  plugins: [
    vue(),

    // Element Plus **按需引入**：模板里真正写到的组件（含 v-loading 这类指令）才进产物。
    //
    // 原来是 main.js 里 `app.use(ElementPlus)` 全量注册，那会把八十来个组件连同样式
    // 整个塞进首屏 —— 实测入口因此多出 838KB（gzip 267KB）JS + 354KB 样式，
    // 弱网下光这一份就是十几秒。改成按需之后走哪页带哪些组件。
    //
    // importStyle 用 'css'：直接吃 Element Plus 预编译好的 CSS，不必再装 sass。
    // dirs 置空：**只**管 Element Plus，本项目的组件一律显式 import ——
    // 少一层「这个名字是哪来的」的谜题，跳转和搜索都还认。
    //
    // 跑 SSR 回归测试时不装：那个测试让表格/弹窗出内容靠的是「全局注册的桩组件」
    // （tests/render.mjs 里的 ElTableStub 等），而这个插件会让 SFC 直接 import
    // 真组件、绕过全局注册 —— 桩就白替了，一百多条断言会一起红。
    // 所以测试态仍按老办法走全局解析。**按需本身是否真的生效，由构建产物体积和
    // 真浏览器回归来保证，不靠这个测试。**
    ...(mode === 'test'
      ? []
      : [
          Components({
            resolvers: [ElementPlusResolver({ importStyle: 'css' })],
            dirs: [],
            dts: false
          })
        ]),

    siteBrand()
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    proxy: {
      // 所有后端接口（含照片、资料、公告文件）统一走 /api
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets'
  }
}))
