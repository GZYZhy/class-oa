/**
 * Markdown 渲染 + 通用格式化工具
 *
 * 通知公告、学生备注等多个地方都要用 Markdown 渲染和文件大小格式化，
 * 抽出来共用，避免各写一份对不上。
 */
import { marked } from 'marked'
import DOMPurify from 'dompurify'

/**
 * Markdown 渲染。**必须过 DOMPurify**：
 * 备注 / 通知都是班委写的，但读的人范围更大（甚至游客），
 * 少这一步就是存储型 XSS。
 * 用默认白名单即可：Markdown 产出的标题/列表/表格/链接/图片/代码块、
 * 以及内联 style（标红这类）都保留，只剥 script、iframe、on* 事件属性、
 * javascript: 这类能执行的东西。
 */
function targetBlank(html) {
  return html.replace(/<a\b([^>]*)>/gi, (match, attrs) => (
    /target\s*=/i.test(attrs)
      ? match
      : `<a${attrs} target="_blank" rel="noopener noreferrer">`
  ))
}

export function renderMarkdown(text) {
  // 通知里的外链图片可能很大：加上原生懒加载与异步解码，
  // 弱网下不会为了文章底部的一张图把整篇正文堵在加载上（不支持的浏览器会忽略）
  const html = marked
    .parse(text || '')
    .replace(/<img\s/gi, '<img loading="lazy" decoding="async" ')
  // 浏览器里 DOMPurify 一定有 sanitize；SSR / 渲染回归测试没有 DOM，
  // dompurify 只导出未初始化的工厂函数。那种环境没有真实的 XSS 面，
  // 原样返回供测试断言；万一有 DOM 却没初始化成功，宁可不出内容
  if (typeof DOMPurify.sanitize === 'function') {
    return targetBlank(DOMPurify.sanitize(html))
  }
  if (typeof window === 'undefined' || !window.document) return targetBlank(html)
  return ''
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function safeUrl(raw) {
  const url = String(raw || '').trim()
  // 只放行常见链接和站内相对地址，挡住 javascript: / data: 这类可执行协议
  if (/^(https?:\/\/|\/|#|\.{1,2}\/)/i.test(url)) return url
  return ''
}

/**
 * 题干只支持 [文字](链接) 和 ![说明](图片) 两种 Markdown，外加换行。
 * 不交给 marked：题干里出现 1. / # 时不该变成列表或标题。
 */
export function renderQuestionStem(text) {
  const source = String(text || '')
  const pattern = /!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)/g
  let result = ''
  let last = 0
  let match
  while ((match = pattern.exec(source))) {
    result += escapeHtml(source.slice(last, match.index)).replace(/\n/g, '<br>')
    if (match[1] !== undefined) {
      const url = safeUrl(match[2])
      result += url
        ? `<img src="${escapeHtml(url)}" alt="${escapeHtml(match[1])}" loading="lazy" decoding="async">`
        : escapeHtml(match[0])
    } else {
      const url = safeUrl(match[4])
      result += url
        ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(match[3])}</a>`
        : escapeHtml(match[3])
    }
    last = pattern.lastIndex
  }
  result += escapeHtml(source.slice(last)).replace(/\n/g, '<br>')
  return result
}

/** 把字节数格式化成易读字符串（B / KB / MB） */
export function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

/**
 * 从 Markdown 文本里摘出纯文本（去掉语法符号）。
 * 用在表格列、搜索摘要等地方，避免用户看到 # ** 这类符号。
 * 只做最基本的剥离：标题/列表符号/粗体/斜体/链接/图片/行内代码。
 */
export function stripMarkdown(text) {
  if (!text) return ''
  let s = String(text)
  // 图片：![alt](url) → alt
  s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
  // 链接：[text](url) → text
  s = s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
  // 行内代码：`code` → code
  s = s.replace(/`([^`]+)`/g, '$1')
  // 粗体 / 斜体：**text** / *text* → text
  s = s.replace(/\*\*(.+?)\*\*/g, '$1')
  s = s.replace(/(^|[\s(])\*([^*\n]+?)\*(?=[\s).,;!?]|$)/g, '$1$2')
  // 标题：# / ## / ### 开头 → 去掉
  s = s.replace(/^#{1,6}\s+/gm, '')
  // 列表：- / * / + / 数字. 开头 → 去掉
  s = s.replace(/^\s*[-*+]\s+/gm, '')
  s = s.replace(/^\s*\d+\.\s+/gm, '')
  // 引用：> 开头
  s = s.replace(/^\s*>\s?/gm, '')
  // 分隔线：--- / ***
  s = s.replace(/^\s*[-*_]{3,}\s*$/gm, '')
  // 多余空行压缩成一个
  s = s.replace(/\n{3,}/g, '\n\n')
  return s.trim()
}
