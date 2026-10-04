<template>
  <!-- 批量导入学生：上传 xlsx → 预览确认 → 结果三步 -->
  <el-dialog
    v-model="visible"
    title="批量导入学生"
    width="620px"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <!-- 步骤 1：上传文件 -->
    <div v-if="step === 1" class="si-step">
      <el-upload
        ref="uploadRef"
        class="si-uploader"
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx"
        :on-exceed="handleExceed"
        :on-change="handleFileChange"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          将 Excel 文件拖到此处，或 <em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            只支持 .xlsx 格式，单文件不超过 20MB；支持的列名：学号、姓名、性别、专业、班级、出生日期、民族、
            政治面貌、生源地、身份证号、考生号、考生类别、科类、考试类型、录取批次、高考总分、
            毕业中学、报到状态、报到时间、在校状态、本人电话、家庭电话、QQ号码、本人电子邮箱、
            家庭通信地址、邮政编码、宿舍、床位、班委、团学会职务、贫困生、备注、高考照片、实地采集
          </div>
        </template>
      </el-upload>

      <el-form v-if="preview?.available_sheets?.length > 1" style="margin-top: 16px;">
        <el-form-item label="工作表">
          <el-select v-model="sheetName" style="width: 100%;" @change="handleSheetChange">
            <el-option
              v-for="sheet in preview.available_sheets"
              :key="sheet"
              :label="sheet"
              :value="sheet"
            />
          </el-select>
        </el-form-item>
      </el-form>
    </div>

    <!-- 步骤 2：预览确认 -->
    <div v-if="step === 2" class="si-step">
      <el-alert
        :title="`共解析 ${preview.total_rows} 行有效数据`"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
      />

      <div class="si-stats">
        <div class="stat-item stat-create">
          <div class="stat-num">{{ preview.will_create }}</div>
          <div class="stat-label">将新增</div>
        </div>
        <div class="stat-item stat-update">
          <div class="stat-num">{{ preview.will_update }}</div>
          <div class="stat-label">将覆盖</div>
        </div>
        <div class="stat-item stat-skip">
          <div class="stat-num">{{ preview.skip_count }}</div>
          <div class="stat-label">跳过</div>
        </div>
        <div class="stat-item stat-photo">
          <div class="stat-num">{{ preview.photo_count }}</div>
          <div class="stat-label">照片</div>
        </div>
      </div>

      <el-alert
        v-if="preview.warnings?.length"
        :title="`有 ${preview.warnings.length} 条警告`"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
      >
        <template #default>
          <ul style="margin: 0; padding-left: 20px; font-size: 13px;">
            <li v-for="(w, i) in preview.warnings.slice(0, 10)" :key="i">{{ w }}</li>
            <li v-if="preview.warnings.length > 10">... 还有 {{ preview.warnings.length - 10 }} 条</li>
          </ul>
        </template>
      </el-alert>

      <div v-if="preview.sample_create?.length" class="si-sample">
        <div class="sample-title">新增样例（前 {{ preview.sample_create.length }} 条）</div>
        <el-table :data="preview.sample_create" size="small" border stripe>
          <el-table-column prop="student_no" label="学号" width="140" />
          <el-table-column prop="name" label="姓名" width="100" />
          <el-table-column prop="class_name" label="班级" />
        </el-table>
      </div>

      <div v-if="preview.sample_update?.length" class="si-sample">
        <div class="sample-title">覆盖样例（前 {{ preview.sample_update.length }} 条）</div>
        <el-table :data="preview.sample_update" size="small" border stripe>
          <el-table-column prop="student_no" label="学号" width="140" />
          <el-table-column prop="name" label="姓名" width="100" />
          <el-table-column prop="class_name" label="班级" />
        </el-table>
      </div>

      <el-alert
        title="覆盖规则：学号已存在的学生，只更新学生信息（姓名/班级/电话等），不动登录账号、密码、角色和推送订阅"
        type="warning"
        effect="dark"
        :closable="false"
        style="margin-top: 16px;"
      />
    </div>

    <!-- 步骤 3：导入结果 -->
    <div v-if="step === 3" class="si-step">
      <el-result
        icon="success"
        title="导入完成"
        :sub-title="result.message"
      >
        <template #extra>
          <div class="si-stats result-stats">
            <div class="stat-item stat-create">
              <div class="stat-num">{{ result.created }}</div>
              <div class="stat-label">新增</div>
            </div>
            <div class="stat-item stat-update">
              <div class="stat-num">{{ result.updated }}</div>
              <div class="stat-label">覆盖</div>
            </div>
            <div class="stat-item stat-skip">
              <div class="stat-num">{{ result.skipped }}</div>
              <div class="stat-label">跳过</div>
            </div>
          </div>
        </template>
      </el-result>

      <el-alert
        v-if="result.warnings?.length"
        :title="`有 ${result.warnings.length} 条警告`"
        type="warning"
        :closable="false"
        show-icon
        style="margin-top: 16px;"
      >
        <template #default>
          <ul style="margin: 0; padding-left: 20px; font-size: 13px;">
            <li v-for="(w, i) in result.warnings.slice(0, 10)" :key="i">{{ w }}</li>
          </ul>
        </template>
      </el-alert>
    </div>

    <template #footer>
      <template v-if="step === 1">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :disabled="!file || previewLoading" :loading="previewLoading" @click="doPreview">
          下一步：预览
        </el-button>
      </template>
      <template v-else-if="step === 2">
        <el-button @click="step = 1">上一步</el-button>
        <el-button type="primary" :loading="confirmLoading" @click="doConfirm">
          确认导入
        </el-button>
      </template>
      <template v-else>
        <el-button type="primary" @click="finish">完成</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { importPreview, importConfirm } from '@/api/student'

// 导入完（或取消）之后由调用方决定刷什么：学生名单页刷列表，初始化浮层刷状态
const emit = defineEmits(['done'])

const visible = ref(false)
const step = ref(1) // 1=上传 2=预览 3=结果
const file = ref(null)
const uploadRef = ref(null)
const sheetName = ref('')
const previewLoading = ref(false)
const confirmLoading = ref(false)
const preview = ref(null)
const result = ref(null)
const token = ref('') // 服务端预览令牌，确认导入时要带回去

function open() {
  reset()
  visible.value = true
}

function reset() {
  step.value = 1
  file.value = null
  sheetName.value = ''
  preview.value = null
  result.value = null
  token.value = ''
  previewLoading.value = false
  confirmLoading.value = false
  // 清空上传组件的文件列表
  if (uploadRef.value) uploadRef.value.clearFiles()
}

function handleFileChange(f) {
  file.value = f.raw || f
}

function handleExceed() {
  ElMessage.warning('只能上传一个文件')
}

async function doPreview() {
  if (!file.value) {
    ElMessage.warning('请先选择文件')
    return
  }
  previewLoading.value = true
  try {
    const data = await importPreview(file.value, sheetName.value || undefined)
    preview.value = data
    token.value = data.token || ''
    step.value = 2
  } catch (e) {
    // request 拦截器会弹错误消息，这里只关 loading
  } finally {
    previewLoading.value = false
  }
}

async function handleSheetChange() {
  // 切工作表时重新预览
  if (!file.value) return
  previewLoading.value = true
  try {
    const data = await importPreview(file.value, sheetName.value)
    preview.value = data
    token.value = data.token || ''
  } catch (e) {
    // 拦截器会弹错
  } finally {
    previewLoading.value = false
  }
}

async function doConfirm() {
  if (!token.value) {
    ElMessage.error('预览已过期，请重新上传')
    return
  }
  confirmLoading.value = true
  try {
    const data = await importConfirm(token.value)
    result.value = data
    step.value = 3
    emit('done') // 库里的数据变了，叫调用方去刷新
  } catch (e) {
    // 拦截器弹错
  } finally {
    confirmLoading.value = false
  }
}

function finish() {
  visible.value = false
  reset()
}

defineExpose({ open })
</script>

<style scoped>
.si-step {
  min-height: 200px;
}
.si-uploader :deep(.el-upload-dragger) {
  padding: 32px 20px;
}
.si-stats {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.si-stats .stat-item {
  flex: 1;
  text-align: center;
  padding: 16px 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
}
.result-stats {
  justify-content: center;
  padding: 0 40px;
}
.stat-item .stat-num {
  font-size: 28px;
  font-weight: 600;
  line-height: 1.2;
  margin-bottom: 4px;
}
.stat-item .stat-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.stat-create .stat-num { color: #67c23a; }
.stat-update .stat-num { color: #e6a23c; }
.stat-skip .stat-num { color: var(--el-text-color-secondary); }
.stat-photo .stat-num { color: #409eff; }

.si-sample + .si-sample {
  margin-top: 16px;
}
.si-sample .sample-title {
  font-size: 14px;
  color: var(--el-text-color-regular);
  margin-bottom: 8px;
  font-weight: 500;
}
</style>
