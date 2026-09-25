<template>
  <div>
    <div class="page-card" v-loading="loading">
      <div class="page-toolbar">
        <h3 class="page-title" style="margin-bottom: 0;">通知公告</h3>
        <!-- 发布/编辑/删除均限班委及以上；普通学生与未登录者只读 -->
        <el-button v-if="userStore.isCommittee" type="primary" @click="openPublish">
          <el-icon><Plus /></el-icon>
          发布通知
        </el-button>
        <el-button v-else-if="!userStore.isLogin" type="primary" plain @click="router.push('/login')">
          <el-icon><Lock /></el-icon>
          登录后可发布
        </el-button>
      </div>

      <!-- 搜索区：标题 + 发布时间区间 -->
      <el-form :inline="true" style="margin-top: 16px;">
        <el-form-item label="标题">
          <el-input
            v-model="searchForm.title"
            placeholder="按标题搜索"
            clearable
            style="width: 200px"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="发布时间">
          <el-date-picker
            v-model="searchForm.dateRange"
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
            <el-icon><Search /></el-icon>搜索
          </el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>

      <!-- 通知列表：手风琴式，最新一条默认展开 -->
      <el-empty v-if="!loading && !list.length" description="暂无通知" style="margin-top: 20px;" />
      <el-collapse v-else v-model="activeNames" class="notice-collapse">
        <el-collapse-item
          v-for="item in list"
          :key="item.id"
          :name="item.id"
        >
          <!-- 标题行 -->
          <template #title>
            <div class="notice-title">
              <el-icon class="title-icon"><BellFilled /></el-icon>
              <span class="title-text">{{ item.title }}</span>
              <el-tag size="small" type="info">{{ item.publisher }}</el-tag>
              <span class="title-date">{{ item.publish_date }}</span>
              <!-- 编辑过的通知自动带更新标识 -->
              <el-tag v-if="item.updated_at" size="small" type="warning" effect="plain">
                已于 {{ formatDateTime(item.updated_at) }} 更新
              </el-tag>
            </div>
          </template>

          <!-- Markdown 正文 -->
          <div class="markdown-body" v-html="renderMarkdown(item.content)"></div>

          <div v-if="userStore.isCommittee" class="notice-footer">
            <span v-if="item.updated_at" class="updated-tip">
              本条已于 {{ formatDateTime(item.updated_at) }} 更新
            </span>
            <el-button type="primary" link @click.stop="openEdit(item)">编辑</el-button>
            <el-button type="danger" link @click.stop="handleDelete(item)">删除</el-button>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 发布 / 编辑弹窗 -->
    <el-dialog
      v-model="publishVisible"
      :title="editingId ? '编辑通知' : '发布通知'"
      width="680px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="90px">
        <el-row :gutter="20">
          <el-col :span="24">
            <el-form-item label="标题" required>
              <el-input v-model="form.title" placeholder="通知标题" maxlength="200" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <!-- 发布人不再由前端填写：后端一律按登录账号的姓名落库，防止冒名 -->
            <el-form-item label="发布人">
              <span class="publisher-tip">
                {{ editingId ? `${form.publisher}（编辑不改变发布人）` : userStore.info?.name }}
              </span>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="发布时间" required>
              <el-date-picker
                v-model="form.publish_date"
                type="date"
                placeholder="选择日期"
                style="width: 100%"
                value-format="YYYY-MM-DD"
              />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="正文" required>
              <el-input
                v-model="form.content"
                type="textarea"
                :rows="10"
                placeholder="支持 Markdown 格式：# 标题、**加粗**、- 列表 等"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="publishVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ editingId ? '保存' : '发布' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import { getNotices, createNotice, updateNotice, deleteNotice } from '@/api/notice'
import { useUserStore } from '@/store/user'

const router = useRouter()
const userStore = useUserStore()

const list = ref([])
const loading = ref(false)
const activeNames = ref([])

const searchForm = reactive({ title: '', dateRange: [] })

const publishVisible = ref(false)
const submitting = ref(false)
const form = reactive({ title: '', publisher: '', publish_date: '', content: '' })
// 非空表示当前是编辑模式
const editingId = ref(null)

// Markdown 渲染（marked 直接输出 HTML）
function renderMarkdown(text) {
  return marked.parse(text || '')
}

/** 后端返回 ISO 时间，展示为「2026-09-24 12:30」 */
function formatDateTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').replace(/\.\d+$/, '').slice(0, 16)
}

async function fetchList() {
  loading.value = true
  try {
    const params = {
      title: searchForm.title || undefined,
      start_date: searchForm.dateRange?.[0] || undefined,
      end_date: searchForm.dateRange?.[1] || undefined,
    }
    list.value = await getNotices(params)
    // 最新一条（列表按时间降序，第一条即最新）默认展开
    activeNames.value = list.value.length ? [list.value[0].id] : []
  } catch (e) {
    ElMessage.error('通知列表加载失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() { fetchList() }

function handleReset() {
  searchForm.title = ''
  searchForm.dateRange = []
  fetchList()
}

function openPublish() {
  editingId.value = null
  form.title = ''
  form.publisher = ''
  form.publish_date = ''
  form.content = ''
  publishVisible.value = true
}

// 编辑已有通知：回填内容，保存后后端自动打上更新时间
function openEdit(item) {
  editingId.value = item.id
  form.title = item.title
  form.publisher = item.publisher
  form.publish_date = item.publish_date
  form.content = item.content
  publishVisible.value = true
}

async function handleSubmit() {
  if (!form.title.trim()) return ElMessage.warning('请填写标题')
  if (!form.publish_date) return ElMessage.warning('请选择发布时间')
  if (!form.content.trim()) return ElMessage.warning('请填写正文')

  // 不带 publisher：发布人由后端按登录账号注入，编辑时后端保留原发布人
  const payload = {
    title: form.title.trim(),
    publish_date: form.publish_date,
    content: form.content
  }

  submitting.value = true
  try {
    if (editingId.value) {
      await updateNotice(editingId.value, payload)
      ElMessage.success('已保存，并标记更新')
    } else {
      await createNotice(payload)
      ElMessage.success('发布成功')
    }
    publishVisible.value = false
    fetchList()
  } catch (e) {
    ElMessage.error(editingId.value ? '保存失败' : '发布失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(item) {
  try {
    await ElMessageBox.confirm(`确定删除「${item.title}」吗？`, '删除确认', { type: 'warning' })
    await deleteNotice(item.id)
    ElMessage.success('已删除')
    fetchList()
  } catch (e) { /* 取消 */ }
}

onMounted(fetchList)
</script>

<style scoped>
.page-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.notice-collapse {
  border-top: 1px solid #ebeef5;
  margin-top: 8px;
}

.notice-title {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding-right: 16px;
}

.title-icon {
  color: #409EFF;
  font-size: 16px;
}

.title-text {
  font-weight: 500;
  color: #303133;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.title-date {
  font-size: 13px;
  color: #909399;
}

.markdown-body {
  padding: 8px 4px;
  color: #303133;
  line-height: 1.7;
}

.notice-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

/* 手机端：通知标题行允许折行，发布者和日期挤到第二行也没关系，
   别让「已于xx更新」那个长标签把标题挤没了 */
@media (max-width: 768px) {
  .notice-title {
    flex-wrap: wrap;
    row-gap: 6px;
    padding-right: 0;
  }

  .title-text {
    flex-basis: 100%;
    white-space: normal;
    line-height: 1.4;
  }

  .title-date {
    margin-left: auto;
  }
}

.publisher-tip {
  color: #606266;
  font-size: 14px;
}

.updated-tip {
  margin-right: auto;
  font-size: 12px;
  color: #E6A23C;
}

/* Markdown 元素样式 */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin: 12px 0 8px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 24px;
  margin: 8px 0;
}

.markdown-body :deep(code) {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 90%;
}

.markdown-body :deep(blockquote) {
  border-left: 4px solid #409EFF;
  padding: 4px 12px;
  margin: 8px 0;
  background: #f0f7ff;
  color: #606266;
}
</style>
