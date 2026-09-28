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
              <!-- 与后端一致：修改申请班委就能批（change_requests.py 用的是
                   committee_required）。能进这个页面的人本来就都是班委及以上 -->
              <template v-if="row.status === 'pending'">
                <el-button type="success" link @click="handleApproveChange(row)">通过</el-button>
                <el-button type="danger" link @click="handleRejectChange(row)">驳回</el-button>
              </template>
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

      <!-- ============ 电动车通行证 ============ -->
      <el-tab-pane label="电动车通行证" name="evpass">
        <div class="tab-toolbar">
          <el-radio-group v-model="evPassStatus" size="small" @change="fetchEvPassList">
            <el-radio-button value="pending">待审核</el-radio-button>
            <el-radio-button value="approved">已通过</el-radio-button>
            <el-radio-button value="rejected">已驳回</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="evPassList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" width="140" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: #909399;">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="brand" label="品牌" width="120" align="center" />
          <el-table-column prop="plate_number" label="牌照号" width="140" align="center" />
          <el-table-column label="申请时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'pending'" type="warning" size="small">待审核</el-tag>
              <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
              <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="340" align="center">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="viewEvLicense(row)">行驶证</el-button>
              <!-- 生成的文档：班委和管理员都能下（留档、报学院盖章用）。
                   后端 _docx_target 只在「本人或班委及以上」放行，且要已通过 -->
              <template v-if="row.status === 'approved'">
                <el-button size="small" link type="success" @click="downloadEvPassDoc(row, 'pass')">申请表</el-button>
                <el-button size="small" link type="success" @click="downloadEvPassDoc(row, 'promise')">承诺书</el-button>
              </template>
              <!-- 审批仅管理员；班委只读 -->
              <template v-if="userStore.isAdmin && row.status === 'pending'">
                <el-button size="small" link type="success" @click="handleApproveEvPass(row)">通过</el-button>
                <el-button size="small" link type="danger" @click="handleRejectEvPass(row)">驳回</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !evPassList.length" description="暂无申请" style="margin-top: 20px;" />
      </el-tab-pane>

      <!-- ============ 导出申请 ============ -->
      <el-tab-pane label="导出申请" name="export">
        <div class="tab-toolbar">
          <el-radio-group v-model="exportStatus" size="small" @change="fetchExportList">
            <el-radio-button value="pending">待审核</el-radio-button>
            <el-radio-button value="generated">已通过</el-radio-button>
            <el-radio-button value="rejected">已驳回</el-radio-button>
            <el-radio-button value="failed">生成失败</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="exportList" v-loading="exportLoading" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" width="150" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: #909399;">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="140" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.export_type === 'excel_list' ? '' : 'primary'">
                {{ row.export_type === 'excel_list' ? '名单 Excel' : '个人信息表 PDF' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="范围" width="120" align="center">
            <template #default="{ row }">{{ scopeLabel(row.scope_type) }}</template>
          </el-table-column>
          <el-table-column label="字段数" width="90" align="center">
            <template #default="{ row }">
              {{ row.export_type === 'excel_list' ? (row.fields?.length || 0) : '全部' }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110" align="center">
            <template #default="{ row }">
              <el-tag :type="exportStatusTag(row.status)" size="small">
                {{ exportStatusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="申请时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="260" align="center">
            <template #default="{ row }">
              <template v-if="row.status === 'generated' || row.status === 'approved'">
                <el-button size="small" link type="success" @click="handleDownloadExport(row)">
                  下载
                </el-button>
              </template>
              <template v-if="row.status === 'failed'">
                <el-tooltip :content="row.error_msg" placement="top">
                  <span style="font-size: 12px; color: #909399; cursor: help;">失败原因</span>
                </el-tooltip>
              </template>
              <template v-if="row.status === 'rejected'">
                <el-tooltip :content="row.reject_reason" placement="top">
                  <span style="font-size: 12px; color: #909399; cursor: help;">驳回理由</span>
                </el-tooltip>
              </template>
              <template v-if="row.status === 'pending' && userStore.isAdmin">
                <el-button size="small" link type="success" @click="handleApproveExport(row)">
                  通过
                </el-button>
                <el-button size="small" link type="danger" @click="handleRejectExport(row)">
                  驳回
                </el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!exportLoading && !exportList.length" description="暂无导出申请" style="margin-top: 20px;" />
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

        <div v-if="currentFeedback.attachments?.length" class="attachment-block">
          <div class="attachment-title">附件</div>
          <div v-for="item in currentFeedback.attachments" :key="item.index" class="attachment-item">
            <el-icon><Paperclip /></el-icon>
            <span class="attachment-name" @click="downloadAttachment(currentFeedback.id, item)">
              {{ item.name }}
            </span>
            <span class="attachment-size">{{ formatFileSize(item.size) }}</span>
          </div>
        </div>

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

    <!-- 请假证明材料预览弹框 -->
    <FileViewer
      v-model="proofViewerVisible"
      :file-url="proofFileUrl"
      :file-name="proofFileName"
      :download-name="proofDownloadName"
      title="请假证明材料"
    />

    <!-- 电动车行驶证预览弹框 -->
    <FileViewer
      v-model="evLicenseViewerVisible"
      :file-url="evLicenseFileUrl"
      :file-name="evLicenseFileName"
      :download-name="evLicenseDownloadName"
      title="电动车行驶证"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Right, ChatDotRound, Paperclip } from '@element-plus/icons-vue'
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
  replyFeedback,
  downloadFeedbackAttachment
} from '@/api/feedback'
import {
  getEvPassList,
  approveEvPass,
  rejectEvPass,
  downloadEvPassDocx,
  downloadEvPassPromiseDocx
} from '@/api/evPass'
import { FIELD_LABELS, STATUS_LABELS, STATUS_TYPES } from '@/utils/changeFields'
import { formatDate, formatDateTime, formatFileSize } from '@/utils/format'
import Watermark from '@/components/Watermark.vue'
import FileViewer from '@/components/FileViewer.vue'
import { useWatermark } from '@/composables/useWatermark'
import { useUserStore } from '@/store/user'
import { useBadgeStore } from '@/store/badge'
import {
  getExportRequests,
  approveExportRequest,
  rejectExportRequest,
  downloadExportFile
} from '@/api/export'

const userStore = useUserStore()
const badgeStore = useBadgeStore()
const watermarkText = useWatermark()

const route = useRoute()

const loading = ref(false)
// 从推送点进来时带着 ?tab=leave 之类的参数，直接落到对应分类；
// 不带参数（正常从菜单进）就还是老样子，停在信息修改申请
const TABS = ['change', 'leave', 'evpass', 'export', 'feedback']
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
    badgeStore.refresh()
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
    badgeStore.refresh()
  }
}

// 请假证明预览
const proofViewerVisible = ref(false)
const proofFileUrl = ref('')
const proofFileName = ref('')
const proofDownloadName = ref('')

function viewLeaveProof(row) {
  // 预览用的文件路径（后端接口）
  proofFileUrl.value = `/api/leaves/${row.id}/proof/admin`
  proofFileName.value = row.proof_original_name || '证明材料'
  // 下载命名规则：姓名_请假证明_开始日期YYYYMMDD.扩展名
  // 沿用请假审批表的命名模式，保持一致
  const ext = (row.proof_original_name || '').match(/\.[^.]+$/)?.[0] || ''
  const dateStr = formatDate(row.start_at).replace(/-/g, '')
  proofDownloadName.value = `${row.student_name}_请假证明_${dateStr}${ext}`
  proofViewerVisible.value = true
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

// —— 电动车通行证 ——
// 班委能看列表、看行驶证、下载已通过的申请表和承诺书（留档用），
// 但通过/驳回只有管理员能点 —— 和后端 ev_passes.py 里
// committee_required / admin_required / _docx_target 的划分一致
const evPassList = ref([])
const evPassStatus = ref('pending')

async function fetchEvPassList() {
  loading.value = true
  try {
    evPassList.value = await getEvPassList(evPassStatus.value || undefined)
  } catch (e) {
    ElMessage.error('通行证申请列表加载失败')
  } finally {
    loading.value = false
    badgeStore.refresh()
  }
}

// 行驶证预览（班委和管理员走 /license/admin 这个口）
const evLicenseViewerVisible = ref(false)
const evLicenseFileUrl = ref('')
const evLicenseFileName = ref('')
const evLicenseDownloadName = ref('')

function viewEvLicense(row) {
  evLicenseFileUrl.value = `/api/ev-passes/${row.id}/license/admin`
  evLicenseFileName.value = row.license_original_name || '行驶证'
  // 下载命名沿用请假证明的模式：姓名_材料名_日期
  const ext = (row.license_original_name || '').match(/\.[^.]+$/)?.[0] || ''
  const dateStr = formatDate(row.created_at).replace(/-/g, '')
  evLicenseDownloadName.value = `${row.student_name}_电动车行驶证_${dateStr}${ext}`
  evLicenseViewerVisible.value = true
}

// 申请表 / 承诺书：班委和管理员都要留档，两种文档的处理完全一样，只是地址和名字不同
function downloadEvPassDoc(row, kind) {
  const [fetchBlob, label] = kind === 'promise'
    ? [downloadEvPassPromiseDocx, '电动车承诺书']
    : [downloadEvPassDocx, '电动车通行证申请表']
  fetchBlob(row.id).then(blob => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${row.student_name}_${label}_${formatDate(row.created_at).replace(/-/g, '')}.docx`
    a.click()
    URL.revokeObjectURL(url)
  }).catch(e => {
    ElMessage.error(e?.response?.data?.detail || '下载失败')
  })
}

function handleApproveEvPass(row) {
  ElMessageBox.confirm(
    `确定通过「${row.student_name}」的电动车通行证补办申请吗？\n` +
    `品牌：${row.brand}　牌照号：${row.plate_number}`,
    '审批确认',
    { type: 'warning', confirmButtonText: '通过', cancelButtonText: '取消' }
  ).then(async () => {
    try {
      await approveEvPass(row.id)
      ElMessage.success('已通过，申请人现在可以下载申请表和承诺书')
      fetchEvPassList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

function handleRejectEvPass(row) {
  ElMessageBox.prompt('请填写驳回理由，会展示给申请人', '驳回申请', {
    inputPlaceholder: '如：行驶证照片不清晰',
    inputValidator: (v) => (v && v.trim() ? true : '请填写驳回理由'),
    confirmButtonText: '驳回',
    cancelButtonText: '取消'
  }).then(async ({ value }) => {
    try {
      await rejectEvPass(row.id, value.trim())
      ElMessage.success('已驳回')
      fetchEvPassList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

// —— 导出申请 ——
const exportList = ref([])
const exportStatus = ref('pending')
const exportLoading = ref(false)

async function fetchExportList() {
  exportLoading.value = true
  try {
    const res = await getExportRequests({
      status: exportStatus.value || undefined,
      page: 1,
      page_size: 100
    })
    exportList.value = res.items || []
  } catch (e) {
    ElMessage.error('加载导出申请列表失败')
    console.error(e)
  } finally {
    exportLoading.value = false
  }
}

function scopeLabel(type) {
  return {
    all: '全部学生',
    filtered: '筛选结果',
    selected: '手动勾选',
    id_range: '学号范围'
  }[type] || type
}

function exportStatusTag(status) {
  return {
    pending: 'warning',
    approved: 'success',
    generated: 'success',
    rejected: 'danger',
    failed: 'info'
  }[status] || 'info'
}

function exportStatusLabel(status) {
  return {
    pending: '待审核',
    approved: '已通过',
    generated: '已生成',
    rejected: '已驳回',
    failed: '生成失败'
  }[status] || status
}

async function handleApproveExport(row) {
  ElMessageBox.confirm(
    `确定通过 ${row.student_name} 的导出申请？\n通过后会自动生成文件。`,
    '通过申请',
    { type: 'success', confirmButtonText: '通过', cancelButtonText: '取消' }
  ).then(async () => {
    try {
      await approveExportRequest(row.id)
      ElMessage.success('已通过，文件生成中…')
      fetchExportList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

async function handleRejectExport(row) {
  ElMessageBox.prompt('请输入驳回理由', '驳回申请', {
    confirmButtonText: '驳回',
    cancelButtonText: '取消',
    type: 'warning',
    inputPattern: /.+/,
    inputErrorMessage: '请填写驳回理由'
  }).then(async ({ value }) => {
    try {
      await rejectExportRequest(row.id, value)
      ElMessage.success('已驳回')
      fetchExportList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

async function handleDownloadExport(row) {
  try {
    const blob = await downloadExportFile(row.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.file_original_name || '学生信息导出'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    ElMessage.success('下载完成')
  } catch (e) {
    ElMessage.error('下载失败：' + (e.message || '未知错误'))
  }
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
    // 红点刷新统一挂在三个列表的 finally 里：每个审核操作成功之后本来就都会重拉列表，
    // 这样将来新增操作时漏掉刷新的概率是零。代价是切 tab 会多发一次请求，可以接受
    badgeStore.refresh()
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

/** index 用后端给的，不靠数组下标猜（班委和学生看到的是同一份下标） */
async function downloadAttachment(feedbackId, item) {
  try {
    const blob = await downloadFeedbackAttachment(feedbackId, item.index)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // blob: URL 上没有后端的 Content-Disposition，文件名只能自己给
    a.download = item.name
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('附件下载失败')
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
  } else if (activeTab.value === 'evpass') {
    fetchEvPassList()
  } else if (activeTab.value === 'export') {
    fetchExportList()
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

.reply-form {
  margin-top: 16px;
}
</style>
