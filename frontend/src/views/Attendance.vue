<template>
  <div class="attendance">
    <!-- 和审核审批一样整页一张卡片：标题、筛选和列表都在里面 -->
    <div class="page-card">
      <h3 class="page-title">考勤记录</h3>
      <!-- 两个标签：原来「点名」的记录原样保留，新加的「签到」是学生自己确认到场 -->
      <el-tabs v-model="activeTab">
        <el-tab-pane label="点名记录" name="records">
          <el-form :inline="true" size="default">
            <el-form-item label="备注">
              <el-input
                v-model="keyword"
                placeholder="搜索点名备注"
                clearable
                style="width: 200px"
                @keyup.enter="handleSearch"
                @clear="handleSearch"
              >
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-form-item label="日期">
              <el-date-picker
                v-model="dateRange"
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
                <el-icon><Search /></el-icon>查询
              </el-button>
              <el-button @click="handleReset">
                <el-icon><Refresh /></el-icon>重置
              </el-button>
              <el-button :loading="exporting" @click="handleExport">
                <el-icon><Download /></el-icon>导出
              </el-button>
            </el-form-item>
          </el-form>

          <!-- 列表 -->
          <el-table
            v-loading="loading"
            :data="rows"
            stripe
            style="margin-top: 16px;"
            empty-text="这段时间还没有点名记录，在学生信息页点一次名就会出现在这里"
          >
            <el-table-column prop="call_date" label="日期" width="120" />
            <el-table-column prop="scope" label="范围" width="90" />
            <el-table-column label="点名时刻" width="150">
              <template #default="{ row }">{{ formatDateTime(row.called_at) }}</template>
            </el-table-column>
            <el-table-column prop="operator_name" label="点名的人" width="110" />
            <el-table-column label="应到" width="80" align="center">
              <template #default="{ row }">{{ row.total }}</template>
            </el-table-column>
            <el-table-column label="实到" width="80" align="center">
              <template #default="{ row }">{{ row.present }}</template>
            </el-table-column>
            <el-table-column label="请假" width="80" align="center">
              <template #default="{ row }">
                <span :class="{ 'at-warn': row.leave }">{{ row.leave }}</span>
              </template>
            </el-table-column>
            <el-table-column label="无应答" width="90" align="center">
              <template #default="{ row }">
                <span :class="{ 'at-danger': row.absent }">{{ row.absent }}</span>
              </template>
            </el-table-column>
            <!-- 一次点名一句话。写得下的会长，所以给整行省略 + 悬浮看全文；
                 没写就是「—」，比空格子好认 -->
            <el-table-column label="备注" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.remark">{{ row.remark }}</span>
                <span v-else class="at-empty">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="190" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">明细</el-button>
                <el-button link type="primary" @click="handleRemark(row)">备注</el-button>
                <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50, 100]"
            :total="total"
            layout="total, sizes, prev, pager, next, jumper"
            background
            class="at-pager"
            @size-change="handleSizeChange"
            @current-change="fetchList"
          />
        </el-tab-pane>

        <el-tab-pane label="签到" name="checkin">
          <CheckinPanel />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 明细：逐个改状态。当天点错了、事后有人说「我其实到了」都在这儿改 -->
    <el-dialog v-model="detailVisible" :title="detailTitle" width="560px">
      <!-- 这次点名的备注也带进来：翻明细时看得到「为什么这次状态长这样」 -->
      <div v-if="detail.remark" class="at-remark">{{ detail.remark }}</div>
      <el-table v-loading="detailLoading" :data="detail.items" max-height="420">
        <el-table-column prop="student_name" label="姓名" />
        <el-table-column prop="student_no" label="学号" width="130" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-select
              :model-value="row.status"
              size="small"
              :disabled="detailSaving"
              @change="(value) => changeStatus(row, value)"
            >
              <el-option label="到" value="present" />
              <el-option label="无应答" value="absent" />
              <el-option label="请假" value="leave" />
            </el-select>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import CheckinPanel from '@/components/CheckinPanel.vue'
import {
  attendanceExportUrl,
  deleteAttendance,
  getAttendance,
  getAttendanceList,
  updateAttendanceItem,
  updateAttendanceRemark
} from '@/api/attendance'
import { blobErrorDetail, downloadFile } from '@/utils/download'
import { formatDateTime } from '@/utils/format'

/** 当前标签页：records = 原来的点名记录，checkin = 签到 */
const activeTab = ref('records')
const loading = ref(false)
const exporting = ref(false)
const rows = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const dateRange = ref(null)
// 备注关键词。和日期范围是「并且」的关系，可以只给一个
const keyword = ref('')

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailSaving = ref(false)
const detail = ref({ items: [], call_date: '', scope: '' })

const detailTitle = computed(() =>
  detail.value.id ? `${detail.value.call_date} ${detail.value.scope} 点名明细` : '点名明细'
)

async function fetchList() {
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (dateRange.value?.length === 2) {
      params.start = dateRange.value[0]
      params.end = dateRange.value[1]
    }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const res = await getAttendanceList(params)
    rows.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取考勤记录失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
  fetchList()
}

function handleReset() {
  dateRange.value = null
  keyword.value = ''
  handleSearch()
}

function handleSizeChange() {
  currentPage.value = 1
  fetchList()
}

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = { items: [], call_date: row.call_date, scope: row.scope }
  try {
    detail.value = await getAttendance(row.id)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取明细失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

/** 改一个人的状态。改完列表上的计数也要跟着变，所以两边都刷一次 */
async function changeStatus(item, status) {
  if (status === item.status) return
  detailSaving.value = true
  try {
    detail.value = await updateAttendanceItem(detail.value.id, item.student_no, status)
    ElMessage.success('已修改')
    fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  } finally {
    detailSaving.value = false
  }
}

/**
 * 给这次点名写一句备注
 *
 * 整条替换：填什么存什么，清空就没了（后端没有单独的「删备注」接口）。
 * 不改明细里的任何状态，所以不用刷明细弹窗，只刷列表
 */
async function handleRemark(row) {
  let value
  try {
    const res = await ElMessageBox.prompt('给这次点名写一句说明（留空即清掉）', '备注', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: row.remark || '',
      inputPlaceholder: '例如：学院临时集合，迟到 5 人',
      inputValidator: (v) => (v || '').trim().length <= 200 || '最多 200 字'
    })
    value = res.value
  } catch {
    // 取消：ElMessageBox 用 reject 表达取消，不是错误
    return
  }
  const remark = (value || '').trim()
  try {
    await updateAttendanceRemark(row.id, remark)
    ElMessage.success(remark ? '备注已保存' : '备注已清掉')
    fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存备注失败')
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.call_date} ${row.scope}」这条考勤记录吗？明细会一起删掉。`,
      '提示',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await deleteAttendance(row.id)
    ElMessage.success('已删除')
    // 删掉当前页最后一条时要往前退一页，否则会停在空页上
    if (rows.value.length === 1 && currentPage.value > 1) currentPage.value -= 1
    fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

/** 导出当前日期区间的明细。
 *  必须走 downloadFile（带登录态、会被 401 拦截器接住），
 *  直接用 <a href> 拿到的是一个 401 的 JSON 还当成文件存下来。
 *  存盘名要自己拼：走 blob 拿不到响应头里的名字 */
async function handleExport() {
  const start = dateRange.value?.[0] || '全部'
  const end = dateRange.value?.[1] || '全部'
  exporting.value = true
  try {
    await downloadFile(attendanceExportUrl(start === '全部' ? null : start, end === '全部' ? null : end),
      `考勤记录_${start}_${end}.xlsx`)
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e, '导出失败'))
  } finally {
    exporting.value = false
  }
}

onMounted(fetchList)
</script>

<style scoped>
.attendance {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.at-pager {
  margin-top: 16px;
  justify-content: flex-end;
}

.at-warn {
  color: var(--el-color-warning);
  font-weight: 600;
}

.at-danger {
  color: var(--el-color-danger);
  font-weight: 600;
}

.at-empty {
  color: var(--el-text-color-placeholder);
}

.at-remark {
  margin-bottom: 10px;
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  line-height: 1.5;
}
</style>
