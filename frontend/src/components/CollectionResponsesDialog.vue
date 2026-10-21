<!--
  收集答卷详情（发起人/管理员）

  三个页签：答卷 / 未填名单 / 统计。打开期间每 5 秒刷新一次，结束或关闭弹窗即停。
  删除答卷只有系统管理员能做（后端 admin_required 兜底），发起班委只看和导出。
-->
<template>
  <el-dialog
    v-model="visible"
    :title="`${detail.title || collection.title || '收集'} · 答卷详情`"
    width="900px"
    top="5vh"
    :close-on-click-modal="false"
    @closed="stopPolling"
  >
    <Watermark :text="watermarkText" />
    <div v-loading="loading" class="cr-body">
      <!-- 顶部信息与操作 -->
      <div class="cr-head">
        <div class="cr-meta">
          <el-tag :type="statusTag(detail.status)" size="small">{{ statusLabel(detail.status) }}</el-tag>
          <el-tag v-if="detail.anonymous" type="warning" size="small" effect="plain">不记名</el-tag>
          <span class="cr-sub">
            已收 {{ detail.submitted_count ?? responses.total }} 份
            · {{ detail.submitted_people ?? 0 }} 人已填
            · 每人 {{ detail.submit_quota ?? 1 }} 份
          </span>
          <span v-if="detail.max_responses" class="cr-sub">
            · 限收 {{ detail.max_responses }} 份（剩 {{ detail.remaining_slots ?? 0 }}）
          </span>
        </div>
        <div class="cr-actions">
          <el-button size="small" :loading="exporting" @click="handleExport">导出 Excel</el-button>
          <el-button
            size="small"
            type="primary"
            :loading="reminding"
            :disabled="!canRemind || remindableCount === 0"
            @click="handleRemind"
          >
            提醒未填（{{ remindableCount }}）
          </el-button>
        </div>
      </div>

      <el-tabs v-model="tab">
        <!-- ---------- 答卷 ---------- -->
        <el-tab-pane :label="`答卷（${responses.total}）`" name="responses">
          <div class="cr-toolbar">
            <span class="cr-sub">按提交时间排序，可切换正序 / 倒序</span>
            <div class="cr-toolbar-right">
              <el-button size="small" @click="toggleOrder">
                {{ order === 'asc' ? '时间正序' : '时间倒序' }}
              </el-button>
              <el-button
                v-if="canDelete"
                size="small"
                type="danger"
                plain
                :disabled="!selectedIds.length"
                @click="handleBatchDelete"
              >
                删除所选（{{ selectedIds.length }}）
              </el-button>
            </div>
          </div>

          <el-table
            v-loading="responseLoading"
            :data="responses.items"
            row-key="id"
            stripe
            max-height="430"
            empty-text="还没有人提交答卷"
            @selection-change="(rows) => (selectedIds = rows.map((row) => row.id))"
          >
            <el-table-column v-if="canDelete" type="selection" width="44" />
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="cr-expand">
                  <CollectionAnswers
                    :questions="detail.questions"
                    :answers="row.answers"
                    :collection-id="detail.id"
                    :response-id="row.id"
                  />
                </div>
              </template>
            </el-table-column>
            <el-table-column label="序号" width="64">
              <template #default="{ row }">第 {{ row.seq_no }} 份</template>
            </el-table-column>
            <el-table-column label="提交人" width="170">
              <template #default="{ row }">
                <template v-if="detail.anonymous">匿名</template>
                <template v-else>
                  <div>{{ row.student_name || '—' }}</div>
                  <div class="cr-sub">{{ row.student_no }}</div>
                </template>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="165">
              <template #default="{ row }">{{ formatDateTime(row.submitted_at) }}</template>
            </el-table-column>
            <el-table-column label="作答" width="80" align="center">
              <template #default="{ row }">{{ row.answers.length }} 题</template>
            </el-table-column>
            <el-table-column v-if="canDelete" label="操作" width="90">
              <template #default="{ row }">
                <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50]"
            :total="responses.total"
            layout="total, sizes, prev, pager, next"
            background
            class="cr-pager"
            @size-change="handleSizeChange"
            @current-change="loadResponses()"
          />
        </el-tab-pane>

        <!-- ---------- 未填名单 ---------- -->
        <el-tab-pane :label="`未填（${pending.total}）`" name="pending">
          <p class="cr-sub cr-hint">
            按「提交份数 &lt; 每人份数」统计；冻结账号催填时会被跳过
            <template v-if="detail.anonymous">。不记名收集不显示每个人交了几份，但仍能看出谁还没填满</template>
          </p>
          <el-table
            v-loading="pendingLoading"
            :data="pending.items"
            stripe
            max-height="430"
            empty-text="所有人都填满了"
          >
            <el-table-column label="姓名" width="120">
              <template #default="{ row }">{{ row.name || '—' }}</template>
            </el-table-column>
            <el-table-column prop="student_no" label="学号" width="140" />
            <el-table-column label="已填" width="110" align="center">
              <template #default="{ row }">
                {{ row.submitted_count == null ? '—' : `${row.submitted_count} 份` }}
              </template>
            </el-table-column>
            <el-table-column label="还差" width="110" align="center">
              <template #default="{ row }">
                {{ row.remaining == null ? '—' : `${row.remaining} 份` }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.frozen" type="info" size="small">已冻结</el-tag>
                <el-tag v-else type="warning" size="small">未填满</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ---------- 统计 ---------- -->
        <el-tab-pane label="统计" name="stats">
          <div v-loading="statsLoading" class="cr-stats">
            <div v-for="(item, index) in statistics.items" :key="item.question_id" class="cr-stat">
              <div class="cr-stat-title">
                <span>{{ index + 1 }}. {{ item.title }}</span>
                <el-tag size="small" type="info" effect="plain">
                  {{ QUESTION_TYPE_LABEL[item.qtype] || item.qtype }}
                </el-tag>
                <span class="cr-sub">{{ item.answered_count }} 份已答</span>
              </div>

              <template v-if="CHOICE_TYPES.has(item.qtype)">
                <div v-for="(option, oi) in item.options" :key="oi" class="cr-stat-row">
                  <span class="cr-stat-name">
                    <span class="cr-letter">{{ letters[oi] }}.</span> {{ option }}
                  </span>
                  <el-progress
                    :percentage="percent(item.counts?.[oi] || 0, item.answered_count)"
                    :stroke-width="12"
                    :show-text="false"
                    class="cr-stat-bar"
                  />
                  <span class="cr-stat-num">{{ item.counts?.[oi] || 0 }} 份</span>
                </div>
              </template>

              <template v-else-if="item.qtype === 'rating'">
                <div class="cr-stat-row">
                  <span class="cr-stat-name">平均分</span>
                  <span class="cr-rating">{{ item.average ?? 0 }} / 5</span>
                </div>
                <div v-for="value in [1, 2, 3, 4, 5]" :key="value" class="cr-stat-row">
                  <span class="cr-stat-name">{{ value }} 分</span>
                  <el-progress
                    :percentage="percent(item.distribution?.[String(value)] || 0, item.answered_count)"
                    :stroke-width="12"
                    :show-text="false"
                    class="cr-stat-bar"
                  />
                  <span class="cr-stat-num">{{ item.distribution?.[String(value)] || 0 }} 份</span>
                </div>
              </template>

              <template v-else-if="item.qtype === 'image'">
                <div class="cr-sub">共收到 {{ item.file_count || 0 }} 张图片</div>
              </template>

              <template v-else>
                <div class="cr-sub">共收到 {{ item.answered_count }} 份文本，内容请在「答卷」里查看</div>
              </template>
            </div>
            <el-empty v-if="!statistics.items.length" description="还没有答卷" :image-size="80" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import CollectionAnswers from '@/components/CollectionAnswers.vue'
import Watermark from '@/components/Watermark.vue'
import {
  batchDeleteCollectionResponses,
  collectionExportUrl,
  deleteCollectionResponse,
  getCollection,
  getCollectionPending,
  getCollectionResponses,
  getCollectionStatistics,
  remindCollection
} from '@/api/collection'
import { useWatermark } from '@/composables/useWatermark'
import { CHOICE_TYPES, QUESTION_TYPE_LABEL, statusLabel, statusTag } from '@/utils/collection'
import { formatDateTime } from '@/utils/format'
import { POLL_LETTERS as letters } from '@/utils/poll'
import { blobErrorDetail, downloadFile } from '@/utils/download'
import { errText } from '@/utils/request'
import { useUserStore } from '@/store/user'

/** 打开期间的刷新间隔：答卷/未填/统计一起刷 */
const POLL_INTERVAL = 5000

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  collection: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:modelValue'])

const userStore = useUserStore()
const watermarkText = useWatermark()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})
const canDelete = computed(() => userStore.isAdmin)

const loading = ref(false)
const tab = ref('responses')
const detail = ref({})
const responses = reactive({ total: 0, items: [] })
const responseLoading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const order = ref('asc')
const selectedIds = ref([])

const pending = reactive({ total: 0, items: [] })
const pendingLoading = ref(false)
const statistics = ref({ items: [] })
const statsLoading = ref(false)

const exporting = ref(false)
const reminding = ref(false)

const canRemind = computed(
  () => detail.value.status === 'open' && !detail.value.cap_reached
)
/** 冻结账号催填也会被跳过，按钮上的数字必须和后端口径一致 */
const remindableCount = computed(
  () => pending.items.filter((row) => !row.frozen).length
)

let timer = null
let loadSeq = 0

async function init() {
  if (!props.collection?.id) return
  const seq = ++loadSeq
  loading.value = true
  tab.value = 'responses'
  page.value = 1
  order.value = 'asc'
  selectedIds.value = []
  try {
    detail.value = await getCollection(props.collection.id)
    if (seq !== loadSeq) return
    await Promise.all([loadResponses(true), loadPending(true), loadStats(true)])
    startPolling()
  } catch (e) {
    ElMessage.error(errText(e, '读取答卷失败'))
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

async function loadResponses(silent = false) {
  if (!detail.value.id) return
  responseLoading.value = !silent
  if (!silent) selectedIds.value = []
  try {
    const data = await getCollectionResponses(detail.value.id, {
      page: page.value,
      page_size: pageSize.value,
      order: order.value
    })
    responses.items = data.items || []
    responses.total = data.total || 0
  } catch (e) {
    if (!silent) ElMessage.error(errText(e, '读取答卷失败'))
  } finally {
    responseLoading.value = false
  }
}

async function loadPending(silent = false) {
  if (!detail.value.id) return
  pendingLoading.value = !silent
  try {
    const data = await getCollectionPending(detail.value.id)
    pending.items = data.items || []
    pending.total = data.total || 0
  } catch (e) {
    if (!silent) ElMessage.error(errText(e, '读取未填名单失败'))
  } finally {
    pendingLoading.value = false
  }
}

async function loadStats(silent = false) {
  if (!detail.value.id) return
  statsLoading.value = !silent
  try {
    const data = await getCollectionStatistics(detail.value.id)
    statistics.value = data
  } catch (e) {
    if (!silent) ElMessage.error(errText(e, '读取统计失败'))
  } finally {
    statsLoading.value = false
  }
}

/** 定时刷新：顺带更新状态与计数（别人正在提交时页面上能看见） */
async function refreshAll() {
  if (!visible.value || !detail.value.id) return
  try {
    detail.value = await getCollection(detail.value.id)
    // 勾选着答卷时不替换表格内容：分页数据一换，选中状态和眼见的行会对不上，
    // 批量删除就有可能删到用户没看见的行。取消勾选后下一轮自然恢复刷新
    const jobs = [loadPending(true), loadStats(true)]
    if (!selectedIds.value.length) jobs.push(loadResponses(true))
    await Promise.all(jobs)
    if (detail.value.status === 'closed') stopPolling()
  } catch (e) {
    /* 轮询失败静默，等下一轮 */
  }
}

function startPolling() {
  stopPolling()
  if (detail.value.status === 'closed') return
  timer = setInterval(refreshAll, POLL_INTERVAL)
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function percent(count, total) {
  if (!total) return 0
  return Math.min(100, Math.round((count / total) * 100))
}

function toggleOrder() {
  order.value = order.value === 'asc' ? 'desc' : 'asc'
  page.value = 1
  loadResponses()
}

function handleSizeChange() {
  page.value = 1
  loadResponses()
}

async function handleDelete(row) {
  const who = detail.value.anonymous ? `第 ${row.seq_no} 份答卷` : `${row.student_name || row.student_no} 的第 ${row.seq_no} 份答卷`
  try {
    await ElMessageBox.confirm(
      `删除「${who}」后不可恢复；竞争收集会同时释放一个名额。确定删除吗？`,
      '删除答卷',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await deleteCollectionResponse(detail.value.id, row.id)
    ElMessage.success('已删除')
    selectedIds.value = []
    await refreshAll()
  } catch (e) {
    ElMessage.error(errText(e, '删除失败'))
  }
}

async function handleBatchDelete() {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${ids.length} 份答卷吗？删除后不可恢复；竞争收集会释放相应名额。`,
      '批量删除',
      { type: 'warning', confirmButtonText: `删除 ${ids.length} 份`, cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const res = await batchDeleteCollectionResponses(detail.value.id, ids)
    ElMessage.success(`已删除 ${res.deleted} 份`)
    selectedIds.value = []
    await refreshAll()
  } catch (e) {
    ElMessage.error(errText(e, '批量删除失败'))
  }
}

async function handleExport() {
  exporting.value = true
  try {
    await downloadFile(
      collectionExportUrl(detail.value.id, order.value),
      `${(detail.value.title || '收集').replace(/[\\/:*?"<>|]/g, '_')}.xlsx`
    )
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e, '导出失败'))
  } finally {
    exporting.value = false
  }
}

async function handleRemind() {
  const count = remindableCount.value
  if (!count) {
    return ElMessage.info('没有可提醒的人（冻结账号会被跳过）')
  }
  try {
    await ElMessageBox.confirm(
      `会给还没填满的 ${count} 人各推一条提醒，可能打扰到他们。确定提醒吗？`,
      '提醒未填',
      { type: 'warning', confirmButtonText: '提醒', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  reminding.value = true
  try {
    const { reminded } = await remindCollection(detail.value.id)
    ElMessage.success(`已提醒 ${reminded} 人`)
    // 提醒不改答卷，只刷新未填名单；不动表格就不会把用户的勾选弄丢
    await loadPending(true)
  } catch (e) {
    ElMessage.error(errText(e, '提醒失败'))
  } finally {
    reminding.value = false
  }
}

watch(visible, (open) => {
  if (open) init()
  else stopPolling()
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.cr-body {
  min-height: 260px;
}

.cr-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.cr-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cr-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.cr-actions {
  display: flex;
  gap: 8px;
}

.cr-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.cr-toolbar-right {
  display: flex;
  gap: 8px;
}

.cr-pager {
  margin-top: 12px;
  justify-content: flex-end;
}

.cr-expand {
  padding: 4px 18px 8px 48px;
  background: var(--el-fill-color-lighter);
}

.cr-hint {
  margin: 0 0 10px;
}

.cr-stats {
  max-height: 440px;
  overflow-y: auto;
  padding-right: 4px;
}

.cr-stat {
  margin-bottom: 20px;
  padding-bottom: 14px;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.cr-stat:last-child {
  border-bottom: none;
}

.cr-stat-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-weight: 600;
}

.cr-stat-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.cr-stat-name {
  width: 180px;
  flex: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cr-letter {
  display: inline-block;
  min-width: 1.5em;
}

.cr-stat-bar {
  flex: 1;
}

.cr-stat-num {
  width: 64px;
  flex: none;
  text-align: right;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.cr-rating {
  font-size: 18px;
  font-weight: 600;
  color: var(--el-color-primary);
}
</style>
