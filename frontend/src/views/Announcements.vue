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

      <!-- 搜索区：一个关键词框（标题或文号，输片段即可）+ 发布时间区间 -->
      <el-form :inline="true" style="margin-top: 16px;">
        <el-form-item>
          <el-input
            v-model="searchForm.keyword"
            placeholder="按标题或文号搜索"
            clearable
            style="width: 240px"
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
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
        <el-table-column prop="doc_number" label="文号" width="220" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.doc_number" type="info" size="small">{{ row.doc_number }}</el-tag>
            <span v-else style="color: var(--el-text-color-disabled);">-</span>
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
        <!-- 在线查看次数（不含下载）。没人看过时淡化显示，免得 0 显得像加载失败 -->
        <el-table-column prop="view_count" label="查看次数" width="100" align="center">
          <template #default="{ row }">
            <span :style="{ color: row.view_count ? 'var(--el-text-color-primary)' : 'var(--el-text-color-disabled)' }">
              {{ row.view_count || 0 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" align="center">
          <template #default="{ row }">
            <el-button
              type="primary"
              link
              :loading="viewingId === row.id"
              @click="handleView(row)"
            >查看</el-button>
            <el-button
              v-if="!userStore.isStudent"
              type="success"
              link
              :loading="downloadingId === row.id"
              @click="handleDownload(row)"
            >
              <!-- 公告 PDF 常有 5MB 以上的，网络差时把进度显示出来 -->
              {{ downloadingId === row.id && progress ? progress + '%' : '下载' }}
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

    <!-- 内嵌 PDF 查看器（不走浏览器原生，防止学生通过查看器的下载按钮绕过权限） -->
    <PdfViewer
      v-model="viewerVisible"
      :file-url="viewerFileUrl"
      :title="viewerTitle"
    />

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
              ? '所有登录用户都能看到并在线查看。'
              : '普通学生看不到这个文件。' }}
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
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          <!-- 公告上限 50MB，慢网络下传几分钟，把百分比显示出来 -->
          发布{{ submitting && uploadProgress ? ` ${uploadProgress}%` : '' }}
        </el-button>
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
import { downloadFile, blobErrorDetail } from '@/utils/download'
import PdfViewer from '@/components/PdfViewer.vue'

const userStore = useUserStore()
const watermarkText = useWatermark()

const list = ref([])
const loading = ref(false)
const uploadVisible = ref(false)
const submitting = ref(false)
// 上传进度百分比（浏览器算不出总大小时为 0，就不显示数字）
const uploadProgress = ref(0)
const selectedFile = ref(null)
const fileInputRef = ref(null)

// PDF 查看器
const viewerVisible = ref(false)
const viewerFileUrl = ref('')
const viewerTitle = ref('')
// 记录当前正在下载的行 id，按钮上显示 loading（网络慢时避免用户以为没点到）
const downloadingId = ref(null)
// 当前下载进度百分比（后端没给 Content-Length 时恒为 0，就不显示数字）
const progress = ref(0)
// 记录当前正在查看的行 id，按钮上显示 loading
const viewingId = ref(null)

const form = reactive({
  title: '',
  doc_number: '',
  publish_date: '',
  // 是否向班委以外公开，默认公开（与后端 Form 默认值一致）
  is_public: true,
})

// 搜索表单：一个关键词框（标题或文号）+ 发布时间区间
const searchForm = reactive({ keyword: '', dateRange: [] })

async function fetchList() {
  loading.value = true
  try {
    list.value = await getAnnouncements({
      keyword: searchForm.keyword.trim() || undefined,
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
  searchForm.keyword = ''
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
  uploadProgress.value = 0
  try {
    await createAnnouncement(fd, (loaded, total) => {
      uploadProgress.value = total ? Math.round((loaded / total) * 100) : 0
    })
    ElMessage.success('发布成功')
    uploadVisible.value = false
    fetchList()
  } catch (e) {
    ElMessage.error('发布失败：' + (e.response?.data?.detail || e.message))
  } finally {
    submitting.value = false
  }
}

// 查看：用内嵌 PdfViewer 弹框渲染，不走浏览器原生 PDF 查看器，
// 这样可以叠水印、不放下载按钮，防止学生通过查看器下载绕过权限。
function handleView(row) {
  viewerFileUrl.value = row.file_path
  viewerTitle.value = row.title
  viewerVisible.value = true
}

// 下载：经 axios 取回，保留原始文件名；按钮上显示 loading，避免网慢时用户以为没点到
async function handleDownload(row) {
  downloadingId.value = row.id
  progress.value = 0
  try {
    // download=true 不能省：后端靠它区分「下载」和「在线查看」——
    // 少了它日志里记成查看（查看次数会跟着涨，水印溯源那里也只有查看记录），
    // 而且响应头是 inline，浏览器不弹存盘
    const sep = row.file_path.includes('?') ? '&' : '?'
    await downloadFile(
      `${row.file_path}${sep}download=true`,
      row.file_name || `${row.title}.pdf`,
      // 公告 PDF 常有 5MB 以上的，网慢时按钮上把百分比写出来
      (loaded, total) => {
        progress.value = total ? Math.round((loaded / total) * 100) : 0
      },
    )
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e))
  } finally {
    downloadingId.value = null
  }
}

async function handleDelete(row) {
  try {
    // 说明里写上访问记录一并清理：删完之后「文件访问日志」里再也查不到这份文件，
    // 管理员水印溯源时也只能看到「已删除」—— 先说清楚，免得事后翻旧账
    await ElMessageBox.confirm(
      `确定删除「${row.title}」吗？它的查看/下载记录也会一并清理。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteAnnouncement(row.id)
    ElMessage.success('已删除')
    fetchList()
  } catch (e) {
    // 取消时静默；真删失败（无权限、已被别人删掉）要把后端的原话放出来
    if (e?.response) ElMessage.error(e.response.data?.detail || '删除失败')
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
  color: var(--el-text-color-primary);
}

.file-input {
  width: 100%;
  padding: 8px;
  border: 1px dashed var(--el-border-color-darker);
  border-radius: 6px;
  background: var(--el-fill-color-light);
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
  color: var(--el-text-color-secondary);
}

.selected-file {
  margin-top: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
