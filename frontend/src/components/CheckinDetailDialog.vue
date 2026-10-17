<template>
  <el-dialog v-model="visible" width="700px">
    <!-- 标题就是列表里那一列，修改按钮跟在标题后面，不再单独占一行 -->
    <template #header>
      <div class="cd-header">
        <span class="cd-header-title">{{ detail.title || '签到明细' }}</span>
        <el-button link type="primary" size="small" @click="editTitle">修改</el-button>
      </div>
    </template>
    <div v-loading="loading" class="cd-body">
      <div class="cd-meta">
        <el-tag :type="detail.status === 'ongoing' ? 'success' : 'info'" size="small">
          {{ detail.status === 'ongoing' ? '进行中' : '已结束' }}
        </el-tag>
        <span class="cd-sub">
          {{ detail.created_by_name }} 发布于 {{ formatDateTime(detail.created_at) }}
        </span>
      </div>
      <div v-if="detail.remark" class="cd-remark-row">
        <span class="cd-label">说明</span>
        <span class="cd-remark-text">{{ detail.remark }}</span>
      </div>
      <div class="cd-line">
        <span class="cd-label">截止时间</span>
        <span>{{ formatDateTime(detail.end_at) }}</span>
        <span v-if="detail.closed_at" class="cd-sub">
          （已于 {{ formatDateTime(detail.closed_at) }} 结束）
        </span>
      </div>
      <div class="cd-line">
        <span class="cd-label">签到情况</span>
        <span>{{ detail.signed_count }} / {{ detail.target_count }} 人已签</span>
        <span v-if="detail.require_photo" class="cd-sub">（需上传照片）</span>
      </div>

      <!-- 地图只读展示：班委核对一下当时要求的位置和半径 -->
      <div v-if="detail.location" class="cd-location">
        <div class="cd-line">
          <span class="cd-label">签到地点</span>
          <span>{{ detail.location.name || '未命名地点' }}</span>
          <span class="cd-sub">
            允许半径 {{ detail.location.radius_m }} 米
          </span>
        </div>
        <MapPicker :model-value="{ lat: detail.location.lat, lng: detail.location.lng }"
          :radius="detail.location.radius_m" readonly />
      </div>

      <el-table :data="detail.targets" max-height="360" size="small" class="cd-table">
        <el-table-column prop="student_name" label="姓名" width="90" />
        <el-table-column prop="student_no" label="学号" width="120" />
        <el-table-column label="出勤状态" width="130">
          <template #default="{ row }">
            <!-- 结算后和点名记录一样，逐人改状态；改的是生成的那条考勤明细 -->
            <el-select
              v-if="detail.finalized_at && detail.attendance_record_id"
              :model-value="row.status"
              size="small"
              :disabled="savingStatus"
              @change="(value) => changeStatus(row, value)"
            >
              <el-option label="到" value="present" />
              <el-option label="无应答" value="absent" />
              <el-option label="请假" value="leave" />
            </el-select>
            <el-tag v-else-if="row.signed_at" type="success" size="small">已签到</el-tag>
            <el-tag v-else-if="row.on_leave" type="warning" size="small">请假中</el-tag>
            <el-tag v-else type="danger" size="small" effect="plain">未签到</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="距离" width="90">
          <template #default="{ row }">
            <span v-if="row.distance_m != null">{{ row.distance_m }} 米</span>
            <span v-else class="cd-sub">—</span>
          </template>
        </el-table-column>
        <el-table-column label="签到时间" width="150">
          <template #default="{ row }">
            {{ row.signed_at ? formatDateTime(row.signed_at) : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="照片">
          <template #default="{ row }">
            <el-button v-if="row.photo_url" link type="primary" @click="openPhoto(row)">
              查看照片
            </el-button>
            <span v-else class="cd-sub">—</span>
          </template>
        </el-table-column>
      </el-table>
      <p class="cd-tip">
        结算后「请假」指截止时刻持有已批准的请假；既没签到又没请假的算无应答。
        请假同学如果也签了到，按「已签到」算。结算后可以在「出勤状态」里直接改，
        和点名记录的明细一致
      </p>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>

  <!-- 看照片和看证明材料用同一个预览框：能缩放、旋转、下载 -->
  <FileViewer
    v-model="photoViewer.visible"
    :file-url="photoViewer.url"
    :file-name="photoViewer.fileName"
    :title="`${photoViewer.studentName} 的签到照片`"
  />
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MapPicker from '@/components/MapPicker.vue'
import FileViewer from '@/components/FileViewer.vue'
import { getCheckin, updateCheckinTitle } from '@/api/checkin'
import { updateAttendanceItem } from '@/api/attendance'
import { formatDateTime } from '@/utils/format'
import { errText } from '@/utils/request'

const emit = defineEmits(['updated'])
const visible = ref(false)
const loading = ref(false)
const savingStatus = ref(false)
const detail = ref({ targets: [] })

// 照片预览框的状态。只是交给 FileViewer 用，不改签到数据
const photoViewer = ref({ visible: false, url: '', fileName: '', studentName: '' })

/** 打开详情。参数是列表行也行，只用到 id */
async function open(row) {
  visible.value = true
  loading.value = true
  detail.value = { targets: [] }
  try {
    detail.value = await getCheckin(row.id)
  } catch (e) {
    ElMessage.error(errText(e, '读取签到明细失败'))
    visible.value = false
  } finally {
    loading.value = false
  }
}

/**
 * 查看签到照片
 *
 * 复用证明材料那个预览框：FileViewer 走 axios 带登录态取图，
 * 还能缩放、旋转、下载。签到页上传前统一压成 JPEG，文件名给 .jpg 即可判成图片。
 */
function openPhoto(row) {
  photoViewer.value = {
    visible: true,
    url: row.photo_url,
    fileName: `${row.student_name}_签到照片.jpg`,
    studentName: row.student_name
  }
}

/**
 * 改签到标题
 *
 * 列表的「标题」列显示的就是它，所以改完要通知父组件刷新列表。
 * 结束后也能改；标题不能为空，否则列表里认不出是哪次签到
 */
async function editTitle() {
  let value
  try {
    const res = await ElMessageBox.prompt('改签到标题', '标题', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: detail.value.title || '',
      inputPlaceholder: '例如：周六晚点名',
      inputPattern: /\S/,
      inputErrorMessage: '标题不能为空'
    })
    value = res.value
  } catch {
    return
  }
  const title = (value || '').trim()
  try {
    const updated = await updateCheckinTitle(detail.value.id, title)
    detail.value.title = updated.title
    ElMessage.success('标题已修改')
    emit('updated')
  } catch (e) {
    ElMessage.error(errText(e, '修改标题失败'))
  }
}

/**
 * 改某人结算后的出勤状态
 *
 * 不新开接口：读写的就是结算生成的那条考勤明细，
 * 这样「点名记录」和「签到详情」看到的是同一份数据。
 */
async function changeStatus(row, status) {
  if (status === row.status) return
  savingStatus.value = true
  try {
    const record = await updateAttendanceItem(
      detail.value.attendance_record_id, row.student_no, status
    )
    // 以服务端返回的明细为准，避免两边各改各的
    const byNo = Object.fromEntries((record.items || []).map((i) => [i.student_no, i.status]))
    for (const target of detail.value.targets) {
      if (byNo[target.student_no]) target.status = byNo[target.student_no]
    }
    ElMessage.success('已修改')
    // 结算后的签到行显示的就是这四个计数，改完要让列表跟着变
    emit('updated')
  } catch (e) {
    ElMessage.error(errText(e, '修改失败'))
  } finally {
    savingStatus.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
.cd-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cd-header-title {
  font-size: var(--el-dialog-title-font-size);
  line-height: var(--el-dialog-font-line-height);
  color: var(--el-text-color-primary);
}

.cd-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cd-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cd-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cd-label {
  margin-right: 8px;
  color: var(--el-text-color-secondary);
}

.cd-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 14px;
}

.cd-remark-row {
  display: flex;
  align-items: flex-start;
  gap: 4px;
}

.cd-remark-text {
  flex: 1;
  color: var(--el-text-color-regular);
  line-height: 1.5;
  white-space: pre-wrap;
}

.cd-location {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cd-table {
  margin-top: 4px;
}

.cd-tip {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
</style>
