/**
 * 后端返回的是 ISO 时间串（如 2026-09-24T01:06:16.123456），
 * 统一切成「2026-09-24 01:06」再展示。
 */
export function formatDateTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').replace(/\.\d+$/, '').slice(0, 16)
}

/**
 * 只保留「日 + 时分」，形如「24日 14:30」
 *
 * 通知的「已于 … 更新」标签用它：年和月在通知列表里本来就是多余的，
 * 写全了反而比标题还长。
 */
export function formatDayTime(value) {
  const text = formatDateTime(value)
  if (text === '-') return text
  const [date, time = ''] = String(text).split(' ')
  const day = date.split('-')[2]
  if (!day) return text
  return time ? `${Number(day)}日 ${time}` : `${Number(day)}日`
}

/** 只取日期部分，形如 2026-09-24 */
export function formatDate(value) {
  if (!value) return '-'
  const s = String(value)
  // 可能是 2026-09-24，也可能是 2026-09-24T01:06:00
  return s.split('T')[0].split(' ')[0]
}

/** 附件大小，形如 320 B / 12.5 KB / 3.2 MB */
export function formatFileSize(bytes) {
  const n = Number(bytes) || 0
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** 水印用的当前时刻，形如「9月24日 14:30」 */
export function formatStamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
