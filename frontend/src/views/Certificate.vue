<template>
  <div>
    <div class="page-card" v-loading="loading">
      <ServiceIntro
        intro="开具在读证明、实习介绍信等文书。"
        deadline="7 个工作日（仅供参考）"
        :notice="'仅限班委出具的文书；学院或学校证明请另行办理。\n提交前请先与班委联系。'"
        submitted="依据材料，PDF / 图片 / Word，单个 ≤20MB，最多 3 个，必填"
        finished="班委上传的成品（PDF），审批后可下载"
      />

      <el-tabs v-model="activeTab">
        <!-- ============ 申请开具 ============ -->
        <el-tab-pane :label="editingId ? '修改申请' : '申请开具'" name="apply">
          <!-- 修改这条申请时把表单预填成它的内容，提交走 PUT 覆盖原记录 -->
          <div v-if="editingId" class="edit-hint">
            正在修改申请，未重新上传的附件保持不变。
          </div>

          <el-form ref="formRef" :model="form" :rules="rules" label-width="110px" style="max-width: 640px;">
            <el-form-item label="证明标题" prop="title">
              <el-input v-model="form.title" placeholder="如：在读证明 / 实习介绍信" maxlength="200" />
            </el-form-item>
            <el-form-item label="收文单位" prop="recipient">
              <el-input v-model="form.recipient" placeholder="请填写收文单位全称" maxlength="200" />
            </el-form-item>
            <el-form-item label="证明正文" prop="content">
              <el-input
                v-model="form.content"
                type="textarea"
                :rows="5"
                placeholder="请写明需要证明的具体内容"
                maxlength="3000"
                show-word-limit
              />
            </el-form-item>
            <el-form-item label="其他要求">
              <el-input
                v-model="form.extra_request"
                type="textarea"
                :rows="3"
                placeholder="如份数、格式、特殊抬头要求等（选填）"
                maxlength="1000"
                show-word-limit
              />
            </el-form-item>
            <el-form-item label="申请依据" prop="attachments">
              <el-upload
                ref="uploadRef"
                :auto-upload="false"
                :limit="3"
                :on-change="handleFileChange"
                :on-remove="handleFileRemove"
                :file-list="fileList"
                accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp,.doc,.docx"
                multiple
              >
                <el-button type="primary" plain>
                  <el-icon><Upload /></el-icon>
                  选择文件
                </el-button>
                <template #tip>
                  <div v-if="editingId" class="el-upload__tip">
                    支持 PDF / 图片 / Word，每个文件不超过 20MB，最多 3 个。超过 1MB 的图片会自动压缩；不重选就沿用当前那批
                  </div>
                  <div v-else class="el-upload__tip">
                    支持 PDF / 图片 / Word，每个文件不超过 20MB，最多 3 个。超过 1MB 的图片会自动压缩
                  </div>
                </template>
              </el-upload>
            </el-form-item>
            <el-form-item prop="confirmed" class="confirm-item">
              <el-checkbox v-model="form.confirmed">
                我确认信息真实有效，提交前已与班委联系
              </el-checkbox>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="submitting" @click="handleSubmit">
                {{ editingId ? '保存修改' : '提交申请' }}{{ submitting && uploadProgress ? ` ${uploadProgress}%` : '' }}
              </el-button>
              <el-button v-if="editingId" @click="cancelEdit">取消修改</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- ============ 我的申请 ============ -->
        <el-tab-pane label="我的申请" name="mine">
          <el-table :data="list" stripe border style="width: 100%;">
            <el-table-column prop="title" label="证明标题" min-width="180" show-overflow-tooltip align="left" />
            <el-table-column prop="recipient" label="收文单位" min-width="180" show-overflow-tooltip align="left" />
            <el-table-column prop="created_at" label="申请时间" width="160" align="center">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
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
            <el-table-column label="操作" min-width="340" align="center">
              <template #default="{ row }">
                <template v-if="row.attachments?.length">
                  <el-button
                    type="primary"
                    link
                    size="small"
                    @click="viewAttachment(row, 0)"
                  >
                    查看附件
                  </el-button>
                </template>
                <template v-if="row.status === 'approved'">
                  <el-button
                    v-if="row.result_original_name"
                    type="success"
                    link
                    size="small"
                    :loading="isDownloading(`cert-${row.id}`)"
                    @click="downloadResult(row)"
                  >
                    {{ isDownloading(`cert-${row.id}`) && downloadPercent
                      ? `${downloadPercent}%` : '下载证明' }}
                  </el-button>
                  <span v-else style="color: #e6a23c; font-size: 12px;">成品上传中…</span>
                </template>
                <template v-if="row.status === 'rejected' && row.reject_reason">
                  <el-tooltip :content="row.reject_reason" placement="top">
                    <span style="color: #f56c6c; font-size: 12px; cursor: help;">驳回原因</span>
                  </el-tooltip>
                </template>
                <!-- 退回补正的理由是让申请人照办的话，得看得见才补得对 -->
                <el-tooltip
                  v-if="row.status === 'correcting' && row.correction_reason"
                  :content="row.correction_reason"
                  placement="top"
                >
                  <span style="color: #e6a23c; font-size: 12px; cursor: help;">补正说明</span>
                </el-tooltip>
                <!-- 待受理、待补正都能改；撤只有待受理能撤（受理过的要撤得找班委先撤回受理） -->
                <el-button
                  v-if="row.status === 'pending' || row.status === 'correcting'"
                  type="warning"
                  link
                  size="small"
                  @click="startEdit(row)"
                >
                  修改
                </el-button>
                <el-button
                  v-if="row.status === 'pending'"
                  type="danger"
                  link
                  size="small"
                  @click="handleDelete(row)"
                >
                  撤销
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!list.length" description="暂无申请记录" style="margin-top: 20px;" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 附件预览弹框 -->
    <FileViewer
      v-model="attachmentViewerVisible"
      :file-url="attachmentFileUrl"
      :file-name="attachmentFileName"
      title="申请依据附件"
    />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { syncRecordTab } from '@/composables/recordTab'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import {
  getMyCertificates,
  submitCertificate,
  updateCertificate,
  deleteCertificate,
  downloadCertificateAttachment,
  downloadCertificateResult
} from '@/api/certificate'
import { formatDateTime, formatFileSize } from '@/utils/format'
import { compressImage } from '@/utils/imageCompress'
import { blobErrorDetail, downloadFile } from '@/utils/download'
import { useDownloadProgress } from '@/composables/useDownloadProgress'
import FileViewer from '@/components/FileViewer.vue'
import ServiceIntro from '@/components/ServiceIntro.vue'

const activeTab = ref('apply')
// 从站内信 / 办件空间的「详情」进来时带 ?tab=record，直接落在记录页签
syncRecordTab(activeTab, 'mine')
const loading = ref(false)
const submitting = ref(false)
const uploadProgress = ref(0)
// 下载成品证明的进度（同一时间只跑一个）
const { percent: downloadPercent, isDownloading, run: runDownload } = useDownloadProgress()
const list = ref([])
const formRef = ref(null)
const uploadRef = ref(null)
// 正在修改的那条记录（null = 新建）。改完走 PUT 覆盖原记录，不会又多出一条
const editingId = ref(null)

const form = reactive({
  title: '',
  recipient: '',
  content: '',
  extra_request: '',
  confirmed: false
})

// 文件列表（el-upload 格式）
const fileList = ref([])
// 实际提交用的 File 对象数组
const selectedFiles = ref([])

const validateAttachments = (_rule, _value, callback) => {
  // 修改时可以不重选：不选就沿用原来那批（后端 PUT 的 attachments 字段就是这么定的）
  if (selectedFiles.value.length === 0 && !editingId.value) {
    callback(new Error('请至少上传一个申请依据附件'))
  } else {
    callback()
  }
}
const validateConfirmed = (_rule, _value, callback) => {
  if (!form.confirmed) callback(new Error('请勾选确认'))
  else callback()
}

const rules = {
  title: [{ required: true, message: '请填写证明标题', trigger: 'blur' }],
  recipient: [{ required: true, message: '请填写收文单位', trigger: 'blur' }],
  content: [{ required: true, message: '请填写证明正文', trigger: 'blur' }],
  attachments: [{ validator: validateAttachments, trigger: 'change' }],
  confirmed: [{ validator: validateConfirmed, trigger: 'change' }]
}

function handleFileChange(file) {
  if (!file.raw) return
  // 图片附件先压小（PDF / Word 原样，规则见 utils/imageCompress.js）。
  // 任务挂在文件上，提交时会等它
  file.__compressTask = (async () => {
    const compressed = await compressImage(file.raw)
    if (compressed === file.raw) return
    file.raw = compressed
    file.name = compressed.name
    file.size = compressed.size
  })()

  file.__compressTask.then(() => {
    if (file.raw.size > 20 * 1024 * 1024) {
      ElMessage.error(`文件「${file.name}」超过 20MB`)
      // 从 fileList 里移除
      fileList.value = fileList.value.filter(f => f.uid !== file.uid)
      return
    }
    // 保持顺序
    selectedFiles.value = fileList.value.map(f => f.raw).filter(Boolean)
    formRef.value?.validateField('attachments')
  })
}

function handleFileRemove(file) {
  selectedFiles.value = fileList.value.filter(f => f.uid !== file.uid).map(f => f.raw).filter(Boolean)
  formRef.value?.validateField('attachments')
}

/** 清空表单，回到「新建」状态 */
function resetForm() {
  form.title = ''
  form.recipient = ''
  form.content = ''
  form.extra_request = ''
  form.confirmed = false
  fileList.value = []
  selectedFiles.value = []
  editingId.value = null
  uploadRef.value?.clearFiles()
}

/** 修改：把这条记录预填进表单并切回申请那一栏 */
function startEdit(row) {
  editingId.value = row.id
  form.title = row.title
  form.recipient = row.recipient
  form.content = row.content
  form.extra_request = row.extra_request || ''
  // 附件不预填（拿不到原来的 File 对象），不重选后端就沿用原来那批
  fileList.value = []
  selectedFiles.value = []
  // 「信息真实有效、已与班委联系」是每次提交都要认一遍的话，不替申请人预勾
  form.confirmed = false
  uploadRef.value?.clearFiles()
  activeTab.value = 'apply'
  formRef.value?.clearValidate()
}

function cancelEdit() {
  resetForm()
  activeTab.value = 'mine'
}

// 提交 / 保存修改
async function handleSubmit() {
  if (!formRef.value) return
  // 刚选的图可能还在压：等它们落地再校验、再取文件，别把原图或空列表交上去
  await Promise.all(fileList.value.map((f) => f.__compressTask).filter(Boolean))
  selectedFiles.value = fileList.value.map((f) => f.raw).filter(Boolean)
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  const data = {
    title: form.title.trim(),
    recipient: form.recipient.trim(),
    content: form.content.trim(),
    extra_request: form.extra_request.trim(),
    files: selectedFiles.value
  }
  const onProgress = (loaded, total) => {
    uploadProgress.value = total ? Math.round((loaded / total) * 100) : 0
  }

  submitting.value = true
  uploadProgress.value = 0
  try {
    if (editingId.value) {
      await updateCertificate(editingId.value, data, onProgress)
      ElMessage.success('已保存修改')
    } else {
      await submitCertificate(data, onProgress)
      ElMessage.success('提交成功，等待管理员审核')
    }
    activeTab.value = 'mine'
    fetchList()
    resetForm()
  } catch (e) {
    ElMessage.error('提交失败：' + (e.response?.data?.detail || e.message))
  } finally {
    submitting.value = false
  }
}

/** 撤销：只有待受理能撤，撤了就真删掉了（连附件） */
function handleDelete(row) {
  ElMessageBox.confirm(
    '撤销后这条申请和附件都会被删掉，不能恢复。',
    '撤销申请',
    { confirmButtonText: '撤销', cancelButtonText: '再想想', type: 'warning' }
  ).then(async () => {
    try {
      await deleteCertificate(row.id)
      ElMessage.success('已撤销')
      // 撤的正好是正在改的那条，就别让表单还停在「修改」上
      if (editingId.value === row.id) resetForm()
      fetchList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '撤销失败')
    }
  }).catch(() => {})
}

// 附件预览
const attachmentViewerVisible = ref(false)
const attachmentFileUrl = ref('')
const attachmentFileName = ref('')
const _currentRow = ref(null)
const _currentIndex = ref(0)

function viewAttachment(row, index) {
  if (!row.attachments?.length) return
  _currentRow.value = row
  _currentIndex.value = index
  const item = row.attachments[index]
  attachmentFileUrl.value = `/api/certificates/${row.id}/attachment/${index}`
  attachmentFileName.value = item.name
  attachmentViewerVisible.value = true
}

// 下载成品
async function downloadResult(row) {
  try {
    await runDownload(`cert-${row.id}`, (onProgress) =>
      downloadFile(
        `/api/certificates/${row.id}/result`,
        row.result_original_name || `证明_${row.title}.pdf`,
        onProgress
      )
    )
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e))
  }
}

async function fetchList() {
  loading.value = true
  try {
    list.value = await getMyCertificates()
  } catch (e) {
    ElMessage.error('申请记录加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(fetchList)
</script>

<style scoped>
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

/* 复选框折行：窄屏下长句子能正常换行，勾选框对齐第一行 */
.confirm-item :deep(.el-form-item__content) {
  line-height: 1.5;
}

.confirm-item :deep(.el-checkbox) {
  align-items: flex-start;
  height: auto;
  white-space: normal;
}

.confirm-item :deep(.el-checkbox__input) {
  margin-top: 2px;
}
</style>
