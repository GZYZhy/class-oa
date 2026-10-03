<template>
  <div class="grade">
    <div class="page-card">
      <div class="gd-bar">
        <span class="gd-tip">
          上传一次成绩后全班可查，学生在「我的信息 → 我的成绩」里看自己的分数
        </span>
        <el-button type="primary" @click="importRef.open()">
          <el-icon><Upload /></el-icon>上传成绩
        </el-button>
      </div>
    </div>

    <div class="page-card">
      <el-table
        v-loading="loading"
        :data="rows"
        stripe
        empty-text="还没有录入过成绩，点右上角「上传成绩」传一份 Excel"
      >
        <el-table-column prop="name" label="测试名称" min-width="180" show-overflow-tooltip />
        <el-table-column label="测试日期" width="120">
          <template #default="{ row }">{{ formatDate(row.tested_at) }}</template>
        </el-table-column>
        <el-table-column label="科目" width="80" align="center">
          <template #default="{ row }">{{ row.subject_count }}</template>
        </el-table-column>
        <el-table-column label="录入人数" width="100" align="center">
          <template #default="{ row }">{{ row.student_count }}</template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column prop="creator_name" label="录入人" width="110" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="detailRef.open(row)">明细</el-button>
            <el-button link type="primary" @click="openEdit(row)">改信息</el-button>
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
        class="gd-pager"
        @size-change="handleSizeChange"
        @current-change="fetchList"
      />
    </div>

    <GradeImportDialog ref="importRef" @done="fetchList" />
    <GradeDetailDialog ref="detailRef" @done="fetchList" />

    <!-- 改测试信息。日期该成哪天、备注写什么，都是录完才发现要改的 -->
    <el-dialog v-model="editVisible" title="修改测试信息" width="480px">
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
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editLoading" @click="handleEditSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteGradeTest, getGradeList, updateGradeTest } from '@/api/grade'
import { formatDate } from '@/utils/format'
import { errText } from '@/utils/request'
import GradeDetailDialog from '@/components/GradeDetailDialog.vue'
import GradeImportDialog from '@/components/GradeImportDialog.vue'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const importRef = ref(null)
const detailRef = ref(null)

const editVisible = ref(false)
const editLoading = ref(false)
const editForm = reactive({ id: null, name: '', tested_at: '', remark: '' })

onMounted(fetchList)

async function fetchList() {
  loading.value = true
  try {
    const res = await getGradeList({ page: currentPage.value, page_size: pageSize.value })
    rows.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error(errText(e, '读取成绩列表失败'))
  } finally {
    loading.value = false
  }
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
.gd-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.gd-tip {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.gd-bar .el-button {
  margin-left: auto;
}

.gd-pager {
  margin-top: 14px;
  justify-content: flex-end;
}
</style>
