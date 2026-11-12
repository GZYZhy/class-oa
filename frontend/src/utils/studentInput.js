/** 把「每行一个学号/姓名」的输入解析成学生值列表 */
export function parseStudentInput(text, rows = [], valueKey = 'student_no') {
  const values = []
  const unknown = []
  const seen = new Set()

  for (const rawLine of String(text || '').split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue

    const no = (line.match(/\d{6,}/) || [])[0]
    let matched = no
      ? rows.filter((row) => String(row.student_no) === no)
      : []

    if (!matched.length) {
      const name = line.replace(/[（(].*?[)）]/g, '').trim()
      matched = rows.filter((row) => row.name === name)
    }

    if (!matched.length) {
      unknown.push(line)
      continue
    }
    for (const row of matched) {
      const value = row[valueKey]
      if (value !== undefined && !seen.has(value)) {
        seen.add(value)
        values.push(value)
      }
    }
  }
  return { values, unknown }
}
