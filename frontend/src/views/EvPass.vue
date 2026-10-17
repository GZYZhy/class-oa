<template>
  <div>
    <div class="page-card" v-loading="loading">
      <ServiceIntro
        intro="为在校内使用的电动自行车办理通行证。"
        deadline="7 个工作日（仅供参考）"
        :notice="'本网络办件仅提供信息表生成，具体向安全稳定工作部（处）报送的工作需要您自行完成。\n操作此办件前请务必与班委联系。'"
        submitted="行驶证（图片或 PDF），不超过 20MB，必填"
        finished="电动车通行证申请表、电动自行车使用承诺书（两份 PDF），审核通过后可下载"
      />

      <el-tabs v-model="activeTab">
        <!-- ============ 申请补办 ============ -->
        <el-tab-pane :label="editingId ? '修改申请' : '申请补办'" name="apply">
          <!-- 修改这条申请时把表单预填成它的内容，提交走 PUT 覆盖原记录 -->
          <div v-if="editingId" class="edit-hint">
            正在修改这条申请，改完点「保存修改」；不重选行驶证就沿用原来那张。
          </div>

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
                ref="uploadRef"
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
                  <div v-if="editingId" class="el-upload__tip">
                    只支持图片或 PDF，大小不超过 20MB；超过 1MB 的图片会自动压缩。不重选就沿用当前那张
                  </div>
                  <div v-else class="el-upload__tip">
                    只支持图片或 PDF，大小不超过 20MB，必填；超过 1MB 的图片会自动压缩
                  </div>
                </template>
              </el-upload>
            </el-form-item>
            <!-- 这句是《电动自行车使用承诺书》上「本人承诺」栏的原话，勾选即表示
                 认下那张纸上的内容（承诺书是要交给安稳部的） -->
            <el-form-item prop="confirmed" class="confirm-item">
              <el-checkbox v-model="form.confirmed">
                <div>本人承诺申请通行证所对应车辆为本人实际使用，绝不进行代办、伪造、线上买卖通行证等违反校规的行为。</div>
              </el-checkbox>
            </el-form-item>

            <el-form-item prop="signConfirmed" class="confirm-item">
              <el-checkbox v-model="form.signConfirmed">
                <div>我确认在承诺书上签字</div>
              </el-checkbox>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="submitting" @click="handleSubmit">
                <!-- 行驶证照片可能有几 MB，慢网络下把进度显示出来 -->
                {{ editingId ? '保存修改' : '提交申请' }}{{ submitting && uploadProgress ? ` ${uploadProgress}%` : '' }}
              </el-button>
              <el-button v-if="editingId" @click="cancelEdit">取消修改</el-button>
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
                <el-tag v-if="row.status === 'pending'" type="warning" size="small">待受理</el-tag>
                <el-tag v-else-if="row.status === 'accepted'" type="primary" size="small">已受理</el-tag>
                <el-tag v-else-if="row.status === 'correcting'" type="warning" size="small">待补正</el-tag>
                <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
                <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="经办班委签字" width="130" align="center">
              <template #default="{ row }">
                <!-- 签不签是管理员批准那一步定的，没签字时申请表上就没有那一行 -->
                <span v-if="row.status === 'approved' && row.sign_name" style="color: #67c23a;">
                  {{ row.sign_name }} 已签
                </span>
                <span v-else style="color: var(--el-text-color-secondary);">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="340" align="center">
              <template #default="{ row }">
                <el-button type="primary" link size="small" @click="viewLicense(row)">行驶证</el-button>
                <template v-if="row.status === 'approved'">
                  <!-- 这份文档的表头写的是「电动车通行证补办登记表」，但学生拿到手
                       要交上去，按「申请表」称呼更贴合用途 -->
                  <el-button
                    type="success"
                    link
                    size="small"
                    :loading="isDownloading(`pass-${row.id}`)"
                    @click="downloadPass(row)"
                  >
                    {{ isDownloading(`pass-${row.id}`) && downloadPercent
                      ? `${downloadPercent}%` : '申请表' }}
                  </el-button>
                  <el-button
                    type="success"
                    link
                    size="small"
                    :loading="isDownloading(`promise-${row.id}`)"
                    @click="downloadPromise(row)"
                  >
                    {{ isDownloading(`promise-${row.id}`) && downloadPercent
                      ? `${downloadPercent}%` : '承诺书' }}
                  </el-button>
                </template>
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
                <!-- 退回补正的理由是让申请人照办的话，得看得见才补得对 -->
                <el-tooltip
                  v-if="row.status === 'correcting' && row.correction_reason"
                  :content="row.correction_reason"
                  placement="top"
                >
                  <span style="color: #e6a23c; font-size: 12px; cursor: help;">补正说明</span>
                </el-tooltip>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getMyEvPasses,
  submitEvPass,
  updateEvPass,
  deleteEvPass,
  downloadEvPassPdf,
  downloadEvPromisePdf
} from '@/api/evPass'
import { formatDate, formatDateTime } from '@/utils/format'
import { compressImage } from '@/utils/imageCompress'
import { blobErrorDetail } from '@/utils/download'
import { useDownloadProgress } from '@/composables/useDownloadProgress'
import FileViewer from '@/components/FileViewer.vue'
import ServiceIntro from '@/components/ServiceIntro.vue'

const activeTab = ref('apply')
const loading = ref(false)
const submitting = ref(false)
// 上传进度百分比（算不出总大小时为 0，就不显示数字）
const uploadProgress = ref(0)
// 申请表 / 承诺书的下载进度（同一时间只跑一个）
const { percent: downloadPercent, isDownloading, run: runDownload } = useDownloadProgress()
const list = ref([])
const formRef = ref(null)
const uploadRef = ref(null)
// 正在修改的那条记录（null = 新建）。改完走 PUT 覆盖原记录，不会又多出一条
const editingId = ref(null)

const form = reactive({
  brand: '',
  plate_number: '',
  license: null,   // 行驶证文件
  confirmed: false,      // 认下承诺书上「本人承诺」那句
  signConfirmed: false,  // 会在承诺书上签字
})

// 自定义校验
const validateLicense = (_rule, _value, callback) => {
  // 修改时可以不重选：不选就沿用原来那张（后端 PUT 的 license_file 字段就是这么定的）
  if (!form.license && !editingId.value) callback(new Error('请上传行驶证'))
  else callback()
}
const validateConfirmed = (_rule, _value, callback) => {
  if (!form.confirmed) callback(new Error('请勾选确认'))
  else callback()
}
const validateSignConfirmed = (_rule, _value, callback) => {
  if (!form.signConfirmed) callback(new Error('请确认会在承诺书上签字'))
  else callback()
}

const rules = {
  brand: [{ required: true, message: '请输入品牌', trigger: 'blur' }],
  plate_number: [{ required: true, message: '请输入牌照号', trigger: 'blur' }],
  license: [{ validator: validateLicense, trigger: 'change' }],
  confirmed: [{ validator: validateConfirmed, trigger: 'change' }],
  signConfirmed: [{ validator: validateSignConfirmed, trigger: 'change' }],
}

// 选择文件
async function handleFileChange(file) {
  // 手机拍的行驶证通常有好几 MB，先压小再校验（PDF 不动，规则见 utils/imageCompress.js）
  if (file.raw) file.raw = await compressImage(file.raw)
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

/** 清空表单，回到「新建」状态 */
function resetForm() {
  form.brand = ''
  form.plate_number = ''
  form.license = null
  form.confirmed = false
  form.signConfirmed = false
  editingId.value = null
  uploadRef.value?.clearFiles()
}

/** 修改：把这条记录预填进表单并切回申请那一栏 */
function startEdit(row) {
  editingId.value = row.id
  form.brand = row.brand
  form.plate_number = row.plate_number
  // 行驶证不预填（拿不到原来的文件对象），不重选后端就沿用原来那张
  form.license = null
  // 两条承诺是每次提交都要认一遍的话，不替申请人预勾
  form.confirmed = false
  form.signConfirmed = false
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
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  const fd = new FormData()
  fd.append('brand', form.brand.trim())
  fd.append('plate_number', form.plate_number.trim())
  // 修改时不重选就是「行驶证不动」，所以没选文件就别 append 了
  if (form.license) {
    fd.append('license_file', form.license)
  }

  const onProgress = (loaded, total) => {
    uploadProgress.value = total ? Math.round((loaded / total) * 100) : 0
  }

  submitting.value = true
  uploadProgress.value = 0
  try {
    if (editingId.value) {
      await updateEvPass(editingId.value, fd, onProgress)
      ElMessage.success('已保存修改')
    } else {
      await submitEvPass(fd, onProgress)
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

/** 撤销：只有待受理能撤，撤了就真删掉了（连行驶证） */
function handleDelete(row) {
  ElMessageBox.confirm(
    '撤销后这条申请和行驶证都会被删掉，不能恢复。',
    '撤销申请',
    { confirmButtonText: '撤销', cancelButtonText: '再想想', type: 'warning' }
  ).then(async () => {
    try {
      await deleteEvPass(row.id)
      ElMessage.success('已撤销')
      // 撤的正好是正在改的那条，就别让表单还停在「修改」上
      if (editingId.value === row.id) resetForm()
      fetchList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '撤销失败')
    }
  }).catch(() => {})
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

// 下载申请表 / 承诺书（都是 PDF）。
// 存盘名要自己拼（走 blob，拿不到响应头里的名字），命名沿用请假证明的模式：
// 姓名_材料名_日期 —— 同一个人可能申请过不止一次
async function savePdf(fetchBlob, row, label, key) {
  await runDownload(key, async (onProgress) => {
    const blob = await fetchBlob(row.id, onProgress)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${row.student_name}_${label}_${formatDate(row.created_at).replace(/-/g, '')}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  })
}

async function downloadPass(row) {
  try {
    await savePdf(downloadEvPassPdf, row, '电动车通行证申请表', `pass-${row.id}`)
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e))
  }
}

async function downloadPromise(row) {
  try {
    await savePdf(downloadEvPromisePdf, row, '电动车承诺书', `promise-${row.id}`)
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
