/** 维护页独立脚本的刷新地址、品牌与同源限制回归。 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const script = readFileSync(new URL('../public/maintenance.js', import.meta.url), 'utf8')
function render(path, site = {}) {
  const current = new URL(path, 'https://class.example')
  const nodes = { 'site-name': {}, 'site-logo': {}, retry: {}, refresh: {} }
  const document = {
    title: '',
    getElementById: (id) => nodes[id],
    querySelector: () => nodes.refresh
  }
  vm.runInNewContext(script, { window: { location: current, __SITE__: site }, document, URL, URLSearchParams })
  return { nodes, document }
}

const returnPath = '/#/schedule?day=2026-11-13'
const result = render(`/maintenance.html?return=${encodeURIComponent(returnPath)}`, { name: '测试班级', logoUrl: '/logo.png' })
assert.equal(result.nodes.retry.href, `https://class.example${returnPath}`)
assert.equal(result.nodes.refresh.content, `60;url=https://class.example${returnPath}`)
assert.equal(result.document.title, '维护中 - 测试班级')
assert.equal(result.nodes['site-name'].textContent, '测试班级')
assert.equal(result.nodes['site-logo'].src, '/logo.png')
for (const target of ['https://outside.example', '//outside.example', 'javascript:alert(1)', '/maintenance.html']) {
  assert.equal(render(`/maintenance.html?return=${encodeURIComponent(target)}`).nodes.retry.href, 'https://class.example/')
}
assert.equal(render('/api/health?check=1').nodes.refresh.content, '60;url=https://class.example/api/health?check=1')
assert.equal(render('/maintenance.html').nodes.retry.href, 'https://class.example/')
const html = readFileSync(new URL('../public/maintenance.html', import.meta.url), 'utf8')
assert.match(html, /http-equiv="refresh" content="60"/)
assert.match(html, /维护中/)
for (const file of ['nginx.conf', 'nginx.conf.template', 'docker-entrypoint.sh']) {
  const config = readFileSync(new URL(`../${file}`, import.meta.url), 'utf8')
  assert.match(config, /error_page 502 \/maintenance\.html/)
  assert.match(config, /proxy_intercept_errors on/)
}
console.log('✓ 维护页每 60 秒重试，保留本站原页面，HTTP 与 HTTPS 配置包含 502 维护页')
