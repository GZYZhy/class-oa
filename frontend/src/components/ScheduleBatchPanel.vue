<template>
  <div class="batch-panel">
    <div v-if="userStore.isExternal" class="batch-note">
      域外账号没有学籍档案，也就没有自己的日程，这里没有可管理的批次。
    </div>
    <div v-else class="batch-note">
      这里是<strong>你自己</strong>分配出去的日程批次（批量创建、课表导入）。撤销一个批次，
      会把它当初发给每个学生的那几条日程一并删掉，不可恢复。
      <el-button size="small" style="margin-left: 8px" @click="load">刷新</el-button>
    </div>

    <el-table
      v-if="!userStore.isExternal"
      v-loading="loading"
      :data="batches"
      empty-text="没有分配过日程"
      stripe
    >
      <el-table-column prop="name" label="批次名称" min-width="200" show-overflow-tooltip align="left" />
      <el-table-column prop="target_count" label="目标人数" width="100" align="right" />
      <!-- 「日程数」是**每人**几条（原来只叫「日程数」，看着像这一批一共几条，
           36 人的生日批次显示成 4 很容易看岔），另给一列合计 -->
      <el-table-column prop="schedule_count" label="每人日程数" width="110" align="right" />
      <el-table-column label="合计" width="100" align="right">
        <template #default="{ row }">{{ (row.target_count || 0) * (row.schedule_count || 0) }}</template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" align="center">
        <template #default="{ row }">
          <el-button type="danger" link size="small" @click="handleDelete(row)">撤销</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listBatches, deleteBatch } from '@/api/schedule'
import { errText } from '@/utils/request'
import { formatDateTime } from '@/utils/format'
import { useUserStore } from '@/store/user'

const userStore = useUserStore()

const batches = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    batches.value = await listBatches()
  } catch (e) {
    ElMessage.error(errText(e, '读取批次失败'))
  } finally {
    loading.value = false
  }
}

async function handleDelete(row) {
  // 撤销是不可恢复的，先把「要删掉多少条」算给用户看：target_count × schedule_count
  const total = (row.target_count || 0) * (row.schedule_count || 0)
  try {
    await ElMessageBox.confirm(
      `撤销「${row.name}」？会从 ${row.target_count} 名学生的日程表里删掉各 ${row.schedule_count} 条日程`
      + `（共 ${total} 条），不可恢复。`,
      '撤销批次',
      { type: 'warning' }
    )
  } catch { return }

  try {
    const res = await deleteBatch(row.id)
    ElMessage.success(`已撤销，删掉 ${res.deleted} 条日程`)
    load()
  } catch (e) {
    ElMessage.error(errText(e, '撤销失败'))
  }
}

// 挂在「系统管理」的 tab 里，这个 tab 不是懒加载的，一进系统管理就挂上了，
// 所以这里自己拉一次
//
// 域外账号（含首次初始化的那个 admin）没有学籍档案，接口是 get_current_student，
// 会回 403「域外账号不支持该功能」—— 不判一下的话，一打开系统管理就弹一条红字
onMounted(() => {
  if (!userStore.isExternal) load()
})
</script>

<style scoped>
.batch-note {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
  margin-bottom: 12px;
}
</style>
