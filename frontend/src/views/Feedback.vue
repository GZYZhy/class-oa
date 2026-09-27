<template>
  <div class="feedback-page">
    <div class="page-card">
      <h3 class="page-title">意见反馈</h3>

      <el-tabs v-model="activeTab">
        <!-- 提交反馈 -->
        <el-tab-pane label="提交反馈" name="submit">
          <el-form :model="form" :rules="rules" ref="formRef" label-width="80px" style="max-width: 640px;">
            <el-form-item label="标题" prop="title">
              <el-input
                v-model="form.title"
                placeholder="请简要概括您的意见或建议"
                maxlength="100"
                show-word-limit
              />
            </el-form-item>

            <el-form-item label="正文" prop="content">
              <el-input
                v-model="form.content"
                type="textarea"
                :rows="8"
                placeholder="请详细描述您的意见或建议，我们会认真对待每一条反馈"
                maxlength="5000"
                show-word-limit
              />
            </el-form-item>

            <el-form-item label="附件">
              <el-upload
                v-model:file-list="fileList"
                :auto-upload="false"
                :multiple="true"
                :limit="maxCount"
                :on-change="handleFileChange"
                :on-exceed="handleExceed"
                :accept="acceptTypes"
              >
                <el-button>选择文件</el-button>
                <template #tip>
                  <div class="el-upload__tip">
                    最多 {{ maxCount }} 个，单个不超过 20MB；支持图片 / 视频 / 音频 / 文档
                  </div>
                </template>
              </el-upload>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="submitting" @click="handleSubmit">
                提交反馈
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 我的反馈 -->
        <el-tab-pane label="我的反馈" name="my">
          <el-table :data="list" v-loading="loading" stripe border style="width: 100%;">
            <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.status === 'unread'" type="info" size="small">未读</el-tag>
                <el-tag v-else-if="row.status === 'read'" type="warning" size="small">已读</el-tag>
                <el-tag v-else-if="row.status === 'replied'" type="success" size="small">已回复</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="160" align="center">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="100" align="center">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="viewDetail(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-if="!loading && !list.length" description="暂无反馈记录" style="margin-top: 20px;" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="反馈详情" width="600px">
      <div v-if="current" class="detail-content">
        <div class="detail-header">
          <h4>{{ current.title }}</h4>
          <div class="detail-meta">
            <el-tag v-if="current.status === 'unread'" type="info" size="small">未读</el-tag>
            <el-tag v-else-if="current.status === 'read'" type="warning" size="small">已读</el-tag>
            <el-tag v-else-if="current.status === 'replied'" type="success" size="small">已回复</el-tag>
            <span class="detail-time">{{ formatDateTime(current.created_at) }}</span>
          </div>
        </div>
        <div class="detail-body">
          {{ current.content }}
        </div>

        <div v-if="current.attachments?.length" class="attachment-block">
          <div class="attachment-title">附件</div>
          <div v-for="item in current.attachments" :key="item.index" class="attachment-item">
            <el-icon><Paperclip /></el-icon>
            <span class="attachment-name" @click="downloadAttachment(current.id, item)">
              {{ item.name }}
            </span>
            <span class="attachment-size">{{ formatFileSize(item.size) }}</span>
          </div>
        </div>

        <div v-if="current.status === 'replied'" class="reply-block">
          <div class="reply-title">
            <el-icon><ChatDotRound /></el-icon>
            <span>班委回复</span>
          </div>
          <div class="reply-meta">
            {{ current.reply_name }}（{{ current.reply_no }}） · {{ formatDateTime(current.reply_at) }}
          </div>
          <div class="reply-content">{{ current.reply_content }}</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Paperclip } from '@element-plus/icons-vue'
import {
  getMyFeedback,
  submitFeedback,
  getMyFeedbackDetail,
  downloadFeedbackAttachment
} from '@/api/feedback'
import { formatDateTime, formatFileSize } from '@/utils/format'

// 与后端 ALLOWED_ATTACHMENT_EXTENSIONS 是同一份清单，改一边要跟着改另一边
const allowedExts = [
  '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic', '.heif',
  '.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm',
  '.mp3', '.m4a', '.wav',
  '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
  '.pdf', '.txt', '.md', '.wps', '.et', '.dps'
]
const acceptTypes = allowedExts.join(',')
const maxSize = 20 * 1024 * 1024
const maxCount = 3

const activeTab = ref('submit')
const submitting = ref(false)
const loading = ref(false)
const list = ref([])
const formRef = ref(null)
const detailVisible = ref(false)
const current = ref(null)
const fileList = ref([])

const form = reactive({
  title: '',
  content: ''
})

const rules = {
  title: [{ required: true, message: '请填写标题', trigger: 'blur' }],
  content: [{ required: true, message: '请填写反馈内容', trigger: 'blur' }]
}

/**
 * 选中文件时就校验，不合格的立刻从列表里摘掉 —— 等到点提交才报错的话，
 * 用户已经多填了一次表单。el-upload 的 accept 只是选择器过滤，
 * 用户在那台机器上仍能切到「所有文件」，所以后缀还得自己再判一次。
 */
function handleFileChange(file) {
  const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase()
  let reason = ''
  if (!allowedExts.includes(ext)) {
    reason = '格式不支持，仅支持图片 / 视频 / 音频 / 文档'
  } else if ((file.size || 0) > maxSize) {
    reason = '超过 20MB'
  }
  if (!reason) return

  ElMessage.error(`「${file.name}」${reason}`)
  // 从 fileList 当前的值里摘，不用 el-upload 回调传进来的数组：
  // 一次选中多个都不合法时，几个回调拿到的是同一份数组的旧快照，
  // 后一个会把前一个刚摘掉的文件又算回来
  fileList.value = fileList.value.filter((f) => f.uid !== file.uid)
}

/** 超出个数时 el-upload 默认一条提示都不弹（onExceed 默认是空函数），必须自己来 */
function handleExceed() {
  ElMessage.warning(`最多只能上传 ${maxCount} 个附件`)
}

async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch (e) {
    return
  }

  const fd = new FormData()
  fd.append('title', form.title.trim())
  fd.append('content', form.content.trim())
  // 字段名必须逐字是 attachments（后端 File(...) 的参数名），写错不会报错，
  // 只会静默把附件丢掉；同名重复 append，后端才收得到多个。
  // raw 才是真实文件对象
  fileList.value.forEach((f) => fd.append('attachments', f.raw || f))

  submitting.value = true
  try {
    await submitFeedback(fd)
    ElMessage.success('反馈已提交，感谢您的宝贵意见')
    form.title = ''
    form.content = ''
    fileList.value = []
    activeTab.value = 'my'
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

async function fetchList() {
  loading.value = true
  try {
    list.value = await getMyFeedback()
  } catch (e) {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

async function viewDetail(row) {
  try {
    current.value = await getMyFeedbackDetail(row.id)
    detailVisible.value = true
  } catch (e) {
    ElMessage.error('加载失败')
  }
}

/** index 用后端给的，不靠数组下标猜；下载名也只能自己给（见下） */
async function downloadAttachment(feedbackId, item) {
  try {
    const blob = await downloadFeedbackAttachment(feedbackId, item.index)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // blob: URL 上没有后端的 Content-Disposition，不给 download 名的话
    // 存下来是一串 UUID，看不出是什么文件
    a.download = item.name
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('附件下载失败')
  }
}

onMounted(fetchList)
</script>

<style scoped>
.feedback-page {
  max-width: 800px;
  margin: 0 auto;
}

.detail-header {
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 16px;
}

.detail-header h4 {
  margin: 0 0 8px 0;
  font-size: 16px;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #909399;
}

.detail-time {
  margin-left: auto;
}

.detail-body {
  line-height: 1.8;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}

.el-upload__tip {
  font-size: 12px;
  color: #909399;
}

.attachment-block {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
}

.attachment-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
}

.attachment-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #909399;
  padding: 4px 0;
}

/* 长文件名要能断行，否则会把大小挤出去、撑破弹窗 */
.attachment-name {
  color: #409eff;
  cursor: pointer;
  word-break: break-all;
}

.attachment-name:hover {
  text-decoration: underline;
}

.attachment-size {
  margin-left: auto;
  flex-shrink: 0;
}

.reply-block {
  margin-top: 20px;
  padding: 16px;
  background: #f0f9eb;
  border-radius: 8px;
  border-left: 4px solid #67c23a;
}

.reply-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #67c23a;
  margin-bottom: 8px;
}

.reply-meta {
  font-size: 12px;
  color: #909399;
  margin-bottom: 10px;
}

.reply-content {
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
