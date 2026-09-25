<template>
  <div class="page-card" v-loading="loading">
    <!-- 这里全是同学的家庭地址、邮箱这类信息，盖一层「谁在看」的水印 -->
    <Watermark :text="watermarkText" />

    <h3 class="page-title" style="margin-bottom: 12px;">审核审批</h3>

    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <!-- ============ 信息修改申请 ============ -->
      <el-tab-pane label="信息修改申请" name="change">
        <div class="tab-toolbar">
          <el-radio-group v-model="changeStatus" size="small" @change="fetchChangeList">
            <el-radio-button value="pending">待审核</el-radio-button>
            <el-radio-button value="approved">已通过</el-radio-button>
            <el-radio-button value="rejected">已驳回</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="changeList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" width="150" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: #909399;">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column label="申请时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>

          <!-- 新旧值对照：左边是学生现在库里的值，右边是申请改成什么 -->
          <el-table-column label="修改内容（原值 → 新值）" min-width="340">
            <template #default="{ row }">
              <div v-for="(next, key) in row.changes" :key="key" class="diff-line">
                <span class="diff-label">{{ FIELD_LABELS[key] || key }}</span>
                <span class="diff-old">{{ row.current?.[key] || '（空）' }}</span>
                <el-icon class="diff-arrow"><Right /></el-icon>
                <span class="diff-new">{{ next || '（清空）' }}</span>
              </div>
              <span v-if="!Object.keys(row.changes || {}).length" style="color: #c0c4cc;">-</span>
            </template>
          </el-table-column>

          <el-table-column label="状态" width="120" align="center">
            <template #default="{ row }">
              <el-tag :type="STATUS_TYPES[row.status]" size="small">
                {{ STATUS_LABELS[row.status] || row.status }}
              </el-tag>
              <div v-if="row.reviewer_name" style="font-size: 12px; color: #909399; margin-top: 4px;">
                {{ row.reviewer_name }}
                <div>{{ formatDateTime(row.reviewed_at) }}</div>
              </div>
              <div v-if="row.reason" style="font-size: 12px; color: #f56c6c; margin-top: 4px;">
                {{ row.reason }}
              </div>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="150" align="center">
            <template #default="{ row }">
              <template v-if="row.status === 'pending' && userStore.isAdmin">
                <el-button type="success" link @click="handleApproveChange(row)">通过</el-button>
                <el-button type="danger" link @click="handleRejectChange(row)">驳回</el-button>
              </template>
              <span v-else-if="row.status === 'pending'" style="color: #909399; font-size: 12px;">
                需管理员审批
              </span>
              <span v-else style="color: #c0c4cc;">已处理</span>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !changeList.length" description="没有修改申请" style="margin-top: 20px;" />
      </el-tab-pane>

      <!-- ============ 请假申请 ============ -->
      <el-tab-pane label="请假申请" name="leave">
        <div class="tab-toolbar">
          <el-radio-group v-model="leaveStatus" size="small" @change="fetchLeaveList">
            <el-radio-button value="pending">待审核</el-radio-button>
            <el-radio-button value="approved">已通过</el-radio-button>
            <el-radio-button value="rejected">已驳回</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="leaveList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" width="150" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: #909399;">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="leave_type" label="类型" width="70" align="center" />
          <el-table-column label="请假时间" width="160" align="center">
            <template #default="{ row }">
              <div>{{ formatDateTime(row.start_at) }}</div>
              <div class="time-sep">至</div>
              <div>{{ formatDateTime(row.end_at) }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="事由" min-width="160" show-overflow-tooltip />
          <el-table-column label="状态" width="110" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'pending'" type="warning" size="small">待审核</el-tag>
              <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
              <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="申请时间" width="150" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="280" align="center">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="viewLeaveProof(row)">
                证明材料
              </el-button>
              <el-button
                v-if="row.status === 'approved'"
                size="small"
                link
                type="success"
                @click="handleDownloadLeaveDocx(row)"
              >
                下载请假表
              </el-button>
              <template v-if="row.status === 'pending'">
                <el-button
                  v-if="userStore.isAdmin"
                  size="small"
                  link
                  type="success"
                  @click="handleApproveLeave(row)"
                >
                  通过
                </el-button>
                <el-button
                  v-if="userStore.isAdmin"
                  size="small"
                  link
                  type="danger"
                  @click="handleRejectLeave(row)"
                >
                  驳回
                </el-button>
                <span v-else style="color: #909399; font-size: 12px;">需管理员审批</span>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !leaveList.length" description="没有请假申请" style="margin-top: 20px;" />
      </el-tab-pane>

      <!-- ============ 意见反馈 ============ -->
      <el-tab-pane label="意见反馈" name="feedback">
        <div class="tab-toolbar">
          <el-radio-group v-model="feedbackStatus" size="small" @change="fetchFeedbackList">
            <el-radio-button value="unread">未读</el-radio-button>
            <el-radio-button value="read">已读</el-radio-button>
            <el-radio-button value="replied">已回复</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="feedbackList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="提交人" width="140" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: #909399;">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'unread'" type="info" size="small">未读</el-tag>
              <el-tag v-else-if="row.status === 'read'" type="warning" size="small">已读</el-tag>
              <el-tag v-else-if="row.status === 'replied'" type="success" size="small">已回复</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="提交时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="180" align="center">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="viewFeedback(row)">
                查看
              </el-button>
              <el-button
                v-if="row.status === 'unread'"
                size="small"
                link
                type="warning"
                @click="handleMarkRead(row)"
              >
                标为已读
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !feedbackList.length" description="暂无反馈" style="margin-top: 20px;" />
      </el-tab-pane>
    </el-tabs>

    <!-- 反馈详情弹窗 -->
    <el-dialog v-model="feedbackDetailVisible" title="反馈详情" width="600px">
      <div v-if="currentFeedback" class="detail-content">
        <div class="detail-header">
          <h4>{{ currentFeedback.title }}</h4>
          <div class="detail-meta">
            <span>{{ currentFeedback.student_name }}（{{ currentFeedback.student_no }}）</span>
            <span class="detail-time">{{ formatDateTime(currentFeedback.created_at) }}</span>
          </div>
        </div>
        <div class="detail-body">{{ currentFeedback.content }}</div>

        <!-- 回复区 -->
        <div v-if="currentFeedback.status === 'replied'" class="reply-block">
          <div class="reply-title">
            <el-icon><ChatDotRound /></el-icon>
            <span>已回复</span>
          </div>
          <div class="reply-meta">
            {{ currentFeedback.reply_name }}（{{ currentFeedback.reply_no }}） ·
            {{ formatDateTime(currentFeedback.reply_at) }}
          </div>
          <div class="reply-content">{{ currentFeedback.reply_content }}</div>
        </div>

        <div v-if="currentFeedback.status !== 'replied'" class="reply-form">
          <el-divider>回复</el-divider>
          <el-input
            v-model="replyContent"
            type="textarea"
            :rows="4"
            placeholder="请输入回复内容"
            maxlength="2000"
            show-word-limit
          />
          <div style="margin-top: 12px; text-align: right;">
            <el-button type="primary" :loading="replying" @click="handleReply">
              提交回复
            </el-button>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Right, ChatDotRound } from '@element-plus/icons-vue'
import {
  getChangeRequests,
  approveChangeRequest,
  rejectChangeRequest
} from '@/api/changeRequest'
import {
  getLeaveList,
  approveLeave,
  rejectLeave,
  downloadLeaveProof,
  downloadLeaveDocx as apiDownloadLeaveDocx
} from '@/api/leave'
import {
  getFeedbackList,
  getFeedbackDetail,
  markFeedbackRead,
  replyFeedback
} from '@/api/feedback'
import { FIELD_LABELS, STATUS_LABELS, STATUS_TYPES } from '@/utils/changeFields'
import { formatDate, formatDateTime } from '@/utils/format'
import Watermark from '@/components/Watermark.vue'
import { useWatermark } from '@/composables/useWatermark'
import { useUserStore } from '@/store/user'

const userStore = useUserStore()
const watermarkText = useWatermark()

const route = useRoute()

const loading = ref(false)
// 从推送点进来时带着 ?tab=leave 之类的参数，直接落到对应分类；
// 不带参数（正常从菜单进）就还是老样子，停在信息修改申请
const TABS = ['change', 'leave', 'feedback']
const activeTab = ref(TABS.includes(route.query.tab) ? route.query.tab : 'change')

// —— 信息修改申请 ——
const changeList = ref([])
const changeStatus = ref('pending')

async function fetchChangeList() {
  loading.value = true
  try {
    changeList.value = await getChangeRequests({ status: changeStatus.value || undefined })
  } catch (e) {
    ElMessage.error('申请列表加载失败')
  } finally {
    loading.value = false
  }
}

async function handleApproveChange(row) {
  try {
    await ElMessageBox.confirm(
      `确定通过「${row.student_name}」的修改申请吗？通过后立即写入其学生信息。`,
      '审核确认',
      { type: 'warning', confirmButtonText: '通过', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 取消
  }
  try {
    await approveChangeRequest(row.id)
    ElMessage.success('已通过，修改已生效')
    fetchChangeList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleRejectChange(row) {
  let reason
  try {
    const res = await ElMessageBox.prompt('请填写驳回理由，会展示给申请人', '驳回申请', {
      inputPlaceholder: '如：请填写真实邮箱',
      inputValidator: (v) => (v && v.trim() ? true : '请填写驳回理由'),
      confirmButtonText: '驳回',
      cancelButtonText: '取消'
    })
    reason = res.value.trim()
  } catch (e) {
    return // 取消
  }
  try {
    await rejectChangeRequest(row.id, reason)
    ElMessage.success('已驳回')
    fetchChangeList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

// —— 请假申请 ——
const leaveList = ref([])
const leaveStatus = ref('pending')

async function fetchLeaveList() {
  loading.value = true
  try {
    leaveList.value = await getLeaveList(leaveStatus.value || undefined)
  } catch (e) {
    ElMessage.error('请假列表加载失败')
  } finally {
    loading.value = false
  }
}

function viewLeaveProof(row) {
  downloadLeaveProof(row.id).then(blob => {
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
  }).catch(e => {
    ElMessage.error(e?.response?.data?.detail || '打开失败')
  })
}

function handleApproveLeave(row) {
  ElMessageBox.confirm(
    `确定通过「${row.student_name}」的${row.leave_type}申请吗？\n` +
    `时间：${formatDateTime(row.start_at)} 至 ${formatDateTime(row.end_at)}`,
    '审批确认',
    { type: 'warning', confirmButtonText: '通过', cancelButtonText: '取消' }
  ).then(async () => {
    try {
      await approveLeave(row.id)
      ElMessage.success('已通过')
      fetchLeaveList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

function handleRejectLeave(row) {
  ElMessageBox.prompt('请填写驳回理由，会展示给申请人', '驳回申请', {
    inputPlaceholder: '如：证明材料不完整',
    inputValidator: (v) => (v && v.trim() ? true : '请填写驳回理由'),
    confirmButtonText: '驳回',
    cancelButtonText: '取消'
  }).then(async ({ value }) => {
    try {
      await rejectLeave(row.id, value.trim())
      ElMessage.success('已驳回')
      fetchLeaveList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

function handleDownloadLeaveDocx(row) {
  apiDownloadLeaveDocx(row.id).then(blob => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${row.student_name}_请假审批表_${formatDate(row.start_at).replace(/-/g, '')}.docx`
    a.click()
    URL.revokeObjectURL(url)
  }).catch(e => {
    ElMessage.error(e?.response?.data?.detail || '下载失败')
  })
}

// —— 意见反馈 ——
const feedbackList = ref([])
const feedbackStatus = ref('unread')
const feedbackDetailVisible = ref(false)
const currentFeedback = ref(null)
const replyContent = ref('')
const replying = ref(false)

async function fetchFeedbackList() {
  loading.value = true
  try {
    feedbackList.value = await getFeedbackList(feedbackStatus.value || undefined)
  } catch (e) {
    ElMessage.error('反馈列表加载失败')
  } finally {
    loading.value = false
  }
}

async function viewFeedback(row) {
  try {
    currentFeedback.value = await getFeedbackDetail(row.id)
    replyContent.value = currentFeedback.value.reply_content || ''
    feedbackDetailVisible.value = true
    // 查看后刷新列表（状态可能从 unread 变 read）
    fetchFeedbackList()
  } catch (e) {
    ElMessage.error('加载失败')
  }
}

async function handleMarkRead(row) {
  try {
    await markFeedbackRead(row.id)
    ElMessage.success('已标记为已读')
    fetchFeedbackList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleReply() {
  if (!replyContent.value.trim()) return ElMessage.warning('请输入回复内容')
  if (!currentFeedback.value) return
  replying.value = true
  try {
    const updated = await replyFeedback(currentFeedback.value.id, replyContent.value.trim())
    currentFeedback.value = updated
    ElMessage.success('回复已发送')
    fetchFeedbackList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '回复失败')
  } finally {
    replying.value = false
  }
}

function handleTabChange() {
  if (activeTab.value === 'change') {
    fetchChangeList()
  } else if (activeTab.value === 'leave') {
    fetchLeaveList()
  } else if (activeTab.value === 'feedback') {
    fetchFeedbackList()
  }
}

// 按当前 tab 拉数据（而不是固定拉修改申请），这样 ?tab=leave 进来才是对的
onMounted(handleTabChange)
</script>

<style scoped>
.page-card {
  /* 水印的定位基准 */
  position: relative;
}

.tab-toolbar {
  display: flex;
  justify-content: flex-end;
}

/* 起止时间竖排两行 */
.time-sep {
  font-size: 12px;
  color: #c0c4cc;
  line-height: 1.4;
}

.diff-line {
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.9;
  font-size: 13px;
}

.diff-label {
  width: 84px;
  color: #909399;
  flex-shrink: 0;
}

.diff-old {
  color: #909399;
  text-decoration: line-through;
}

.diff-arrow {
  color: #c0c4cc;
}

.diff-new {
  color: #303133;
  font-weight: 500;
}

/* 手机上「原值 → 新值」一条可能折行，改成上下排列不容易串行 */
@media (max-width: 768px) {
  .diff-line {
    display: block;
    line-height: 1.7;
    margin-bottom: 4px;
  }

  .diff-label {
    width: auto;
    margin-right: 6px;
  }

  .diff-arrow {
    display: none;
  }

  .diff-new::before {
    content: '→ ';
    color: #c0c4cc;
  }
}

/* 反馈详情弹窗里的样式 */
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

.reply-form {
  margin-top: 16px;
}
</style>
