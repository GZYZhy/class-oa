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
        <!-- 这里必须写成 openCreate()：裸写 openCreate 会让 Vue 把 MouseEvent 当成
             第一个参数（date）塞进 editForm.date / end_date，保存时 daysInRange 里
             就报 "(endStr || startStr).split is not a function" -->
        <el-button type="primary" @click="openCreate()">
          <el-icon><Plus /></el-icon>新建日程
        </el-button>
      </div>
    </div>

    <!-- 日历表格 -->
    <div class="page-card calendar-wrapper" v-loading="loading">
      <div class="calendar-grid">
        <!-- 表头 -->
        <div class="cal-header cal-row">
          <!-- 时间列顶上那一格本来是空的：放个当前时间（hh:mm），一眼看得出现在几点 -->
          <div class="cal-time-col">
            <div class="now-clock-label">当前时间</div>
            <div class="now-clock">{{ nowClock }}</div>
          </div>
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

        <!-- 全天事件行：紧跟表头，和下面一样按 7 个格子组织。
             格线由那 7 个空的 .cal-day-col 画，事件本身绝对定位跨列铺开，
             所以跨天的（导入时写成横向合并、或逐列重复写同一段文字）是连着的
             一条。高度随条数增长，见 allDayHeight -->
        <div class="cal-row cal-allday" :style="{ minHeight: allDayHeight }">
          <div class="cal-time-col">全天</div>
          <div v-for="(day, idx) in weekDays" :key="idx" class="cal-day-col"></div>
          <div class="cal-allday-overlay">
            <div
              v-for="bar in allDayBars"
              :key="bar.key"
              class="all-day-item"
              :class="'theme-' + evtTheme(bar.evt.event_type)"
              :style="bar.style"
              @click.stop="openEdit(bar.evt, bar.evts)"
            >
              <span class="all-day-title">{{ bar.evt.title }}</span>
            </div>
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
        <el-form-item :label="editForm.all_day ? '开始日期' : '日期'" required>
          <el-date-picker
            v-model="editForm.date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
          />
        </el-form-item>
        <el-form-item label="全天">
          <el-switch v-model="editForm.all_day" />
          <span style="margin-left: 12px; color: var(--el-text-color-secondary); font-size: 13px">
            只要日期，不设起止时刻
          </span>
        </el-form-item>
        <!-- 全天事件给「起止日期」（跨天就是日历上连着的一条），普通的才要时刻 -->
        <el-form-item v-if="editForm.all_day" label="结束日期">
          <el-date-picker
            v-model="editForm.end_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="和开始同一天"
          />
        </el-form-item>
        <el-form-item v-else label="时间" required>
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
        <!-- 标签叫「重复到」而不是「结束日期」：全天事件那一栏也叫结束日期，
             两个挨着放会分不清哪个是哪个 -->
        <el-form-item v-if="editForm.repeat_type !== 'none'" label="重复到">
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

        <!-- 班委：影响范围（只在新建时有意义；编辑时改由下面那栏决定发给谁） -->
        <el-form-item v-if="userStore.isCommittee && !editDialog.isEdit" label="影响范围">
          <el-radio-group v-model="editForm.scope_mode">
            <el-radio value="self">仅自己</el-radio>
            <el-radio value="all">全部学生</el-radio>
            <el-radio value="selected">指定学生</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item
          v-if="userStore.isCommittee && !editDialog.isEdit && editForm.scope_mode === 'selected'"
          label="选择学生"
        >
          <el-button size="small" @click="studentPicker.open = true">
            已选 {{ selectedStudents.length }} 人
          </el-button>
        </el-form-item>

        <!--
          编辑时的范围选择。跨天的全天事件（一天一条，日历上是一根条）不显示：
          那一整条是当作一件事改的（保存和删除都是整条处理），摆出「仅本次」却
          整条一起改，等于骗人
        -->
        <el-form-item v-if="editDialog.isEdit && editDialog.isRepeat && !isMultiDayBar" label="修改范围">
          <el-radio-group v-model="editForm.scope">
            <el-radio value="single">仅本次</el-radio>
            <el-radio value="forward">本次及以后</el-radio>
            <el-radio value="all">全部</el-radio>
          </el-radio-group>
        </el-form-item>

        <!--
          分配出去的日程（shareCount > 1）才有这一栏。个人日程、以及别人发给
          自己的那份都是 1，不显示 —— 后者本来也没资格改到别人表里
        -->
        <el-form-item v-if="editDialog.isEdit && editDialog.shareCount > 1" label="改谁的表">
          <el-radio-group v-model="editForm.share">
            <el-radio :value="true">所有人的（{{ editDialog.shareCount }} 人）</el-radio>
            <el-radio :value="false">仅我自己的</el-radio>
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
    <!-- destroy-on-close：关掉就把 el-upload 一起销毁，下次打开是干净的实例。
         它内部那份文件列表不销毁，配上 :limit="1" 会把新选的文件直接吞掉 -->
    <el-dialog
      v-model="importDialog.open"
      title="导入日程"
      width="720px"
      destroy-on-close
      @closed="resetImport"
    >
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
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
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
import { daysInRange } from '@/utils/schedule'
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

// 表头角上那个时钟。30 秒一跳就够：分钟数最多晚半分钟才翻，不用每秒重渲染整张表
const now = ref(new Date())
const nowClock = computed(() => {
  const h = String(now.value.getHours()).padStart(2, '0')
  const m = String(now.value.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
})
let clockTimer = null

onMounted(() => {
  loadSchedules()
  loadSemesterInfo()
  if (userStore.isCommittee) {
    loadStudents()
  }
  clockTimer = setInterval(() => { now.value = new Date() }, 30000)
})

onUnmounted(() => clearInterval(clockTimer))

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

// ---------- 全天事件：排一行，按格子定位，跨天的连成一条 ----------
//
// 导入的课表里，一个跨天事件有两种写法：横向合并（B5:D5 一格）、或者在它覆盖
// 的每一天的列里重复写同一段文字。后端两种都摊成「一天一条」（模型里没有
// 「跨天日程」这个概念），所以这里再把相邻几天、标题相同的那几条合回一条 ——
// 两种写法在页面上都是连着的一条。
const allDayBars = computed(() => {
  const dayIdx = {}
  weekDays.value.forEach((d, i) => { dayIdx[d.date] = i })

  // 先按标题归拢，每条记住落在第几列。同一天出现两次同名事件时，下面按顺序
  // 逐个消费，两条都会画出来，不会少一条
  const byTitle = new Map()
  for (const evt of schedules.value) {
    if (!evt.all_day) continue
    const i = dayIdx[evt.instance_date]
    if (i === undefined) continue   // 不在本周（查询就是按周取的，到不了这）
    if (!byTitle.has(evt.title)) byTitle.set(evt.title, [])
    byTitle.get(evt.title).push({ i, evt })
  }

  const bars = []
  for (const list of byTitle.values()) {
    list.sort((a, b) => a.i - b.i)
    let run = [list[0]]
    for (let k = 1; k <= list.length; k++) {
      // 断开：下一条不是紧挨着的下一天（k === list.length 是收尾）
      if (k === list.length || list[k].i !== list[k - 1].i + 1) {
        bars.push({
          start: run[0].i,
          end: run[run.length - 1].i,
          evt: run[0].evt,
          evts: run.map(r => r.evt)   // 这根条上的每一天，编辑和删除要整条处理
        })
        run = k < list.length ? [list[k]] : []
      } else {
        run.push(list[k])
      }
    }
  }

  // 贪心分行：同一列上撞车了才需要第二行。占满一周的「国庆放假」下面再放
  // 「收假返校」就靠这个错开
  bars.sort((a, b) => a.start - b.start || b.end - a.end)
  const lineEnds = []
  for (const bar of bars) {
    let li = lineEnds.findIndex(end => end < bar.start)
    if (li === -1) {
      li = lineEnds.length
      lineEnds.push(bar.end)
    } else {
      lineEnds[li] = bar.end
    }
    bar.line = li
    bar.key = `${bar.evt.id}-${bar.start}-${bar.end}`
    bar.style = {
      top: `${bar.line * 24 + 3}px`,
      left: `calc(${(bar.start * 100) / 7}% + 3px)`,
      width: `calc(${((bar.end - bar.start + 1) * 100) / 7}% - 6px)`
    }
  }
  return bars
})

// 行高得跟着行数走：里面是绝对定位，撑不起父容器的高度。
// 一条都没有时也留出一行，免得切周的时候整块日历上下跳
const allDayHeight = computed(() => {
  const lines = allDayBars.value.reduce((m, b) => Math.max(m, b.line + 1), 0)
  return `${Math.max(lines, 1) * 24 + 6}px`
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
  records: [],   // 编辑时这根条上的所有天（全天事件才可能不止一条）
  shareCount: 1, // 这条日程在几个学生的表里；>1 才有「改谁的表」这一栏
  shareFrom: null, // 沿用分组用：新添的全天天数按它取目标学生
})

const defaultForm = () => ({
  title: '',
  event_type: '',
  date: formatDate(new Date()),
  end_date: '',
  start_time: '08:00',
  end_time: '09:00',
  all_day: false,
  location: '',
  description: '',
  repeat_type: 'none',
  repeat_end_date: '',
  notify_enabled: false,
  notify_minutes_before: 10,
  scope_mode: 'self',  // self / all / selected
  scope: 'all',        // 编辑范围
  share: true,         // 编辑分配出去的日程时，默认改所有人的表
})

const editForm = ref(defaultForm())
const saving = ref(false)

function openCreate(date = null, time = null) {
  editForm.value = defaultForm()
  if (date) {
    editForm.value.date = date
    editForm.value.end_date = date   // 打开「全天」时先当单天，要跨天再往后拖
  }
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
    records: [],
    shareCount: 1,
    shareFrom: null,
  }
}

function openEdit(evt, records = null) {
  const allDay = !!evt.all_day
  // 全天事件在库里是一天一条（导入的跨天事件、自己新建跨天的都是这么存的），
  // 日历上一根条可能压着好几条。传进来就按一整条来编辑，见 allDayBars
  const run = records?.length ? records : [evt]
  editForm.value = {
    title: evt.title,
    event_type: evt.event_type || '',
    date: run[0].instance_date,
    end_date: run[run.length - 1].instance_date,
    // 全天事件库里存的时刻是 00:00–23:59，直接填进时间框会落在可选范围外
    // （框里是空的）。关掉「全天」时给个正常的上课时间
    start_time: allDay ? '08:00' : (evt.start_time.split('T')[1]?.substring(0, 5) || '08:00'),
    end_time: allDay ? '09:00' : (evt.end_time.split('T')[1]?.substring(0, 5) || '09:00'),
    all_day: allDay,
    location: evt.location || '',
    description: evt.description || '',
    repeat_type: evt.repeat_type,
    repeat_end_date: evt.repeat_end_date || '',
    notify_enabled: evt.notify_enabled,
    notify_minutes_before: evt.notify_minutes_before || 10,
    scope_mode: 'self',
    scope: 'all',
    share: true,   // 默认「所有人的」，要只改自己那份得手动改
  }
  editDialog.value = {
    visible: true,
    isEdit: true,
    isRepeat: evt.repeat_type !== 'none',
    currentId: evt.id,
    currentInstanceDate: evt.instance_date,
    records: run,
    shareCount: evt.share_count || 1,
    shareFrom: run[0].id,
  }
}

// 表单里那些与「有没有时刻」无关的字段
function formFields() {
  const form = editForm.value
  return {
    title: form.title.trim(),
    event_type: form.event_type,
    location: form.location,
    description: form.description,
    repeat_type: form.repeat_type,
    repeat_end_date: form.repeat_end_date || null,
    notify_enabled: form.notify_enabled,
    notify_minutes_before: form.notify_minutes_before,
  }
}

// 班委的分配范围（普通学生传了后端也会忽略）
function targetFields() {
  const form = editForm.value
  return {
    target_all: userStore.isCommittee && form.scope_mode === 'all',
    target_student_ids: userStore.isCommittee && form.scope_mode === 'selected'
      ? selectedStudents.value : [],
  }
}

// 这次改动要不要一并改掉别人的表。只有自己分配出去的日程（shareCount > 1）才有
// 这一栏；没有这一栏时一律不带 share，免得给个人日程白带个参数
function shareEnabled() {
  return editDialog.value.shareCount > 1 && editForm.value.share
}

// 日历上这根条压着不止一天（跨天的全天事件，库里是一天一条）
const isMultiDayBar = computed(() => (editDialog.value.records || []).length > 1)

// 全天事件在库里是「一天一条」：模型里没有跨天日程，导入的跨天事件也是这么摊的
// （见后端 schedule_import_service），页面上再按相邻同标题合回一条（allDayBars）。
// 所以「起止日期」建的时候要摊开，编辑的时候要跟原来那几条对一遍：
// 日期还在的就地改，新添的日期建出来，去掉了的日期删掉
//
// 返回 false 表示用户在选择器里点了取消，这次保存整个作废（别关弹窗、别弹成功）
async function saveAllDay(days) {
  const form = editForm.value
  const base = { ...formFields(), all_day: true }
  const share = shareEnabled()
  const records = editDialog.value.records || []
  // 范围改小了就是删日程。清空「结束日期」（点输入框上的 ×）也算 —— 那是误触，
  // 不能悄悄把其余几天抹掉，还把别人表里的那几天一起删了
  const dropping = records.filter(r => !days.includes(r.instance_date))
  if (dropping.length) {
    const others = share ? `其他 ${editDialog.value.shareCount - 1} 人的表里也会一起删掉。` : ''
    try {
      await ElMessageBox.confirm(
        `日期范围缩小了，会删掉原来的 ${dropping.length} 天。${others}`,
        '确认缩小范围',
        { type: 'warning' }
      )
    } catch {
      return false
    }
  }
  // 编辑前这根条上的那几条（按日期索引）；处理完还留在里面的就是要去掉的
  const left = new Map(records.map(r => [r.instance_date, r]))

  for (const day of days) {
    // 全天事件不带时刻：一天的头和尾（跟导入、iCal 导出的约定一致）
    const times = { start_time: `${day}T00:00:00`, end_time: `${day}T23:59:00` }
    const hit = left.get(day)
    if (hit) {
      left.delete(day)
      // scope 跟着「修改范围」走（跨天的条不显示那一栏，form.scope 就是 all）
      await updateSchedule(hit.id, day, { ...base, ...times, scope: form.scope }, share)
    } else {
      // 新添的天也要发给原来那批人：不带 share_from 的话，把 3 天的活动改成
      // 5 天，新加的两天只落在自己表里 —— 正是这次要消灭的那种「别人那儿没变」
      await createSchedule({
        ...base, ...times, ...targetFields(),
        share_from: share ? editDialog.value.shareFrom : null,
      })
    }
  }

  // 范围改小了：多出来的那几天删掉
  for (const gone of left.values()) {
    await deleteSchedule(gone.id, gone.instance_date, 'all', share)
  }
  return true
}

async function handleSave() {
  const form = editForm.value
  if (!form.title.trim()) {
    ElMessage.warning('请输入日程标题')
    return
  }
  if (!form.all_day && form.start_time >= form.end_time) {
    ElMessage.warning('结束时间必须晚于开始时间')
    return
  }
  if (form.repeat_type !== 'none' && !form.repeat_end_date) {
    ElMessage.warning('请设置重复结束日期')
    return
  }

  const days = form.all_day ? daysInRange(form.date, form.end_date) : []
  if (form.all_day && !days.length) {
    ElMessage.warning('结束日期不能早于开始日期')
    return
  }
  // 每个目标学生一天一条，一天一次请求。范围拉太大就是几百次请求，拦一道
  if (days.length > 31) {
    ElMessage.warning('全天事件一次最多 31 天')
    return
  }

  saving.value = true
  try {
    if (form.all_day) {
      // 用户在缩小范围的确认框里点了取消：这次不保存，弹窗留着让他改回去
      if (await saveAllDay(days) === false) return
    } else if (editDialog.value.isEdit && isMultiDayBar.value) {
      // 跨天的全天条关掉「全天」：跟保存/删除其它情况一样，整条一起转，
      // 否则只转了点中的那一天，其余几天留在原地当全天，条子莫名其妙少一截
      for (const r of editDialog.value.records) {
        await updateSchedule(
          r.id,
          r.instance_date,
          {
            ...formFields(),
            all_day: false,
            start_time: `${r.instance_date}T${form.start_time}:00`,
            end_time: `${r.instance_date}T${form.end_time}:00`,
          },
          shareEnabled()
        )
      }
    } else {
      const times = {
        start_time: `${form.date}T${form.start_time}:00`,
        end_time: `${form.date}T${form.end_time}:00`,
      }
      if (editDialog.value.isEdit) {
        await updateSchedule(
          editDialog.value.currentId,
          editDialog.value.currentInstanceDate,
          { ...formFields(), ...times, all_day: false, scope: form.scope },
          shareEnabled()
        )
      } else {
        await createSchedule({ ...formFields(), ...times, all_day: false, ...targetFields() })
      }
    }
    ElMessage.success(saveToast())
    editDialog.value.visible = false
    loadSchedules()
  } catch (e) {
    // request.js 的拦截器不弹提示，不接住的话失败就是「点了保存什么都没发生」
    ElMessage.error(errText(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

/** 保存成功的提示：下发了就说清改了几个人，不然用户不知道别人的表动没动 */
function saveToast() {
  if (!editDialog.value.isEdit) return '已创建'
  if (!shareEnabled()) return '已更新'
  return `已更新，同时改掉了其他 ${editDialog.value.shareCount - 1} 人的表`
}

async function handleDelete() {
  // 跨天的全天事件是「一天一条」，日历上看着是一根条。删就整条一起删 ——
  // 只删点中的那一天，条会缺一块、剩下的还在
  const records = editDialog.value.records || []
  const whole = records.length > 1 ? records : null
  const share = shareEnabled()
  const others = share ? editDialog.value.shareCount - 1 : 0
  // 会连别人的表一起动，先讲清楚。ElMessageBox 的 message 是纯文本，
  // 别指望 \n 换行，拼成一句话
  const extra = others ? `这条日程还发给了其他 ${others} 人，会从他们的表里一并删掉。` : ''
  try {
    await ElMessageBox.confirm(
      (whole
        ? `确定删除这条跨 ${whole.length} 天的全天事件？`
        : (editDialog.value.isRepeat ? '确定删除？可选范围：仅本次 / 本次及以后 / 全部' : '确定删除此日程？')
      ) + extra,
      '删除确认',
      { type: 'warning' }
    )
  } catch { return }

  try {
    if (whole) {
      for (const r of whole) await deleteSchedule(r.id, r.instance_date, 'all', share)
    } else {
      await deleteSchedule(
        editDialog.value.currentId,
        editDialog.value.currentInstanceDate,
        editForm.value.scope,
        share
      )
    }
    ElMessage.success(others ? `已删除，其他 ${others} 人的表里也一并删掉了` : '已删除')
    editDialog.value.visible = false
    loadSchedules()
  } catch (e) {
    // 同上：不接住的话，403（这条不是你分配的）会表现成「点了删除什么都没发生」
    ElMessage.error(errText(e, '删除失败'))
  }
}

// ---------- 学生列表（班委用） ----------
const allStudents = ref([])
const selectedStudents = ref([])
const studentPicker = ref({ open: false, keyword: '' })

async function loadStudents() {
  try {
    const { items } = await getStudentList({ page: 1, page_size: 500 })
    allStudents.value = items
  } catch (e) {
    // 不接住的话选人弹窗是空的，用户只会以为「班里一个学生都没有」
    ElMessage.error(errText(e, '学生名单加载失败'))
  }
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
// 用户有没有手动动过预览表的勾选。没动过 = 全选（空数组就是全选），
// 动过又勾成空 = 他真的一条都不想导，不能再当成全选
const importTouched = ref(false)
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

// 关掉导入弹窗就把它整个复位。不复位的话 el-upload 内部那份文件列表还留着
// 上一次的文件，而它带着 :limit="1"，再打开时拖第二个文件会被直接吞掉 ——
// 不提示、不出现、importFile 还是空，「下一步」永远是灰的，只能刷新页面
function resetImport() {
  importStep.value = 0
  importFile.value = null
  importPreview.value = { items: [], week_count: 0, schedule_count: 0, all_day_count: 0, warnings: [] }
  importToken.value = ''
  importSelectedIndices.value = []
  importSelectedStudents.value = []
  importTouched.value = false
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
      // 默认全选：selectedIndices 为空就是全选（后端也是这个口径）
      importSelectedIndices.value = []
      importTouched.value = false
    } catch (e) {
      // request.js 的拦截器只打 console，不接住的话这里就是「点了下一步没反应」
      ElMessage.error(errText(e, '解析文件失败'))
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
  importTouched.value = true
}

async function handleImportConfirm() {
  if (importForm.value.target_mode === 'selected' && importSelectedStudents.value.length === 0) {
    ElMessage.warning('请选择目标学生')
    return
  }
  // 手动勾成一条不剩就别往下走：空数组在后端表示「全部」，反选到空会被当成全选，
  // 一不留神把整份课表导给全班
  if (importTouched.value && !importSelectedIndices.value.length) {
    ElMessage.warning('请至少勾选一条日程')
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
    loadSchedules()
  } catch (e) {
    // 预览缓存 10 分钟就过期（后端 _PREVIEW_TTL_SECONDS），点了确认才报错。
    // 不接住的话按钮转一圈就没了，用户只会以为「点了没反应」
    ElMessage.error(errText(e, '导入失败'))
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
    } catch (e) {
      // 不接住的话弹窗照常打开、链接是空的，点「复制」复制的也是空串
      subscribeUrl.value = ''
      ElMessage.error(errText(e, '订阅链接获取失败'))
    } finally {
      subscribeLoading.value = false
    }
  }
})

function copySubscribeUrl() {
  if (!subscribeUrl.value) {
    ElMessage.warning('订阅链接还没取到')
    return
  }
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
  } catch (e) {
    ElMessage.error(errText(e, '重置失败'))
  }
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
  /* 这个工具栏必换行：窄窗口（截图里那种半屏、手机）一行放不下「翻周 + 今天 +
     导入 + 订阅 + 新建日程」，不换行时最右边的按钮会被挤出可见区域，点都点不到 */
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.week-nav {
  display: flex;
  flex-wrap: wrap;
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
  flex-wrap: wrap;
  gap: 8px;
  /* 换行后按钮组仍然贴右边，不然它会跑到「翻周」下面去左对齐 */
  margin-left: auto;
}

/* 窄屏：180px 的日期栏太占地方，让它跟着内容收缩 */
@media (max-width: 560px) {
  .week-label {
    min-width: 0;
  }
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

/* 表头角上的当前时间。60px 一格，字要小到 4 个字放得下 */
.now-clock-label {
  font-size: 10px;
  line-height: 1.2;
  color: var(--el-text-color-placeholder);
}

.now-clock {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--el-text-color-primary);
  font-variant-numeric: tabular-nums;
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

/* 全天事件行（表头正下方那一行） */
.cal-allday {
  position: relative;
  background: var(--el-fill-color-blank);
}

.cal-allday .cal-time-col {
  font-size: 12px;
  padding-top: 6px;
}

/* 和 .cal-events-overlay 一个套路：让开时间列，0% 才与周一列左边对齐 */
.cal-allday-overlay {
  position: absolute;
  top: 0;
  left: 60px;
  right: 0;
  bottom: 0;
  pointer-events: none;
}

.all-day-item {
  position: absolute;
  height: 20px;
  line-height: 20px;
  background: var(--evt-bg, var(--el-color-info-light-8));
  border-left: 3px solid var(--evt, var(--el-color-info));
  border-radius: 3px;
  padding: 0 6px;
  font-size: 12px;
  cursor: pointer;
  pointer-events: auto;
  overflow: hidden;
  box-sizing: border-box;
  transition: box-shadow 0.15s;
}

.all-day-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  z-index: 10;
}

.all-day-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
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
