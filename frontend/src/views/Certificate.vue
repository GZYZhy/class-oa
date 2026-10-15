<template>
  <div>
    <div class="page-card" v-loading="loading">
      <ServiceIntro
        :notice="'班委会开具的介绍信公信力有限，如需学院或学校证明、各类导师签字的文件，请勿在此提交。\n提交前请与班委联系。'"
        submitted="申请依据材料，支持 PDF / 图片 / Word，单个不超过 20MB，最多 3 个，必填"
        finished="由班委上传的证明成品（PDF），审核通过后可下载"
      />

      <el-tabs v-model="activeTab">
        <!-- ============ 申请开具 ============ -->
        <el-tab-pane label="申请开具" name="apply">
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
                  <div class="el-upload__tip">支持 PDF / 图片 / Word，每个文件不超过 20MB，最多 3 个</div>
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
                提交申请{{ submitting && uploadProgress ? ` ${uploadProgress}%` : '' }}
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- ============ 我的申请 ============ -->
        <el-tab-pane label="我的申请" name="mine">
          <el-table :data="list" stripe border style="width: 100%;">
            <el-table-column prop="title" label="证明标题" min-width="180" show-overflow-tooltip />
            <el-table-column prop="recipient" label="收文单位" min-width="180" show-overflow-tooltip />
            <el-table-column prop="created_at" label="申请时间" width="160" align="center">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.status === 'pending'" type="warning" size="small">待审核</el-tag>
                <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
                <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="280" align="center">
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
                    :loading="downloadingId === row.id"
                    @click="downloadResult(row)"
                  >
                    下载证明
                  </el-button>
                  <span v-else style="color: #e6a23c; font-size: 12px;">成品上传中…</span>
                </template>
                <template v-if="row.status === 'rejected' && row.reject_reason">
                  <el-tooltip :content="row.reject_reason" placement="top">
                    <span style="color: #f56c6c; font-size: 12px; cursor: help;">驳回原因</span>
                  </el-tooltip>
                </template>
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
import { ElMessage } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import {
  getMyCertificates,
  submitCertificate,
  downloadCertificateAttachment,
  downloadCertificateResult
} from '@/api/certificate'
import { formatDateTime, formatFileSize } from '@/utils/format'
import { blobErrorDetail, downloadFile } from '@/utils/download'
import FileViewer from '@/components/FileViewer.vue'
import ServiceIntro from '@/components/ServiceIntro.vue'

const activeTab = ref('apply')
const loading = ref(false)
const submitting = ref(false)
const uploadProgress = ref(0)
const downloadingId = ref(null)
const list = ref([])
const formRef = ref(null)

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
  if (selectedFiles.value.length === 0) {
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
  const raw = file.raw
  if (!raw) return
  if (raw.size > 20 * 1024 * 1024) {
    ElMessage.error(`文件「${file.name}」超过 20MB`)
    // 从 fileList 里移除
    fileList.value = fileList.value.filter(f => f.uid !== file.uid)
    return
  }
  // 保持顺序
  selectedFiles.value = fileList.value.map(f => f.raw).filter(Boolean)
  formRef.value?.validateField('attachments')
}

function handleFileRemove(file) {
  selectedFiles.value = fileList.value.filter(f => f.uid !== file.uid).map(f => f.raw).filter(Boolean)
  formRef.value?.validateField('attachments')
}

// 提交
async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  submitting.value = true
  uploadProgress.value = 0
  try {
    await submitCertificate({
      title: form.title.trim(),
      recipient: form.recipient.trim(),
      content: form.content.trim(),
      extra_request: form.extra_request.trim(),
      files: selectedFiles.value
    }, (loaded, total) => {
      uploadProgress.value = total ? Math.round((loaded / total) * 100) : 0
    })
    ElMessage.success('提交成功，等待管理员审核')
    // 重置表单
    form.title = ''
    form.recipient = ''
    form.content = ''
    form.extra_request = ''
    form.confirmed = false
    fileList.value = []
    selectedFiles.value = []
    activeTab.value = 'mine'
    fetchList()
  } catch (e) {
    ElMessage.error('提交失败：' + (e.response?.data?.detail || e.message))
  } finally {
    submitting.value = false
  }
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
  downloadingId.value = row.id
  try {
    await downloadFile(
      `/api/certificates/${row.id}/result`,
      row.result_original_name || `证明_${row.title}.pdf`
    )
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e))
  } finally {
    downloadingId.value = null
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
