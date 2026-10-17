<template>
  <div class="attendance">
    <!-- 和审核审批一样整页一张卡片：标题、筛选和列表都在里面 -->
    <div class="page-card">
      <div class="at-head">
        <h3 class="page-title">考勤记录</h3>
        <div class="at-actions">
          <!-- 点名：从学生信息页挪过来的，结果就落在本页的列表里 -->
          <el-button @click="rollCallRef?.open()">
            <el-icon><Pointer /></el-icon>点名
          </el-button>
          <el-button type="primary" @click="createRef?.open()">
            <el-icon><Plus /></el-icon>发布签到
          </el-button>
          <el-button @click="openExport">
            <el-icon><Download /></el-icon>导出
          </el-button>
          <!-- 勾选后才可用：一句确认删掉，省得一条条点 -->
          <el-button
            type="danger"
            plain
            :disabled="!selection.length"
            @click="handleBatchDelete"
          >
            批量删除<template v-if="selection.length">（{{ selection.length }}）</template>
          </el-button>
        </div>
      </div>

      <!-- 点名和签到共用一套筛选：关键词对点名查备注、对签到查标题 -->
      <el-form :inline="true" size="default">
        <el-form-item label="搜索">
          <el-input
            v-model="keyword"
            placeholder="搜索点名备注或签到标题"
            clearable
            style="width: 240px"
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
        </el-form-item>
      </el-form>

      <!-- 列表 -->
      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="rows"
        :row-key="rowKey"
        stripe
        style="margin-top: 12px;"
        empty-text="还没有考勤或签到记录。点一次名、发布一次签到都会出现在这里"
        @selection-change="handleSelectionChange"
      >
        <!-- 跨页保留勾选：导出一份记录时不用一页一页地重选 -->
        <el-table-column type="selection" width="46" :reserve-selection="true" fixed="left" />
        <el-table-column prop="date" label="日期" width="110" />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag
              :type="row.type === 'checkin' ? 'success' : 'primary'"
              size="small"
              effect="plain"
            >
              {{ row.type === 'checkin' ? '签到' : '点名' }}
            </el-tag>
          </template>
        </el-table-column>
        <!-- 范围：点名是「全班 / 团员 / 班委 / x 人」，签到按应到人数显示 x 人 -->
        <el-table-column label="范围" width="100">
          <template #default="{ row }">
            <span>{{ row.type === 'checkin' ? `${row.target_count}人` : row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">
            <div>{{ formatDateTime(row.time) }}</div>
            <div v-if="row.type === 'checkin'" class="at-sub">
              {{ row.status === 'ongoing' ? '截止' : '结束' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="operator_name" label="发起人" width="110" />
        <el-table-column label="出勤情况" min-width="210">
          <template #default="{ row }">
            <!-- 点名，以及结算后的签到：标准四计数。签到结算后本行直接换成
                 这个格式，不再另生成一条「点名」行 -->
            <template v-if="row.type === 'attendance' || row.status !== 'ongoing'">
              <span>应到 {{ row.total }}</span>
              <span class="at-sep">·</span>
              <span>实到 {{ row.present }}</span>
              <span class="at-sep">·</span>
              <span :class="{ 'at-warn': row.leave }">请假 {{ row.leave }}</span>
              <span class="at-sep">·</span>
              <span :class="{ 'at-danger': row.absent }">无应答 {{ row.absent }}</span>
            </template>
            <!-- 进行中的签到：实时人数，明细里有逐人情况 -->
            <template v-else>
              <span :class="{ 'at-done': row.signed_count > 0 }">
                已签 {{ row.signed_count }} / {{ row.target_count }}
              </span>
              <el-tag type="success" size="small" class="at-tag">进行中</el-tag>
            </template>
          </template>
        </el-table-column>
        <!-- 备注：点名是那一句话，签到就是标题（搜索也搜它）。
             签到自己的补充说明在明细里，不丢 -->
        <el-table-column label="备注" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.type === 'checkin'">{{ row.title }}</span>
            <span v-else-if="row.remark">{{ row.remark }}</span>
            <span v-else class="at-empty">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <div class="at-ops">
              <template v-if="row.type === 'attendance'">
                <el-button link type="primary" @click="openDetail(row)">明细</el-button>
                <el-button link type="primary" @click="handleRemark(row)">备注</el-button>
                <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
              </template>
              <template v-else>
                <el-button link type="primary" @click="copyText(row.link)">链接</el-button>
                <el-button link type="primary" @click="openCheckinDetail(row)">明细</el-button>
                <el-button link type="danger" @click="handleDeleteCheckin(row)">删除</el-button>
                <el-button
                  v-if="row.status === 'ongoing'"
                  link
                  type="danger"
                  @click="handleCloseCheckin(row)"
                >结束</el-button>
              </template>
            </div>
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
        @current-change="() => fetchList()"
      />
    </div>

    <!-- 点名明细：逐个改状态。当天点错了、事后有人说「我其实到了」都在这儿改 -->
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

    <!-- 签到详情：标题、备注、地点、要求和逐人签到情况，结束后同样能打开 -->
    <CheckinDetailDialog ref="checkinDetailRef" @updated="() => fetchList()" />

    <CheckinCreateDialog ref="createRef" @saved="() => fetchList()" />

    <!-- 点名弹窗：点完上报成功就刷新列表，新记录当场可见 -->
    <RollCallDialog ref="rollCallRef" @saved="() => fetchList()" />

    <!-- 导出：要么导勾选的，要么导当前筛选结果。两者含的记录不同，先说清楚条数 -->
    <el-dialog v-model="exportVisible" title="导出考勤与签到" width="420px">
      <el-radio-group v-model="exportMode" class="at-export-modes">
        <el-radio value="selected" :disabled="!selection.length">
          只导出选中的记录（{{ selection.length }} 条）
        </el-radio>
        <el-radio value="filtered">导出当前筛选结果（{{ total }} 条）</el-radio>
      </el-radio-group>
      <p class="at-tip">
        一个文件两个工作表：点名与签到结算后的明细都在「考勤记录」，
        「签到记录」放每人的签到时间、距离和请假情况。
      </p>
      <template #footer>
        <el-button @click="exportVisible = false">取消</el-button>
        <el-button type="primary" :loading="exporting" @click="doExport">导出</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import CheckinCreateDialog from '@/components/CheckinCreateDialog.vue'
import CheckinDetailDialog from '@/components/CheckinDetailDialog.vue'
import RollCallDialog from '@/components/RollCallDialog.vue'
import {
  attendanceExportUrl,
  batchDeleteAttendance,
  deleteAttendance,
  getAttendance,
  getAttendanceOverview,
  updateAttendanceItem,
  updateAttendanceRemark
} from '@/api/attendance'
import { closeCheckin, deleteCheckin } from '@/api/checkin'
import { copyText } from '@/utils/clipboard'
import { blobErrorDetail, downloadFile } from '@/utils/download'
import { formatDateTime } from '@/utils/format'
import { errText } from '@/utils/request'

const loading = ref(false)
const exporting = ref(false)
const rows = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const dateRange = ref(null)
// 关键词对点名查备注、对签到查标题。和日期范围是「并且」的关系，可以只给一个
const keyword = ref('')

const tableRef = ref(null)
const selection = ref([])
const createRef = ref(null)
const checkinDetailRef = ref(null)
const rollCallRef = ref(null)

const exportVisible = ref(false)
const exportMode = ref('filtered')

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailSaving = ref(false)
const detail = ref({ items: [], call_date: '', scope: '' })

const detailTitle = computed(() =>
  detail.value.id ? `${detail.value.call_date} ${detail.value.scope} 点名明细` : '点名明细'
)

/** 点名的 id 和签到的 id 各自独立，加前缀才不会撞到一起（跨页勾选靠它） */
function rowKey(row) {
  return `${row.type}-${row.id}`
}

async function fetchList(quiet = false) {
  if (!quiet) loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (dateRange.value?.length === 2) {
      params.start = dateRange.value[0]
      params.end = dateRange.value[1]
    }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const res = await getAttendanceOverview(params)
    rows.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    // 后台静默刷新失败不打扰用户，下一次轮询会再试
    if (!quiet) ElMessage.error(errText(e, '读取考勤记录失败'))
  } finally {
    if (!quiet) loading.value = false
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

function handleSelectionChange(selected) {
  selection.value = selected
}

/** 有进行中的签到时定时刷新：已签人数是实时变的，不用等用户自己点 */
let refreshTimer = null
function startAutoRefresh() {
  refreshTimer = setInterval(() => {
    const ongoing = rows.value.some((r) => r.type === 'checkin' && r.status === 'ongoing')
    if (ongoing && document.visibilityState === 'visible' && !loading.value) fetchList(true)
  }, 30000)
}

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = { items: [], call_date: row.date, scope: row.title }
  try {
    detail.value = await getAttendance(row.id)
  } catch (e) {
    ElMessage.error(errText(e, '读取明细失败'))
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

function openCheckinDetail(row) {
  checkinDetailRef.value?.open(row)
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
    ElMessage.error(errText(e, '修改失败'))
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
    ElMessage.error(errText(e, '保存备注失败'))
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.date} ${row.title}」这条考勤记录吗？明细会一起删掉。`
      + '若它由签到自动生成，那次签到和链接也会一并删除。',
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
    ElMessage.error(errText(e, '删除失败'))
  }
}

/** 删除签到。结算生成的考勤记录会一起删，链接随即失效 */
async function handleDeleteCheckin(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.title}」这次签到吗？链接会失效，已结算的考勤记录也会一起删掉。`,
      '提示',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await deleteCheckin(row.id)
    ElMessage.success('已删除')
    if (rows.value.length === 1 && currentPage.value > 1) currentPage.value -= 1
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, '删除失败'))
  }
}

/**
 * 批量删除勾选的记录
 *
 * 勾选跨页保留，所以删完直接清空勾选并刷新当前页；后端把签到生成的考勤
 * 连签到一起删，这里只负责说清楚后果。若当前页的记录被删光，回退一页
 */
async function handleBatchDelete() {
  if (!selection.value.length) return
  const checkinCount = selection.value.filter((r) => r.type === 'checkin').length
  const recordCount = selection.value.length - checkinCount
  const parts = []
  if (recordCount) parts.push(`${recordCount} 条点名记录`)
  if (checkinCount) parts.push(`${checkinCount} 条签到`)
  try {
    await ElMessageBox.confirm(
      `确定删除选中的${parts.join('、')}吗？`
      + (checkinCount
        ? '签到的链接会失效，照片以及结算生成的考勤一并删除。'
        : '')
      + '删除后不可恢复。',
      '批量删除',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  const onPage = rows.value.filter((row) =>
    selection.value.some((picked) => rowKey(picked) === rowKey(row))
  ).length
  try {
    const res = await batchDeleteAttendance({
      recordIds: selection.value.filter((r) => r.type === 'attendance').map((r) => r.id),
      checkinIds: selection.value.filter((r) => r.type === 'checkin').map((r) => r.id)
    })
    ElMessage.success(`已删除 ${res.deleted} 条记录`)
    tableRef.value?.clearSelection()
    selection.value = []
    if (onPage >= rows.value.length && currentPage.value > 1) currentPage.value -= 1
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, '批量删除失败'))
  }
}

/**
 * 提前结束并结算
 *
 * 结束不是「关掉入口」这么简单：它会立刻生成考勤记录，之后就不能再签了。
 * 所以给一次确认，并说清后果
 */
async function handleCloseCheckin(row) {
  try {
    await ElMessageBox.confirm(
      `确定结束「${row.title}」吗？结束后立即结算，还没签的同学不能再签。`,
      '结束签到',
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

function openExport() {
  // 勾了东西就默认导勾选的，否则导当前筛选结果
  exportMode.value = selection.value.length ? 'selected' : 'filtered'
  exportVisible.value = true
}

/**
 * 按选中的模式下载
 *
 * 必须走 downloadFile（带登录态、会被 401 拦截器接住），
 * 直接用 <a href> 拿到的是一个 401 的 JSON 还当成文件存下来。
 * 存盘名要自己拼：走 blob 拿不到响应头里的名字
 */
async function doExport() {
  const start = dateRange.value?.[0] || null
  const end = dateRange.value?.[1] || null
  let url
  let filename
  if (exportMode.value === 'selected' && selection.value.length) {
    url = attendanceExportUrl({
      recordIds: selection.value.filter((r) => r.type === 'attendance').map((r) => r.id),
      checkinIds: selection.value.filter((r) => r.type === 'checkin').map((r) => r.id)
    })
    filename = `考勤与签到_选中${selection.value.length}条.xlsx`
  } else {
    url = attendanceExportUrl({ start, end, keyword: keyword.value.trim() || undefined })
    filename = `考勤与签到_${start || '全部'}_${end || '全部'}.xlsx`
  }
  exporting.value = true
  try {
    await downloadFile(url, filename)
    exportVisible.value = false
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e, '导出失败'))
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  fetchList()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  clearInterval(refreshTimer)
})
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

.at-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.at-actions {
  display: flex;
  gap: 8px;
}

.at-warn {
  color: var(--el-color-warning);
  font-weight: 600;
}

.at-danger {
  color: var(--el-color-danger);
  font-weight: 600;
}

.at-done {
  color: var(--el-color-success);
  font-weight: 600;
}

.at-tag {
  margin-left: 8px;
}

/* 操作列里的按钮不折行，宁可整列宽一点 */
.at-ops {
  white-space: nowrap;
}

.at-sep {
  margin: 0 4px;
  color: var(--el-text-color-placeholder);
}

.at-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
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

.at-tip {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.at-export-modes {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
}
</style>
