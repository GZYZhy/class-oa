/**
 * 后端返回的是 ISO 时间串（如 2026-09-24T01:06:16.123456），
 * 统一切成「2026-09-24 01:06」再展示。
 */
export function formatDateTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').replace(/\.\d+$/, '').slice(0, 16)
}

/** 只取日期部分，形如 2026-09-24 */
export function formatDate(value) {
  if (!value) return '-'
  const s = String(value)
  // 可能是 2026-09-24，也可能是 2026-09-24T01:06:00
  return s.split('T')[0].split(' ')[0]
}

/** 水印用的当前时刻，形如「9月24日 14:30」 */
export function formatStamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
