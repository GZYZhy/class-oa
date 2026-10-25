<!--
  投票收集页里的「收集」面板

  和投票列表并排放在同一页的两个 Tab 里，各自维护关键词、状态和页码；
  这个组件一直挂载，切走再切回来搜索条件还在。
-->
<template>
  <div class="cp">
    <!-- 筛选 -->
    <div class="cp-bar">
      <el-form :inline="true" size="default" class="cp-filter">
        <el-form-item label="标题">
          <el-input
            v-model="keyword"
            placeholder="搜索收集标题"
            clearable
            style="width: 200px"
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="status" style="width: 130px" @change="handleSearch">
            <el-option label="全部" value="" />
            <el-option label="未开始" value="pending" />
            <el-option label="进行中" value="open" />
            <el-option label="已结束" value="closed" />
          </el-select>
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
    </div>

    <!-- 列表 -->
    <el-table
      v-loading="loading"
      :data="rows"
      stripe
      style="margin-top: 16px;"
      empty-text="还没有收集"
    >
      <!-- 标题和下面那行详情都靠左；全局表格规则会把没标方向的列居中 -->
      <el-table-column label="标题" min-width="230" align="left">
        <template #default="{ row }">
          <div class="cp-title">
            <span>{{ row.title }}</span>
            <el-tag v-if="row.anonymous" type="warning" size="small" effect="plain">不记名</el-tag>
            <el-tag v-if="row.max_responses" type="danger" size="small" effect="plain">
              竞争 {{ row.max_responses }} 份
            </el-tag>
            <el-tag v-if="row.allow_withdraw" type="info" size="small" effect="plain">可撤回</el-tag>
          </div>
          <div v-if="row.description" class="cp-sub">{{ markdownPreview(row.description) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="92">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="范围" width="120">
        <template #default="{ row }">
          <span class="cp-sub">{{ row.scope_label || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="份数" width="170">
        <template #default="{ row }">
          <div>已收 {{ row.submitted_count }} 份</div>
          <div class="cp-sub">
            {{ row.submitted_people }} / {{ row.target_count }} 人已填 · 每人 {{ row.submit_quota }} 份
          </div>
          <div v-if="row.max_responses" class="cp-sub">
            剩 {{ row.remaining_slots ?? 0 }} 个名额
          </div>
        </template>
      </el-table-column>
      <el-table-column label="我的状态" width="105" align="center">
        <template #default="{ row }">
          <span :class="{ 'cp-warn': row.is_target && !row.quota_reached && row.status === 'open' }">
            {{ collectionMyState(row) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="截止时间" width="160">
        <template #default="{ row }">
          <div>{{ formatDateTime(row.end_at) }}</div>
          <div v-if="row.closed_at" class="cp-sub">已于 {{ formatDateTime(row.closed_at) }} 结束</div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <!-- 普通参与者去统一填写页；发起人/管理员看实时答卷仍用弹窗 -->
          <el-button link type="primary" @click="openMainAction(row)">
            {{ row.can_manage ? '实时预览' : collectionActionText(row) }}
          </el-button>
          <el-dropdown
            v-if="row.can_manage"
            trigger="click"
            @command="(cmd) => handleCommand(cmd, row)"
          >
            <el-button link type="primary">
              管理<el-icon><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit">编辑</el-dropdown-item>
                <el-dropdown-item command="responses">答卷详情</el-dropdown-item>
                <!-- 管理入口走弹窗后，仍从这里去统一填写页（自己也要填的时候用） -->
                <el-dropdown-item command="openFillPage">
                  {{ row.can_submit ? '去填写' : '打开填写页' }}
                </el-dropdown-item>
                <el-dropdown-item command="share">分享</el-dropdown-item>
                <el-dropdown-item
                  command="remind"
                  :disabled="row.status !== 'open' || row.cap_reached"
                >
                  提醒未填
                </el-dropdown-item>
                <el-dropdown-item command="togglePause" :disabled="!canPause(row)">
                  {{ row.status === 'paused' ? '恢复收集' : '暂停收集' }}
                </el-dropdown-item>
                <el-dropdown-item command="extend" :disabled="!canExtend(row)">
                  延长5分钟
                </el-dropdown-item>
                <el-dropdown-item command="close" :disabled="row.status === 'closed'">
                  立即结束
                </el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="currentPage"
      v-model:page-size="pageSize"
      :page-sizes="[10, 20, 50]"
      :total="total"
      layout="total, sizes, prev, pager, next"
      background
      class="cp-pager"
      @size-change="handleSizeChange"
      @current-change="fetchList"
    />

    <CollectionCreateDialog ref="createRef" @saved="fetchList" />
    <CollectionResponsesDialog
      v-model="responsesVisible"
      :collection="responsesCollection"
    />
    <ShareLinkDialog
      v-model="shareVisible"
      dialog-title="分享收集"
      :title="shareTitle"
      :subtitle="shareSubtitle"
      :link="shareLink"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Refresh, Search } from '@element-plus/icons-vue'
import CollectionCreateDialog from '@/components/CollectionCreateDialog.vue'
import CollectionResponsesDialog from '@/components/CollectionResponsesDialog.vue'
import ShareLinkDialog from '@/components/ShareLinkDialog.vue'
import {
  closeCollection,
  deleteCollection,
  extendCollection,
  getCollections,
  pauseCollection,
  remindCollection,
  resumeCollection
} from '@/api/collection'
import {
  collectionActionText,
  collectionMyState,
  markdownPreview,
  statusLabel,
  statusTag
} from '@/utils/collection'
import { formatDateTime } from '@/utils/format'
import { errText } from '@/utils/request'
import { openShareInNewTab, shareUrl } from '@/utils/share-url'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const status = ref('')
const keyword = ref('')

const createRef = ref(null)
const responsesVisible = ref(false)
const responsesCollection = ref({})

const shareVisible = ref(false)
const shareTitle = ref('')
const shareSubtitle = ref('')
const shareLink = ref('')

async function fetchList() {
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (status.value) params.status = status.value
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const res = await getCollections(params)
    rows.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error(errText(e, '读取收集列表失败'))
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
  fetchList()
}

function handleReset() {
  status.value = ''
  keyword.value = ''
  handleSearch()
}

function handleSizeChange() {
  currentPage.value = 1
  fetchList()
}

/** 只有进行中/暂停中能暂停或恢复 */
function canPause(row) {
  return row.status === 'open' || row.status === 'paused'
}

/** 截止前都能延长（未开始也行，和签到同一口径）；已结束不行 */
function canExtend(row) {
  return canPause(row)
}

/** 主按钮：普通参与者去统一填写页；发起人/管理员用实时答卷弹窗 */
function openMainAction(row) {
  if (row.can_manage) return openResponses(row)
  openSharePage(row)
}

/** 新标签页打开统一的填写页（管理下拉里的「去填写 / 打开填写页」也走这里） */
function openSharePage(row) {
  if (row.share_token) openShareInNewTab('collect', row.share_token)
}

function handleCommand(command, row) {
  if (command === 'edit') return createRef.value?.openForEdit(row)
  if (command === 'responses') return openResponses(row)
  if (command === 'openFillPage') return openSharePage(row)
  if (command === 'share') return openShare(row)
  if (command === 'remind') return handleRemind(row)
  if (command === 'togglePause') return handleTogglePause(row)
  if (command === 'extend') return handleExtend(row)
  if (command === 'close') return handleClose(row)
  if (command === 'delete') return handleDelete(row)
}

function openResponses(row) {
  responsesCollection.value = { ...row }
  responsesVisible.value = true
}

function openShare(row) {
  shareTitle.value = `收集：${row.title}`
  shareSubtitle.value = [
    row.scope_label,
    `每人 ${row.submit_quota} 份`,
    row.max_responses ? `限收 ${row.max_responses} 份` : '',
    `截止 ${formatDateTime(row.end_at)}`
  ]
    .filter(Boolean)
    .join(' · ')
  shareLink.value = shareUrl('collect', row.share_token)
  shareVisible.value = true
}

async function handleRemind(row) {
  try {
    await ElMessageBox.confirm(
      `会给还没填满的同学各推一条提醒，可能打扰到他们。确定提醒「${row.title}」吗？`,
      '提醒未填',
      { type: 'warning', confirmButtonText: '提醒', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const { reminded } = await remindCollection(row.id)
    ElMessage.success(reminded ? `已提醒 ${reminded} 人` : '没有可提醒的人')
  } catch (e) {
    ElMessage.error(errText(e, '提醒失败'))
  }
}

async function handleTogglePause(row) {
  const pausing = row.status !== 'paused'
  try {
    await ElMessageBox.confirm(
      pausing
        ? '暂停期间不能提交答卷，已交的答卷照常能看；到截止时间仍会自动结束。确定暂停吗？'
        : '恢复后范围内的人又能接着填。确定恢复吗？',
      pausing ? '暂停收集' : '恢复收集',
      { type: 'warning', confirmButtonText: pausing ? '暂停' : '恢复', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await (pausing ? pauseCollection : resumeCollection)(row.id)
    ElMessage.success(pausing ? '已暂停' : '已恢复')
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, pausing ? '暂停失败' : '恢复失败'))
  }
}

/** 和签到一样：点一下就延 5 分钟，不弹确认 */
async function handleExtend(row) {
  try {
    await extendCollection(row.id)
    ElMessage.success('已延长5分钟')
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, '延长失败'))
  }
}

async function handleClose(row) {
  try {
    await ElMessageBox.confirm(
      `结束后所有人都不能再提交，已收 ${row.submitted_count} 份答卷保留。确定立即结束「${row.title}」吗？`,
      '立即结束',
      { type: 'warning', confirmButtonText: '结束收集', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const res = await closeCollection(row.id)
    ElMessage.success(`已结束，共收到 ${res.response_count} 份`)
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, '结束失败'))
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `已有 ${row.submitted_count} 份答卷，删除后会一起清掉，不可恢复。确定删除「${row.title}」吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await deleteCollection(row.id)
    ElMessage.success('已删除')
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, '删除失败'))
  }
}

/** 给页面头部的「发起收集」按钮用 */
function openCreate() {
  createRef.value?.open()
}

defineExpose({ openCreate, refresh: fetchList })

onMounted(fetchList)
</script>

<style scoped>
.cp-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.cp-filter {
  margin-bottom: 0;
}

.cp-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.cp-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.cp-warn {
  color: var(--el-color-warning);
}

.cp-pager {
  margin-top: 14px;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .cp-filter {
    width: 100%;
  }

  .cp-filter :deep(.el-form-item) {
    display: flex;
    width: 100%;
    margin-right: 0;
    margin-bottom: 10px;
  }

  .cp-filter :deep(.el-form-item__label) {
    width: 44px;
    padding-right: 8px;
    flex-shrink: 0;
    justify-content: flex-start;
  }

  .cp-filter :deep(.el-form-item__content) {
    flex: 1;
    min-width: 0;
  }

  .cp-filter :deep(.el-input),
  .cp-filter :deep(.el-select) {
    width: 100% !important;
  }
}
</style>
