<template>
  <div class="leave-apply">
    <div class="page-card">
      <h3 class="page-title">请假申请</h3>

      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 20px;">
        <template #title>温馨提示</template>
        本网办事项仅用于简化流程、避免材料递交繁琐，请假审批是否通过由学校决定。
      </el-alert>

      <el-tabs v-model="activeTab">
        <!-- 提交申请 -->
        <el-tab-pane label="提交申请" name="apply">
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
                  <div class="el-upload__tip">支持 PDF / 图片，最大 20MB，必填</div>
                </template>
              </el-upload>
            </el-form-item>

            <el-form-item prop="agreed">
              <el-checkbox v-model="form.agreed" class="agree-checkbox">
                <div>我已阅读并同意遵守学校相关规定，确认以上信息真实有效</div>
                <div>我授权系统为我按以上信息生成“请假申请表”，并确认是我个人意愿的真实体现。</div>
              </el-checkbox>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="submitting" @click="handleSubmit">
                提交申请
              </el-button>
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
            <el-table-column prop="reason" label="事由" min-width="180" show-overflow-tooltip />
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.status === 'pending'" type="warning" size="small">待审核</el-tag>
                <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
                <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="申请时间" width="160" align="center">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="180" align="center">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="viewProof(row)">
                  查看证明
                </el-button>
                <el-button
                  v-if="row.status === 'approved'"
                  size="small"
                  link
                  type="success"
                  @click="downloadDocx(row)"
                >
                  下载请假表
                </el-button>
              </template>
            </el-table-column>
            <el-table-column label="审核意见" width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.status === 'rejected'" style="color: #f56c6c;">
                  {{ row.reject_reason || '未填写理由' }}
                </span>
                <span v-else-if="row.status === 'approved'" style="color: #67c23a;">
                  {{ row.reviewer_name || '管理员' }} 已通过
                </span>
                <span v-else style="color: #c0c4cc;">待审核</span>
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
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getMyLeaves, submitLeave, downloadLeaveDocx } from '@/api/leave'
import { formatDate, formatDateTime } from '@/utils/format'
import FileViewer from '@/components/FileViewer.vue'

const activeTab = ref('apply')
const submitting = ref(false)
const loading = ref(false)
const leaves = ref([])
const formRef = ref(null)
const fileList = ref([])

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
  agreed: false
})

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
        if (!fileList.value.length) callback(new Error('请上传请假辅助证明'))
        else callback()
      },
      trigger: 'change'
    }
  ],
  agreed: [
    {
      validator: (_, value, callback) => {
        if (!value) callback(new Error('请先勾选同意条款'))
        else callback()
      },
      trigger: 'change'
    }
  ]
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

function handleFileChange(file) {
  fileList.value = [file]
  // 手动触发校验
  formRef.value?.validateField('proof')
}

function handleFileRemove() {
  fileList.value = []
  // 移掉文件后同步刷新提示，不然红字会一直留在原地
  formRef.value?.validateField('proof')
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

  if (!fileList.value.length) {
    return ElMessage.warning('请上传请假辅助证明')
  }

  const fd = new FormData()
  fd.append('leave_type', form.leave_type)
  fd.append('start_at', form.start_at)
  fd.append('end_at', form.end_at)
  fd.append('reason', form.reason)
  fd.append('travel_mode', form.travel_mode)
  fd.append('travel_detail', form.travel_detail)
  fd.append('destination', form.destination)
  fd.append('destination_phone', form.destination_phone)
  // el-upload 的 raw 才是真实文件对象
  fd.append('proof', fileList.value[0].raw || fileList.value[0])

  submitting.value = true
  try {
    await submitLeave(fd)
    ElMessage.success('申请已提交，等待管理员审核')
    // 切到记录页
    activeTab.value = 'history'
    await fetchLeaves()
    // 清空表单
    Object.assign(form, {
      leave_type: '病假',
      start_at: '',
      end_at: '',
      reason: '',
      travel_mode: '',
      travel_detail: '',
      destination: '',
      destination_phone: '',
      agreed: false
    })
    fileList.value = []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
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

function downloadDocx(row) {
  downloadLeaveDocx(row.id).then(blob => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // 只取日期部分做文件名，和后端生成的保持一致
    a.download = `${row.student_name}_请假审批表_${formatDate(row.start_at).replace(/-/g, '')}.docx`
    a.click()
    URL.revokeObjectURL(url)
  }).catch(e => {
    ElMessage.error(e?.response?.data?.detail || '下载失败')
  })
}

onMounted(() => {
  fetchLeaves()
})
</script>

<style scoped>
.leave-apply {
  max-width: 860px;
  margin: 0 auto;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

/* 起止时间竖排两行，比一行 "a ~ b" 好读 */
.time-sep {
  font-size: 12px;
  color: #c0c4cc;
  line-height: 1.4;
}

.el-upload__tip {
  font-size: 12px;
  color: #909399;
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
