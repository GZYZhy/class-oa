/**
 * 学生可以申请修改的字段清单。
 * 必须和后端 app/api/change_requests.py 的 EDITABLE_FIELDS 保持一致（顺序也一致），
 * 「我的信息」的申请表单、「审核」页的新旧值对照都用这份，改一处就够。
 *
 * maxLength 对应后端 schemas/change_request.py 里的 max_length。
 */
export const CHANGE_FIELDS = [
  { prop: 'qq', label: 'QQ号码', maxLength: 30, placeholder: '请输入 QQ 号码' },
  { prop: 'email', label: '电子邮箱', maxLength: 100, placeholder: '请输入电子邮箱' },
  { prop: 'family_address', label: '家庭地址', maxLength: 200, placeholder: '请输入家庭通信地址' },
  { prop: 'postal_code', label: '邮政编码', maxLength: 10, placeholder: '6 位数字' },
  { prop: 'league_position', label: '团学会职务', maxLength: 50, placeholder: '没有就留空' },
  { prop: 'is_poor', label: '是否贫困生' },
  { prop: 'bed', label: '床位号', maxLength: 20, placeholder: '如：1 号床' }
]

/** 字段名 → 中文标签 */
export const FIELD_LABELS = Object.fromEntries(CHANGE_FIELDS.map((f) => [f.prop, f.label]))

export const STATUS_LABELS = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已驳回'
}

/** el-tag 的颜色：待审黄、通过绿、驳回红 */
export const STATUS_TYPES = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger'
}
