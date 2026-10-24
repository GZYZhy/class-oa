<template>
  <div class="statistics">
    <!-- 全班数据都在这里，盖一层「谁在看」的水印 -->
    <Watermark :text="watermarkText" />

    <!-- 概览：除「总人数」外每张都能点开看名单（key 为空的不弹窗、也不显示成可点） -->
    <div class="overview-grid">
      <div
        v-for="item in overviewCards"
        :key="item.label"
        class="mini-card"
        :class="{ clickable: item.key }"
        :title="item.key ? '点击查看名单' : ''"
        @click="openRoster(item.key)"
      >
        <span class="mini-dot" :style="{ background: item.color }"></span>
        <span class="mini-value">{{ item.value }}</span>
        <span class="mini-label">{{ item.label }}</span>
      </div>
    </div>

    <!-- 第一行：三个构成环 -->
    <el-row :gutter="20" class="row">
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <h3 class="page-title">性别构成</h3>
          <div class="stat-chart" data-chart="gender"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <h3 class="page-title">政治面貌</h3>
          <div class="stat-chart" data-chart="political"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <h3 class="page-title">在校状态</h3>
          <div class="stat-chart" data-chart="status"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第二行：两组有长尾的分布 -->
    <el-row :gutter="20" class="row">
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">民族构成</h3>
          <div class="stat-chart" data-chart="ethnicity"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">年龄分布</h3>
          <div class="stat-chart" data-chart="age"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第三行：分数段 + 出生月份 -->
    <el-row :gutter="20" class="row">
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">
            高考分数段
            <span class="title-extra">
              平均 {{ scoreSummary?.avg || 0 }} · 最高 {{ scoreSummary?.max || 0 }} · 最低 {{ scoreSummary?.min || 0 }}
            </span>
          </h3>
          <div class="stat-chart" data-chart="score"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">出生月份</h3>
          <div class="stat-chart" data-chart="birthMonth"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第四行：生源地。省份多，独占一行给足宽度；只画前 13，
         再多的话每根条只剩几像素高，看着就是一片糊 -->
    <el-row :gutter="20" class="row">
      <el-col :span="24">
        <div class="page-card">
          <h3 class="page-title">
            生源地
            <span v-if="provinceExtra" class="title-extra">{{ provinceExtra }}</span>
          </h3>
          <div class="stat-chart chart-tall" data-chart="province"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第五行：职务。
         这份数据的值几乎全是 1（每个职务一个人），画成条形图就是「整片等长色块」，
         信息量为零还占一屏 —— 改用紧凑榜单：名次 + 名称 + 相对长度 + 人数 -->
    <el-row :gutter="20" class="row">
      <el-col :span="24">
        <div class="page-card">
          <h3 class="page-title">
            职务构成
            <span class="title-extra">按人数排序</span>
          </h3>
          <div class="rank-cols">
            <div class="rank-col">
              <div class="rank-caption">班委</div>
              <div v-if="classPositions.length" class="rank-list">
                <div v-for="(it, i) in classPositions" :key="it.name" class="rank-row">
                  <span class="rank-idx">{{ i + 1 }}</span>
                  <span class="rank-name" :title="it.name">{{ it.name }}</span>
                  <span class="rank-track"><i :style="{ width: it.pct + '%' }"></i></span>
                  <span class="rank-num">{{ it.value }}</span>
                </div>
              </div>
              <div v-else class="rank-empty">暂无</div>
            </div>
            <div class="rank-col">
              <div class="rank-caption">团学会</div>
              <div v-if="leaguePositions.length" class="rank-list">
                <div v-for="(it, i) in leaguePositions" :key="it.name" class="rank-row">
                  <span class="rank-idx">{{ i + 1 }}</span>
                  <span class="rank-name" :title="it.name">{{ it.name }}</span>
                  <span class="rank-track"><i :style="{ width: it.pct + '%' }"></i></span>
                  <span class="rank-num">{{ it.value }}</span>
                </div>
              </div>
              <div v-else class="rank-empty">暂无</div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 第六行：考生与资助信息。
         考生类别 / 科类 / 录取批次 这三项全班通常只有一种写法，
         画成饼图就是「一整块 100%」；贫困生也只有是/否两瓣。
         统一压成一排键值，信息照样在，版面立刻清爽 -->
    <el-row :gutter="20" class="row">
      <el-col :span="24">
        <div class="page-card">
          <h3 class="page-title">考生与资助信息</h3>
          <div class="kv-grid">
            <div v-for="row in infoRows" :key="row.label" class="kv-item">
              <span class="kv-label">{{ row.label }}</span>
              <span class="kv-value">{{ row.value }}</span>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 名单弹窗：点概览卡打开，看这份名单具体是谁。
         弹窗里是一整份班级名单，同样盖一层水印；
         max-height 管住长名单，否则弹窗会撑到一千多像素、把按钮滚出屏幕 -->
    <el-dialog append-to-body v-model="rosterVisible" :title="rosterTitle" width="560px">
      <Watermark :text="watermarkText" />
      <el-table :data="roster?.rows || []" size="small" max-height="420px" v-loading="rosterLoading">
        <el-table-column v-if="roster?.column" prop="group" :label="roster.column" width="120" />
        <el-table-column prop="name" label="姓名" />
        <el-table-column prop="student_no" label="学号" width="130" />
        <el-table-column label="操作" width="76" align="center">
          <template #default="{ row }">
            <el-button type="primary" link @click="goStudentDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { CHART_PALETTE, renderDonut, renderBar } from '@/utils/chart'
import { ElMessage } from 'element-plus'
import { useStudentStore } from '@/store/student'
import { errText } from '@/utils/request'
import { buildRoster, countMinority } from '@/utils/statGroups'
import Watermark from '@/components/Watermark.vue'
import { useWatermark } from '@/composables/useWatermark'

const watermarkText = useWatermark()
const router = useRouter()
const studentStore = useStudentStore()
const stats = ref(null)
const total = ref(0)
const scoreSummary = ref({ avg: 0, max: 0, min: 0 })

// 图表实例，key 为 data-chart 标识
const chartInstances = {}

/* 分布对象 → 数组。
   toOrdered 保持后端给的顺序（年龄、月份、分数段本身有序，排了反而乱）；
   toRanked 按人数从多到少，并算好相对最大值的百分比给榜单用 */
function toOrdered(obj) {
  return Object.entries(obj || {}).map(([name, value]) => ({ name, value }))
}

function toRanked(obj) {
  const list = toOrdered(obj)
  list.sort((a, b) => b.value - a.value || a.name.localeCompare(b.name, 'zh'))
  const max = Math.max(1, ...list.map((i) => i.value))
  return list.map((i) => ({ ...i, pct: Math.round((i.value / max) * 100) }))
}

// 图表配置：key 与模板中 data-chart 一一对应
// 环形图/条形图的样式与配色在 utils/chart.js 里统一实现，首页用的是同一套
function buildCharts(s) {
  return {
    gender: (dom) => renderDonut(dom, toOrdered(s.gender)),
    political: (dom) => renderDonut(dom, toRanked(s.political_status)),
    status: (dom) => renderDonut(dom, toRanked(s.school_status)),

    ethnicity: (dom) => renderBar(dom, toRanked(s.ethnicity), { horizontal: true, color: CHART_PALETTE[0] }),
    province: (dom) => renderBar(dom, provinceTop.value, { horizontal: true, color: CHART_PALETTE[0] }),
    age: (dom) => renderBar(dom, toOrdered(s.ages).map((d) => ({ ...d, name: `${d.name}岁` })), { color: CHART_PALETTE[5] }),
    score: (dom) => renderBar(dom, toOrdered(s.score_ranges), { color: CHART_PALETTE[2] }),
    birthMonth: (dom) => renderBar(dom, toOrdered(s.birth_months), { color: CHART_PALETTE[4] })
  }
}

/* 生源地：只画前 13，标题里标出总省份数 */
const provinceAll = computed(() => toRanked(stats.value?.provinces))
const provinceTop = computed(() => provinceAll.value.slice(0, 13))
const provinceExtra = computed(() =>
  provinceAll.value.length > 13 ? `TOP 13 / 共 ${provinceAll.value.length} 个省份` : ''
)

/* 班委任职表的显示顺序：系统管理里排的那一份，「关于班级」页用的是同一个 */
const committeeOrder = computed(() => stats.value?.committee_order || [])

/* 榜单数据 */
const classPositions = computed(() => toRanked(stats.value?.class_positions))
const leaguePositions = computed(() => toRanked(stats.value?.league_positions))

/* 键值行：把「一整块 100%」的三张饼压成文字 */
function fmtDist(obj) {
  const list = toRanked(obj)
  return list.length ? list.map((i) => `${i.name} ${i.value}`).join(' · ') : '—'
}

const infoRows = computed(() => [
  { label: '考生类别', value: fmtDist(stats.value?.exam_category) },
  { label: '科类', value: fmtDist(stats.value?.subject_type) },
  { label: '录取批次', value: fmtDist(stats.value?.admission_batch) },
  { label: '贫困生', value: fmtDist(stats.value?.poor_student) }
])

const overviewCards = computed(() => [
  { label: '总人数', value: total.value, color: CHART_PALETTE[0] },
  { label: '男生', value: stats.value?.gender?.['男'] || 0, color: CHART_PALETTE[2], key: 'male' },
  { label: '女生', value: stats.value?.gender?.['女'] || 0, color: CHART_PALETTE[1], key: 'female' },
  { label: '共青团员', value: stats.value?.political_status?.['共青团员'] || 0, color: CHART_PALETTE[5], key: 'league' },
  { label: '班委', value: stats.value?.class_committee_count || 0, color: CHART_PALETTE[3], key: 'committee' },
  { label: '团学会成员', value: stats.value?.league_count || 0, color: CHART_PALETTE[4], key: 'leagueMember' },
  { label: '贫困生', value: stats.value?.poor_student?.['是'] || 0, color: CHART_PALETTE[6], key: 'poor' },
  // 不数「有几种民族」而是数人：种类数只在每个少数民族恰好一个人时才等于名单行数，
  // 那样卡上的数字点开就会和弹窗里的条数对不上（见 utils/statGroups.js 的 countMinority）
  { label: '少数民族人数', value: countMinority(stats.value?.ethnicity), color: CHART_PALETTE[7], key: 'minority' }
])

// 名单弹窗：点概览卡打开，看这份名单具体是谁
const roster = ref(null)
const rosterVisible = ref(false)
const rosterLoading = ref(false)

const rosterTitle = computed(() =>
  roster.value ? `${roster.value.title}（${roster.value.rows.length}人）` : ''
)

// 全班名单：第一次点开才拉，之后再点都复用这一次的结果（全班几十人，本地分组足够）。
// 缓存的是 **promise** 而不是结果 —— 连点两张不同的卡时，第二次会在第一次还没回来
// 的时候发起，只认结果的话就会白发一次请求。
let rosterSource = null

function loadStudents() {
  if (!rosterSource) {
    rosterSource = studentStore.fetchAllStudents().catch((e) => {
      rosterSource = null // 失败不记一辈子，下次点还能重试
      throw e
    })
  }
  return rosterSource
}

async function openRoster(key) {
  if (!key) return // 「总人数」这类卡没有名单
  roster.value = null
  rosterVisible.value = true
  rosterLoading.value = true
  try {
    // 班委那张要跟着系统管理里排好的顺序（statistics 接口一起带下来的学号数组）
    roster.value = buildRoster(key, await loadStudents(), committeeOrder.value)
  } catch (e) {
    // 拦截器不弹错，这里不报就成了「点了没反应」
    rosterVisible.value = false
    ElMessage.error(errText(e, '名单加载失败'))
  } finally {
    rosterLoading.value = false
  }
}

/** 名单里的「详情」：跳学生信息页并直接弹开这个人的详情（那边认 ?open=<id>） */
function goStudentDetail(row) {
  router.push({ path: '/students', query: { open: row.id } })
}

function disposeCharts() {
  Object.keys(chartInstances).forEach((key) => {
    chartInstances[key].dispose()
    delete chartInstances[key]
  })
}

/** 按当前主题把页面上所有图表重画一遍 */
function renderAll() {
  disposeCharts()
  if (!stats.value) return
  const builders = buildCharts(stats.value)
  document.querySelectorAll('.stat-chart').forEach((dom) => {
    const key = dom.dataset.chart
    if (builders[key]) chartInstances[key] = builders[key](dom)
  })
}

function onResize() {
  Object.values(chartInstances).forEach((inst) => inst.resize())
}

// 深浅模式切换：ECharts 的配色是 init 时从 CSS 变量读的，不重画就会停在旧主题
let themeObserver = null

onMounted(async () => {
  stats.value = await studentStore.fetchStatistics()
  total.value = stats.value.total || 0
  scoreSummary.value = stats.value.score_summary || scoreSummary.value

  renderAll()
  window.addEventListener('resize', onResize)
  themeObserver = new MutationObserver(renderAll)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  themeObserver?.disconnect()
  disposeCharts()
})
</script>

<style scoped>
.statistics {
  /* 水印的定位基准：水印铺满整个统计页 */
  position: relative;
}

/* 概览：自适应列宽，手机两列、宽屏一行铺满，不再靠 el-col 的断点硬切 */
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 12px;
}

.mini-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 14px 16px;
  border-radius: 14px;
  /* 和 page-card 同一道受光面，小卡也有方向感 */
  background: var(--app-surface-sheen) padding-box;
  border: 1px solid var(--app-border);
  box-shadow: var(--app-shadow);
}

/* 能点开的卡：给个手型和抬起效果。否则「这儿能点」全靠猜 —— 页面上没有任何线索 */
.mini-card.clickable {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
}

.mini-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: var(--app-shadow-hover);
  border-color: var(--app-secondary-border);
}

/* 颜色只留在这一颗小点上：八个大数字各自染成红绿紫会更花，小点是「分类标点」 */
.mini-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-bottom: 6px;
}

.mini-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.15;
  color: var(--el-text-color-primary);
  font-variant-numeric: tabular-nums;
}

.mini-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.row {
  margin-top: 20px;
}

.title-extra {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
  margin-left: 10px;
  letter-spacing: 0;
}

.stat-chart {
  width: 100%;
  height: 240px;
}

.chart-tall {
  height: 320px;
}

/* 榜单：名次 / 名称 / 相对长度 / 人数。比条形图省一屏，也更像「数据表」而不是画图 */
.rank-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.rank-caption {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 10px;
}

.rank-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.rank-row {
  display: grid;
  grid-template-columns: 14px minmax(52px, 88px) 1fr 22px;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.rank-idx {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-variant-numeric: tabular-nums;
}

.rank-name {
  color: var(--el-text-color-regular);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rank-track {
  height: 6px;
  border-radius: 3px;
  background: var(--el-fill-color-light);
  overflow: hidden;
}

.rank-track i {
  display: block;
  height: 100%;
  border-radius: 3px;
  /* 主色→副色的横向渐变，和标题条、菜单激活态同一套语义 */
  background: linear-gradient(90deg, var(--el-color-primary), var(--app-secondary));
}

.rank-num {
  text-align: right;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}

.rank-empty {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  padding: 6px 0;
}

/* 键值面板：替代「一整块 100%」的饼图 */
.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
}

.kv-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 12px 16px;
  border-radius: 12px;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--app-outline);
}

.kv-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.kv-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

/* 手机上屏幕窄，缩一缩内边距和图表高度，少滚动几屏 */
@media (max-width: 768px) {
  .overview-grid {
    grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
    gap: 10px;
  }

  .mini-card {
    padding: 12px 14px;
  }

  .mini-value {
    font-size: 20px;
  }

  .stat-chart {
    height: 200px;
  }

  .chart-tall {
    height: 260px;
  }

  .rank-cols {
    grid-template-columns: 1fr;
    gap: 16px;
  }
}
</style>
