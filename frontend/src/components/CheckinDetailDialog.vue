<template>
  <el-dialog v-model="visible" :title="detail.title || '签到详情'" width="700px">
    <div v-loading="loading" class="cd-body">
      <div class="cd-meta">
        <el-tag :type="detail.status === 'ongoing' ? 'success' : 'info'" size="small">
          {{ detail.status === 'ongoing' ? '进行中' : '已结束' }}
        </el-tag>
        <span class="cd-sub">
          {{ detail.created_by_name }} 发布于 {{ formatDateTime(detail.created_at) }}
        </span>
      </div>
      <div v-if="detail.remark" class="cd-remark">{{ detail.remark }}</div>
      <div class="cd-line">
        <span class="cd-label">截止时间</span>
        <span>{{ formatDateTime(detail.end_at) }}</span>
        <span v-if="detail.closed_at" class="cd-sub">
          （已于 {{ formatDateTime(detail.closed_at) }} 提前结束）
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
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.signed_at" type="success" size="small">已签到</el-tag>
            <el-tag v-else-if="row.on_leave" type="warning" size="small">请假</el-tag>
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
        请假同学如果也签了到，按「已签到」算
      </p>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import MapPicker from '@/components/MapPicker.vue'
import { getCheckin } from '@/api/checkin'
import { formatDateTime } from '@/utils/format'
import { errText } from '@/utils/request'

const visible = ref(false)
const loading = ref(false)
const detail = ref({ targets: [] })

/** 打开详情。参数是列表行也行，只用到 id */
async function open(row) {
  visible.value = true
  loading.value = true
  detail.value = { targets: [] }
  try {
    detail.value = await getCheckin(row.id)
  } catch (e) {
    ElMessage.error(errText(e, '读取签到详情失败'))
    visible.value = false
  } finally {
    loading.value = false
  }
}

/** 照片接口要登录态：新窗口打开会带上同一个 Cookie，直接交给浏览器 */
function openPhoto(row) {
  window.open(row.photo_url, '_blank', 'noopener')
}

defineExpose({ open })
</script>

<style scoped>
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

.cd-remark {
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  line-height: 1.5;
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
