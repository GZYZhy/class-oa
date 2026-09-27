import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
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
export default defineConfig({
  plugins: [vue(), siteBrand()],
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
})
