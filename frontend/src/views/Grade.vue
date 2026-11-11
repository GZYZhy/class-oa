<template>
  <div class="grade">
    <!-- 全班成绩都在这一页，盖一层「谁在什么时候看的」 -->
    <Watermark :text="watermarkText" />
    <div class="page-card">
      <div class="page-toolbar page-heading">
        <h3 class="page-title">成绩管理</h3>
        <span class="page-count" role="status">共 {{ total }} 场测试</span>
      </div>
      <div class="gd-bar">
        <el-form :inline="true" size="default" class="gd-filter" @submit.prevent>
          <el-form-item label="考试名称">
            <el-input
              v-model="keyword"
              placeholder="搜索考试名称"
              clearable
              style="width: 200px"
              @keyup.enter="handleSearch"
              @clear="handleSearch"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item class="gd-actions">
            <el-button type="primary" @click="handleSearch">查询</el-button>
            <el-button @click="handleReset">重置</el-button>
            <el-button type="primary" @click="importRef.open()">
              <el-icon><Upload /></el-icon>上传成绩
            </el-button>
          </el-form-item>
        </el-form>
        <span class="gd-tip">
          上传一次成绩后全班可查，学生在「我的信息 → 我的成绩」里看自己的分数
        </span>
      </div>

      <ListFeedback :error="loadError" :loading="loading" @retry="fetchList" />

      <div v-if="isMobile && !loadError" v-loading="loading" class="mobile-records">
        <el-empty v-if="!loading && !rows.length" :description="keyword.trim() ? '没有匹配的成绩记录' : '还没有成绩记录'" />
        <article v-for="row in rows" :key="row.id" class="mobile-record">
          <h4>{{ row.name }}</h4>
          <div class="mobile-record-meta">
            <span>{{ formatDate(row.tested_at) }}</span>
            <span>{{ row.subject_count }} 科</span>
            <span>{{ row.student_count }} 人已录入</span>
          </div>
          <p v-if="row.remark" class="grade-remark">{{ row.remark }}</p>
          <div class="mobile-record-actions">
            <el-button link type="primary" @click="detailRef.open(row)">查看明细</el-button>
            <el-button link type="primary" @click="statsRef.open(row)">成绩统计</el-button>
            <el-dropdown trigger="click" @command="handleRowAction($event, row)">
              <el-button link :aria-label="`${row.name}的更多操作`">更多<el-icon><ArrowDown /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit">修改信息</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除测试</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </article>
      </div>

      <el-table
        v-if="!isMobile && !loadError"
        v-loading="loading"
        :data="rows"
        stripe
        style="margin-top: 12px;"
        :empty-text="keyword.trim() ? '没有匹配的成绩记录' : '还没有成绩记录'"
      >
        <el-table-column prop="name" label="测试名称" min-width="180" show-overflow-tooltip align="left" />
        <el-table-column label="测试日期" width="120">
          <template #default="{ row }">{{ formatDate(row.tested_at) }}</template>
        </el-table-column>
        <el-table-column label="科目" width="80" align="center">
          <template #default="{ row }">{{ row.subject_count }}</template>
        </el-table-column>
        <el-table-column label="录入人数" width="100" align="center">
          <template #default="{ row }">{{ row.student_count }}</template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip align="left" />
        <el-table-column prop="creator_name" label="录入人" width="110" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="detailRef.open(row)">明细</el-button>
            <el-button link type="primary" @click="statsRef.open(row)">统计</el-button>
            <el-button link type="primary" @click="openEdit(row)">改信息</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="!loadError"
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        :layout="isMobile ? 'total, prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
        :pager-count="isMobile ? 5 : 7"
        background
        class="gd-pager"
        @size-change="handleSizeChange"
        @current-change="fetchList"
      />
    </div>

    <GradeImportDialog ref="importRef" @done="fetchList" />
    <GradeDetailDialog ref="detailRef" @done="fetchList" />
    <GradeStatsDialog ref="statsRef" />

    <!-- 改测试信息。日期该成哪天、备注写什么，都是录完才发现要改的 -->
    <el-dialog append-to-body v-model="editVisible" title="修改测试信息" width="520px">
      <div class="wm-host">
        <Watermark :text="watermarkText" />
        <el-form label-width="88px">
          <el-form-item label="测试名称">
            <el-input v-model="editForm.name" maxlength="100" />
          </el-form-item>
          <el-form-item label="测试日期">
            <el-date-picker
              v-model="editForm.tested_at"
              type="date"
              value-format="YYYY-MM-DD"
              style="width: 180px"
            />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="editForm.remark" type="textarea" :rows="3" maxlength="2000" />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editLoading" @click="handleEditSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import ListFeedback from '@/components/ListFeedback.vue'
import { useLatestRequest } from '@/composables/useLatestRequest'
import { usePageState } from '@/composables/usePageState'
import { useIsMobile } from '@/composables/useIsMobile'
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteGradeTest, getGradeList, updateGradeTest } from '@/api/grade'
import { formatDate } from '@/utils/format'
import { errText } from '@/utils/request'
import GradeDetailDialog from '@/components/GradeDetailDialog.vue'
import GradeImportDialog from '@/components/GradeImportDialog.vue'
import GradeStatsDialog from '@/components/GradeStatsDialog.vue'
import Watermark from '@/components/Watermark.vue'
import { useWatermark } from '@/composables/useWatermark'

const watermarkText = useWatermark()
const isMobile = useIsMobile()
const loading = ref(false)
const loadError = ref('')
const listRequest = useLatestRequest()
const rows = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
// 考试名称关键词。空串 = 不过滤
const keyword = ref('')
usePageState('Grade', { currentPage, pageSize, keyword }, loading)
const importRef = ref(null)
const detailRef = ref(null)
const statsRef = ref(null)

const editVisible = ref(false)
const editLoading = ref(false)
const editForm = reactive({ id: null, name: '', tested_at: '', remark: '' })

onMounted(fetchList)

async function fetchList() {
  const requestId = listRequest.start()
  loadError.value = ''
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const res = await getGradeList(params)
    if (!listRequest.isCurrent(requestId)) return
    rows.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    if (listRequest.isCurrent(requestId)) loadError.value = '读取成绩列表失败'
  } finally {
    if (listRequest.isCurrent(requestId)) loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
  fetchList()
}

function handleReset() {
  keyword.value = ''
  handleSearch()
}

function handleSizeChange() {
  currentPage.value = 1
  fetchList()
}

function openEdit(row) {
  editForm.id = row.id
  editForm.name = row.name
  editForm.tested_at = formatDate(row.tested_at)
  editForm.remark = row.remark || ''
  editVisible.value = true
}

function handleRowAction(command, row) {
  if (command === 'edit') openEdit(row)
  else if (command === 'delete') handleDelete(row)
}

async function handleEditSave() {
  if (!editForm.name.trim()) {
    ElMessage.warning('测试名称不能为空')
    return
  }
  editLoading.value = true
  try {
    await updateGradeTest(editForm.id, {
      name: editForm.name.trim(),
      tested_at: editForm.tested_at,
      remark: editForm.remark
    })
    ElMessage.success('已保存')
    editVisible.value = false
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, '保存失败'))
  } finally {
    editLoading.value = false
  }
}

async function handleDelete(row) {
  const tip = row.student_count
    ? `「${row.name}」已有 ${row.student_count} 人共 ${row.subject_count} 科成绩，删除后不可恢复。确定删除吗？`
    : `确定删除「${row.name}」吗？`
  try {
    await ElMessageBox.confirm(tip, '删除成绩记录', { type: 'warning' })
  } catch {
    return // 取消
  }
  try {
    await deleteGradeTest(row.id)
    ElMessage.success('已删除')
    // 删掉本页最后一条时往前翻一页，否则会停在空白页
    if (rows.value.length === 1 && currentPage.value > 1) currentPage.value -= 1
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, '删除失败'))
  }
}
</script>

<style scoped>
.grade-remark {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
/* 水印的定位基准 */
.grade,
.wm-host {
  position: relative;
}

.gd-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

/* 搜索表单自己带下边距，在横排里会把上传按钮顶歪 */
.gd-filter {
  margin-bottom: 0;
}

.gd-tip {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .gd-filter {
    width: 100%;
  }

  .gd-filter :deep(.gd-actions .el-form-item__content) {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .gd-filter :deep(.gd-actions .el-button) {
    margin-left: 0;
  }

  .gd-tip {
    line-height: 1.5;
  }
}

.gd-pager {
  margin-top: 14px;
  justify-content: flex-end;
}
</style>
