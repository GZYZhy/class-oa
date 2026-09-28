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
      <el-collapse v-else v-model="activeNames" class="notice-collapse" @change="handleExpand">
        <el-collapse-item
          v-for="item in list"
          :key="item.id"
          :name="item.id"
        >
          <!-- 标题行 -->
          <template #title>
            <div class="notice-title">
              <el-icon class="title-icon"><BellFilled /></el-icon>
              <!-- 未读小圆点：只靠菜单红点的话，知道有几条未读却看不出是哪几条 -->
              <span
                v-if="userStore.isLogin && !item.is_read"
                class="unread-dot"
                title="未读"
              ></span>
              <span class="title-text">{{ item.title }}</span>
              <!-- 发布/编辑人：第一个是首发人（蓝），后续编辑者（绿），多了自动换行 -->
              <div class="publisher-tags">
                <el-tag
                  v-for="(editor, idx) in item.editors"
                  :key="editor.no || editor.name || idx"
                  size="small"
                  :type="idx === 0 ? 'info' : 'success'"
                  effect="light"
                  :title="editor.time ? (idx === 0 ? '发布于 ' : '编辑于 ') + editor.time : ''"
                  class="publisher-tag"
                >
                  {{ idx === 0 ? '' : '✎ ' }}{{ editor.name || '未知' }}
                </el-tag>
              </div>
              <span class="title-date">{{ item.publish_date }}</span>
              <!-- 编辑过的通知自动带更新标识 -->
              <el-tag v-if="item.updated_at" size="small" type="warning" effect="plain">
                已于 {{ formatDateTime(item.updated_at) }} 更新
              </el-tag>
            </div>
          </template>

          <!-- Markdown 正文 -->
          <div class="markdown-body" v-html="renderMarkdown(item.content)"></div>

          <!-- 附件列表 -->
          <div v-if="item.attachments?.length" class="notice-attachments">
            <div class="attach-title">
              <el-icon><Paperclip /></el-icon>
              附件（{{ item.attachments.length }}）
            </div>
            <div class="attach-list">
              <div
                v-for="(att, idx) in item.attachments"
                :key="idx"
                class="attach-item"
                @click="downloadAttachment(item.id, idx, att.name)"
              >
                <el-icon><Document /></el-icon>
                <span class="attach-name">{{ att.name }}</span>
                <span class="attach-size">{{ formatFileSize(att.size) }}</span>
                <el-icon class="attach-download"><Download /></el-icon>
              </div>
            </div>
          </div>

          <div v-if="userStore.isCommittee" class="notice-footer">
            <span v-if="item.updated_at" class="updated-tip">
              本条已于 {{ formatDateTime(item.updated_at) }} 更新
            </span>
            <el-button type="primary" link @click.stop="openReads(item)">已读情况</el-button>
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
            <el-form-item label="参与人">
              <div v-if="editingId && form.editors?.length" class="editors-list">
                <el-tag
                  v-for="(ed, idx) in form.editors"
                  :key="ed.no || ed.name || idx"
                  size="small"
                  :type="idx === 0 ? 'info' : 'success'"
                  effect="light"
                >
                  {{ idx === 0 ? '首发：' : '编辑：' }}{{ ed.name || '未知' }}
                </el-tag>
              </div>
              <span v-else class="publisher-tip">
                {{ userStore.info?.name }}（你将作为首发人）
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
          <el-col :span="24">
            <el-form-item label="附件">
              <div class="upload-area">
                <!-- 已有附件（编辑模式下显示，可删除） -->
                <div v-if="editingAttachments.length" class="existing-attachments">
                  <div
                    v-for="(att, idx) in editingAttachments"
                    :key="'old-' + idx"
                    class="attach-row"
                  >
                    <el-icon><Document /></el-icon>
                    <span class="attach-name">{{ att.name }}</span>
                    <span class="attach-size">{{ formatFileSize(att.size) }}</span>
                    <el-button
                      type="danger"
                      link
                      size="small"
                      @click="removeOldAttachment(idx)"
                    >移除</el-button>
                  </div>
                </div>
                <!-- 新上传的文件 -->
                <div v-if="newAttachments.length" class="existing-attachments">
                  <div
                    v-for="(file, idx) in newAttachments"
                    :key="'new-' + idx"
                    class="attach-row"
                  >
                    <el-icon><Document /></el-icon>
                    <span class="attach-name">{{ file.name }}</span>
                    <span class="attach-size">{{ formatFileSize(file.size) }}</span>
                    <el-button
                      type="danger"
                      link
                      size="small"
                      @click="removeNewAttachment(idx)"
                    >移除</el-button>
                  </div>
                </div>
                <el-button
                  v-if="editingAttachments.length + newAttachments.length < maxAttachments"
                  type="primary"
                  plain
                  size="small"
                  @click="$refs.attachInput.click()"
                >
                  <el-icon><Upload /></el-icon>
                  添加附件
                </el-button>
                <input
                  ref="attachInput"
                  type="file"
                  multiple
                  :accept="allowedAttachmentExts"
                  style="display: none;"
                  @change="handleAttachChange"
                />
                <div class="upload-tip">
                  最多 {{ maxAttachments }} 个，支持图片 / 视频 / 音频 / 文档，单文件不超过 20MB
                </div>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="publishVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          <!-- 通知可以带多个附件，慢网络下把上传进度显示出来 -->
          {{ editingId ? '保存' : '发布' }}{{ submitting && uploadProgress ? ` ${uploadProgress}%` : '' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 已读情况（班委及以上）：谁看了、谁还没看。点开才请求，不在列表里逐条预取 -->
    <el-dialog
      v-model="readsVisible"
      :title="`已读情况 · ${readsTitle}`"
      width="560px"
    >
      <div v-loading="readsLoading" class="reads-body">
        <div v-if="reads" class="reads-summary">
          已读 <b>{{ reads.read_count }}</b> / {{ reads.total }} 人
          <span class="reads-left">未读 {{ reads.total - reads.read_count }} 人</span>
        </div>
        <el-table :data="reads?.rows || []" size="small" max-height="380">
          <el-table-column prop="name" label="姓名" width="110" />
          <el-table-column prop="student_no" label="学号" width="130" />
          <el-table-column label="状态">
            <template #default="{ row }">
              <el-tag v-if="row.read_at" size="small" type="success" effect="plain">
                {{ formatDateTime(row.read_at) }}
              </el-tag>
              <el-tag v-else size="small" type="info" effect="plain">未读</el-tag>
              <!-- 冻结账号永远读不了，标出来省得班委反复纳闷 -->
              <el-tag v-if="row.frozen" size="small" type="danger" effect="plain" class="frozen-tag">
                已冻结
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import {
  getNotices,
  createNotice,
  updateNotice,
  deleteNotice,
  markNoticeRead,
  getNoticeReads
} from '@/api/notice'
import { downloadFile } from '@/utils/download'
import { useUserStore } from '@/store/user'
import { useBadgeStore } from '@/store/badge'

// 允许的附件扩展名（与后端 ALLOWED_ATTACHMENT_EXTENSIONS 对应）
const ALLOWED_ATTACHMENT_EXTS =
  '.jpg,.jpeg,.png,.gif,.bmp,.webp,.heic,.heif,.mp4,.mov,.m4v,.avi,.mkv,.webm,.mp3,.m4a,.wav,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.pdf,.txt,.md,.wps,.et,.dps'
const MAX_ATTACHMENTS = 3
const MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024

const router = useRouter()
const userStore = useUserStore()
const badgeStore = useBadgeStore()

const list = ref([])
const loading = ref(false)
const activeNames = ref([])

const searchForm = reactive({ title: '', dateRange: [] })

const publishVisible = ref(false)
const submitting = ref(false)
// 上传进度百分比（算不出总大小时为 0，就不显示数字）
const uploadProgress = ref(0)
const form = reactive({ title: '', publisher: '', publish_date: '', content: '', editors: [] })
// 非空表示当前是编辑模式
const editingId = ref(null)

// 附件
const attachInput = ref(null)
const allowedAttachmentExts = ALLOWED_ATTACHMENT_EXTS
const maxAttachments = MAX_ATTACHMENTS
// 编辑模式下保留的原附件（去掉被移除的）
const editingAttachments = ref([])
// 新上传的附件
const newAttachments = ref([])

// 已读情况弹窗
const readsVisible = ref(false)
const readsLoading = ref(false)
const reads = ref(null)
const readsTitle = ref('')

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

    // 程序性展开不会触发 el-collapse 的 change，得手动补一次「展开即已读」。
    // 但只在**没有任何搜索条件**时补：班委搜一个关键词，被搜出来的第一条
    // 会莫名其妙变成已读
    // 不等它：标记已读是后台的事，不该拖慢列表渲染（本地状态会立刻翻过去）
    if (userStore.isLogin && !params.title && !params.start_date && !params.end_date) {
      markRead(list.value.slice(0, 1))
    }
  } catch (e) {
    ElMessage.error('通知列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 把给定的通知标记为已读，成功后刷新菜单红点
 *
 * 乐观更新：先本地翻成已读，手感不必等网络；某一条失败了单独还原它。
 */
async function markRead(items) {
  const unread = items.filter((item) => item && !item.is_read)
  if (!unread.length) return

  unread.forEach((item) => { item.is_read = true })
  await Promise.all(
    unread.map((item) =>
      markNoticeRead(item.id).catch(() => { item.is_read = false })
    )
  )
  badgeStore.refresh()
}

/** 展开即已读（用户选定的口径）
 *
 * el-collapse 的 change 给的是「当前展开的全部 id」，不是「刚点开的那一条」，
 * 所以这里不比对差异，只把现在开着、且还没读过的都标记掉 —— 它们都摊在屏幕上，
 * 说看过了不算冤枉。游客挡掉：点了也没地方记。
 */
function handleExpand(names) {
  if (!userStore.isLogin) return
  const ids = (Array.isArray(names) ? names : [names]).map(Number)
  markRead(list.value.filter((item) => ids.includes(item.id)))
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
  editingAttachments.value = []
  newAttachments.value = []
  publishVisible.value = true
}

// 编辑已有通知：回填内容，保存后后端自动打上更新时间
function openEdit(item) {
  editingId.value = item.id
  form.title = item.title
  form.publisher = item.publisher
  form.publish_date = item.publish_date
  form.content = item.content
  form.editors = item.editors || []
  // 回填附件：先全部保留，用户可以手动移除
  editingAttachments.value = (item.attachments || []).map(a => ({ ...a }))
  newAttachments.value = []
  publishVisible.value = true
}

// 附件选择
function handleAttachChange(e) {
  const files = Array.from(e.target.files || [])
  const remaining = maxAttachments - editingAttachments.value.length - newAttachments.value.length
  if (files.length > remaining) {
    ElMessage.warning(`最多只能再添加 ${remaining} 个附件`)
  }
  const toAdd = files.slice(0, remaining)
  for (const f of toAdd) {
    // 校验大小
    if (f.size > MAX_ATTACHMENT_SIZE) {
      ElMessage.warning(`「${f.name}」超过 20MB，已跳过`)
      continue
    }
    // 校验后缀
    const ext = '.' + f.name.split('.').pop()?.toLowerCase()
    if (!ALLOWED_ATTACHMENT_EXTS.split(',').includes(ext)) {
      ElMessage.warning(`「${f.name}」不支持的文件类型`)
      continue
    }
    newAttachments.value.push(f)
  }
  // 重置 input，方便下次选同名文件也能触发
  e.target.value = ''
}

function removeOldAttachment(idx) {
  editingAttachments.value.splice(idx, 1)
}

function removeNewAttachment(idx) {
  newAttachments.value.splice(idx, 1)
}

// 格式化文件大小
function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

// 下载通知附件
async function downloadAttachment(noticeId, index, name) {
  try {
    await downloadFile(`/api/notices/${noticeId}/attachments/${index}`, name)
  } catch (e) {
    ElMessage.error('下载失败')
  }
}

async function handleSubmit() {
  if (!form.title.trim()) return ElMessage.warning('请填写标题')
  if (!form.publish_date) return ElMessage.warning('请选择发布时间')
  if (!form.content.trim()) return ElMessage.warning('请填写正文')

  // 组装 FormData
  const fd = new FormData()
  fd.append('title', form.title.trim())
  fd.append('publish_date', form.publish_date)
  fd.append('content', form.content)

  // 编辑模式：传保留的原附件下标
  if (editingId.value) {
    const keepIndices = editingAttachments.value.map(a => a.index)
    fd.append('keep_attachments', JSON.stringify(keepIndices))
  }

  // 新上传的附件
  for (const f of newAttachments.value) {
    fd.append('attachments', f)
  }

  submitting.value = true
  uploadProgress.value = 0
  // 附件可能几十 MB，上传期间的进度回调（两个接口共用一份）
  const onProgress = (loaded, total) => {
    uploadProgress.value = total ? Math.round((loaded / total) * 100) : 0
  }
  try {
    if (editingId.value) {
      await updateNotice(editingId.value, fd, onProgress)
      ElMessage.success('已保存，并标记更新')
    } else {
      const created = await createNotice(fd, onProgress)
      // 自己刚发的通知不该再给自己亮红点
      await markRead([created])
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

/** 打开某条通知的已读情况（按需请求，不在列表里逐条预取） */
async function openReads(item) {
  readsTitle.value = item.title
  reads.value = null
  readsVisible.value = true
  readsLoading.value = true
  try {
    reads.value = await getNoticeReads(item.id)
  } catch (e) {
    ElMessage.error('已读情况加载失败')
    readsVisible.value = false
  } finally {
    readsLoading.value = false
  }
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

/* 未读小圆点：跟着标题走，标题超长截断时也不会被挤掉（flex 默认不收缩） */
.unread-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f56c6c;
}

.title-date {
  font-size: 13px;
  color: #909399;
}

/* 发布人标签组：自动换行，手机端不挤 */
.publisher-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  flex-shrink: 0;
}

.publisher-tag {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

/* 通知附件 */
.notice-attachments {
  margin: 12px 0 8px;
  padding: 10px 14px;
  background: #f5f7fa;
  border-radius: 6px;
}

.attach-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.attach-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.attach-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
}

.attach-item:hover {
  background: #ecf5ff;
}

.attach-item .attach-name {
  flex: 1;
  font-size: 13px;
  color: #409eff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.attach-item .attach-size {
  font-size: 12px;
  color: #909399;
  flex-shrink: 0;
}

.attach-item .attach-download {
  font-size: 14px;
  color: #409eff;
  flex-shrink: 0;
}

/* 弹窗里的上传区 */
.upload-area {
  width: 100%;
}

.existing-attachments {
  margin-bottom: 8px;
}

.attach-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #f5f7fa;
  border-radius: 4px;
  margin-bottom: 4px;
}

.attach-row .attach-name {
  flex: 1;
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.attach-row .attach-size {
  font-size: 12px;
  color: #909399;
  flex-shrink: 0;
}

.upload-tip {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
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

.editors-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}


.updated-tip {
  margin-right: auto;
  font-size: 12px;
  color: #E6A23C;
}

/* 已读情况弹窗：给表格一个最小高度，切换通知时 loading 转圈不会跳一下 */
.reads-body {
  min-height: 120px;
}

.reads-summary {
  margin-bottom: 12px;
  font-size: 14px;
  color: #303133;
}

.reads-left {
  margin-left: 8px;
  font-size: 13px;
  color: #909399;
}

.frozen-tag {
  margin-left: 6px;
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
