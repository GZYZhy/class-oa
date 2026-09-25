<template>
  <div>
    <div class="page-card" v-loading="loading">
      <div class="page-toolbar">
        <h3 class="page-title" style="margin-bottom: 0;">文件公开</h3>
        <!-- 上传/删除限班委及以上；普通学生只读，且不给下载按钮（可在线查看） -->
        <el-button v-if="userStore.isCommittee" type="primary" @click="openUpload">
          <el-icon><Plus /></el-icon>
          发布文件
        </el-button>
      </div>

      <!-- 搜索区：标题 + 发布时间区间 -->
      <el-form :inline="true" style="margin-top: 16px;">
        <el-form-item label="标题">
          <el-input
            v-model="searchForm.title"
            placeholder="按标题搜索"
            clearable
            style="width: 200px"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="发布时间">
          <el-date-picker
            v-model="searchForm.dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            style="width: 260px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSearch">
            <el-icon><Search /></el-icon>搜索
          </el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>

      <!-- 文件列表 -->
      <el-table :data="list" stripe border style="width: 100%; margin-top: 8px;">
        <el-table-column label="序号" type="index" width="70" align="center" />
        <el-table-column prop="title" label="文件标题" min-width="240">
          <template #default="{ row }">
            <span class="ann-title">{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="doc_number" label="文号" width="160" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.doc_number" type="info" size="small">{{ row.doc_number }}</el-tag>
            <span v-else style="color: #c0c4cc;">-</span>
          </template>
        </el-table-column>
        <el-table-column label="发布人" width="120" align="center">
          <template #default="{ row }">
            <!-- 本功能上线前录入的老数据没有发布人 -->
            <span :style="{ color: row.publisher ? '#303133' : '#c0c4cc' }">
              {{ row.publisher || '-' }}
            </span>
          </template>
        </el-table-column>
        <!-- 可见范围只有班委及以上才关心：学生看到的必然都是「全体公开」 -->
        <el-table-column v-if="userStore.isCommittee" label="可见范围" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_public" type="success" size="small">全体公开</el-tag>
            <el-tag v-else type="warning" size="small">仅班委</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="publish_date" label="发布时间" width="140" align="center" sortable />
        <el-table-column label="操作" width="220" align="center">
          <template #default="{ row }">
            <el-button type="primary" link @click="viewFile(row)">查看</el-button>
            <el-button v-if="!userStore.isStudent" type="success" link @click="downloadFile(row)">
              下载
            </el-button>
            <el-button v-if="userStore.isCommittee" type="danger" link @click="handleDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !list.length" description="暂无公开文件" style="margin-top: 30px;" />

      <!-- 公开文件谁都能看，盖一层「谁在看」的水印（普通学生访问时也盖） -->
      <Watermark :text="watermarkText" />
    </div>

    <!-- 上传弹窗 -->
    <el-dialog v-model="uploadVisible" title="发布公开文件" width="520px" :close-on-click-modal="false">
      <el-form :model="form" label-width="90px">
        <el-form-item label="文件标题" required>
          <el-input v-model="form.title" placeholder="请输入文件标题" maxlength="200" />
        </el-form-item>
        <el-form-item label="文号">
          <el-input v-model="form.doc_number" placeholder="如：理院〔2026〕5号" />
        </el-form-item>
        <el-form-item label="发布时间" required>
          <el-date-picker
            v-model="form.publish_date"
            type="date"
            placeholder="选择发布时间"
            style="width: 100%"
            value-format="YYYY-MM-DD"
          />
        </el-form-item>
        <el-form-item label="公开范围">
          <el-radio-group v-model="form.is_public">
            <el-radio :value="true">向班委以外公开</el-radio>
            <el-radio :value="false">仅班委可见</el-radio>
          </el-radio-group>
          <div class="form-tip">
            {{ form.is_public
              ? '全体登录用户都能在「文件公开」里看到并在线查看。'
              : '普通学生的列表里不会出现这个文件，也不能通过链接查看。' }}
          </div>
        </el-form-item>
        <el-form-item label="PDF文件" required>
          <input
            ref="fileInputRef"
            type="file"
            accept=".pdf,application/pdf"
            class="file-input"
            @change="handleFileChange"
          />
          <div v-if="selectedFile" class="selected-file">
            <el-icon><Document /></el-icon>
            {{ selectedFile.name }}（{{ (selectedFile.size / 1024).toFixed(1) }} KB）
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAnnouncements, createAnnouncement, deleteAnnouncement } from '@/api/announcement'
import { useUserStore } from '@/store/user'
import Watermark from '@/components/Watermark.vue'
import { useWatermark } from '@/composables/useWatermark'

const userStore = useUserStore()
const watermarkText = useWatermark()

const list = ref([])
const loading = ref(false)
const uploadVisible = ref(false)
const submitting = ref(false)
const selectedFile = ref(null)
const fileInputRef = ref(null)

const form = reactive({
  title: '',
  doc_number: '',
  publish_date: '',
  // 是否向班委以外公开，默认公开（与后端 Form 默认值一致）
  is_public: true,
})

// 搜索表单
const searchForm = reactive({ title: '', dateRange: [] })

async function fetchList() {
  loading.value = true
  try {
    list.value = await getAnnouncements({
      title: searchForm.title || undefined,
      start_date: searchForm.dateRange?.[0] || undefined,
      end_date: searchForm.dateRange?.[1] || undefined,
    })
  } catch (e) {
    ElMessage.error('文件列表加载失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() { fetchList() }

function handleReset() {
  searchForm.title = ''
  searchForm.dateRange = []
  fetchList()
}

function openUpload() {
  form.title = ''
  form.doc_number = ''
  form.publish_date = ''
  form.is_public = true
  selectedFile.value = null
  if (fileInputRef.value) fileInputRef.value.value = ''
  uploadVisible.value = true
}

function handleFileChange(e) {
  const file = e.target.files[0]
  if (file && !file.name.toLowerCase().endsWith('.pdf')) {
    ElMessage.warning('只允许选择 PDF 文件')
    e.target.value = ''
    return
  }
  selectedFile.value = file || null
}

async function handleSubmit() {
  if (!form.title.trim()) return ElMessage.warning('请填写文件标题')
  if (!form.publish_date) return ElMessage.warning('请选择发布时间')
  if (!selectedFile.value) return ElMessage.warning('请选择 PDF 文件')

  // 组装 multipart 表单
  const fd = new FormData()
  fd.append('title', form.title.trim())
  fd.append('doc_number', form.doc_number.trim())
  fd.append('publish_date', form.publish_date)
  // multipart 里布尔值走字符串，FastAPI 的 bool = Form(...) 能认 true/false
  fd.append('is_public', form.is_public ? 'true' : 'false')
  fd.append('file', selectedFile.value)

  submitting.value = true
  try {
    await createAnnouncement(fd)
    ElMessage.success('发布成功')
    uploadVisible.value = false
    fetchList()
  } catch (e) {
    ElMessage.error('发布失败：' + (e.response?.data?.detail || e.message))
  } finally {
    submitting.value = false
  }
}

// 查看：新标签页打开 PDF
function viewFile(row) {
  window.open(row.file_path, '_blank')
}

// 下载：a 标签触发，保留原始文件名
function downloadFile(row) {
  const a = document.createElement('a')
  a.href = row.file_path
  a.download = row.file_name || `${row.title}.pdf`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.title}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await deleteAnnouncement(row.id)
    ElMessage.success('已删除')
    fetchList()
  } catch (e) {
    // 用户点取消时不提示
  }
}

onMounted(fetchList)
</script>

<style scoped>
.page-card {
  /* 水印的定位基准 */
  position: relative;
}

.page-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.ann-title {
  color: #303133;
}

.file-input {
  width: 100%;
  padding: 8px;
  border: 1px dashed #c0c4cc;
  border-radius: 6px;
  background: #fafafa;
}

.file-input::file-selector-button {
  padding: 5px 12px;
  margin-right: 10px;
  border: none;
  border-radius: 4px;
  background: #409eff;
  color: #fff;
  cursor: pointer;
}

.form-tip {
  width: 100%;
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: #909399;
}

.selected-file {
  margin-top: 8px;
  font-size: 13px;
  color: #606266;
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
