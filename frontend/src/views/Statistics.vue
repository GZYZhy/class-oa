<template>
  <div class="statistics">
    <!-- 全班数据都在这里，盖一层「谁在看」的水印 -->
    <Watermark :text="watermarkText" />

    <!-- 概览卡片：手机上一行 2 个，平板上 4 个，宽屏 8 个。
         除「总人数」外每张都能点开看名单（key 为空的那张不弹窗，也不显示成可点） -->
    <el-row :gutter="16">
      <el-col :xs="12" :sm="6" :md="3" v-for="item in overviewCards" :key="item.label">
        <div
          class="mini-card"
          :class="{ clickable: item.key }"
          :title="item.key ? '点击查看名单' : ''"
          :style="{ borderLeftColor: item.color }"
          @click="openRoster(item.key)"
        >
          <div class="mini-value" :style="{ color: item.color }">{{ item.value }}</div>
          <div class="mini-label">{{ item.label }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- 第一行：性别 + 政治面貌 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">性别分布</h3>
          <div class="stat-chart" data-chart="gender"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">政治面貌</h3>
          <div class="stat-chart" data-chart="political"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第二行：民族 + 贫困生 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">民族构成</h3>
          <div class="stat-chart chart-tall" data-chart="ethnicity"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">贫困生</h3>
          <div class="stat-chart" data-chart="poor"></div>
          <el-table :data="poorTableData" size="small" style="margin-top: 10px;">
            <el-table-column prop="name" label="类别" />
            <el-table-column prop="value" label="人数" align="center" />
            <el-table-column label="占比" align="center">
              <template #default="{ row }">
                {{ ((row.value / total) * 100).toFixed(1) }}%
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>
    </el-row>

    <!-- 第三行：高考分数 + 年龄分布 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">
            高考分数段
            <span style="font-size: 13px; color: var(--el-text-color-secondary); font-weight: normal; margin-left: 12px;">
              平均 {{ scoreSummary?.avg || 0 }} · 最高 {{ scoreSummary?.max || 0 }} · 最低 {{ scoreSummary?.min || 0 }}
            </span>
          </h3>
          <div class="stat-chart" data-chart="score"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">年龄分布</h3>
          <div class="stat-chart" data-chart="age"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第四行：宿舍分布 + 宿舍楼 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="16">
        <div class="page-card">
          <h3 class="page-title">宿舍分布统计</h3>
          <div class="stat-chart chart-wide" data-chart="dormitory"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <h3 class="page-title">单元分布</h3>
          <div class="stat-chart" data-chart="building"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第五行：生源地 + 出生月份 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="14">
        <div class="page-card">
          <h3 class="page-title">生源地分布（按省份）</h3>
          <div class="stat-chart chart-tall" data-chart="province"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="10">
        <div class="page-card">
          <h3 class="page-title">出生月份分布</h3>
          <div class="stat-chart" data-chart="birthMonth"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第六行：考生信息 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <h3 class="page-title">考生类别</h3>
          <div class="stat-chart" data-chart="examCategory"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <h3 class="page-title">科类分布</h3>
          <div class="stat-chart" data-chart="subjectType"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <h3 class="page-title">录取批次</h3>
          <div class="stat-chart" data-chart="admission"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第七行：职务统计 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">班委职务分布</h3>
          <div class="stat-chart chart-tall" data-chart="classPosition"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">团学会职务分布</h3>
          <div class="stat-chart chart-tall" data-chart="leaguePosition"></div>
        </div>
      </el-col>
    </el-row>

    <!-- 第八行：毕业中学 + 在校状态 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="16">
        <div class="page-card">
          <h3 class="page-title">毕业中学分布（TOP 15）</h3>
          <div class="stat-chart chart-tall" data-chart="highSchool"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <h3 class="page-title">在校状态</h3>
          <div class="stat-chart" data-chart="status"></div>
          <el-table :data="statusTableData" size="small" style="margin-top: 10px;">
            <el-table-column prop="name" label="状态" />
            <el-table-column prop="value" label="人数" align="center" />
          </el-table>
        </div>
      </el-col>
    </el-row>

    <!-- 名单弹窗：点概览卡打开，看这份名单具体是谁。
         水印和「学生详情」那个弹窗一个道理（StudentList.vue 里那句注释）——
         弹窗里是一整份班级名单，同样盖一层「谁在看」。
         max-height 管住长名单：团员 27 人，不限制的话弹窗会撑到一千多像素，
         连标题和关闭按钮一起被滚出屏幕 -->
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
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import echarts from '@/utils/chart'
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

const poorTableData = computed(() =>
  Object.entries(stats.value?.poor_student || {}).map(([name, value]) => ({ name, value }))
)

const statusTableData = computed(() =>
  Object.entries(stats.value?.school_status || {}).map(([name, value]) => ({ name, value }))
)

// 饼图渲染
function renderPie(dom, entries, colors) {
  const inst = echarts.init(dom)
  inst.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c}人 ({d}%)' },
    legend: { bottom: '2%', left: 'center', type: 'scroll' },
    color: colors,
    series: [{
      type: 'pie',
      radius: ['40%', '65%'],
      center: ['50%', '42%'],
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
      label: { formatter: '{b}\n{c}人', fontSize: 11 },
      labelLine: { length: 8, length2: 8 },
      data: entries.map(([name, value]) => ({ name, value }))
    }]
  })
  return inst
}

// 柱状图渲染（支持横向）
function renderBar(dom, xData, yData, color1, color2, horizontal = false) {
  const inst = echarts.init(dom)
  const series = [{
    type: 'bar',
    data: yData,
    barWidth: horizontal ? '60%' : '55%',
    itemStyle: {
      color: new echarts.graphic.LinearGradient(
        horizontal ? 0 : 0, 0, horizontal ? 1 : 0, horizontal ? 0 : 1,
        [{ offset: 0, color: color1 }, { offset: 1, color: color2 }]
      ),
      borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]
    },
    label: { show: true, position: horizontal ? 'right' : 'top', formatter: '{c}', fontSize: 11 }
  }]
  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    series
  }
  if (horizontal) {
    option.xAxis = { type: 'value' }
    option.yAxis = { type: 'category', data: xData, axisLabel: { fontSize: 11 } }
  } else {
    option.xAxis = { type: 'category', data: xData, axisLabel: { fontSize: 11 } }
    option.yAxis = { type: 'value', minInterval: 1 }
  }
  inst.setOption(option)
  return inst
}

// 图表配置：key 与模板中 data-chart 一一对应
// 新增图表时，在此加一项并在模板加一个 data-chart 容器即可
function buildCharts(s) {
  return {
    gender: (dom) => renderPie(dom, Object.entries(s.gender || {}), ['#409EFF', '#F56C6C']),
    political: (dom) => renderPie(dom, Object.entries(s.political_status || {}), ['#E6A23C', '#909399']),
    poor: (dom) => renderPie(dom, Object.entries(s.poor_student || {}), ['#909399', '#E6A23C', '#F56C6C']),
    building: (dom) => renderPie(dom, Object.entries(s.buildings || {}), ['#409EFF', '#67C23A']),
    examCategory: (dom) => renderPie(dom, Object.entries(s.exam_category || {}), ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399']),
    subjectType: (dom) => renderPie(dom, Object.entries(s.subject_type || {}), ['#E6A23C', '#409EFF', '#67C23A', '#9b59b6']),
    admission: (dom) => renderPie(dom, Object.entries(s.admission_batch || {}), ['#67C23A', '#409EFF', '#E6A23C', '#9b59b6']),
    status: (dom) => renderPie(dom, Object.entries(s.school_status || {}), ['#67C23A', '#909399']),

    ethnicity: (dom) => {
      const d = Object.entries(s.ethnicity || {})
      return renderBar(dom, d.map(x => x[0]), d.map(x => x[1]), '#83bff6', '#188df0', true)
    },
    score: (dom) => {
      const d = Object.entries(s.score_ranges || {})
      return renderBar(dom, d.map(x => x[0]), d.map(x => x[1]), '#67C23A', '#95d475')
    },
    age: (dom) => {
      const d = Object.entries(s.ages || {})
      return renderBar(dom, d.map(x => x[0] + '岁'), d.map(x => x[1]), '#9b59b6', '#b07cc6')
    },
    dormitory: (dom) => {
      const d = Object.entries(s.dormitory || {})
      return renderBar(dom, d.map(x => x[0]), d.map(x => x[1]), '#E6A23C', '#ebb563')
    },
    province: (dom) => {
      const d = Object.entries(s.provinces || {})
      return renderBar(dom, d.map(x => x[0]), d.map(x => x[1]), '#1abc9c', '#48c9b0', true)
    },
    birthMonth: (dom) => {
      const d = Object.entries(s.birth_months || {})
      return renderBar(dom, d.map(x => x[0]), d.map(x => x[1]), '#3498db', '#5dade2')
    },
    classPosition: (dom) => {
      const d = Object.entries(s.class_positions || {})
      return renderBar(dom, d.map(x => x[0]), d.map(x => x[1]), '#e74c3c', '#ec7063', true)
    },
    leaguePosition: (dom) => {
      const d = Object.entries(s.league_positions || {})
      return renderBar(dom, d.map(x => x[0]), d.map(x => x[1]), '#8e44ad', '#bb8fce', true)
    },
    highSchool: (dom) => {
      const d = Object.entries(s.high_schools || {}).slice(0, 15)
      return renderBar(dom, d.map(x => x[0]), d.map(x => x[1]), '#2ecc71', '#58d68d', true)
    },
  }
}

const overviewCards = computed(() => [
  { label: '总人数', value: total.value, color: '#409EFF' },
  { label: '男生', value: stats.value?.gender?.['男'] || 0, color: '#67C23A', key: 'male' },
  { label: '女生', value: stats.value?.gender?.['女'] || 0, color: '#F56C6C', key: 'female' },
  { label: '共青团员', value: stats.value?.political_status?.['共青团员'] || 0, color: '#E6A23C', key: 'league' },
  { label: '班委', value: stats.value?.class_committee_count || 0, color: '#9b59b6', key: 'committee' },
  { label: '团学会成员', value: stats.value?.league_count || 0, color: '#1abc9c', key: 'leagueMember' },
  { label: '贫困生', value: stats.value?.poor_student?.['是'] || 0, color: '#e74c3c', key: 'poor' },
  // 不数「有几种民族」而是数人：种类数只在每个少数民族恰好一个人时才等于名单行数，
  // 那样卡上的数字点开就会和弹窗里的条数对不上（见 utils/statGroups.js 的 countMinority）
  { label: '少数民族人数', value: countMinority(stats.value?.ethnicity), color: '#34495e', key: 'minority' },
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
    roster.value = buildRoster(key, await loadStudents())
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

onMounted(async () => {
  stats.value = await studentStore.fetchStatistics()
  total.value = stats.value.total || 0
  scoreSummary.value = stats.value.score_summary || scoreSummary.value

  // 遍历页面中所有图表容器，按 data-chart 匹配配置并初始化
  const builders = buildCharts(stats.value)
  document.querySelectorAll('.stat-chart').forEach(dom => {
    const key = dom.dataset.chart
    if (builders[key]) {
      chartInstances[key] = builders[key](dom)
    }
  })

  // 窗口尺寸变化时统一重绘
  window.addEventListener('resize', () => {
    Object.values(chartInstances).forEach(inst => inst.resize())
  })
})
</script>

<style scoped>
.statistics {
  /* 水印的定位基准：水印铺满整个统计页 */
  position: relative;
}

.mini-card {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 16px 20px;
  border-left: 4px solid #409EFF;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.05);
}

/* 能点开的卡：给个手型和抬起效果。否则「这儿能点」全靠猜 —— 页面上没有任何线索 */
.mini-card.clickable {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.mini-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 20px 0 rgba(0, 0, 0, 0.1);
}

.mini-value {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
}

.mini-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.stat-chart {
  width: 100%;
  height: 260px;
}

.chart-tall {
  height: 320px;
}

.chart-wide {
  height: 280px;
}

/* 手机上屏幕窄，缩一缩内边距和图表高度，少滚动几屏 */
@media (max-width: 768px) {
  .mini-card {
    padding: 12px 14px;
    margin-bottom: 12px;
  }

  .mini-value {
    font-size: 20px;
  }

  .stat-chart,
  .chart-tall,
  .chart-wide {
    height: 240px;
  }
}
</style>
