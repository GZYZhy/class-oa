import request from '@/utils/request'

/**
 * 解析成绩 Excel（不写库），返回识别结果 + 预览令牌
 *
 * 表头要求：第一行必须有「学号」，可选「姓名」，其余列都当科目。
 * @param {File} file
 * @param {string} [sheetName] - 工作表名，留空用第一张
 */
export function gradeImportPreview(file, sheetName) {
  const formData = new FormData()
  formData.append('file', file)
  const params = {}
  if (sheetName) params.sheet_name = sheetName
  return request({
    url: '/grades/import/preview',
    method: 'post',
    params,
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/**
 * 确认录入
 *
 * @param {{token: string, name: string, tested_at: string, remark?: string,
 *          subjects: string[], subject_modes?: Record<string, string>,
 *          subject_full_scores?: Record<string, number>, notify?: boolean}} data
 *   subjects 是**保留**的科目名（勾掉的列连数据一起不要），顺序即列序。
 *   subject_modes / subject_full_scores 的键都是科目名，没给的按计分 / 100。
 */
export function gradeImportConfirm(data) {
  return request({ url: '/grades/import', method: 'post', data })
}

/** 成绩列表（班委及以上），只带聚合计数 */
export function getGradeList(params) {
  return request({ url: '/grades', method: 'get', params })
}

/** 明细：测试信息 + 科目 + 每个学生每格的成绩（班委及以上） */
export function getGradeDetail(id) {
  return request({ url: `/grades/${id}`, method: 'get' })
}

/** 改测试名称 / 日期 / 备注，传了才改 */
export function updateGradeTest(id, data) {
  return request({ url: `/grades/${id}`, method: 'patch', data })
}

/** 删整次测试（连带它的科目与全部成绩） */
export function deleteGradeTest(id) {
  return request({ url: `/grades/${id}`, method: 'delete' })
}

/**
 * 单科统计（班委及以上）
 *
 * 只有单科的平均/最高/最低/及格率/分数段，**没有总分**。
 */
export function getGradeStats(id) {
  return request({ url: `/grades/${id}/stats`, method: 'get' })
}

/**
 * 加一科
 *
 * @param {string} name 科目名
 * @param {{mode?: string, full_score?: number}} [extra]
 *   mode: 'score' 计分 / 'pass_fail' 通过制
 */
export function addGradeSubject(id, name, extra = {}) {
  return request({ url: `/grades/${id}/subjects`, method: 'post', data: { name, ...extra } })
}

/**
 * 改一科的形态 / 满分，只改传了的那些
 *
 * 那一科已有数据跟新形态对不上时后端回 400（不做静默清空），文案可直接弹。
 */
export function updateGradeSubject(id, subjectId, data) {
  return request({ url: `/grades/${id}/subjects/${subjectId}`, method: 'patch', data })
}

/** 删一科（连带它下面所有成绩） */
export function removeGradeSubject(id, subjectId) {
  return request({ url: `/grades/${id}/subjects/${subjectId}`, method: 'delete' })
}

/**
 * 写一个格子
 *
 * @param {number} id 测试 ID
 * @param {{student_no: string, subject_id: number, value: string}} data
 *   value 空串 = 清空；数字；或缺考 / 免修 / 缓考 / 违纪
 */
export function putGradeScore(id, data) {
  return request({ url: `/grades/${id}/scores`, method: 'put', data })
}

/** 我的各次成绩（学生，只看自己） */
export function getMyGrades() {
  return request({ url: '/grades/mine', method: 'get' })
}
