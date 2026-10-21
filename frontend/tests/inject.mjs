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
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
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

console.log('▶ 分享页 SSI：占位符保留、条件分支完整')
{
  const out = renderSite(template, { SITE_NAME: '测试班' })
  assert.ok(
    out.includes('<!--# include virtual="/api/share-meta${request_uri}" -->'),
    'SSI include 必须原样保留（${request_uri} 不能被渲染掉）'
  )
  assert.ok(
    out.includes('<!--# if expr="$request_uri = /^\\/share\\//" -->'),
    'SSI 条件块原样保留'
  )
  assert.ok(
    out.includes('<!--# else -->') && out.includes('<!--# endif -->'),
    '条件块有完整的 else / endif'
  )
  assert.ok(out.includes('/share-boot.js'), '分享页启动脚本在 head 里')
  assert.ok(out.includes('<title>测试班</title>'), '非分享页的站点标题仍在 else 分支里')
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

console.log('▶ 生产链路：HEAD_INJECT 非空时放宽 CSP，默认部署保持严格')
{
  const entrypoint = read('../docker-entrypoint.sh')
  const csp = read('../security-headers.conf')

  assert.ok(
    read('../Dockerfile').includes('cp /etc/nginx/security-headers.conf /etc/nginx/orig/'),
    'Dockerfile 应把 CSP 原始副本留在 /etc/nginx/orig'
  )
  assert.ok(
    entrypoint.includes('cp -f "$ORIG_DIR/security-headers.conf" "$CSP_FILE"'),
    '每次启动应先恢复原始 CSP，删掉 HEAD_INJECT 后 restart 才能收回权限'
  )
  assert.ok(
    /if \[ -n "\$HEAD_INJECT" \]/.test(entrypoint),
    '只有 HEAD_INJECT 非空时才放宽'
  )
  // 只看真正下发的那一行，注释里提到 unsafe-inline 不算
  const cspLine = csp.split('\n').find((l) => l.startsWith('add_header Content-Security-Policy'))
  assert.ok(cspLine, 'security-headers.conf 里应有 CSP 响应头')
  assert.ok(
    !/script-src[^;]*'unsafe-inline'/.test(cspLine),
    '镜像内置的 CSP 默认不允许内联脚本'
  )

  // 真跑一遍 entrypoint 里那条 sed，确认它能改到实际下发的这份 CSP
  const sedExpr = entrypoint.match(/sed -i "([^"]+)"/)?.[1]
  assert.ok(sedExpr, 'entrypoint 里应有放宽 CSP 的 sed')
  const dir = mkdtempSync(join(tmpdir(), 'csp-'))
  const file = join(dir, 'security-headers.conf')
  writeFileSync(file, csp)
  // -i.bak 在 GNU 和 BSD sed 上都认；只用 -i 时 macOS 会把下一个参数当备份后缀
  const r = spawnSync('sed', ['-i.bak', sedExpr, file], { encoding: 'utf8' })
  assert.equal(r.status, 0, r.stderr)
  const relaxed = readFileSync(file, 'utf8')
  rmSync(dir, { recursive: true, force: true })

  assert.ok(
    /script-src 'self' 'unsafe-inline' https:/.test(relaxed),
    '放宽后应允许内联脚本与任意 https 脚本'
  )
  assert.ok(
    relaxed.includes("https://*.amap.com 'unsafe-eval'"),
    '放宽只加词，不能弄丢原有的高德白名单与 unsafe-eval'
  )
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
