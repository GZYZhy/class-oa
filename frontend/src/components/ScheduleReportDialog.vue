<template>
  <el-dialog
    append-to-body
    v-model="visible"
    :title="studentId ? `${studentName || '学生'}的报告` : '我的报告'"
    width="760px"
    destroy-on-close
    @opened="load"
  >
    <div class="sr-toolbar">
      <el-button
        v-for="preset in PRESETS"
        :key="preset.key"
        size="small"
        :type="activePreset === preset.key ? 'primary' : ''"
        @click="pickPreset(preset.key)"
      >
        {{ preset.label }}
      </el-button>
      <el-date-picker
        v-model="range"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        size="small"
        @change="activePreset = 'custom'"
      />
    </div>

    <div v-loading="loading" class="sr-body">
      <div v-if="error" class="sr-error">
        {{ error }}
        <el-button link type="primary" @click="load">重试</el-button>
      </div>

      <template v-else-if="report">
        <div class="sr-hero">
          <p class="sr-kicker">{{ rangeText }}</p>
          <h3>{{ report.student_name }} 的时间切片</h3>
          <p class="sr-intro">{{ intro }}</p>
        </div>

        <div class="sr-cards">
          <div class="sr-card">
            <strong>{{ report.total_events }}</strong>
            <span>个日程</span>
          </div>
          <div class="sr-card">
            <strong>{{ hours }}</strong>
            <span>小时在安排里</span>
          </div>
          <div class="sr-card">
            <strong>{{ report.active_days }}</strong>
            <span>天有记录</span>
          </div>
          <div class="sr-card">
            <strong>{{ busyText }}</strong>
            <span>班级繁忙度</span>
          </div>
        </div>

        <section v-if="regularTypes.length" class="sr-section">
          <h4>时间都去了哪儿</h4>
          <div v-for="type in regularTypes" :key="type.name" class="sr-type">
            <div class="sr-type-head">
              <span>{{ type.name }}</span>
              <span>{{ type.count }} 次 · {{ Math.round(type.minutes / 60 * 10) / 10 }} 小时 · {{ type.percent }}%</span>
            </div>
            <el-progress :percentage="type.percent" :show-text="false" :stroke-width="8" />
          </div>
        </section>

        <section v-if="report.collective" class="sr-section">
          <h4>
            集体生活
            <span class="sr-collective-total">
              共 {{ report.collective.count }} 次 · {{ Math.round(report.collective.minutes / 60 * 10) / 10 }} 小时
            </span>
          </h4>
          <div v-for="item in report.collective.breakdown" :key="item.name" class="sr-type">
            <div class="sr-type-head">
              <span>{{ item.name }}</span>
              <span>{{ item.count }} 次 · {{ Math.round(item.minutes / 60 * 10) / 10 }} 小时 · {{ collectivePercent(item) }}%</span>
            </div>
            <el-progress :percentage="collectivePercent(item)" :show-text="false" :stroke-width="8" />
          </div>
        </section>

        <section class="sr-section">
          <h4>节奏</h4>
          <div class="sr-rhythm">
            <div>
              <p class="sr-label">最常出现的日子</p>
              <strong>{{ peakWeekdayText }}</strong>
            </div>
            <div>
              <p class="sr-label">最常开始的时间</p>
              <strong>{{ peakHourText }}</strong>
            </div>
            <div>
              <p class="sr-label">最早 / 最晚</p>
              <strong class="sr-extremes">
                <span>最早 {{ formatTime(report.earliest_time) }}</span>
                <span>最晚 {{ formatTime(report.latest_time) }}</span>
              </strong>
            </div>
            <div>
              <p class="sr-label">最常去的地方</p>
              <strong>{{ topLocationText }}</strong>
            </div>
          </div>
          <div class="sr-week">
            <div v-for="(item, index) in weekBars" :key="index" class="sr-week-col">
              <div class="sr-week-bar" :style="{ height: item.height }" />
              <span>{{ item.label }}</span>
            </div>
          </div>
          <div class="sr-offhours">
            <div>
              <p class="sr-label">非工作时间日程</p>
              <strong>{{ report.off_hours_events }} 个</strong>
            </div>
            <div>
              <p class="sr-label">非工作时间时长</p>
              <strong>{{ offHoursText }}</strong>
            </div>
            <span class="sr-offhours-note">8:00–11:30、13:30–17:00 之外</span>
          </div>
        </section>

        <p class="sr-note">{{ evaluation }}</p>
        <p class="sr-disclaimer">仅统计系统内日程，数据仅供参考娱乐。</p>
      </template>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { getMyScheduleReport, getStudentScheduleReport } from '@/api/schedule'
import { errText } from '@/utils/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  studentId: { type: [Number, String], default: null },
  studentName: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])

const PRESETS = [
  { key: 'week', label: '本周' },
  { key: 'month', label: '本月' },
  { key: 'days30', label: '近 30 天' }
]
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const COLLECTIVE_NAMES = new Set(['工作', '会议', '活动'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})
const range = ref([])
const activePreset = ref('week')
const loading = ref(false)
const error = ref('')
const report = ref(null)
const requestSeq = ref(0)

const hours = computed(() => report.value ? Math.round(report.value.total_minutes / 60 * 10) / 10 : 0)
const regularTypes = computed(() => (report.value?.types || [])
  .filter((type) => !COLLECTIVE_NAMES.has(type.name)))
const rangeText = computed(() => {
  if (!report.value) return ''
  return `${report.value.start_date} 至 ${report.value.end_date}`
})
const busyText = computed(() => {
  const value = report.value?.busy_top_percent
  return value == null ? '样本不足' : `前 ${value}%`
})
const peakWeekdayText = computed(() => {
  const index = report.value?.peak_weekday
  return index == null ? '还没有计时日程' : WEEKDAYS[index]
})
const peakHourText = computed(() => {
  const hour = report.value?.peak_hour
  return hour == null ? '还没有计时日程' : `${String(hour).padStart(2, '0')}:00 前后`
})
const topLocationText = computed(() => {
  const location = report.value?.top_location
  if (!location) return '还没有记录地点'
  const count = report.value?.top_location_count
  return count ? `${location}（${count} 次）` : location
})
const offHoursText = computed(() => {
  const value = report.value?.off_hours_minutes || 0
  return `${Math.round(value / 60 * 10) / 10} 小时`
})
const weekBars = computed(() => {
  const counts = report.value?.weekday_counts || []
  const max = Math.max(...counts, 1)
  return WEEKDAYS.map((label, index) => ({
    label,
    height: `${Math.round((counts[index] || 0) / max * 100)}%`
  }))
})
const intro = computed(() => {
  if (!report.value) return ''
  if (!report.value.total_events) {
    return '这段时间的日程表是空的，没有安排，也是一种安排。'
  }
  return `这段时间，日程表上留下了 ${report.value.total_events} 个印记，累计 ${hours.value} 小时。`
})
const evaluation = computed(() => {
  if (!report.value) return ''
  if (!report.value.total_events) return '这段时间没有留下日程记录。照顾好自己，辛苦了。'
  const top = report.value.types[0]
  const busy = report.value.busy_top_percent
  const rhythm = report.value.peak_hour == null
    ? '安排没有落在具体时刻里'
    : `最常开始于 ${String(report.value.peak_hour).padStart(2, '0')}:00 前后`
  const rank = busy == null
    ? '班级样本还不够多，这份报告先当作一段记录'
    : `繁忙程度位于班级前 ${busy}%`
  return `最常见的安排是「${top?.name || '未分类'}」，${rhythm}。${rank}。把每一段时间都安排得清清楚楚，辛苦了。`
})

function iso(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function pickPreset(key) {
  activePreset.value = key
  const now = new Date()
  if (key === 'week') {
    const monday = new Date(now)
    monday.setDate(now.getDate() - ((now.getDay() + 6) % 7))
    const sunday = new Date(monday)
    sunday.setDate(monday.getDate() + 6)
    range.value = [iso(monday), iso(sunday)]
  } else if (key === 'month') {
    range.value = [
      iso(new Date(now.getFullYear(), now.getMonth(), 1)),
      iso(new Date(now.getFullYear(), now.getMonth() + 1, 0))
    ]
  } else {
    const start = new Date(now)
    start.setDate(now.getDate() - 29)
    range.value = [iso(start), iso(now)]
  }
}

function formatTime(value) {
  if (!value) return '—'
  return String(value).slice(0, 5)
}

function collectivePercent(item) {
  const total = report.value?.total_events || 0
  return total ? Math.round(item.count * 100 / total) : 0
}

async function load() {
  if (!range.value?.[0] || !range.value?.[1]) pickPreset(activePreset.value)
  const [start, end] = range.value
  const seq = ++requestSeq.value
  loading.value = true
  error.value = ''
  report.value = null
  try {
    const data = props.studentId
      ? await getStudentScheduleReport(props.studentId, start, end)
      : await getMyScheduleReport(start, end)
    if (seq === requestSeq.value) report.value = data
  } catch (e) {
    if (seq === requestSeq.value) error.value = errText(e, '读取报告失败')
  } finally {
    if (seq === requestSeq.value) loading.value = false
  }
}

watch(() => props.modelValue, (open) => {
  if (open) {
    activePreset.value = 'week'
    pickPreset('week')
  }
})
watch(range, () => {
  if (props.modelValue && range.value?.length === 2) load()
})
</script>

<style scoped>
.sr-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
.sr-toolbar :deep(.el-date-editor) {
  margin-left: auto;
}
.sr-body {
  min-height: 220px;
}
.sr-error {
  padding: 28px 0;
  color: var(--el-color-danger);
  text-align: center;
}
.sr-kicker {
  margin: 0 0 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.sr-hero h3 {
  margin: 0 0 8px;
  font-size: 24px;
}
.sr-intro {
  margin: 0;
  color: var(--el-text-color-regular);
  line-height: 1.8;
}
.sr-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 18px 0;
}
.sr-card {
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-fill-color-extra-light);
}
.sr-card strong {
  display: block;
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}
.sr-card span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.sr-section {
  margin-top: 20px;
}
.sr-section h4 {
  margin: 0 0 12px;
  font-size: 15px;
}
.sr-type + .sr-type {
  margin-top: 10px;
}
.sr-type-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 5px;
  font-size: 13px;
}
.sr-type-head span:last-child {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-align: right;
}
.sr-collective-total {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 400;
}
.sr-rhythm {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.sr-rhythm > div {
  padding: 12px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.sr-label {
  margin: 0 0 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.sr-rhythm strong {
  font-size: 14px;
}
.sr-extremes {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.sr-extremes span {
  white-space: nowrap;
}
.sr-offhours {
  display: flex;
  align-items: flex-end;
  gap: 24px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding: 12px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.sr-offhours strong {
  font-size: 15px;
}
.sr-offhours-note {
  margin-left: auto;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.sr-week {
  display: flex;
  align-items: end;
  gap: 8px;
  height: 90px;
  margin-top: 14px;
}
.sr-week-col {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: end;
  height: 100%;
  gap: 4px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.sr-week-bar {
  width: 100%;
  min-height: 3px;
  border-radius: 4px 4px 0 0;
  background: var(--el-color-primary);
  opacity: 0.7;
}
.sr-note {
  margin: 20px 0 0;
  padding: 14px;
  border-left: 3px solid var(--el-color-primary);
  border-radius: 0 8px 8px 0;
  background: var(--el-color-primary-light-9);
  color: var(--el-text-color-regular);
  line-height: 1.8;
}
.sr-disclaimer {
  margin: 12px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-align: right;
}
@media (max-width: 640px) {
  .sr-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sr-rhythm {
    grid-template-columns: 1fr;
  }
  .sr-toolbar :deep(.el-date-editor) {
    width: 100%;
    margin-left: 0;
  }
  .sr-hero h3 {
    font-size: 20px;
  }
}
</style>
