// 运行时注入的回归测试：head 注入 + 按需引入时容易漏掉的服务组件样式。
//
// 这两件事都只在「真实构建 + 容器启动」这条路上出错，开发时看不出来：
//   · HEAD_INJECT 里出现引号、尖括号、$、反斜杠、换行时不能被转义或截断；
//   · ElMessage / ElMessageBox / v-loading 是函数或指令，按需插件看不见，
//     样式得 main.js 手动引，漏了就是截图里那种「裸弹窗」。
//
// 跑法（已挂在 npm test 后面）：node tests/inject.mjs

import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { renderSite } from '../vite.config.js'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const read = (rel) => readFileSync(HERE + rel, 'utf8')

const template = read('../index.html')

console.log('▶ 头部注入：特殊字符与换行原样保留')
{
  // 一段典型的跟踪器代码：双引号、单引号、尖括号、&、$、反斜杠、中文、换行都有
  const snippet = [
    '<script>',
    '  // 路径里的反斜杠 \\ 和美元符 $ 都不能被吃掉',
    '  var u = "https://t.example.com/a.js?a=1&b=2";',
    "  window.track = { name: '统计', u: u, price: '$5' };",
    '</script>',
    '<meta name="verify" content="a&b">'
  ].join('\n')

  const out = renderSite(template, { SITE_NAME: '测试班', HEAD_INJECT: snippet })

  assert.ok(out.includes(snippet), '注入内容应与配置逐字相同')
  assert.ok(!out.includes('${HEAD_INJECT}'), '占位符应被替换干净')
  assert.ok(out.includes('</head>'), '注入不能破坏文档结构')
  assert.ok(out.includes('<title>测试班</title>'), '品牌替换应同时正常')
}

console.log('▶ 头部注入：不配置时不留下占位符')
{
  const out = renderSite(template, { SITE_NAME: '测试班' })
  assert.ok(!out.includes('${HEAD_INJECT}'), '空值时占位符也应消失')
}

console.log('▶ 头部注入：拼错的名字保持原样，便于发现')
{
  const out = renderSite('前 ${SITE_NOPE} 后', { SITE_NOPE: '不该用上' })
  assert.equal(out, '前 ${SITE_NOPE} 后', '未知占位符不应被悄悄清空')
}

console.log('▶ 生产链路：entrypoint 的白名单里包含 HEAD_INJECT')
{
  const entrypoint = read('../docker-entrypoint.sh')
  // envsubst 只替换白名单里的键，漏了这里线上就永远插不进去
  const whitelist = entrypoint.match(/envsubst '([^']+)'/g) || []
  assert.ok(
    whitelist.some((line) => line.includes('${HEAD_INJECT}')),
    'docker-entrypoint.sh 的 envsubst 白名单缺少 ${HEAD_INJECT}'
  )
  assert.ok(entrypoint.includes('export HEAD_INJECT'), 'entrypoint 应导出 HEAD_INJECT')
}

console.log('▶ 生产链路：envsubst 也能逐字保留多行与特殊字符')
{
  // entrypoint 用的就是 envsubst。本机没装就跳过（镜像里一定有）
  const probe = spawnSync('envsubst', ['--version'], { encoding: 'utf8' })
  if (probe.status === 0) {
    const snippet = '第一行 <script>\n  if ($ && "x") { /* \\ 反斜杠 */ }\n</script> 末行'
    const r = spawnSync(
      'envsubst',
      ['${SITE_NAME} ${HEAD_INJECT}'],
      {
        input: '<title>${SITE_NAME}</title>\n${HEAD_INJECT}\n',
        encoding: 'utf8',
        env: { ...process.env, SITE_NAME: '测试班', HEAD_INJECT: snippet }
      }
    )
    assert.equal(r.status, 0, r.stderr)
    assert.equal(r.stdout, `<title>测试班</title>\n${snippet}\n`)
  } else {
    console.log('  （本机没有 envsubst，跳过）')
  }
}

console.log('▶ 服务组件样式：函数式组件与 v-loading 的 CSS 必须手动引入')
{
  const main = read('../src/main.js')
  for (const name of ['message', 'message-box', 'loading']) {
    assert.ok(
      main.includes(`element-plus/es/components/${name}/style/css`),
      `main.js 缺少 ${name} 的样式引入`
    )
  }
}

console.log('✅ 注入与样式检查通过')
