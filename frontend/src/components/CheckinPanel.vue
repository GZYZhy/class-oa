<template>
  <div class="checkin-panel">
    <div class="cp-bar">
      <el-button type="primary" @click="createRef.open()">
        <el-icon><Plus /></el-icon>发布签到
      </el-button>
      <el-button :loading="loading" @click="fetchList">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <span class="cp-tip">
        到截止时间自动结算成一条考勤记录；范围内同学会收到站内信
      </span>
    </div>

    <el-table
      v-loading="loading"
      :data="rows"
      stripe
      empty-text="还没有签到。发布一次，范围内的同学就会收到站内信"
    >
      <el-table-column label="标题" min-width="200">
        <template #default="{ row }">
          <div>{{ row.title }}</div>
          <div class="cp-sub">{{ row.created_by_name }} 发布</div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'ongoing' ? 'success' : 'info'" size="small">
            {{ row.status === 'ongoing' ? '进行中' : '已结束' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="签到情况" width="110" align="center">
        <template #default="{ row }">
          <span :class="{ 'cp-done': row.signed_count > 0 }">
            {{ row.signed_count }} / {{ row.target_count }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="截止时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.end_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="210" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="copyText(row.link)">复制链接</el-button>
          <el-button link type="primary" @click="detailRef.open(row)">详情</el-button>
          <el-button
            v-if="row.status === 'ongoing'"
            link
            type="danger"
            @click="handleClose(row)"
          >提前结束</el-button>
        </template>
      </el-table-column>
    </el-table>

    <CheckinCreateDialog ref="createRef" @saved="fetchList" />
    <CheckinDetailDialog ref="detailRef" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import CheckinCreateDialog from '@/components/CheckinCreateDialog.vue'
import CheckinDetailDialog from '@/components/CheckinDetailDialog.vue'
import { closeCheckin, getCheckins } from '@/api/checkin'
import { copyText } from '@/utils/clipboard'
import { formatDateTime } from '@/utils/format'
import { errText } from '@/utils/request'

const loading = ref(false)
const rows = ref([])
const createRef = ref(null)
const detailRef = ref(null)

async function fetchList() {
  loading.value = true
  try {
    const res = await getCheckins()
    rows.value = res.items || []
  } catch (e) {
    ElMessage.error(errText(e, '读取签到列表失败'))
  } finally {
    loading.value = false
  }
}

/**
 * 提前结束并结算
 *
 * 结束不是「关掉入口」这么简单：它会立刻生成考勤记录，之后就不能再签了。
 * 所以给一次确认，并说清后果
 */
async function handleClose(row) {
  try {
    await ElMessageBox.confirm(
      `确定提前结束「${row.title}」吗？结束后立即结算，还没签的同学不能再签。`,
      '提前结束签到',
      { type: 'warning', confirmButtonText: '结束并结算', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await closeCheckin(row.id)
    ElMessage.success('已结束并结算')
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, '结束失败'))
  }
}

onMounted(fetchList)
</script>

<style scoped>
.cp-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.cp-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cp-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cp-done {
  color: var(--el-color-success);
  font-weight: 600;
}
</style>
