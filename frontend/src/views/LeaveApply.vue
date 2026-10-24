<template>
  <div>
    <div class="page-card">
      <h3 class="page-title">请假申请</h3>

      <ServiceIntro
        intro="因病因事无法参加课程或集体活动时提交。"
        deadline="3 个工作日（仅供参考）"
        notice="本服务仅简化流程，是否准假由学校决定。"
        submitted="请假证明（病假条、诊断证明等），PDF 或图片，单个 ≤20MB，必填"
        finished="请假审批表（PDF），审批后可下载"
      />

      <el-tabs v-model="activeTab">
        <!-- 提交申请 -->
        <el-tab-pane :label="editingId ? '修改申请' : '提交申请'" name="apply">
          <!-- 修改这条申请时把表单预填成它的内容，提交走 PUT 覆盖原记录 -->
          <div v-if="editingId" class="edit-hint">
            正在修改申请，未重新上传的材料保持不变。
          </div>

          <el-form :model="form" :rules="rules" ref="formRef" label-width="110px" style="max-width: 640px;">
            <el-form-item label="请假类型" prop="leave_type">
              <el-radio-group v-model="form.leave_type">
                <el-radio value="病假">病假</el-radio>
                <el-radio value="事假">事假</el-radio>
                <el-radio value="公假">公假</el-radio>
              </el-radio-group>
            </el-form-item>

            <!-- 起止时间精确到「时」，和请假审批表模板的「年 月 日 时」对齐。
                 value-format 里的 00 是字面量：选完分钟后会落到整点 -->
            <el-form-item label="开始时间" prop="start_at">
              <el-date-picker
                v-model="form.start_at"
                type="datetime"
                placeholder="选择开始时间"
                format="YYYY-MM-DD HH:00"
                value-format="YYYY-MM-DD HH:00"
                style="width: 100%;"
              />
            </el-form-item>

            <el-form-item label="结束时间" prop="end_at">
              <el-date-picker
                v-model="form.end_at"
                type="datetime"
                placeholder="选择结束时间"
                format="YYYY-MM-DD HH:00"
                value-format="YYYY-MM-DD HH:00"
                style="width: 100%;"
              />
              <div class="form-tip">时间精确到小时，分钟按整点计</div>
              <div v-if="days > 0" class="form-tip">共 {{ days }} 天</div>
            </el-form-item>

            <el-form-item label="请假事由" prop="reason">
              <el-input
                v-model="form.reason"
                type="textarea"
                :rows="4"
                placeholder="请详细说明请假原因"
                maxlength="2000"
                show-word-limit
              />
            </el-form-item>

            <el-form-item label="出行方式">
              <el-input v-model="form.travel_mode" placeholder="如：高铁、自驾、飞机等" />
            </el-form-item>

            <el-form-item label="行程">
              <el-input v-model="form.travel_detail" placeholder="车次/航班号等" />
            </el-form-item>

            <el-form-item label="去向地址">
              <el-input v-model="form.destination" placeholder="目的地详细地址" />
            </el-form-item>

            <el-form-item label="联系电话">
              <el-input v-model="form.destination_phone" placeholder="去向地联系电话" />
            </el-form-item>

            <el-form-item label="辅助证明" prop="proof">
              <el-upload
                :file-list="fileList"
                :auto-upload="false"
                :limit="1"
                :on-change="handleFileChange"
                :on-remove="handleFileRemove"
                accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp"
              >
                <el-button>选择文件</el-button>
                <template #tip>
                  <div v-if="editingId" class="el-upload__tip">
                    支持 PDF / 图片，最大 20MB。超过 1MB 的图片会自动压缩；不重选就沿用当前那份
                  </div>
                  <div v-else class="el-upload__tip">
                    支持 PDF / 图片，最大 20MB，必填。超过 1MB 的图片会自动压缩
                  </div>
                </template>
              </el-upload>
            </el-form-item>

            <el-form-item prop="agreed">
              <el-checkbox v-model="form.agreed" class="agree-checkbox">
                <div>我已阅读并同意遵守学校相关规定，确认以上信息真实有效</div>
                <div>我授权系统为我按以上信息生成“请假申请表”，并确认是我个人意愿的真实体现。</div>
              </el-checkbox>
            </el-form-item>

            <!-- 这段是《示例大学学生请假审批表》上「本人承诺」栏的原话，
                 勾选即表示认下表上这两条，落在纸面上的表不用再重复誊写一遍 -->
            <el-form-item prop="promised">
              <el-checkbox v-model="form.promised" class="agree-checkbox">
                <div>本人承诺：</div>
                <div>1、请假期间保持与班导师和辅导员的联系，请假期满按时返校并办理销假手续。</div>
                <div>2、请假期间个人人身安全及财产安全责任自负。</div>
              </el-checkbox>
            </el-form-item>

            <el-form-item prop="signConfirmed">
              <!-- 勾上就检查签字图：没有就当场手写，别等到点了提交才发现 -->
              <el-checkbox
                v-model="form.signConfirmed"
                class="agree-checkbox"
                @change="handleSignConfirmedChange"
              >
                <div>我确认在请假审批表上签字</div>
              </el-checkbox>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="submitting" @click="handleSubmit">
                <!-- 证明材料多是拍照，慢网络下传得久，把进度显示出来 -->
                {{ editingId ? '保存修改' : '提交申请' }}{{ submitting && uploadProgress ? ` ${uploadProgress}%` : '' }}
              </el-button>
              <el-button v-if="editingId" @click="cancelEdit">取消修改</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 我的记录 -->
        <el-tab-pane label="我的记录" name="history">
          <el-table :data="leaves" v-loading="loading" stripe border style="width: 100%;">
            <el-table-column prop="leave_type" label="类型" width="80" align="center" />
            <el-table-column label="请假时间" width="160" align="center">
              <template #default="{ row }">
                <div>{{ formatDateTime(row.start_at) }}</div>
                <div class="time-sep">至</div>
                <div>{{ formatDateTime(row.end_at) }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="reason" label="事由" min-width="180" show-overflow-tooltip align="left" />
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.status === 'pending'" type="warning" size="small">待受理</el-tag>
                <el-tag v-else-if="row.status === 'accepted'" type="primary" size="small">已受理</el-tag>
                <el-tag v-else-if="row.status === 'correcting'" type="warning" size="small">待补正</el-tag>
                <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
                <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
                <el-tag v-else-if="row.status === 'revoked'" type="info" size="small">已撤销</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="申请时间" width="160" align="center">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="240" align="center">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="viewProof(row)">
                  查看证明
                </el-button>
                <!-- 待受理、待补正都能改；撤只有待受理能撤（受理过的要撤得找班委先撤回受理） -->
                <el-button
                  v-if="row.status === 'pending' || row.status === 'correcting'"
                  size="small"
                  link
                  type="warning"
                  @click="startEdit(row)"
                >
                  修改
                </el-button>
                <el-button
                  v-if="row.status === 'pending'"
                  size="small"
                  link
                  type="danger"
                  @click="handleDelete(row)"
                >
                  撤销
                </el-button>
                <el-button
                  v-if="row.status === 'approved'"
                  size="small"
                  link
                  type="success"
                  :loading="isDownloading(`leave-${row.id}`)"
                  @click="downloadPdf(row)"
                >
                  {{ isDownloading(`leave-${row.id}`) && downloadPercent
                    ? `${downloadPercent}%` : '下载请假表' }}
                </el-button>
              </template>
            </el-table-column>
            <el-table-column label="审核意见" width="180" show-overflow-tooltip align="left">
              <template #default="{ row }">
                <span v-if="row.status === 'rejected'" style="color: #f56c6c;">
                  {{ row.reject_reason || '未填写理由' }}
                </span>
                <span v-else-if="row.status === 'approved'" style="color: #67c23a;">
                  {{ row.reviewer_name || '管理员' }} 已通过
                  <!-- 班导师意见是批准时填的（选填），没填就不占地方 -->
                  <div v-if="row.advisor_opinion" style="color: var(--el-text-color-regular);">
                    班导师意见：{{ row.advisor_opinion }}
                  </div>
                </span>
                <!-- 退回补正的理由是让申请人照办的话，得跟状态一起看得见 -->
                <span v-else-if="row.status === 'correcting'" style="color: #e6a23c;">
                  需补正：{{ row.correction_reason || '请补齐材料' }}
                </span>
                <!-- 已撤销不再展示当初的审核意见（用户口径），审核信息留在库里备查 -->
                <span v-else-if="row.status === 'revoked'" style="color: var(--el-text-color-disabled);">—</span>
                <span v-else style="color: var(--el-text-color-disabled);">
                  {{ row.status === 'accepted' ? '已受理，等待审批' : '待受理' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 我的证明材料预览弹框 -->
    <FileViewer
      v-model="proofViewerVisible"
      :file-url="proofFileUrl"
      :file-name="proofFileName"
      title="我的证明材料"
    />

    <!-- 没有签字图时先让人手写一张：请假审批表上要印本人签字 -->
    <QuickSignDialog ref="signGuard" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getMyLeaves, submitLeave, updateLeave, deleteLeave, downloadLeavePdf } from '@/api/leave'
import { formatDate, formatDateTime } from '@/utils/format'
import { compressImage } from '@/utils/imageCompress'
import { blobErrorDetail } from '@/utils/download'
import { useDownloadProgress } from '@/composables/useDownloadProgress'
import FileViewer from '@/components/FileViewer.vue'
import ServiceIntro from '@/components/ServiceIntro.vue'
import QuickSignDialog from '@/components/QuickSignDialog.vue'

const activeTab = ref('apply')
const submitting = ref(false)
// 上传进度百分比（算不出总大小时为 0，就不显示数字）
const uploadProgress = ref(0)
// 下载请假表的进度（同一时间只跑一个）
const { percent: downloadPercent, isDownloading, run: runDownload } = useDownloadProgress()
const loading = ref(false)
const leaves = ref([])
const formRef = ref(null)
const fileList = ref([])
// 签名检查：勾「确认签字」或提交时发现没有签字图，就弹窗手写
const signGuard = ref(null)
// 正在修改的那条记录（null = 新建）。改完走 PUT 覆盖原记录，不会又多出一条
const editingId = ref(null)

// 起止时间都是 'YYYY-MM-DD HH:00' 这种字符串，交给后端解析成 datetime
const form = reactive({
  leave_type: '病假',
  start_at: '',
  end_at: '',
  reason: '',
  travel_mode: '',
  travel_detail: '',
  destination: '',
  destination_phone: '',
  agreed: false,
  promised: false,        // 认下审批表上「本人承诺」栏的两条
  signConfirmed: false    // 会在审批表上签字
})

/** 三个勾选项的校验只有提示语不同，共用一份 */
function mustCheck(message) {
  return [
    {
      validator: (_, value, callback) => {
        if (!value) callback(new Error(message))
        else callback()
      },
      trigger: 'change'
    }
  ]
}

const rules = {
  leave_type: [{ required: true, message: '请选择请假类型', trigger: 'change' }],
  start_at: [{ required: true, message: '请选择开始时间', trigger: 'change' }],
  end_at: [{ required: true, message: '请选择结束时间', trigger: 'change' }],
  reason: [{ required: true, message: '请填写请假事由', trigger: 'blur' }],
  // 证明文件存在 fileList 里、不在 form 上，所以不能用 required：
  // required 读的是 form.proof，恒为 undefined，会把提交永远卡住
  proof: [
    {
      validator: (_, __, callback) => {
        // 修改时可以不重选：不选就沿用原来那份（后端 PUT 的 proof 字段就是这么定的）
        if (editingId.value || fileList.value.length) callback()
        else callback(new Error('请上传请假辅助证明'))
      },
      trigger: 'change'
    }
  ],
  agreed: mustCheck('请先勾选同意条款'),
  promised: mustCheck('请先勾选承诺内容'),
  signConfirmed: mustCheck('请确认会在请假审批表上签字')
}

function parseTime(text) {
  // 'YYYY-MM-DD HH:00'，直接从字符串取，避免时区误差
  if (!text) return null
  const [date, time] = text.split(' ')
  const [y, m, d] = date.split('-').map(Number)
  return new Date(y, m - 1, d, Number((time || '0:00').split(':')[0]))
}

// 跨几个日历天（含起止当天），与后端生成 Word 时的算法保持一致
const days = computed(() => {
  const s = parseTime(form.start_at)
  const e = parseTime(form.end_at)
  if (!s || !e) return 0
  const a = new Date(s.getFullYear(), s.getMonth(), s.getDate())
  const b = new Date(e.getFullYear(), e.getMonth(), e.getDate())
  return Math.round((b - a) / 86400000) + 1
})

async function handleFileChange(file) {
  // 手机拍的证明动辄好几 MB，上传前先压小（PDF 不动，规则见 utils/imageCompress.js）。
  // 压完把 raw 换掉 —— 提交时取的就是它
  if (file.raw) file.raw = await compressImage(file.raw)
  fileList.value = [file]
  // 手动触发校验
  formRef.value?.validateField('proof')
}

function handleFileRemove() {
  fileList.value = []
  // 移掉文件后同步刷新提示，不然红字会一直留在原地
  formRef.value?.validateField('proof')
}

/** 清空表单，回到「新建」状态 */
function resetForm() {
  Object.assign(form, {
    leave_type: '病假',
    start_at: '',
    end_at: '',
    reason: '',
    travel_mode: '',
    travel_detail: '',
    destination: '',
    destination_phone: '',
    agreed: false,
    promised: false,
    signConfirmed: false
  })
  fileList.value = []
  editingId.value = null
}

/** 修改：把这条记录预填进表单并切回表单那一栏 */
function startEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    leave_type: row.leave_type,
    // 后端给的是 ISO（2026-10-15T08:00:00），选择器要的是 'YYYY-MM-DD HH:00'
    start_at: toPickerValue(row.start_at),
    end_at: toPickerValue(row.end_at),
    reason: row.reason,
    travel_mode: row.travel_mode || '',
    travel_detail: row.travel_detail || '',
    destination: row.destination || '',
    destination_phone: row.destination_phone || '',
    // 三条承诺是每次提交都要认一遍的话，不替申请人预勾
    agreed: false,
    promised: false,
    signConfirmed: false
  })
  fileList.value = []
  activeTab.value = 'apply'
  formRef.value?.clearValidate()
}

function cancelEdit() {
  resetForm()
  activeTab.value = 'history'
}

function toPickerValue(value) {
  return value ? formatDateTime(value).slice(0, 13) + ':00' : ''
}

/**
 * 勾选「我确认在请假审批表上签字」时顺手检查签字图：没有就当场手写。
 * 手写被取消时把这个勾去掉 —— 没提供签名就不算确认过。
 */
async function handleSignConfirmedChange(value) {
  if (!value) return
  if (await signGuard.value?.ensure()) return
  form.signConfirmed = false
}

async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch (e) {
    return
  }

  if (new Date(form.end_at.replace(' ', 'T')) <= new Date(form.start_at.replace(' ', 'T'))) {
    return ElMessage.warning('结束时间必须晚于开始时间')
  }

  if (!editingId.value && !fileList.value.length) {
    return ElMessage.warning('请上传请假辅助证明')
  }

  // 审批表上要印本人签字，系统里没有就先手写一张（签完自动保存并继续提交）
  if (!(await signGuard.value?.ensure())) return

  const fd = new FormData()
  fd.append('leave_type', form.leave_type)
  fd.append('start_at', form.start_at)
  fd.append('end_at', form.end_at)
  fd.append('reason', form.reason)
  fd.append('travel_mode', form.travel_mode)
  fd.append('travel_detail', form.travel_detail)
  fd.append('destination', form.destination)
  fd.append('destination_phone', form.destination_phone)
  // el-upload 的 raw 才是真实文件对象。
  // 修改时不选文件就是「证明不动」，所以这个地方是空的就别 append 了
  if (fileList.value.length) {
    fd.append('proof', fileList.value[0].raw || fileList.value[0])
  }

  const onProgress = (loaded, total) => {
    uploadProgress.value = total ? Math.round((loaded / total) * 100) : 0
  }

  submitting.value = true
  uploadProgress.value = 0
  try {
    if (editingId.value) {
      await updateLeave(editingId.value, fd, onProgress)
      ElMessage.success('已保存修改')
    } else {
      await submitLeave(fd, onProgress)
      ElMessage.success('申请已提交，等待管理员审核')
    }
    // 切到记录页
    activeTab.value = 'history'
    await fetchLeaves()
    resetForm()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

/** 撤销：只有待受理能撤，撤了就真删掉了（连证明材料） */
function handleDelete(row) {
  ElMessageBox.confirm(
    '撤销后这条申请和证明材料都会被删掉，不能恢复。',
    '撤销申请',
    { confirmButtonText: '撤销', cancelButtonText: '再想想', type: 'warning' }
  ).then(async () => {
    try {
      await deleteLeave(row.id)
      ElMessage.success('已撤销')
      // 撤的正好是正在改的那条，就别让表单还停在「修改」上
      if (editingId.value === row.id) resetForm()
      fetchLeaves()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '撤销失败')
    }
  }).catch(() => {})
}

async function fetchLeaves() {
  loading.value = true
  try {
    leaves.value = await getMyLeaves()
  } catch (e) {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

// 证明材料预览
const proofViewerVisible = ref(false)
const proofFileUrl = ref('')
const proofFileName = ref('')

function viewProof(row) {
  proofFileUrl.value = `/api/leaves/${row.id}/proof`
  proofFileName.value = row.proof_original_name || '证明材料'
  proofViewerVisible.value = true
}

async function downloadPdf(row) {
  try {
    await runDownload(`leave-${row.id}`, async (onProgress) => {
      const blob = await downloadLeavePdf(row.id, onProgress)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      // 只取日期部分做文件名，和后端生成的保持一致
      a.download = `${row.student_name}_请假审批表_${formatDate(row.start_at).replace(/-/g, '')}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    })
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e, '下载失败，请稍后重试'))
  }
}

onMounted(() => {
  fetchLeaves()
})
</script>

<style scoped>
.form-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

/* 修改模式的提示条。用 Element 的调色板变量，深色模式跟着一起变 */
.edit-hint {
  max-width: 640px;
  margin-bottom: 12px;
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  font-size: 13px;
}

/* 起止时间竖排两行，比一行 "a ~ b" 好读 */
.time-sep {
  font-size: 12px;
  color: var(--el-text-color-disabled);
  line-height: 1.4;
}

.el-upload__tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* 确认行：两句声明在手机上很长，而 Element Plus 的复选框默认
   white-space: nowrap 且高度写死 32px，文字既不能换行、换了也会被裁掉。
   这里放开换行、高度自适应，方框改成对齐第一行而不是整块垂直居中 */
.agree-checkbox {
  white-space: normal;
  height: auto;
  align-items: flex-start;
}

.agree-checkbox :deep(.el-checkbox__label) {
  line-height: 1.6;
}

/* 方框下移一点对齐第一行的中线（行高约 22px、方框 14px） */
.agree-checkbox :deep(.el-checkbox__input) {
  margin-top: 4px;
}

/* 两句声明分块显示，各占一行，不和行内折行混在一起 */
.agree-checkbox :deep(.el-checkbox__label) div + div {
  margin-top: 2px;
}
</style>
