<template>
  <div v-loading="loading">
    <!-- 和其他页面一样：page-card 套 page-title，tab 在卡片里 -->
    <div class="page-card">
      <h3 class="page-title">我的信息</h3>

      <!-- 顶部 Tab：学生账号能看到「基本信息」，域外账号只有「账户设置」 -->
      <el-tabs v-model="activeTab">
        <!-- 基本信息：只有学生账号才有 -->
        <el-tab-pane v-if="!userStore.isExternal" label="基本信息" name="info">
          <div class="tab-section">
            <template v-if="me">
              <!-- 两张照片：高考照片 + 实地采集，点一下放大 -->
              <div class="photos-row">
                <div
                  v-for="item in PHOTOS"
                  :key="item.type"
                  class="photo-item"
                  :class="{ 'photo-empty-box': !hasPhoto(item.type) }"
                  @click="openPhotos(item.type)"
                >
                  <img
                    v-if="hasPhoto(item.type)"
                    :src="photoUrl(item.type)"
                    class="photo-img"
                    :alt="item.label"
                    @error="onImgError"
                  />
                  <div v-else class="photo-placeholder">
                    <el-icon style="font-size: 34px;"><Avatar /></el-icon>
                    <span>暂无照片</span>
                  </div>
                  <div class="photo-label">{{ item.label }}</div>
                </div>
              </div>
              <p class="photos-tip">点击照片可放大查看</p>

              <el-descriptions :column="detailColumns" border style="margin-top: 16px;">
                <el-descriptions-item label="学号">{{ me.student_no || '-' }}</el-descriptions-item>
                <el-descriptions-item label="姓名">{{ me.name || '-' }}</el-descriptions-item>
                <el-descriptions-item label="性别">{{ me.gender || '-' }}</el-descriptions-item>
                <el-descriptions-item label="出生日期">{{ me.birth_date || '-' }}</el-descriptions-item>
                <el-descriptions-item label="民族">{{ me.ethnicity || '-' }}</el-descriptions-item>
                <el-descriptions-item label="政治面貌">{{ me.political_status || '-' }}</el-descriptions-item>
                <el-descriptions-item label="学院/班级">{{ me.class_name || '-' }}</el-descriptions-item>
                <el-descriptions-item label="专业">{{ me.major || '-' }}</el-descriptions-item>
                <el-descriptions-item label="宿舍">{{ me.dormitory || '-' }}</el-descriptions-item>
                <el-descriptions-item label="床位号">{{ me.bed || '-' }}</el-descriptions-item>
                <el-descriptions-item label="本人电话">{{ me.phone || '-' }}</el-descriptions-item>
                <el-descriptions-item label="高考总分">{{ me.gaokao_score ?? '-' }}</el-descriptions-item>
                <!-- 备注是班委内部记录，普通学生拿到的一律是 null，只有班委/管理员能看到自己的 -->
                <el-descriptions-item v-if="me.remark" label="备注" :span="detailColumns">
                  {{ me.remark }}
                </el-descriptions-item>
              </el-descriptions>
            </template>
            <el-empty v-else-if="!loading" description="未获取到个人信息" />
          </div>

          <!-- 申请修改：默认收起来，点「修改」才展开；一次只能有一条待审核的申请 -->
          <div class="tab-section">
            <div class="page-toolbar">
              <h3 class="page-title" style="margin-bottom: 0;">申请修改</h3>
              <el-button v-if="canApply" type="primary" @click="openForm">修改</el-button>
            </div>

            <!-- 已经有一条排队等审：只解释原因，不给入口 -->
            <el-alert
              v-if="pending"
              type="warning"
              :closable="false"
              show-icon
              style="margin-top: 16px;"
            >
              <template #title>
                你有一条待审核的申请（{{ formatDateTime(pending.created_at) }} 提交），班委处理后才能再次提交。
              </template>
              <div style="margin-top: 4px;">{{ describeChanges(pending.changes) }}</div>
            </el-alert>

            <el-alert
              v-else-if="!formVisible"
              type="info"
              :closable="false"
              show-icon
              style="margin-top: 16px;"
              title="点右上角「修改」可申请改动下方内容，提交后需班委审核，审核通过才会真正生效。"
            />

            <el-form v-else :model="form" label-width="100px" style="max-width: 640px; margin-top: 16px;">
              <el-form-item v-for="f in CHANGE_FIELDS" :key="f.prop" :label="f.label">
                <el-select v-if="f.prop === 'is_poor'" v-model="form.is_poor" style="width: 160px">
                  <el-option label="是" value="是" />
                  <el-option label="否" value="否" />
                </el-select>
                <el-input
                  v-else
                  v-model="form[f.prop]"
                  :type="f.prop === 'family_address' ? 'textarea' : 'text'"
                  :rows="2"
                  :placeholder="f.placeholder"
                  :maxlength="f.maxLength"
                />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="submitting" @click="handleSubmit">提交申请</el-button>
                <el-button @click="formVisible = false">取消</el-button>
              </el-form-item>
            </el-form>
          </div>

          <!-- 申请记录 -->
          <div class="tab-section">
            <h3 class="page-title">我的申请记录</h3>
            <el-table :data="records" stripe border style="width: 100%;">
              <el-table-column label="申请时间" width="160" align="center">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="申请修改的内容" min-width="260">
                <template #default="{ row }">{{ describeChanges(row.changes) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="100" align="center">
                <template #default="{ row }">
                  <el-tag :type="STATUS_TYPES[row.status]" size="small">
                    {{ STATUS_LABELS[row.status] || row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="审核人" width="100" align="center">
                <template #default="{ row }">{{ row.reviewer_name || '-' }}</template>
              </el-table-column>
              <el-table-column label="审核时间" width="160" align="center">
                <template #default="{ row }">{{ formatDateTime(row.reviewed_at) }}</template>
              </el-table-column>
              <el-table-column label="驳回理由" min-width="160">
                <template #default="{ row }">
                  <span :style="{ color: row.reason ? '#f56c6c' : '#c0c4cc' }">{{ row.reason || '-' }}</span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!records.length" description="还没有提交过申请" style="margin-top: 20px;" />
          </div>
        </el-tab-pane>

        <!-- 账户设置：改密码 + 通知设置，所有登录用户都能看到 -->
        <el-tab-pane label="账户设置" name="account">
          <!-- 修改密码 -->
          <div class="tab-section">
            <h3 class="page-title">修改密码</h3>
            <el-form :model="pwdForm" label-width="100px" style="max-width: 480px; margin-top: 12px;">
              <el-form-item label="原密码">
                <el-input v-model="pwdForm.old_password" type="password" show-password />
              </el-form-item>
              <el-form-item label="新密码">
                <el-input
                  v-model="pwdForm.new_password"
                  type="password"
                  show-password
                  placeholder="6-32 位，需同时包含字母和数字"
                />
              </el-form-item>
              <el-form-item label="确认密码">
                <el-input
                  v-model="pwdForm.confirm"
                  type="password"
                  show-password
                  @keyup.enter="handleChangePassword"
                />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="pwdLoading" @click="handleChangePassword">
                  确认修改
                </el-button>
              </el-form-item>
            </el-form>
          </div>

          <!-- 通知设置：浏览器通知 + Bark 推送 -->
          <div class="tab-section">
            <h3 class="page-title">通知设置</h3>
            <p class="section-sub" style="margin-bottom: 12px;">
              有审核结果、新通知等情况时，通过以下方式推送给你
            </p>

            <!-- 安装到桌面：Chrome/Edge/Android 能触发原生安装横幅，iOS 没有 -->
            <el-alert
              v-if="!standalone && canInstall"
              type="success"
              :closable="false"
              show-icon
              style="margin-bottom: 16px;"
            >
              <template #title>把这个应用装到桌面</template>
              <div class="install-row">
                <span>装进桌面后像原生应用一样打开，全屏显示，没有地址栏。</span>
                <el-button type="primary" size="small" :loading="installing" @click="handleInstall">
                  安装应用
                </el-button>
              </div>
            </el-alert>

            <!-- ==================== 浏览器通知 ==================== -->
            <div class="section-title">浏览器通知</div>
            <div class="section-sub">用本机浏览器直接收，不用装任何东西</div>

            <!-- 不支持 / 环境限制 -->
            <el-alert v-if="webState === 'blocked'" type="warning" :closable="false" show-icon>
              <template #title>当前环境用不了浏览器通知</template>
              {{ webNote }}
            </el-alert>

            <!-- iPhone：普通标签页里连权限弹窗都弹不出来，必须先添加到主屏 -->
            <el-alert v-else-if="webState === 'ios-tab'" type="info" :closable="false" show-icon>
              <template #title>iPhone 上需要先「添加到主屏」</template>
              在 Safari 里点底部的分享按钮 →「添加到主屏」，然后<b>从主屏图标打开</b>本应用，
              再回到这里开启通知。普通标签页里收不到网页通知，这是 iOS 的限制。
            </el-alert>

            <!-- 浏览器记住了「不允许」 -->
            <el-alert v-else-if="webState === 'denied'" type="warning" :closable="false" show-icon>
              <template #title>本站的通知被浏览器拒绝了</template>
              点地址栏左侧的站点设置，把「通知」改回「允许」，然后重新开启。
            </el-alert>

            <template v-else>
              <div class="status-row">
                <el-tag v-if="webState === 'on'" type="success" size="small">已开启</el-tag>
                <el-tag v-else type="info" size="small">未开启</el-tag>
                <span class="desc">
                  {{ webState === 'on' ? '本机浏览器已订阅' : '开启后本机能收到站内通知' }}
                </span>
              </div>

              <div v-if="webCount > 0" class="desc count">
                本账号共有 {{ webCount }} 台设备已开启浏览器通知
              </div>

              <div class="actions">
                <el-button
                  v-if="webState === 'off'"
                  type="primary"
                  size="small"
                  :loading="webBusy"
                  @click="handleWebEnable"
                >
                  开启通知
                </el-button>
                <template v-else>
                  <el-button size="small" :loading="webTesting" @click="handleWebTest">
                    发送测试
                  </el-button>
                  <el-button size="small" :loading="webBusy" @click="handleWebDisable">
                    关闭通知
                  </el-button>
                </template>
              </div>
            </template>

            <el-divider />

            <!-- ==================== Bark 推送 ==================== -->
            <div class="section-title">Bark 推送</div>
            <div class="section-sub">手机上装 Bark App，填一个设备 ID 就能收</div>

            <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px;">
              <template #title>怎么拿到设备 ID</template>
              在手机上装好 Bark App，打开后首页显示的那串字符就是设备 ID。
              复制粘贴到下面即可（粘整条链接也行，会自动识别）。
            </el-alert>

            <el-form :model="barkForm" label-width="100px">
              <el-form-item label="设备 ID">
                <el-input
                  v-model="barkForm.bark_key"
                  placeholder="留空并保存 = 关闭推送"
                  clearable
                  @keyup.enter="handleBarkSave"
                />
              </el-form-item>
            </el-form>

            <div class="actions">
              <el-button size="small" :loading="barkTesting" @click="handleBarkTest">发送测试推送</el-button>
              <el-button type="primary" size="small" :loading="barkSaving" @click="handleBarkSave">保存</el-button>
              <el-button v-if="savedBarkKey" link type="danger" size="small" @click="handleBarkUnbind">
                解除绑定
              </el-button>
            </div>

            <div class="hint-note footnote">
              两个渠道都开着的话，同一台设备会收到两条通知（浏览器一条、Bark 一条）。
              只想要其中一种，把另一种关掉即可。
            </div>
          </div>
        </el-tab-pane>

        <!-- 办件空间：我申请的 / 我审批的 -->
        <el-tab-pane label="办件空间" name="workspace">
          <el-tabs v-model="workspaceTab">
            <!-- 我申请的 -->
            <el-tab-pane label="我申请的" name="submitted">
              <div v-loading="submittedLoading" class="workspace-list">
                <div v-if="submittedList.length" class="case-list">
                  <div
                    v-for="item in submittedList"
                    :key="`${item.type}-${item.id}`"
                    class="case-item"
                    @click="goToDetail(item)"
                  >
                    <div class="case-header">
                      <el-tag size="small" type="info" effect="plain">{{ item.type_name }}</el-tag>
                      <el-tag :type="item.status_type" size="small">{{ item.status_label }}</el-tag>
                    </div>
                    <div class="case-title">{{ item.title }}</div>
                    <div class="case-meta">
                      <span>提交时间：{{ formatDateTime(item.created_at) }}</span>
                      <span v-if="item.updated_at && item.updated_at !== item.created_at">
                        处理时间：{{ formatDateTime(item.updated_at) }}
                      </span>
                    </div>
                    <div v-if="item.reviewer_name" class="case-meta">
                      处理人：{{ item.reviewer_name }}
                    </div>
                    <div v-if="item.reason" class="case-reason">
                      驳回理由：{{ item.reason }}
                    </div>
                    <div class="case-actions" @click.stop>
                      <el-button size="small" type="primary" link @click="goToDetail(item)">
                        查看详情
                      </el-button>
                    </div>
                  </div>
                </div>
                <el-empty v-else-if="!submittedLoading" description="还没有申请过任何办件" />
              </div>
            </el-tab-pane>

            <!-- 我审批的 -->
            <el-tab-pane v-if="canReview" label="我审批的" name="involved">
              <div v-loading="involvedLoading" class="workspace-list">
                <div v-if="involvedList.length" class="case-list">
                  <div
                    v-for="item in involvedList"
                    :key="`${item.type}-${item.id}`"
                    class="case-item"
                    @click="goToDetail(item)"
                  >
                    <div class="case-header">
                      <el-tag size="small" type="info" effect="plain">{{ item.type_name }}</el-tag>
                      <el-tag :type="item.status_type" size="small">{{ item.status_label }}</el-tag>
                    </div>
                    <div class="case-title">{{ item.title }}</div>
                    <div class="case-meta">
                      <span>申请人：{{ item.applicant_name || '-' }}
                        <span v-if="item.applicant_no" style="color:#909399;">({{ item.applicant_no }})</span>
                      </span>
                    </div>
                    <div class="case-meta">
                      <span>申请时间：{{ formatDateTime(item.created_at) }}</span>
                      <span v-if="item.updated_at">处理时间：{{ formatDateTime(item.updated_at) }}</span>
                    </div>
                    <div v-if="item.reason" class="case-reason">
                      驳回理由：{{ item.reason }}
                    </div>
                    <div class="case-actions" @click.stop>
                      <el-button size="small" type="primary" link @click="goToDetail(item)">
                        查看详情
                      </el-button>
                    </div>
                  </div>
                </div>
                <el-empty v-else-if="!involvedLoading" description="还没有处理过任何办件" />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 照片查看器 -->
    <el-image-viewer
      v-if="viewerVisible"
      :url-list="viewerList"
      :initial-index="viewerIndex"
      @close="viewerVisible = false"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMyInfo } from '@/api/student'
import { changePassword } from '@/api/auth'
import { submitChangeRequest, getMyChangeRequests } from '@/api/changeRequest'
import {
  getBarkSetting,
  saveBarkSetting,
  testBarkPush
} from '@/api/bark'
import {
  getWebpushState,
  saveWebpushSubscription,
  removeWebpushSubscription,
  testWebpush
} from '@/api/webpush'
import {
  CHANGE_FIELDS,
  FIELD_LABELS,
  STATUS_LABELS,
  STATUS_TYPES
} from '@/utils/changeFields'
import { formatDateTime } from '@/utils/format'
import { useIsMobile } from '@/composables/useIsMobile'
import { useUserStore } from '@/store/user'
import { rankOf } from '@/utils/roles'
import { getMySubmitted, getMyInvolved } from '@/api/workspace'
import {
  isSupported,
  isIos,
  isStandalone as checkIsStandalone,
  canInstall as checkCanInstall,
  triggerInstallPrompt,
  currentSubscription,
  subscribe,
  unsubscribe
} from '@/utils/webpush'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 手机上 3 列会把标签挤成竖排（「政 治 面 貌」），收成 1 列
const isMobile = useIsMobile()
const detailColumns = computed(() => (isMobile.value ? 1 : 3))

// 当前激活的 tab：从 URL query 读，域外账号默认是账户设置
const activeTab = ref('info')

// 同步 URL 的 tab 参数（支持分享链接直接定位到某个 tab）
// 注意：这里必须认识全部 tab。漏掉一个的话，点它就会立刻被这个 watcher
// 拽回默认 tab（切 tab 时同 URL 会被反写一次），表现成「点了没反应」
watch(
  () => route.query.tab,
  (val) => {
    // 域外账号没有「基本信息」，其余 tab 都放行
    const known = ['info', 'account', 'workspace']
    if (known.includes(val) && !(val === 'info' && userStore.isExternal)) {
      activeTab.value = val
    } else {
      // 默认 tab：学生 → info，域外 → account
      activeTab.value = userStore.isExternal ? 'account' : 'info'
    }
  },
  { immediate: true }
)

// 切换 tab 时更新 URL，方便刷新后还在同一个 tab
watch(activeTab, (val) => {
  if (route.query.tab !== val) {
    router.replace({ query: { ...route.query, tab: val } })
  }
})

// 两个照片位：高考照片和实地采集，字段名与后端 students 表一致
const PHOTOS = [
  { type: 'gaokao', field: 'gaokao_photo', label: '高考照片' },
  { type: 'on_site', field: 'on_site_photo', label: '实地采集' }
]

const loading = ref(false)
const me = ref(null)
const records = ref([])

// 申请表单默认收起来，点「修改」才展开
const formVisible = ref(false)
const submitting = ref(false)

// 表单先摆全部字段，拿到自己的信息后再回填
const form = reactive(Object.fromEntries(CHANGE_FIELDS.map((f) => [f.prop, ''])))

/** 已经有一条排队等着审，就锁住表单（后端也会拒，前端锁住体验更好） */
const pending = computed(() => records.value.find((r) => r.status === 'pending'))
const canApply = computed(() => !pending.value && !formVisible.value)

// 照片查看器
const viewerVisible = ref(false)
const viewerList = ref([])
const viewerIndex = ref(0)

// ---------- 修改密码 ----------
const pwdLoading = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

// ---------- 通知设置 ----------
const installing = ref(false)
const standalone = ref(false)
const canInstall = ref(false)

// 浏览器通知
const webState = ref('off')
const webNote = ref('')
const webBusy = ref(false)
const webTesting = ref(false)
const webCount = ref(0)
const vapidKey = ref('')

// Bark
const barkSaving = ref(false)
const barkTesting = ref(false)
const savedBarkKey = ref('')
const barkForm = reactive({ bark_key: '' })

const KEY_PATTERN = /^[A-Za-z0-9_-]{5,128}$/

// ---------- 办件空间 ----------
const workspaceTab = ref('submitted')
const submittedList = ref([])
const submittedLoading = ref(false)
const involvedList = ref([])
const involvedLoading = ref(false)

// 能不能看到「我审批的」tab：班委及以上
const canReview = computed(() => rankOf(userStore.info?.role) >= rankOf('committee'))

// 同步 URL 的 sub 参数（办件空间内的子 tab）。
// immediate 是为了让通知里的 ...&sub=involved 直接落到「我审批的」
watch(
  () => route.query.sub,
  (val) => {
    if (val === 'involved' && canReview.value) {
      workspaceTab.value = 'involved'
    } else {
      workspaceTab.value = 'submitted'
    }
  },
  { immediate: true }
)

watch(workspaceTab, (val) => {
  if (activeTab.value !== 'workspace') return
  if (route.query.sub !== val) {
    router.replace({ query: { ...route.query, sub: val } })
  }
})

async function fetchSubmitted() {
  submittedLoading.value = true
  try {
    submittedList.value = await getMySubmitted()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    submittedLoading.value = false
  }
}

async function fetchInvolved() {
  if (!canReview.value) return
  involvedLoading.value = true
  try {
    involvedList.value = await getMyInvolved()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    involvedLoading.value = false
  }
}

// 切到办件空间 tab 时才拉数据，避免浪费请求
watch(activeTab, (val) => {
  if (val === 'workspace') {
    fetchSubmitted()
    if (canReview.value && workspaceTab.value === 'involved') {
      fetchInvolved()
    }
  }
})

watch(workspaceTab, (val) => {
  if (activeTab.value !== 'workspace') return
  if (val === 'submitted') fetchSubmitted()
  if (val === 'involved') fetchInvolved()
})

function goToDetail(item) {
  if (item.detail_url) {
    router.push(item.detail_url)
  }
}

/** 照片走带鉴权的接口，不直连静态目录（和「学生信息」页一个取法） */
function photoUrl(type) {
  return `/api/students/${me.value?.id}/photo?type=${type}`
}

function hasPhoto(type) {
  const field = PHOTOS.find((p) => p.type === type)?.field
  return !!me.value?.[field]
}

function onImgError(e) {
  e.target.style.display = 'none'
}

/** 打开查看器：只在已有的照片之间翻页 */
function openPhotos(activeType) {
  const photos = PHOTOS.filter((p) => hasPhoto(p.type))
  if (!photos.length) return
  viewerList.value = photos.map((p) => photoUrl(p.type))
  const index = photos.findIndex((p) => p.type === activeType)
  viewerIndex.value = index >= 0 ? index : 0
  viewerVisible.value = true
}

/** 把 {"qq":"123","email":null} 说成「QQ号码：123；电子邮箱：（清空）」 */
function describeChanges(changes) {
  const parts = Object.entries(changes || {}).map(
    ([key, value]) => `${FIELD_LABELS[key] || key}：${value ? value : '（清空）'}`
  )
  return parts.length ? parts.join('；') : '-'
}

/** 回填表单：显示当前值，学生在此基础上改 */
function resetForm() {
  for (const { prop } of CHANGE_FIELDS) {
    form[prop] = me.value?.[prop] ?? ''
  }
}

function openForm() {
  resetForm()
  formVisible.value = true
}

/** 只把改动过的字段提交上去，避免整表覆盖 */
function buildChanges() {
  const changes = {}
  for (const { prop } of CHANGE_FIELDS) {
    const next = (form[prop] ?? '').trim()
    const old = (me.value?.[prop] ?? '').trim()
    if (next !== old) changes[prop] = next
  }
  return changes
}

function validate() {
  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
    ElMessage.warning('电子邮箱格式不正确')
    return false
  }
  if (form.postal_code && !/^\d{6}$/.test(form.postal_code.trim())) {
    ElMessage.warning('邮政编码应为 6 位数字')
    return false
  }
  return true
}

// ---------- 修改密码 ----------
async function handleChangePassword() {
  if (!pwdForm.old_password) return ElMessage.warning('请输入原密码')
  if (pwdForm.new_password.length < 6 || pwdForm.new_password.length > 32) {
    return ElMessage.warning('新密码长度需为 6-32 位')
  }
  if (!/[A-Za-z]/.test(pwdForm.new_password) || !/\d/.test(pwdForm.new_password)) {
    return ElMessage.warning('新密码必须同时包含字母和数字')
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    return ElMessage.warning('两次输入的新密码不一致')
  }

  pwdLoading.value = true
  try {
    await changePassword({
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password
    })
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm = ''
    ElMessage.success('密码修改成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  } finally {
    pwdLoading.value = false
  }
}

// ---------- 通知设置：浏览器通知 ----------
function cleanKey(raw) {
  let text = (raw || '').trim()
  if (text.includes('://')) {
    text = text.split('://')[1]
    text = text.includes('/') ? text.split('/')[1] : ''
  }
  return text.split('/')[0].split('?')[0].trim()
}

async function refreshWebState() {
  if (!isSupported()) {
    webState.value = 'blocked'
    webNote.value =
      '这个浏览器没有提供网页通知能力，可以改用下面的 Bark 推送，或换 Chrome / Edge / Safari 打开本站。'
    return
  }
  if (isIos() && !checkIsStandalone()) {
    webState.value = 'ios-tab'
    return
  }
  if (Notification.permission === 'denied') {
    webState.value = 'denied'
    return
  }
  try {
    webState.value = (await currentSubscription()) ? 'on' : 'off'
  } catch (e) {
    webState.value = 'blocked'
    webNote.value = '浏览器通知要求以 HTTPS 打开本站，用 http 或局域网 IP 访问时用不了。'
  }
}

async function loadWebpushServerState() {
  const data = await getWebpushState()
  vapidKey.value = data.vapid_public_key || ''
  webCount.value = data.count || 0

  // 对账：本机明明有订阅，服务端却一条都没有 —— 顺手补登记一次
  const sub = await currentSubscription().catch(() => null)
  if (sub && webCount.value === 0) {
    await saveWebpushSubscription(sub.toJSON())
    webCount.value = 1
  }
}

async function handleWebEnable() {
  if (!vapidKey.value) return ElMessage.error('推送服务还没准备好，请稍后重试')

  webBusy.value = true
  try {
    const sub = await subscribe(vapidKey.value)
    await saveWebpushSubscription(sub.toJSON())
    await refreshWebState()
    await loadWebpushServerState()
    ElMessage.success('已开启，本机会收到浏览器通知')
  } catch (e) {
    await refreshWebState()
    ElMessage.error(e?.response?.data?.detail || e?.message || '开启失败')
  } finally {
    webBusy.value = false
  }
}

async function handleWebDisable() {
  webBusy.value = true
  try {
    const sub = await currentSubscription()
    if (sub) {
      await removeWebpushSubscription(sub.endpoint)
      await unsubscribe()
    }
    await refreshWebState()
    await loadWebpushServerState()
    ElMessage.success('已关闭浏览器通知')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '操作失败')
  } finally {
    webBusy.value = false
  }
}

async function handleWebTest() {
  webTesting.value = true
  try {
    const res = await testWebpush()
    ElMessage.success(res.message || '已发送，请查看本机通知')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发送失败')
  } finally {
    webTesting.value = false
  }
}

async function handleInstall() {
  installing.value = true
  try {
    const ok = await triggerInstallPrompt()
    if (ok) {
      ElMessage.success('已添加到桌面')
      canInstall.value = false
    }
  } catch (e) {
    ElMessage.error('安装失败')
  } finally {
    installing.value = false
  }
}

// ---------- 通知设置：Bark ----------
function checkedKey() {
  const raw = barkForm.bark_key.trim()
  const key = cleanKey(raw)
  if (raw && !key) {
    ElMessage.warning('没能从里面认出设备 ID，请从 Bark App 首页复制')
    return null
  }
  if (key && !KEY_PATTERN.test(key)) {
    ElMessage.warning('设备 ID 格式不对，请从 Bark App 首页完整复制')
    return null
  }
  return key
}

async function handleBarkSave() {
  const key = checkedKey()
  if (key === null) return
  barkSaving.value = true
  try {
    const res = await saveBarkSetting(key)
    savedBarkKey.value = key
    barkForm.bark_key = key
    ElMessage.success(res.message || '设置成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    barkSaving.value = false
  }
}

async function handleBarkTest() {
  const key = checkedKey()
  if (key === null) return
  if (!key) return ElMessage.warning('请先填入设备 ID')

  barkTesting.value = true
  try {
    await saveBarkSetting(key)
    savedBarkKey.value = key
    barkForm.bark_key = key
    const res = await testBarkPush()
    ElMessage.success(res.message || '已发送，请查看手机')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '推送失败')
  } finally {
    barkTesting.value = false
  }
}

async function handleBarkUnbind() {
  barkSaving.value = true
  try {
    const res = await saveBarkSetting('')
    savedBarkKey.value = ''
    barkForm.bark_key = ''
    ElMessage.success(res.message || '已解除绑定')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    barkSaving.value = false
  }
}

// ---------- 申请修改 ----------
async function handleSubmit() {
  if (pending.value) return ElMessage.warning('已有一条待审核的申请')
  if (!validate()) return
  const changes = buildChanges()
  if (!Object.keys(changes).length) return ElMessage.warning('没有修改任何内容')

  submitting.value = true
  try {
    await submitChangeRequest(changes)
    ElMessage.success('已提交，等待班委审核')
    formVisible.value = false
    await fetchStudentData()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

// 学生专属数据（基本信息 + 申请记录），域外账号不加载
async function fetchStudentData() {
  if (userStore.isExternal) return
  me.value = await getMyInfo()
  records.value = await getMyChangeRequests()
  resetForm()
}

// 账户设置数据（所有登录用户都加载）
async function fetchAccountData() {
  try {
    await refreshWebState()
    await loadWebpushServerState()
  } catch (e) {
    // 读不到状态不影响使用
  }

  try {
    const data = await getBarkSetting()
    savedBarkKey.value = data.bark_key || ''
    barkForm.bark_key = savedBarkKey.value
  } catch (e) {
    // 读不到 Bark 设置不影响改密码
  }
}

async function fetchData() {
  loading.value = true
  try {
    // 两类数据并行拉
    await Promise.all([fetchStudentData().catch(() => {}), fetchAccountData().catch(() => {})])
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  // 确保登录状态已解析（路由守卫通常已经做了，但以防万一）
  if (!userStore.resolved) await userStore.fetchMe()

  // 安装 PWA 提示
  standalone.value = checkIsStandalone()
  canInstall.value = checkCanInstall()

  await fetchData()
})
</script>

<style scoped>
/* tab 内的分节：外层 page-card 已经给了白底和内边距，这里只要间距 */
.tab-section {
  margin-bottom: 28px;
}

.tab-section:last-child {
  margin-bottom: 0;
}

.page-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.photos-row {
  display: flex;
  gap: 20px;
  margin-top: 4px;
}

.photo-item {
  position: relative;
  width: 200px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #ebeef5;
  cursor: zoom-in;
}

.photo-empty-box {
  cursor: default;
}

.photo-img {
  width: 100%;
  height: 160px;
  object-fit: contain;
  display: block;
  background: #f5f7fa;
  padding: 8px;
  box-sizing: border-box;
}

.photo-placeholder {
  height: 160px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #c0c4cc;
  background: #f5f7fa;
  font-size: 13px;
}

.photo-label {
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  text-align: center;
  padding: 6px 0;
  font-size: 13px;
}

.photos-tip {
  text-align: center;
  font-size: 12px;
  color: #c0c4cc;
  margin: 8px 0 0 0;
  width: 100%;
  max-width: 420px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.section-sub {
  margin: 2px 0 12px;
  font-size: 12px;
  color: #909399;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.desc {
  font-size: 12px;
  color: #909399;
}

.count {
  margin-bottom: 8px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0 0 0;
}

.hint-note {
  color: #909399;
}

.footnote {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #ebeef5;
  line-height: 1.6;
}

.install-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

/* ---------- 办件空间 ---------- */
.workspace-list {
  min-height: 200px;
}

.case-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.case-item {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 16px;
  cursor: pointer;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.case-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}

.case-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.case-title {
  font-size: 15px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 6px;
  line-height: 1.4;
}

.case-meta {
  font-size: 12px;
  color: #909399;
  display: flex;
  gap: 16px;
  line-height: 1.8;
  flex-wrap: wrap;
}

.case-reason {
  margin-top: 6px;
  font-size: 12px;
  color: #f56c6c;
}

.case-actions {
  margin-top: 8px;
  text-align: right;
}

/* 手机适配 */
@media (max-width: 768px) {
  .photos-row {
    flex-wrap: wrap;
  }
  .photo-item {
    width: calc(50% - 10px);
  }

  .case-item {
    padding: 12px;
  }

  .case-meta {
    gap: 12px;
  }
}
</style>
