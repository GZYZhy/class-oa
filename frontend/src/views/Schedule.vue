<template>
  <div class="schedule-page">
    <!-- 顶部工具栏 -->
    <div class="page-card toolbar">
      <div class="week-nav">
        <el-button :icon="ArrowLeft" circle @click="prevWeek" />
        <span class="week-label">
          {{ weekLabel }}<template v-if="weekOfSemester">（第{{ weekOfSemester }}周）</template>
        </span>
        <el-button :icon="ArrowRight" circle @click="nextWeek" />
        <el-button size="small" @click="goToday">今天</el-button>
      </div>
      <div class="actions">
        <el-button v-if="userStore.isCommittee" @click="importDialog.open = true">
          <el-icon><Upload /></el-icon>导入
        </el-button>
        <el-button @click="subscribeDialog.open = true">
          <el-icon><Link /></el-icon>订阅
        </el-button>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>新建日程
        </el-button>
      </div>
    </div>

    <!-- 日历表格 -->
    <div class="page-card calendar-wrapper" v-loading="loading">
      <div class="calendar-grid">
        <!-- 表头 -->
        <div class="cal-header cal-row">
          <div class="cal-time-col"></div>
          <div
            v-for="(day, idx) in weekDays"
            :key="idx"
            class="cal-day-col"
            :class="{ today: day.isToday }"
          >
            <div class="day-weekday">{{ day.weekdayLabel }}</div>
            <div class="day-date">{{ day.md }}</div>
          </div>
        </div>

        <!-- 时间行 + 日程块 overlay：包在同一个定位容器里，
             overlay 的 (0,0) 才正好对齐「首行顶部、时间列右侧」 -->
        <div class="cal-body">
          <div
            v-for="(slot, slotIdx) in timeSlots"
            :key="slot"
            class="cal-row cal-time-row"
            :style="{ height: slotHeight + 'px' }"
          >
            <div class="cal-time-col" :class="{ 'hour-mark': slot.endsWith(':00') }">
              {{ slot }}
            </div>
            <div
              v-for="(day, dayIdx) in weekDays"
              :key="dayIdx"
              class="cal-day-col cal-cell"
              :class="{ 'hour-cell': slot.endsWith(':00') }"
              @click="handleCellClick(day.date, slot)"
            >
              <!-- 日程块渲染用绝对定位，放在一个 overlay 层里 -->
            </div>
          </div>

          <!-- 日程块 overlay（绝对定位；不含时间列，left 百分比才和日期列对齐） -->
          <div class="cal-events-overlay">
            <div
              v-for="evt in positionedEvents"
              :key="evt.key"
              class="cal-event"
              :class="'theme-' + evtTheme(evt.event_type)"
              :style="evt.style"
              @click.stop="openEdit(evt)"
            >
              <div class="evt-title">{{ evt.title }}</div>
              <div v-if="evt.event_type" class="evt-type">{{ evt.event_type }}</div>
              <div v-if="evt.location" class="evt-location">{{ evt.location }}</div>
              <el-icon v-if="evt.notify_enabled" class="evt-bell"><Bell /></el-icon>
            </div>
          </div>
        </div>
      </div>

      <!-- 全天事件区 -->
      <div v-if="allDayEvents.length" class="all-day-section">
        <div class="all-day-label">全天事件</div>
        <div class="all-day-list">
          <div
            v-for="evt in allDayEvents"
            :key="evt.id + '-' + evt.instance_date"
            class="all-day-item"
            :class="'theme-' + evtTheme(evt.event_type)"
            @click="openEdit(evt)"
          >
            <span class="all-day-date">{{ formatDateShort(evt.instance_date) }}</span>
            <span class="all-day-title">{{ evt.title }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建/编辑弹窗 -->
    <el-dialog
      v-model="editDialog.visible"
      :title="editDialog.isEdit ? '编辑日程' : '新建日程'"
      width="480px"
    >
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="标题" required>
          <el-input v-model="editForm.title" maxlength="200" placeholder="请输入日程标题" />
        </el-form-item>
        <el-form-item label="类型">
          <el-input v-model="editForm.event_type" maxlength="20" placeholder="如 课程 / 体育 / 网络课 / 会议 / 活动（可不填）" />
        </el-form-item>
        <el-form-item label="日期" required>
          <el-date-picker
            v-model="editForm.date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
          />
        </el-form-item>
        <el-form-item label="时间" required>
          <el-time-select
            v-model="editForm.start_time"
            :start="'07:00'"
            :step="'00:10'"
            :end="'21:50'"
            placeholder="开始时间"
            style="width: 45%"
          />
          <span style="margin: 0 8px">至</span>
          <el-time-select
            v-model="editForm.end_time"
            :start="'07:10'"
            :step="'00:10'"
            :end="'22:00'"
            placeholder="结束时间"
            style="width: 45%"
          />
        </el-form-item>
        <el-form-item label="地点">
          <el-input v-model="editForm.location" maxlength="200" placeholder="选填" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.description" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
        <el-form-item label="重复">
          <el-radio-group v-model="editForm.repeat_type">
            <el-radio value="none">不重复</el-radio>
            <el-radio value="weekly">每周</el-radio>
            <el-radio value="monthly">每月</el-radio>
            <el-radio value="odd_week">单周</el-radio>
            <el-radio value="even_week">双周</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="editForm.repeat_type !== 'none'" label="结束日期">
          <el-date-picker
            v-model="editForm.repeat_end_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="重复到哪一天"
          />
        </el-form-item>
        <el-form-item label="开启通知">
          <el-switch v-model="editForm.notify_enabled" />
          <span style="margin-left: 12px; color: var(--el-text-color-secondary); font-size: 13px">
            默认关闭，开启后开始前
            <el-input-number
              v-model="editForm.notify_minutes_before"
              :min="1"
              :max="1440"
              size="small"
              :disabled="!editForm.notify_enabled"
              style="width: 100px; margin: 0 4px"
            />
            分钟提醒
          </span>
        </el-form-item>

        <!-- 班委：影响范围 -->
        <el-form-item v-if="userStore.isCommittee" label="影响范围">
          <el-radio-group v-model="editForm.scope_mode">
            <el-radio value="self">仅自己</el-radio>
            <el-radio value="all">全部学生</el-radio>
            <el-radio value="selected">指定学生</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="userStore.isCommittee && editForm.scope_mode === 'selected'" label="选择学生">
          <el-button size="small" @click="studentPicker.open = true">
            已选 {{ selectedStudents.length }} 人
          </el-button>
        </el-form-item>

        <!-- 编辑时的范围选择 -->
        <el-form-item v-if="editDialog.isEdit && editDialog.isRepeat" label="修改范围">
          <el-radio-group v-model="editForm.scope">
            <el-radio value="single">仅本次</el-radio>
            <el-radio value="forward">本次及以后</el-radio>
            <el-radio value="all">全部</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="editDialog.isEdit" type="danger" @click="handleDelete">删除</el-button>
        <span style="flex: 1"></span>
        <el-button @click="editDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 学生选择器（简化版：输入框 + 搜索，后续可优化） -->
    <el-dialog v-model="studentPicker.open" title="选择学生" width="600px">
      <el-input v-model="studentPicker.keyword" placeholder="搜索学生姓名/学号" clearable style="margin-bottom: 12px" />
      <div class="student-picker-list">
        <el-checkbox
          v-for="s in filteredStudents"
          :key="s.id"
          :label="s.id"
          v-model="selectedStudents"
        >
          {{ s.name }}（{{ s.student_no }}）
        </el-checkbox>
      </div>
      <template #footer>
        <el-button @click="studentPicker.open = false">取消</el-button>
        <el-button type="primary" @click="studentPicker.open = false">确定</el-button>
      </template>
    </el-dialog>

    <!-- 导入弹窗 -->
    <el-dialog v-model="importDialog.open" title="导入日程" width="720px">
      <el-steps :active="importStep" finish-status="success" align-center style="margin-bottom: 24px">
        <el-step title="上传文件" />
        <el-step title="确认日程" />
        <el-step title="选择目标" />
      </el-steps>

      <!-- 步骤 1：上传 -->
      <div v-if="importStep === 0" class="import-step">
        <el-upload
          drag
          :auto-upload="false"
          :limit="1"
          accept=".xlsx"
          :on-change="handleImportFile"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">将 .xlsx 文件拖到此处，或<em>点击上传</em></div>
          <template #tip>
            <div class="el-upload__tip">
              支持 10 分钟粒度的周课表格式（多 sheet，每周一张），20MB 以内
            </div>
          </template>
        </el-upload>
      </div>

      <!-- 步骤 2：确认 -->
      <div v-else-if="importStep === 1" class="import-step" v-loading="importLoading">
        <div class="import-summary">
          识别到 <b>{{ importPreview.week_count }}</b> 周、
          <b>{{ importPreview.schedule_count }}</b> 条日程、
          <b>{{ importPreview.all_day_count }}</b> 个全天事件
        </div>
        <div v-if="importPreview.warnings?.length" class="import-warnings">
          <el-alert
            v-for="(w, i) in importPreview.warnings.slice(0, 5)"
            :key="i"
            :title="w"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 8px"
          />
          <div v-if="importPreview.warnings.length > 5" class="more-warn">
            还有 {{ importPreview.warnings.length - 5 }} 条警告...
          </div>
        </div>
        <el-table
          :data="importPreview.items"
          max-height="320"
          size="small"
          @selection-change="handleImportSelect"
          ref="importTableRef"
        >
          <el-table-column type="selection" width="40" />
          <el-table-column prop="title" label="标题" min-width="160" />
          <el-table-column label="星期" width="60">
            <template #default="{ row }">{{ weekdayLabel(row.weekday) }}</template>
          </el-table-column>
          <el-table-column label="时间" width="130">
            <template #default="{ row }">
              <span v-if="!row.all_day">{{ row.start_time }} - {{ row.end_time }}</span>
              <span v-else>全天</span>
            </template>
          </el-table-column>
          <el-table-column prop="location" label="地点" min-width="120" />
          <el-table-column label="重复" width="80">
            <template #default="{ row }">{{ repeatLabel(row.repeat_type) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 步骤 3：目标 -->
      <div v-else-if="importStep === 2" class="import-step">
        <el-form label-width="100px">
          <el-form-item label="批次名称">
            <el-input v-model="importForm.batch_name" maxlength="200" placeholder="给这批日程起个名字" />
          </el-form-item>
          <el-form-item label="导入给">
            <el-radio-group v-model="importForm.target_mode">
              <el-radio value="all">全部学生</el-radio>
              <el-radio value="selected">指定学生</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="importForm.target_mode === 'selected'" label="选择学生">
            <el-button size="small" @click="importStudentPicker.open = true">
              已选 {{ importSelectedStudents.length }} 人
            </el-button>
          </el-form-item>
          <el-form-item label="日程数量">
            <span>{{ importSelectedItems.length }} 条</span>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="importDialog.open = false">取消</el-button>
        <el-button v-if="importStep > 0" @click="importStep--">上一步</el-button>
        <el-button
          v-if="importStep < 2"
          type="primary"
          @click="importNextStep"
          :disabled="importStep === 0 && !importFile"
          :loading="importLoading"
        >
          下一步
        </el-button>
        <el-button
          v-if="importStep === 2"
          type="primary"
          @click="handleImportConfirm"
          :loading="importSubmitting"
        >
          确认导入
        </el-button>
      </template>
    </el-dialog>

    <!-- 导入学生选择器 -->
    <el-dialog v-model="importStudentPicker.open" title="选择学生" width="600px">
      <el-input v-model="importStudentPicker.keyword" placeholder="搜索" clearable style="margin-bottom: 12px" />
      <div class="student-picker-list">
        <el-checkbox
          v-for="s in importFilteredStudents"
          :key="s.id"
          :label="s.id"
          v-model="importSelectedStudents"
        >
          {{ s.name }}（{{ s.student_no }}）
        </el-checkbox>
      </div>
      <template #footer>
        <el-button @click="importStudentPicker.open = false">确定</el-button>
      </template>
    </el-dialog>

    <!-- 订阅弹窗 -->
    <el-dialog v-model="subscribeDialog.open" title="日历订阅" width="520px">
      <div v-loading="subscribeLoading">
        <div class="subscribe-section">
          <div class="subscribe-label">你的私有订阅链接</div>
          <div class="subscribe-url-row">
            <el-input :value="subscribeUrl" readonly />
            <el-button @click="copySubscribeUrl">
              <el-icon><CopyDocument /></el-icon>复制
            </el-button>
          </div>
          <div class="subscribe-tip">
            <el-icon><Warning /></el-icon>
            链接包含你的私人令牌，请勿分享给他人
          </div>
        </div>

        <el-divider />

        <div class="subscribe-section">
          <el-button type="danger" :icon="Refresh" @click="handleResetToken">
            重置订阅令牌
          </el-button>
          <div class="subscribe-tip danger">
            重置后旧链接立即失效，需要在所有日历客户端重新添加
          </div>
        </div>

        <el-divider />

        <div class="subscribe-section">
          <div class="subscribe-label">如何添加到日历</div>
          <div class="subscribe-guide">
            <p><b>📱 iOS / 苹果日历</b></p>
            <p>设置 → 日历 → 账户 → 添加账户 → 其他 → 添加已订阅的日历 → 粘贴链接</p>
            <p><b>🖥️ Mac 日历</b></p>
            <p>文件 → 新建日历订阅 → 粘贴链接</p>
            <p><b>📅 Google 日历</b></p>
            <p>其他日历 → 通过 URL 添加 → 粘贴链接</p>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useUserStore } from '@/store/user'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft, ArrowRight, Plus, Upload, Link, Bell,
  UploadFilled, Refresh, Warning, CopyDocument
} from '@element-plus/icons-vue'
import {
  listSchedules, createSchedule, updateSchedule, deleteSchedule,
  importPreview as apiImportPreview, importConfirm as apiImportConfirm,
  getIcalToken, resetIcalToken, getSemesterInfo
} from '@/api/schedule'
import { getStudentList } from '@/api/student'
import { errText } from '@/utils/request'

const userStore = useUserStore()

// ---------- 时间常量 ----------
const slotHeight = 28  // 每个 10 分钟格子的高度（px）
const startHour = 7
const endHour = 22  // 不含

// 生成 10 分钟粒度的时间槽
const timeSlots = computed(() => {
  const slots = []
  for (let h = startHour; h < endHour; h++) {
    for (let m = 0; m < 60; m += 10) {
      slots.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)
    }
  }
  return slots
})

// ---------- 周导航 ----------
const currentMonday = ref(getMonday(new Date()))

function getMonday(d) {
  const date = new Date(d)
  const day = date.getDay() || 7  // 周日=7
  date.setDate(date.getDate() - day + 1)
  date.setHours(0, 0, 0, 0)
  return date
}

const weekDays = computed(() => {
  const days = []
  const weekdays = ['一', '二', '三', '四', '五', '六', '日']
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  for (let i = 0; i < 7; i++) {
    const d = new Date(currentMonday.value)
    d.setDate(d.getDate() + i)
    days.push({
      date: formatDate(d),
      month: d.getMonth() + 1,
      day: d.getDate(),
      // 表头就写「10.08」。别用 date（那是 2026-10-08 完整串，
      // 和 month 拼起来会渲染成「10/2026-10-08」，踩过）
      md: `${d.getMonth() + 1}.${String(d.getDate()).padStart(2, '0')}`,
      weekday: i + 1,
      weekdayLabel: '周' + weekdays[i],
      isToday: d.getTime() === today.getTime()
    })
  }
  return days
})

const weekLabel = computed(() => {
  const start = weekDays.value[0]
  const end = weekDays.value[6]
  if (start.month === end.month) {
    return `${start.month}月${start.day}日 - ${end.day}日`
  }
  return `${start.month}月${start.day}日 - ${end.month}月${end.day}日`
})

// 学期第 1 周的周一，由后端给（课表导入时按表名「第N周」折算出来的）。
// 千万别在前端按「9 月 1 日所在周」自己估：估出来比表名早两周，
// 表名「第4周」的课在页面上会显示成第 6 周（踩过一次）。
const semesterFirstMonday = ref(null)

async function loadSemesterInfo() {
  try {
    const data = await getSemesterInfo()
    if (!data.week_start) {
      semesterFirstMonday.value = null
      return
    }
    // 手动拼日期：new Date('2026-09-14') 是按 UTC 解析的，换个时区就差一天
    const [y, m, d] = data.week_start.split('-').map(Number)
    semesterFirstMonday.value = new Date(y, m - 1, d)
  } catch (e) {
    // 拿不到只是不显示周次，别影响看日程
    semesterFirstMonday.value = null
  }
}

const weekOfSemester = computed(() => {
  if (!semesterFirstMonday.value) return null
  const diffDays = Math.round((currentMonday.value - semesterFirstMonday.value) / 86400000)
  const week = Math.floor(diffDays / 7) + 1
  // 学期外的周（寒暑假）不显示，免得冒出「第 -3 周」
  return week >= 1 ? week : null
})

function prevWeek() {
  const d = new Date(currentMonday.value)
  d.setDate(d.getDate() - 7)
  currentMonday.value = d
}

function nextWeek() {
  const d = new Date(currentMonday.value)
  d.setDate(d.getDate() + 7)
  currentMonday.value = d
}

function goToday() {
  currentMonday.value = getMonday(new Date())
}

function formatDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function formatDateShort(dateStr) {
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

// ---------- 数据加载 ----------
const loading = ref(false)
const schedules = ref([])

async function loadSchedules() {
  if (!weekDays.value.length) return
  loading.value = true
  try {
    const start = weekDays.value[0].date
    const end = weekDays.value[6].date
    const data = await listSchedules(start, end)
    schedules.value = data
  } catch (e) {
    // 必须自己弹：request.js 的响应拦截器只打 console，不弹提示。
    // 不弹的话加载失败和「这周真没日程」长得一模一样 —— 都是空表格，
    // 用户只会以为导入没生效（踩过一次）。
    schedules.value = []
    ElMessage.error(errText(e, '日程加载失败'))
  } finally {
    loading.value = false
  }
}

watch(currentMonday, () => {
  loadSchedules()
})

onMounted(() => {
  loadSchedules()
  loadSemesterInfo()
  if (userStore.isCommittee) {
    loadStudents()
  }
})

// ---------- 定位日程块 ----------
const positionedEvents = computed(() => {
  const events = []
  const slotsPerHour = 6
  const startSlotIdx = 0  // 07:00 是第 0 个

  for (const evt of schedules.value) {
    if (evt.all_day) continue
    const dayIdx = new Date(evt.instance_date).getDay() || 7  // 周一=0 不对，要调整
    // 调整：周一为 0（数组下标）
    const dayIndex = (new Date(evt.instance_date).getDay() + 6) % 7

    // 计算起始和结束的 slot 索引
    const startStr = evt.start_time.split('T')[1]?.substring(0, 5) || '00:00'
    const endStr = evt.end_time.split('T')[1]?.substring(0, 5) || '00:00'
    const [sh, sm] = startStr.split(':').map(Number)
    const [eh, em] = endStr.split(':').map(Number)
    const startIdx = (sh - startHour) * slotsPerHour + Math.floor(sm / 10)
    const endIdx = (eh - startHour) * slotsPerHour + Math.floor(em / 10)

    if (startIdx < 0 || endIdx > timeSlots.value.length) continue

    const top = startIdx * slotHeight
    const height = (endIdx - startIdx) * slotHeight - 2  // -2 留间隙

    events.push({
      ...evt,
      key: `${evt.id}-${evt.instance_date}`,
      style: {
        top: top + 'px',
        height: Math.max(height, 20) + 'px',
        left: `calc(${dayIndex * (100 / 7)}% + 4px)`,
        width: `calc(${100 / 7}% - 8px)`,
      }
    })
  }
  return events
})

const allDayEvents = computed(() => {
  return schedules.value.filter(e => e.all_day)
    .sort((a, b) => new Date(a.instance_date) - new Date(b.instance_date))
})

// ---------- 点击格子新建 ----------
function handleCellClick(date, time) {
  openCreate(date, time)
}

// ---------- 新建/编辑弹窗 ----------
const editDialog = ref({
  visible: false,
  isEdit: false,
  isRepeat: false,
  currentId: null,
  currentInstanceDate: null,
})

const defaultForm = () => ({
  title: '',
  event_type: '',
  date: formatDate(new Date()),
  start_time: '08:00',
  end_time: '09:00',
  location: '',
  description: '',
  repeat_type: 'none',
  repeat_end_date: '',
  notify_enabled: false,
  notify_minutes_before: 10,
  scope_mode: 'self',  // self / all / selected
  scope: 'all',        // 编辑范围
})

const editForm = ref(defaultForm())
const saving = ref(false)

function openCreate(date = null, time = null) {
  editForm.value = defaultForm()
  if (date) editForm.value.date = date
  if (time) {
    editForm.value.start_time = time
    // 默认 1 小时
    const [h, m] = time.split(':').map(Number)
    let endH = h + 1
    let endM = m
    if (endH >= endHour) { endH = endHour - 1; endM = 50 }
    editForm.value.end_time = `${String(endH).padStart(2, '0')}:${String(endM).padStart(2, '0')}`
  }
  editDialog.value = {
    visible: true,
    isEdit: false,
    isRepeat: false,
    currentId: null,
    currentInstanceDate: editForm.value.date,
  }
}

function openEdit(evt) {
  editForm.value = {
    title: evt.title,
    event_type: evt.event_type || '',
    date: evt.instance_date,
    start_time: evt.start_time.split('T')[1]?.substring(0, 5) || '08:00',
    end_time: evt.end_time.split('T')[1]?.substring(0, 5) || '09:00',
    location: evt.location || '',
    description: evt.description || '',
    repeat_type: evt.repeat_type,
    repeat_end_date: evt.repeat_end_date || '',
    notify_enabled: evt.notify_enabled,
    notify_minutes_before: evt.notify_minutes_before || 10,
    scope_mode: 'self',
    scope: 'all',
  }
  editDialog.value = {
    visible: true,
    isEdit: true,
    isRepeat: evt.repeat_type !== 'none',
    currentId: evt.id,
    currentInstanceDate: evt.instance_date,
  }
}

async function handleSave() {
  if (!editForm.value.title.trim()) {
    ElMessage.warning('请输入日程标题')
    return
  }
  if (editForm.value.start_time >= editForm.value.end_time) {
    ElMessage.warning('结束时间必须晚于开始时间')
    return
  }
  if (editForm.value.repeat_type !== 'none' && !editForm.value.repeat_end_date) {
    ElMessage.warning('请设置重复结束日期')
    return
  }

  saving.value = true
  try {
    const data = {
      title: editForm.value.title.trim(),
      event_type: editForm.value.event_type,
      location: editForm.value.location,
      description: editForm.value.description,
      start_time: `${editForm.value.date}T${editForm.value.start_time}:00`,
      end_time: `${editForm.value.date}T${editForm.value.end_time}:00`,
      all_day: false,
      repeat_type: editForm.value.repeat_type,
      repeat_end_date: editForm.value.repeat_end_date || null,
      notify_enabled: editForm.value.notify_enabled,
      notify_minutes_before: editForm.value.notify_minutes_before,
      target_all: userStore.isCommittee && editForm.value.scope_mode === 'all',
      target_student_ids: userStore.isCommittee && editForm.value.scope_mode === 'selected'
        ? selectedStudents.value : [],
    }

    if (editDialog.value.isEdit) {
      await updateSchedule(
        editDialog.value.currentId,
        editDialog.value.currentInstanceDate,
        {
          title: data.title,
          event_type: data.event_type,
          location: data.location,
          description: data.description,
          start_time: data.start_time,
          end_time: data.end_time,
          repeat_type: data.repeat_type,
          repeat_end_date: data.repeat_end_date,
          notify_enabled: data.notify_enabled,
          notify_minutes_before: data.notify_minutes_before,
          scope: editForm.value.scope,
        }
      )
      ElMessage.success('已更新')
    } else {
      await createSchedule(data)
      ElMessage.success('已创建')
    }
    editDialog.value.visible = false
    loadSchedules()
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  try {
    await ElMessageBox.confirm(
      editDialog.value.isRepeat ? '确定删除？可选范围：仅本次 / 本次及以后 / 全部' : '确定删除此日程？',
      '删除确认',
      { type: 'warning' }
    )
  } catch { return }

  try {
    await deleteSchedule(
      editDialog.value.currentId,
      editDialog.value.currentInstanceDate,
      editForm.value.scope
    )
    ElMessage.success('已删除')
    editDialog.value.visible = false
    loadSchedules()
  } catch {}
}

// ---------- 学生列表（班委用） ----------
const allStudents = ref([])
const selectedStudents = ref([])
const studentPicker = ref({ open: false, keyword: '' })

async function loadStudents() {
  try {
    const { items } = await getStudentList({ page: 1, page_size: 500 })
    allStudents.value = items
  } catch {}
}

const filteredStudents = computed(() => {
  const kw = studentPicker.value.keyword?.trim()
  if (!kw) return allStudents.value
  return allStudents.value.filter(s =>
    s.name.includes(kw) || s.student_no.includes(kw)
  )
})

// ---------- 导入 ----------
const importDialog = ref({ open: false })
const importStep = ref(0)
const importFile = ref(null)
const importLoading = ref(false)
const importSubmitting = ref(false)
const importPreview = ref({ items: [], week_count: 0, schedule_count: 0, all_day_count: 0, warnings: [] })
const importToken = ref('')
const importSelectedIndices = ref([])
const importSelectedItems = computed(() => {
  if (!importSelectedIndices.value.length) return importPreview.value.items
  return importSelectedIndices.value.map(i => importPreview.value.items[i]).filter(Boolean)
})

const importForm = ref({
  batch_name: '',
  target_mode: 'all',
})

const importStudentPicker = ref({ open: false, keyword: '' })
const importSelectedStudents = ref([])

const importFilteredStudents = computed(() => {
  const kw = importStudentPicker.value.keyword?.trim()
  if (!kw) return allStudents.value
  return allStudents.value.filter(s =>
    s.name.includes(kw) || s.student_no.includes(kw)
  )
})

function handleImportFile(file) {
  importFile.value = file
}

async function importNextStep() {
  if (importStep.value === 0) {
    // 上传 → 预览
    importLoading.value = true
    try {
      const data = await apiImportPreview(importFile.value.raw)
      importPreview.value = data
      importToken.value = data.token
      importStep.value = 1
      nextTick(() => {
        // 默认全选
        const table = document.querySelector('.el-table')
        // 简单处理：不操作 DOM，selectedIndices 为空表示全选
        importSelectedIndices.value = []
      })
    } finally {
      importLoading.value = false
    }
  } else if (importStep.value === 1) {
    // 预览 → 目标
    importStep.value = 2
  }
}

function handleImportSelect(selection) {
  // 直接用对象引用定位。不能按「标题+时间+星期」反查：忠实导入之后
  // 同名的条目会大量重复（「国庆放假」一周里有 7 条），反查会全部命中最前面那条，
  // 勾 3 行实际只提交同一个下标
  const all = importPreview.value.items
  importSelectedIndices.value = selection.map(item => all.indexOf(item)).filter(i => i >= 0)
}

async function handleImportConfirm() {
  if (importForm.value.target_mode === 'selected' && importSelectedStudents.value.length === 0) {
    ElMessage.warning('请选择目标学生')
    return
  }

  importSubmitting.value = true
  try {
    await apiImportConfirm({
      token: importToken.value,
      batch_name: importForm.value.batch_name || '导入日程',
      target_all: importForm.value.target_mode === 'all',
      target_student_ids: importSelectedStudents.value,
      selected_indices: importSelectedIndices.value,
    })
    ElMessage.success('导入成功')
    // 跳到导入内容的第一周。不跳的话页面还停在原来的周，而课表是从 9 月开学
    // 那一周开始的，用户看不到刚导进来的课，会以为导入没生效（踩过一次）
    const first = importPreview.value.items.find(it => it.start_date)
    if (first) currentMonday.value = getMonday(new Date(first.start_date))
    importDialog.value.open = false
    importStep.value = 0
    importFile.value = null
    loadSchedules()
  } finally {
    importSubmitting.value = false
  }
}

function weekdayLabel(w) {
  return ['', '一', '二', '三', '四', '五', '六', '日'][w] || ''
}

function repeatLabel(t) {
  const map = { none: '不重复', weekly: '每周', monthly: '每月', odd_week: '单周', even_week: '双周' }
  return map[t] || t
}

// 事件类型 → 配色主题（CSS 里的 .theme-*）。
// 前三种是课表解析出来的（见后端 schedule_import_service 的单元格解析），
// 会议、活动是学生自己新建日程时常用的两种。
// Element 的调色板一共就五个色位，这里正好用完，所以「活动」和认不出来的
// 类型同为灰 —— 想再区分就得自己造色值，那样深色模式也得跟着手写一份
const TYPE_THEME = {
  '课程': 'primary',
  '体育': 'success',
  '网络课': 'warning',
  '会议': 'danger',
  '活动': 'info'
}

function evtTheme(type) {
  return TYPE_THEME[type] || 'info'
}

// ---------- 订阅 ----------
const subscribeDialog = ref({ open: false })
const subscribeLoading = ref(false)
const subscribeUrl = ref('')

watch(() => subscribeDialog.value.open, async (val) => {
  if (val) {
    subscribeLoading.value = true
    try {
      const data = await getIcalToken()
      subscribeUrl.value = data.url
    } finally {
      subscribeLoading.value = false
    }
  }
})

function copySubscribeUrl() {
  navigator.clipboard.writeText(subscribeUrl.value)
    .then(() => ElMessage.success('已复制到剪贴板'))
    .catch(() => ElMessage.error('复制失败，请手动复制'))
}

async function handleResetToken() {
  try {
    await ElMessageBox.confirm(
      '确定要重置订阅令牌吗？旧链接将立即失效，需要在所有日历客户端重新添加。',
      '重置确认',
      { type: 'warning' }
    )
  } catch { return }

  try {
    const data = await resetIcalToken()
    subscribeUrl.value = data.url
    ElMessage.success('已重置')
  } catch {}
}
</script>

<style scoped>
.schedule-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.week-nav {
  display: flex;
  align-items: center;
  gap: 12px;
}

.week-label {
  font-size: 16px;
  font-weight: 600;
  min-width: 180px;
  text-align: center;
}

.actions {
  display: flex;
  gap: 8px;
}

/* 日历网格 */
.calendar-wrapper {
  overflow: hidden;
  padding: 0;
}

.calendar-grid {
  position: relative;
  display: flex;
  flex-direction: column;
}

.cal-row {
  display: flex;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.cal-time-col {
  width: 60px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  text-align: center;
  padding-top: 2px;
  border-right: 1px solid var(--el-border-color-lighter);
}

.cal-time-col.hour-mark {
  color: var(--el-text-color-primary);
  font-weight: 500;
}

.cal-day-col {
  flex: 1;
  min-width: 0;
  border-right: 1px solid var(--el-border-color-lighter);
}

.cal-day-col:last-child {
  border-right: none;
}

/* 表头 */
.cal-header {
  background: var(--el-fill-color-light);
  position: sticky;
  top: 0;
  z-index: 2;
  font-size: 13px;
}

.cal-header .cal-day-col {
  padding: 8px 0;
  text-align: center;
}

.cal-header .cal-time-col {
  padding-top: 8px;
}

.day-weekday {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.day-date {
  font-size: 12px;
  font-weight: 500;
  margin-top: 2px;
}

.cal-day-col.today .day-date {
  color: var(--el-color-primary);
}

/* 时间行区域：日程块 overlay 的定位参照 */
.cal-body {
  position: relative;
}

/* 时间行 */
.cal-time-row {
  position: relative;
}

.cal-cell {
  cursor: pointer;
  transition: background 0.15s;
}

.cal-cell:hover {
  background: var(--el-fill-color-light);
}

.cal-cell.hour-cell {
  border-top: 1px solid var(--el-border-color-lighter);
}

/* 日程块 overlay */
.cal-events-overlay {
  position: absolute;
  top: 0;
  left: 60px;   /* 让开时间列：overlay 的 0% 与周一列左边对齐 */
  right: 0;
  bottom: 0;
  pointer-events: none;
}

/* 按事件类型涂色。--evt 是主色、--evt-bg 是同色系的浅底，
   一律取 Element 的调色板变量，深色模式跟着自动切。
   只认常见的几种类型，其余的（包括用户自己填的、以及没填类型的）
   走默认灰 —— 不写死 switch，也就不会出现「这个类型没颜色」 */
.theme-primary {
  --evt: var(--el-color-primary);
  --evt-bg: var(--el-color-primary-light-8);
}

.theme-success {
  --evt: var(--el-color-success);
  --evt-bg: var(--el-color-success-light-8);
}

.theme-warning {
  --evt: var(--el-color-warning);
  --evt-bg: var(--el-color-warning-light-8);
}

.theme-danger {
  --evt: var(--el-color-danger);
  --evt-bg: var(--el-color-danger-light-8);
}

.theme-info {
  --evt: var(--el-color-info);
  --evt-bg: var(--el-color-info-light-8);
}

.cal-event {
  position: absolute;
  background: var(--evt-bg, var(--el-color-info-light-8));
  border-left: 3px solid var(--evt, var(--el-color-info));
  border-radius: 3px;
  padding: 2px 6px;
  font-size: 12px;
  cursor: pointer;
  pointer-events: auto;
  overflow: hidden;
  transition: box-shadow 0.15s;
  box-sizing: border-box;
}

.cal-event:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  z-index: 10;
}

.evt-title {
  font-weight: 600;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evt-type,
.evt-location {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evt-bell {
  position: absolute;
  top: 2px;
  right: 4px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

/* 全天事件区 */
.all-day-section {
  border-top: 2px solid var(--el-border-color);
  padding: 12px 16px;
  display: flex;
  gap: 12px;
}

.all-day-label {
  flex-shrink: 0;
  width: 60px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  padding-top: 2px;
}

.all-day-list {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.all-day-item {
  background: var(--evt-bg, var(--el-color-info-light-8));
  border-left: 3px solid var(--evt, var(--el-color-info));
  padding: 4px 10px;
  border-radius: 3px;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
}

.all-day-date {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

/* 导入 */
.import-step {
  min-height: 200px;
}

.import-summary {
  font-size: 14px;
  margin-bottom: 12px;
  color: var(--el-text-color-primary);
}

.import-summary b {
  color: var(--el-color-primary);
  font-size: 16px;
  margin: 0 2px;
}

.import-warnings {
  margin-bottom: 12px;
}

.more-warn {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-align: center;
  margin-top: 4px;
}

/* 学生选择器 */
.student-picker-list {
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

/* 订阅 */
.subscribe-section {
  margin-bottom: 8px;
}

.subscribe-label {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

.subscribe-url-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.subscribe-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
}

.subscribe-tip.danger {
  color: var(--el-color-danger);
  margin-top: 8px;
}

.subscribe-guide {
  font-size: 13px;
  line-height: 1.8;
  color: var(--el-text-color-regular);
}

.subscribe-guide p {
  margin: 4px 0;
}
</style>
