<template>
  <div>
    <div class="page-card" v-loading="loading">
      <!-- 重要提示 -->
      <el-alert type="warning" :closable="false" show-icon class="notice-alert">
        <div class="alert-text">
          本网络办件仅提供信息表生成，具体向安全稳定工作部（处）报送的工作需要您自行完成。
          操作此办件前请务必与班委联系。
        </div>
      </el-alert>

      <el-tabs v-model="activeTab">
        <!-- ============ 申请补办 ============ -->
        <el-tab-pane label="申请补办" name="apply">
          <el-form ref="formRef" :model="form" :rules="rules" label-width="110px" style="max-width: 640px;">
            <!-- 标签用「电动车品牌」（5 字）而不是「电动自行车品牌」（7 字）：
                 label-width 110px 里扣掉 12px 右内边距，再扣掉必填的 * 号，
                 7 个字（约 98px）放不下，会折成两行 -->
            <el-form-item label="电动车品牌" prop="brand">
              <el-input v-model="form.brand" placeholder="如：雅迪 / 爱玛 / 小牛" maxlength="100" />
            </el-form-item>
            <el-form-item label="牌照号" prop="plate_number">
              <el-input v-model="form.plate_number" placeholder="如：北京1234567" maxlength="50" />
            </el-form-item>
            <el-form-item label="行驶证" prop="license">
              <el-upload
                :auto-upload="false"
                :limit="1"
                :on-change="handleFileChange"
                :on-exceed="handleExceed"
                accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp"
              >
                <el-button type="primary" plain>
                  <el-icon><Upload /></el-icon>
                  选择行驶证（图片或PDF）
                </el-button>
                <template #tip>
                  <div class="el-upload__tip">只支持图片或 PDF，大小不超过 20MB，必填</div>
                </template>
              </el-upload>
            </el-form-item>
            <el-form-item prop="confirmed" class="confirm-item">
              <el-checkbox v-model="form.confirmed">
                我确认信息真实，遵守学校规定，车辆本人使用，提交前已与班委联系
              </el-checkbox>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="submitting" @click="handleSubmit">
                提交申请
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- ============ 我的申请 ============ -->
        <el-tab-pane label="我的申请" name="mine">
          <el-table :data="list" stripe border style="width: 100%;">
            <el-table-column prop="brand" label="品牌" width="130" align="center" />
            <el-table-column prop="plate_number" label="牌照号" width="140" align="center" />
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
                <el-button type="primary" link size="small" @click="viewLicense(row)">行驶证</el-button>
                <template v-if="row.status === 'approved'">
                  <!-- 这份文档的表头写的是「电动车通行证补办登记表」，但学生拿到手
                       要交上去，按「申请表」称呼更贴合用途 -->
                  <el-button type="success" link size="small" @click="downloadPass(row)">申请表</el-button>
                  <el-button type="success" link size="small" @click="downloadPromise(row)">承诺书</el-button>
                </template>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!list.length" description="暂无申请记录" style="margin-top: 20px;" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 行驶证预览弹框 -->
    <FileViewer
      v-model="licenseViewerVisible"
      :file-url="licenseFileUrl"
      :file-name="licenseFileName"
      title="电动车行驶证"
    />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getMyEvPasses, submitEvPass } from '@/api/evPass'
import { formatDate, formatDateTime } from '@/utils/format'
import { blobErrorDetail, downloadFile } from '@/utils/download'
import FileViewer from '@/components/FileViewer.vue'

const activeTab = ref('apply')
const loading = ref(false)
const submitting = ref(false)
const list = ref([])
const formRef = ref(null)

const form = reactive({
  brand: '',
  plate_number: '',
  license: null,   // 行驶证文件
  confirmed: false,
})

// 自定义校验
const validateLicense = (_rule, _value, callback) => {
  if (!form.license) callback(new Error('请上传行驶证'))
  else callback()
}
const validateConfirmed = (_rule, _value, callback) => {
  if (!form.confirmed) callback(new Error('请勾选确认'))
  else callback()
}

const rules = {
  brand: [{ required: true, message: '请输入品牌', trigger: 'blur' }],
  plate_number: [{ required: true, message: '请输入牌照号', trigger: 'blur' }],
  license: [{ validator: validateLicense, trigger: 'change' }],
  confirmed: [{ validator: validateConfirmed, trigger: 'change' }],
}

// 选择文件
function handleFileChange(file) {
  // 再校验一遍大小和类型（和请假证明一致）
  const raw = file.raw
  if (raw) {
    if (raw.size > 20 * 1024 * 1024) {
      ElMessage.error('文件不能超过 20MB')
      form.license = null
      return
    }
  }
  form.license = raw
  formRef.value?.validateField('license')
}

function handleExceed() {
  ElMessage.warning('只能上传一个行驶证文件')
}

// 提交
async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  const fd = new FormData()
  fd.append('brand', form.brand.trim())
  fd.append('plate_number', form.plate_number.trim())
  fd.append('license_file', form.license)

  submitting.value = true
  try {
    await submitEvPass(fd)
    ElMessage.success('提交成功，等待管理员审核')
    activeTab.value = 'mine'
    fetchList()
  } catch (e) {
    ElMessage.error('提交失败：' + (e.response?.data?.detail || e.message))
  } finally {
    submitting.value = false
  }
}

// 行驶证预览
const licenseViewerVisible = ref(false)
const licenseFileUrl = ref('')
const licenseFileName = ref('')

function viewLicense(row) {
  licenseFileUrl.value = `/api/ev-passes/${row.id}/license`
  licenseFileName.value = row.license_original_name || '行驶证'
  licenseViewerVisible.value = true
}

// 下载申请表 / 承诺书。
// 存盘名要自己拼（downloadFile 走 blob，拿不到响应头里的名字），
// 命名沿用请假证明的模式：姓名_材料名_日期 —— 同一个人可能申请过不止一次
function docxName(row, label) {
  const dateStr = formatDate(row.created_at).replace(/-/g, '')
  return `${row.student_name}_${label}_${dateStr}.docx`
}

async function downloadPass(row) {
  try {
    await downloadFile(`/api/ev-passes/${row.id}/pass-docx`, docxName(row, '电动车通行证申请表'))
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e))
  }
}

async function downloadPromise(row) {
  try {
    await downloadFile(`/api/ev-passes/${row.id}/promise-docx`, docxName(row, '电动车承诺书'))
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e))
  }
}

async function fetchList() {
  loading.value = true
  try {
    list.value = await getMyEvPasses()
  } catch (e) {
    ElMessage.error('申请记录加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(fetchList)
</script>

<style scoped>
.notice-alert {
  margin-bottom: 16px;
}

.alert-text {
  font-size: 13px;
  line-height: 1.6;
}

/* 确认框这段字在手机上会顶出屏幕右边：el-checkbox 的文本默认
   white-space: nowrap（左右两栏的表单里这是对的，可这里是一整句话）。
   放开折行，并把勾选框留在第一行的位置，而不是垂直居中到两行中间。
   行高也要一并放开 —— 表单控件默认的 32px 行高撑不住两行文字 */
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
