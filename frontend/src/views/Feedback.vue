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
import { ChatDotRound } from '@element-plus/icons-vue'
import { getMyFeedback, submitFeedback, getMyFeedbackDetail } from '@/api/feedback'
import { formatDateTime } from '@/utils/format'

const activeTab = ref('submit')
const submitting = ref(false)
const loading = ref(false)
const list = ref([])
const formRef = ref(null)
const detailVisible = ref(false)
const current = ref(null)

const form = reactive({
  title: '',
  content: ''
})

const rules = {
  title: [{ required: true, message: '请填写标题', trigger: 'blur' }],
  content: [{ required: true, message: '请填写反馈内容', trigger: 'blur' }]
}

async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch (e) {
    return
  }

  submitting.value = true
  try {
    await submitFeedback({
      title: form.title.trim(),
      content: form.content.trim()
    })
    ElMessage.success('反馈已提交，感谢您的宝贵意见')
    form.title = ''
    form.content = ''
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
