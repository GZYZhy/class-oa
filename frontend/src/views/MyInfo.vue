<template>
  <div v-loading="loading">
    <!-- 基本信息：只读，任何人都不能在这里直接改，要改走下面的申请 -->
    <div class="page-card">
      <h3 class="page-title">我的信息</h3>

      <template v-if="me">
        <!-- 两张照片：高考照片 + 实地采集，点一下放大 -->
        <div class="photos-row">
          <div
            v-for="item in PHOTOS"
            :key="item.type"
            class="photo-item"
            :class="{ 'photo-empty-box': !hasPhoto(item.type) }"
            @click="openPhotos(item.type)"
          >
            <img
              v-if="hasPhoto(item.type)"
              :src="photoUrl(item.type)"
              class="photo-img"
              :alt="item.label"
              @error="onImgError"
            />
            <div v-else class="photo-placeholder">
              <el-icon style="font-size: 34px;"><Avatar /></el-icon>
              <span>暂无照片</span>
            </div>
            <div class="photo-label">{{ item.label }}</div>
          </div>
        </div>
        <p class="photos-tip">点击照片可放大查看</p>

        <el-descriptions :column="detailColumns" border style="margin-top: 16px;">
          <el-descriptions-item label="学号">{{ me.student_no || '-' }}</el-descriptions-item>
          <el-descriptions-item label="姓名">{{ me.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="性别">{{ me.gender || '-' }}</el-descriptions-item>
          <el-descriptions-item label="出生日期">{{ me.birth_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="民族">{{ me.ethnicity || '-' }}</el-descriptions-item>
          <el-descriptions-item label="政治面貌">{{ me.political_status || '-' }}</el-descriptions-item>
          <el-descriptions-item label="学院/班级">{{ me.class_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="专业">{{ me.major || '-' }}</el-descriptions-item>
          <el-descriptions-item label="宿舍">{{ me.dormitory || '-' }}</el-descriptions-item>
          <el-descriptions-item label="床位号">{{ me.bed || '-' }}</el-descriptions-item>
          <el-descriptions-item label="本人电话">{{ me.phone || '-' }}</el-descriptions-item>
          <el-descriptions-item label="高考总分">{{ me.gaokao_score ?? '-' }}</el-descriptions-item>
          <!-- 备注是班委内部记录，普通学生拿到的一律是 null，只有班委/管理员能看到自己的 -->
          <el-descriptions-item v-if="me.remark" label="备注" :span="detailColumns">
            {{ me.remark }}
          </el-descriptions-item>
        </el-descriptions>
      </template>
      <el-empty v-else-if="!loading" description="未获取到个人信息" />
    </div>

    <!-- 申请修改：默认收起来，点「修改」才展开；一次只能有一条待审核的申请 -->
    <div class="page-card" style="margin-top: 20px;">
      <div class="page-toolbar">
        <h3 class="page-title" style="margin-bottom: 0;">申请修改</h3>
        <el-button v-if="canApply" type="primary" @click="openForm">修改</el-button>
      </div>

      <!-- 已经有一条排队等审：只解释原因，不给入口 -->
      <el-alert
        v-if="pending"
        type="warning"
        :closable="false"
        show-icon
        style="margin-top: 16px;"
      >
        <template #title>
          你有一条待审核的申请（{{ formatDateTime(pending.created_at) }} 提交），班委处理后才能再次提交。
        </template>
        <div style="margin-top: 4px;">{{ describeChanges(pending.changes) }}</div>
      </el-alert>

      <el-alert
        v-else-if="!formVisible"
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 16px;"
        title="点右上角「修改」可申请改动下方内容，提交后需班委审核，审核通过才会真正生效。"
      />

      <el-form v-else :model="form" label-width="100px" style="max-width: 640px; margin-top: 16px;">
        <el-form-item v-for="f in CHANGE_FIELDS" :key="f.prop" :label="f.label">
          <el-select v-if="f.prop === 'is_poor'" v-model="form.is_poor" style="width: 160px">
            <el-option label="是" value="是" />
            <el-option label="否" value="否" />
          </el-select>
          <el-input
            v-else
            v-model="form[f.prop]"
            :type="f.prop === 'family_address' ? 'textarea' : 'text'"
            :rows="2"
            :placeholder="f.placeholder"
            :maxlength="f.maxLength"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">提交申请</el-button>
          <el-button @click="formVisible = false">取消</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 申请记录 -->
    <div class="page-card" style="margin-top: 20px;">
      <h3 class="page-title">我的申请记录</h3>
      <el-table :data="records" stripe border style="width: 100%;">
        <el-table-column label="申请时间" width="160" align="center">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="申请修改的内容" min-width="260">
          <template #default="{ row }">{{ describeChanges(row.changes) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="STATUS_TYPES[row.status]" size="small">
              {{ STATUS_LABELS[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="审核人" width="100" align="center">
          <template #default="{ row }">{{ row.reviewer_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="审核时间" width="160" align="center">
          <template #default="{ row }">{{ formatDateTime(row.reviewed_at) }}</template>
        </el-table-column>
        <el-table-column label="驳回理由" min-width="160">
          <template #default="{ row }">
            <span :style="{ color: row.reason ? '#f56c6c' : '#c0c4cc' }">{{ row.reason || '-' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!records.length" description="还没有提交过申请" style="margin-top: 20px;" />
    </div>

    <!-- 照片查看器 -->
    <el-image-viewer
      v-if="viewerVisible"
      :url-list="viewerList"
      :initial-index="viewerIndex"
      @close="viewerVisible = false"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getMyInfo } from '@/api/student'
import { submitChangeRequest, getMyChangeRequests } from '@/api/changeRequest'
import { CHANGE_FIELDS, FIELD_LABELS, STATUS_LABELS, STATUS_TYPES } from '@/utils/changeFields'
import { formatDateTime } from '@/utils/format'
import { useIsMobile } from '@/composables/useIsMobile'

// 手机上 3 列会把标签挤成竖排（「政 治 面 貌」），收成 1 列
const isMobile = useIsMobile()
const detailColumns = computed(() => (isMobile.value ? 1 : 3))

// 两个照片位：高考照片和实地采集，字段名与后端 students 表一致
const PHOTOS = [
  { type: 'gaokao', field: 'gaokao_photo', label: '高考照片' },
  { type: 'on_site', field: 'on_site_photo', label: '实地采集' }
]

const loading = ref(false)
const submitting = ref(false)
const me = ref(null)
const records = ref([])

// 申请表单默认收起来，点「修改」才展开
const formVisible = ref(false)

// 表单先摆全部字段，拿到自己的信息后再回填
const form = reactive(Object.fromEntries(CHANGE_FIELDS.map((f) => [f.prop, ''])))

/** 已经有一条排队等着审，就锁住表单（后端也会拒，前端锁住体验更好） */
const pending = computed(() => records.value.find((r) => r.status === 'pending'))
const canApply = computed(() => !pending.value && !formVisible.value)

// 照片查看器
const viewerVisible = ref(false)
const viewerList = ref([])
const viewerIndex = ref(0)

/** 照片走带鉴权的接口，不直连静态目录（和「学生信息」页一个取法） */
function photoUrl(type) {
  return `/api/students/${me.value?.id}/photo?type=${type}`
}

function hasPhoto(type) {
  const field = PHOTOS.find((p) => p.type === type)?.field
  return !!me.value?.[field]
}

function onImgError(e) {
  e.target.style.display = 'none'
}

/** 打开查看器：只在已有的照片之间翻页 */
function openPhotos(activeType) {
  const photos = PHOTOS.filter((p) => hasPhoto(p.type))
  if (!photos.length) return
  viewerList.value = photos.map((p) => photoUrl(p.type))
  const index = photos.findIndex((p) => p.type === activeType)
  viewerIndex.value = index >= 0 ? index : 0
  viewerVisible.value = true
}

/** 把 {"qq":"123","email":null} 说成「QQ号码：123；电子邮箱：（清空）」 */
function describeChanges(changes) {
  const parts = Object.entries(changes || {}).map(
    ([key, value]) => `${FIELD_LABELS[key] || key}：${value ? value : '（清空）'}`
  )
  return parts.length ? parts.join('；') : '-'
}

/** 回填表单：显示当前值，学生在此基础上改 */
function resetForm() {
  for (const { prop } of CHANGE_FIELDS) {
    form[prop] = me.value?.[prop] ?? ''
  }
}

function openForm() {
  resetForm()
  formVisible.value = true
}

/** 只把改动过的字段提交上去，避免整表覆盖 */
function buildChanges() {
  const changes = {}
  for (const { prop } of CHANGE_FIELDS) {
    const next = (form[prop] ?? '').trim()
    const old = (me.value?.[prop] ?? '').trim()
    if (next !== old) changes[prop] = next
  }
  return changes
}

function validate() {
  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
    ElMessage.warning('电子邮箱格式不正确')
    return false
  }
  if (form.postal_code && !/^\d{6}$/.test(form.postal_code.trim())) {
    ElMessage.warning('邮政编码应为 6 位数字')
    return false
  }
  return true
}

async function fetchData() {
  loading.value = true
  try {
    me.value = await getMyInfo()
    records.value = await getMyChangeRequests()
    resetForm()
  } catch (e) {
    ElMessage.error('个人信息加载失败')
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  if (pending.value) return ElMessage.warning('已有一条待审核的申请')
  if (!validate()) return
  const changes = buildChanges()
  if (!Object.keys(changes).length) return ElMessage.warning('没有修改任何内容')

  submitting.value = true
  try {
    await submitChangeRequest(changes)
    ElMessage.success('已提交，等待班委审核')
    formVisible.value = false
    await fetchData()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

onMounted(fetchData)
</script>

<style scoped>
.page-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.photos-row {
  display: flex;
  gap: 20px;
  margin-top: 4px;
}

.photo-item {
  position: relative;
  width: 200px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #ebeef5;
  cursor: zoom-in;
}

/* 没有照片时不显示放大手势 */
.photo-empty-box {
  cursor: default;
}

.photo-img {
  width: 100%;
  height: 160px;
  /* contain 保证原比例完整展示、不裁切 */
  object-fit: contain;
  display: block;
  background: #f5f7fa;
  padding: 8px;
  box-sizing: border-box;
}

.photo-placeholder {
  height: 160px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #c0c4cc;
  background: #f5f7fa;
  font-size: 13px;
}

.photo-label {
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  text-align: center;
  padding: 6px 0;
  font-size: 13px;
}

.photos-tip {
  text-align: center;
  font-size: 12px;
  color: #c0c4cc;
  margin: 8px 0 0 0;
  /* 定宽会和照片一起居中；窄屏时收成整行，不然会顶出横向滚动条 */
  width: 100%;
  max-width: 420px;
}
</style>
