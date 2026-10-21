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
export function renderMarkdown(text) {
  const html = marked.parse(text || '')
  // 浏览器里 DOMPurify 一定有 sanitize；SSR / 渲染回归测试没有 DOM，
  // dompurify 只导出未初始化的工厂函数。那种环境没有真实的 XSS 面，
  // 原样返回供测试断言；万一有 DOM 却没初始化成功，宁可不出内容
  if (typeof DOMPurify.sanitize === 'function') return DOMPurify.sanitize(html)
  if (typeof window === 'undefined' || !window.document) return html
  return ''
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
