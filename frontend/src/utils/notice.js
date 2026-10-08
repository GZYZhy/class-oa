/**
 * 从路由 query 里取要定位的通知 id
 *
 * 返回 number，取不到就是 null。
 *
 * **必须转成数字**：路由里的 query 一律是字符串，而列表项的 id 是后端 JSON 给的
 * number、`el-collapse-item` 的 `:name` 也是 number —— 字符串 '123' 和数字 123
 * 不相等，面板不会展开，表现出来就是「点了链接没反应」。
 *
 * 边界都收全：`?id=1&id=2` 会变成数组、空串、非数字、0 / 负数 / 小数都当没给。
 */
export function noticeIdFromQuery(query) {
  const raw = Array.isArray(query?.id) ? query.id[0] : query?.id
  if (raw === undefined || raw === null) return null
  const text = String(raw).trim()
  if (!/^\d+$/.test(text)) return null
  const id = Number(text)
  return id > 0 ? id : null
}
