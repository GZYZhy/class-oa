<template>
  <div class="page-card">
    <h3 class="page-title">系统管理</h3>

    <el-tabs v-model="activeTab">
      <!-- ============ 账号角色管理 ============ -->
      <el-tab-pane label="账号角色管理" name="users">
        <el-form :inline="true">
          <el-form-item label="搜索">
            <el-input
              v-model="userKeyword"
              placeholder="姓名或学号"
              clearable
              style="width: 200px"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="openCreateExternal">
              <el-icon><Plus /></el-icon>新建域外账号
            </el-button>
          </el-form-item>
        </el-form>

        <el-table :data="filteredUsers" v-loading="loadingUsers" stripe border style="width: 100%;">
          <el-table-column prop="student_no" label="学号" width="130" align="center" />
          <el-table-column prop="name" label="姓名" width="110" align="center" />
          <el-table-column label="类型" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_external" type="warning" size="small">域外</el-tag>
              <el-tag v-else type="info" size="small">学生</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="160" align="center">
            <template #default="{ row }">
              <el-select
                :model-value="row.role"
                size="small"
                style="width: 130px"
                @change="(val) => handleRoleChange(row, val)"
              >
                <el-option
                  v-for="(label, value) in ROLE_LABELS"
                  :key="value"
                  :label="label"
                  :value="value"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="密码状态" width="150" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.must_change_password" type="warning" size="small">待改密</el-tag>
              <el-tag v-else type="success" size="small">已设置</el-tag>
            </template>
          </el-table-column>
          <!-- 每次登录成功都会刷新，点表头可排序，方便看出谁最近还没登过 -->
          <el-table-column prop="last_login_at" label="最近登录时间" width="170" align="center" sortable>
            <template #default="{ row }">
              <span v-if="row.last_login_at">{{ formatDateTime(row.last_login_at) }}</span>
              <span v-else style="color: #c0c4cc;">从未登录</span>
            </template>
          </el-table-column>
          <el-table-column prop="last_login_ip" label="最近登录IP" width="150" align="center">
            <template #default="{ row }">
              <span v-if="row.last_login_ip" style="font-family: monospace; font-size: 12px;">
                {{ row.last_login_ip }}
              </span>
              <span v-else style="color: #c0c4cc;">-</span>
            </template>
          </el-table-column>
          <el-table-column label="身份证号" width="100" align="center">
            <template #default="{ row }">
              <!-- 域外账号没有身份证号这一说 -->
              <span v-if="row.is_external" style="color: #c0c4cc;">-</span>
              <el-tag v-else-if="row.has_id_card" type="info" size="small">已录入</el-tag>
              <el-tag v-else type="danger" size="small">缺失</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" align="center">
            <template #default="{ row }">
              <template v-if="row.is_external">
                <el-button link type="primary" size="small" @click="openEditExternal(row)">编辑</el-button>
                <el-button link type="primary" size="small" @click="handleExtResetPassword(row)">重置密码</el-button>
                <el-button link type="danger" size="small" @click="handleExtDelete(row)">删除</el-button>
              </template>
              <span v-else style="color: #c0c4cc;">-</span>
            </template>
          </el-table-column>
        </el-table>
        <div class="tip">
          共 {{ filteredUsers.length }} 个账号，改角色会对该账号立即生效并记入日志。
          域外账号不与学生关联，不会出现在学生名单、点名和各类统计里。
        </div>
      </el-tab-pane>

      <!-- ============ 重置密码 ============ -->
      <el-tab-pane label="重置密码" name="reset">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="重置后密码回到「身份证号后 6 位」，该生下次登录仍会被要求改密码。"
          style="margin-bottom: 16px;"
        />
        <el-form :inline="true">
          <el-form-item label="选择账号">
            <!-- 只列学生账号：域外账号没有身份证号，重置方式不同，在「账号角色管理」里操作 -->
            <el-select
              v-model="resetTarget"
              filterable
              placeholder="输入姓名或学号搜索"
              style="width: 280px"
            >
              <el-option
                v-for="u in studentUsers"
                :key="u.student_no"
                :label="`${u.name}（${u.student_no}）`"
                :value="u.student_no"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="danger" :loading="resetting" :disabled="!resetTarget" @click="handleReset">
              重置密码
            </el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <!-- ============ 操作日志 ============ -->
      <el-tab-pane label="操作日志" name="logs">
        <el-form :inline="true">
          <el-form-item label="操作人">
            <el-input v-model="logFilter.operator" placeholder="姓名或学号" clearable style="width: 160px" />
          </el-form-item>
          <el-form-item label="动作">
            <el-input v-model="logFilter.action" placeholder="如：发布通知" clearable style="width: 160px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="handleLogSearch">查询</el-button>
            <el-button @click="handleLogReset">重置</el-button>
            <el-button type="danger" plain :loading="clearingLogs" @click="handleClearLogs">
              清空日志
            </el-button>
          </el-form-item>
        </el-form>

        <el-table :data="logs" v-loading="loadingLogs" stripe border style="width: 100%;">
          <el-table-column label="时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作人" width="140" align="center">
            <template #default="{ row }">
              {{ row.operator_name || '-' }}
              <div style="font-size: 12px; color: #909399;">{{ row.operator_no }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="action" label="动作" width="130" align="center" />
          <el-table-column prop="ip" label="操作IP" width="140" align="center">
            <template #default="{ row }">
              <span v-if="row.ip" style="font-family: monospace; font-size: 12px;">{{ row.ip }}</span>
              <span v-else style="color: #c0c4cc;">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="target" label="对象" min-width="180" show-overflow-tooltip />
          <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip />
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="logPage"
            v-model:page-size="logPageSize"
            :page-sizes="[20, 50, 100, 200]"
            :total="logTotal"
            layout="total, sizes, prev, pager, next"
            background
            @size-change="fetchLogs"
            @current-change="fetchLogs"
          />
        </div>
      </el-tab-pane>

      <!-- ============ 资料下载管理 ============ -->
      <el-tab-pane label="资料下载管理" name="resources">
        <div class="resource-toolbar">
          <el-button type="primary" :loading="uploading" @click="handleUploadClick">
            <el-icon><Upload /></el-icon>上传新资料
          </el-button>
          <input
            ref="fileInputRef"
            type="file"
            style="display: none"
            @change="handleFileSelected"
          />
          <span class="tip">管理「资料下载」页面显示的条目。文件存在服务器上，改名不影响文件本身。</span>
        </div>

        <div v-for="group in resourceGroups" :key="group.category" class="resource-group">
          <div class="resource-group-title">
            <el-icon><FolderOpened /></el-icon>
            {{ group.category }}
            <span class="group-count">{{ group.items.length }} 份</span>
          </div>

          <el-table :data="group.items" v-loading="loadingResources" stripe border style="width: 100%;">
            <el-table-column label="序号" width="60" align="center">
              <template #default="{ $index }">{{ $index + 1 }}</template>
            </el-table-column>
            <el-table-column prop="name" label="名称" min-width="200" show-overflow-tooltip />
            <el-table-column prop="original_name" label="原始文件名" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span style="font-family: monospace; font-size: 12px;">{{ row.original_name || row.file_name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="排序" width="140" align="center">
              <template #default="{ row, $index }">
                <el-button size="small" :disabled="$index === 0" @click="moveResource(row, -1)">
                  <el-icon><Top /></el-icon>
                </el-button>
                <el-button size="small" :disabled="$index === group.items.length - 1" @click="moveResource(row, 1)">
                  <el-icon><Bottom /></el-icon>
                </el-button>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" align="center">
              <template #default="{ row }">
                <el-button size="small" @click="handleEditResource(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="handleDeleteResource(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ============ 新建 / 编辑域外账号 ============ -->
    <el-dialog
      v-model="extDialogVisible"
      :title="extForm.editing ? '编辑域外账号' : '新建域外账号'"
      width="520px"
    >
      <el-form :model="extForm" label-width="110px">
        <el-form-item label="登录名" required>
          <!-- 登录名是账号的主键，建好之后不能改（改了等于换一个账号） -->
          <el-input
            v-model="extForm.login_name"
            :disabled="extForm.editing"
            maxlength="20"
            placeholder="登录时填在「学号」那一栏，如 teacher"
          />
        </el-form-item>
        <el-form-item label="展示用户名" required>
          <el-input
            v-model="extForm.display_name"
            maxlength="50"
            placeholder="姓名、水印都用它，如 李俊刚"
          />
        </el-form-item>
        <el-form-item label="等效权限" required>
          <el-select v-model="extForm.role" style="width: 100%">
            <el-option
              v-for="(label, value) in ROLE_LABELS"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!extForm.editing" label="初始密码" required>
          <el-input v-model="extForm.password" placeholder="6-32 位，需同时含字母和数字" />
        </el-form-item>
        <el-form-item label="头像">
          <input
            ref="extAvatarInput"
            type="file"
            accept="image/*"
            style="display: none"
            @change="handleExtAvatarPicked"
          />
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <el-button @click="extAvatarInput?.click()">选择图片</el-button>
            <span class="tip" style="margin: 0;">
              {{ extAvatarText }}
            </span>
            <el-button
              v-if="extForm.avatarFile || (extForm.hasAvatar && !extForm.removeAvatar)"
              link
              type="danger"
              @click="handleExtAvatarClear"
            >
              清除头像
            </el-button>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="extDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="extSaving" @click="handleExtSave">
          {{ extForm.editing ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getUsers,
  setUserRole,
  resetUserPassword,
  createExternalUser,
  updateExternalUser,
  deleteExternalUser,
  getLogs,
  clearLogs,
  listResources,
  uploadResource,
  updateResource,
  reorderResources,
  deleteResource
} from '@/api/admin'
import { ROLE_LABELS } from '@/utils/roles'
import { formatDateTime } from '@/utils/format'

const activeTab = ref('users')

// ---------- 账号角色 ----------
const users = ref([])
const loadingUsers = ref(false)
const userKeyword = ref('')

const filteredUsers = computed(() => {
  const kw = userKeyword.value.trim()
  if (!kw) return users.value
  return users.value.filter((u) => u.name.includes(kw) || u.student_no.includes(kw))
})

// 「重置密码」tab 的候选：只列学生账号。
// 那里的语义是「重置为身份证号后 6 位」，对域外账号不适用
// （域外账号的密码由管理员在下面的对话框里直接指定）
const studentUsers = computed(() => users.value.filter((u) => !u.is_external))

async function fetchUsers() {
  loadingUsers.value = true
  try {
    users.value = await getUsers()
  } catch (e) {
    ElMessage.error('账号列表加载失败')
  } finally {
    loadingUsers.value = false
  }
}

async function handleRoleChange(row, role) {
  if (role === row.role) return
  try {
    await ElMessageBox.confirm(
      `确定把「${row.name}」的角色改为「${ROLE_LABELS[role]}」吗？`,
      '修改角色',
      { type: 'warning' }
    )
  } catch (e) {
    return // 取消，下拉框绑的是 model-value，不刷新也不会串值
  }
  try {
    await setUserRole(row.student_no, role)
    ElMessage.success('角色已更新')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  }
}

// ---------- 重置密码 ----------
const resetTarget = ref('')
const resetting = ref(false)

async function handleReset() {
  const target = users.value.find((u) => u.student_no === resetTarget.value)
  if (!target) return
  try {
    await ElMessageBox.confirm(
      `确定把「${target.name}」的密码重置为原始密码吗？`,
      '重置密码',
      { type: 'warning', confirmButtonText: '重置' }
    )
  } catch (e) {
    return // 取消
  }

  resetting.value = true
  try {
    const res = await resetUserPassword(resetTarget.value)
    if (res.password) {
      // 没有身份证号时密码退化成学号后 6 位，后端把明文回带，好让管理员转告学生
      ElMessageBox.alert(`该生没有身份证号，密码已重置为：${res.password}`, '重置成功', {
        confirmButtonText: '知道了'
      })
    } else {
      ElMessage.success('已重置为身份证号后 6 位')
    }
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '重置失败')
  } finally {
    resetting.value = false
  }
}

// ---------- 域外账号（不与学生关联的账号：老师、协助人员等）----------
// 新建和编辑共用一个对话框，靠 extForm.editing 区分。
// 登录名是账号主键，建好之后不让改（要换登录名等于换个账号，重新建即可）
const extDialogVisible = ref(false)
const extSaving = ref(false)
const extAvatarInput = ref(null)
const extForm = reactive({
  editing: false,
  login_name: '',
  display_name: '',
  role: 'student',
  password: '',
  avatarFile: null,   // 本次选中的新图片
  hasAvatar: false,   // 服务端已有的头像
  removeAvatar: false // 编辑时勾了「清除头像」
})

const extAvatarText = computed(() => {
  if (extForm.avatarFile) return `已选择：${extForm.avatarFile.name}`
  if (extForm.hasAvatar && !extForm.removeAvatar) return '已有头像，重新选择可替换'
  if (extForm.removeAvatar) return '保存后清除头像'
  return '不传则用姓名首字占位，单张不超过 2MB'
})

function resetExtForm() {
  extForm.editing = false
  extForm.login_name = ''
  extForm.display_name = ''
  extForm.role = 'student'
  extForm.password = ''
  extForm.avatarFile = null
  extForm.hasAvatar = false
  extForm.removeAvatar = false
  // 清掉原生 input 里的选择，否则再打开还是上次那个文件
  if (extAvatarInput.value) extAvatarInput.value.value = ''
}

function openCreateExternal() {
  resetExtForm()
  extDialogVisible.value = true
}

function openEditExternal(row) {
  resetExtForm()
  extForm.editing = true
  extForm.login_name = row.student_no
  extForm.display_name = row.name
  extForm.role = row.role || 'student'
  extForm.hasAvatar = !!row.has_avatar
  extDialogVisible.value = true
}

function handleExtAvatarPicked(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning('头像不能超过 2MB')
    e.target.value = ''
    return
  }
  extForm.avatarFile = file
  extForm.removeAvatar = false
}

function handleExtAvatarClear() {
  extForm.avatarFile = null
  extForm.removeAvatar = true
  if (extAvatarInput.value) extAvatarInput.value.value = ''
}

async function handleExtSave() {
  if (!extForm.editing) {
    if (!extForm.login_name.trim()) return ElMessage.warning('请填写登录名')
  }
  if (!extForm.display_name.trim()) return ElMessage.warning('请填写展示用户名')
  if (!extForm.editing) {
    // 规则与后端 _clean_login_name 一致：非空、不超过 20 位、不能有空格
    // （不限定字母数字，老师也可能想用姓名当登录名）
    const name = extForm.login_name.trim()
    if (name.length > 20) return ElMessage.warning('登录名不能超过 20 位')
    if (/\s/.test(name)) return ElMessage.warning('登录名不能包含空格')
    if (extForm.password.length < 6 || extForm.password.length > 32) {
      return ElMessage.warning('初始密码长度需为 6-32 位')
    }
    if (!/[A-Za-z]/.test(extForm.password) || !/\d/.test(extForm.password)) {
      return ElMessage.warning('初始密码必须同时包含字母和数字')
    }
  }

  const fd = new FormData()
  fd.append('display_name', extForm.display_name.trim())
  fd.append('role', extForm.role)
  if (extForm.editing) {
    // 用 remove_avatar 明确告诉后端「是清了还是没动」——
    // 不传 avatar 字段时后端无法区分这两种情况
    fd.append('remove_avatar', extForm.removeAvatar ? 'true' : 'false')
  } else {
    fd.append('login_name', extForm.login_name.trim())
    fd.append('password', extForm.password)
  }
  if (extForm.avatarFile) fd.append('avatar', extForm.avatarFile)

  extSaving.value = true
  try {
    if (extForm.editing) {
      await updateExternalUser(extForm.login_name, fd)
      ElMessage.success('已保存')
    } else {
      await createExternalUser(fd)
      ElMessage.success('域外账号已创建')
    }
    extDialogVisible.value = false
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    extSaving.value = false
  }
}

async function handleExtResetPassword(row) {
  let value
  try {
    const res = await ElMessageBox.prompt(
      `给「${row.name}」设置一个新密码（6-32 位，需同时含字母和数字）。设置后立即生效，不会要求他再改一次。`,
      '重置密码',
      {
        confirmButtonText: '确定',
        inputPlaceholder: '新密码',
        inputValidator: (v) => {
          if (!v || v.length < 6 || v.length > 32) return '长度需为 6-32 位'
          if (!/[A-Za-z]/.test(v) || !/\d/.test(v)) return '必须同时包含字母和数字'
          return true
        }
      }
    )
    value = res.value
  } catch (e) {
    return // 取消
  }

  try {
    await resetUserPassword(row.student_no, value)
    ElMessage.success('密码已重置')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '重置失败')
  }
}

async function handleExtDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除域外账号「${row.name}」（${row.student_no}）吗？头像和推送订阅会一并清除，历史操作日志保留。`,
      '删除账号',
      { type: 'warning', confirmButtonText: '删除' }
    )
  } catch (e) {
    return // 取消
  }
  try {
    await deleteExternalUser(row.student_no)
    ElMessage.success('已删除')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// ---------- 操作日志 ----------
const logs = ref([])
const loadingLogs = ref(false)
const logTotal = ref(0)
const logPage = ref(1)
const logPageSize = ref(50)
const logFilter = reactive({ operator: '', action: '' })

async function fetchLogs() {
  loadingLogs.value = true
  try {
    const res = await getLogs({
      operator: logFilter.operator || undefined,
      action: logFilter.action || undefined,
      page: logPage.value,
      page_size: logPageSize.value
    })
    logs.value = res.items
    logTotal.value = res.total
  } catch (e) {
    ElMessage.error('操作日志加载失败')
  } finally {
    loadingLogs.value = false
  }
}

function handleLogSearch() {
  logPage.value = 1
  fetchLogs()
}

function handleLogReset() {
  logFilter.operator = ''
  logFilter.action = ''
  handleLogSearch()
}

// 清空是「全清」，不是只清当前筛选出来的那些，所以确认文案里要写明白
const clearingLogs = ref(false)

async function handleClearLogs() {
  try {
    await ElMessageBox.confirm(
      `确定清空全部操作日志吗？共 ${logTotal.value} 条。清空后无法恢复，也不会留下清空记录。`,
      '清空日志',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 取消
  }

  clearingLogs.value = true
  try {
    const res = await clearLogs()
    ElMessage.success(`已清空 ${res.deleted} 条日志`)
    logPage.value = 1
    fetchLogs()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '清空失败')
  } finally {
    clearingLogs.value = false
  }
}

// ---------- 资料下载管理 ----------
const resources = ref([])
const loadingResources = ref(false)
const uploading = ref(false)
const fileInputRef = ref(null)

// 按分类分组给展示
const resourceGroups = computed(() => {
  const groups = {}
  const order = []
  for (const r of resources.value) {
    if (!groups[r.category]) {
      groups[r.category] = []
      order.push(r.category)
    }
    groups[r.category].push(r)
  }
  return order.map((cat) => ({
    category: cat,
    items: groups[cat].sort((a, b) => a.sort_order - b.sort_order)
  }))
})

async function fetchResources() {
  loadingResources.value = true
  try {
    resources.value = await listResources()
  } catch (e) {
    ElMessage.error('资料列表加载失败')
  } finally {
    loadingResources.value = false
  }
}

function handleUploadClick() {
  fileInputRef.value?.click()
}

async function handleFileSelected(e) {
  const file = e.target.files?.[0]
  if (!file) return

  try {
    // 弹框填名称和分类
    const { value: name, } = await ElMessageBox.prompt('请输入资料名称', '上传资料', {
      confirmButtonText: '下一步',
      cancelButtonText: '取消',
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空'
    })
    const { value: category } = await ElMessageBox.prompt('请输入分类（如：徽章标志、常用表格）', '选择分类', {
      confirmButtonText: '上传',
      cancelButtonText: '取消',
      inputValue: resourceGroups.value[0]?.category || '',
      inputPattern: /\S+/,
      inputErrorMessage: '分类不能为空'
    })

    const formData = new FormData()
    formData.append('name', name)
    formData.append('category', category)
    formData.append('file', file)

    uploading.value = true
    try {
      await uploadResource(formData)
      ElMessage.success('上传成功')
      fetchResources()
    } catch (err) {
      ElMessage.error(err?.response?.data?.detail || '上传失败')
    } finally {
      uploading.value = false
    }
  } catch (e) {
    // 用户取消了 prompt
  } finally {
    // 重置 input，否则同一个文件下次还能触发 change
    e.target.value = ''
  }
}

async function handleEditResource(row) {
  try {
    const { value: name } = await ElMessageBox.prompt('修改资料名称', '编辑资料', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: row.name,
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空'
    })
    const { value: category } = await ElMessageBox.prompt('修改分类', '编辑资料', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: row.category,
      inputPattern: /\S+/,
      inputErrorMessage: '分类不能为空'
    })

    const formData = new FormData()
    formData.append('name', name)
    formData.append('category', category)
    await updateResource(row.id, formData)
    ElMessage.success('已更新')
    fetchResources()
  } catch (e) {
    if (e !== 'cancel') return // 用户取消
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  }
}

async function handleDeleteResource(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.name}」吗？文件也会一并删除，无法恢复。`,
      '删除资料',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch (e) {
    return
  }
  try {
    await deleteResource(row.id)
    ElMessage.success('已删除')
    fetchResources()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

async function moveResource(row, direction) {
  // direction: -1=上移, 1=下移
  const group = resourceGroups.value.find((g) => g.category === row.category)
  if (!group) return
  const idx = group.items.findIndex((r) => r.id === row.id)
  if (idx < 0) return
  const newIdx = idx + direction
  if (newIdx < 0 || newIdx >= group.items.length) return

  // 本地交换，发请求
  const newItems = [...group.items]
  ;[newItems[idx], newItems[newIdx]] = [newItems[newIdx], newItems[idx]]
  const order = newItems.map((r) => r.id)

  try {
    await reorderResources(row.category, order)
    fetchResources()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '排序失败')
  }
}

onMounted(() => {
  fetchUsers()
  fetchLogs()
  fetchResources()
})
</script>

<style scoped>
.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.tip {
  margin-top: 12px;
  font-size: 13px;
  color: #909399;
}

/* ---------- 资料下载管理 ---------- */
.resource-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.resource-toolbar .tip {
  margin: 0;
}

.resource-group {
  margin-bottom: 24px;
}

.resource-group:last-child {
  margin-bottom: 0;
}

.resource-group-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.group-count {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
  margin-left: 4px;
}
</style>
