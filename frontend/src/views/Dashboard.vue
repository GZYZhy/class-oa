<template>
  <div class="dashboard">
    <!-- 欢迎横幅 -->
    <div class="welcome-banner">
      <div class="banner-content">
        <div>
          <h1>欢迎来到统26-1班</h1>
          <p>北方工业大学理学院统计学系 · 共{{ stats?.total || 0 }}名同学</p>
        </div>
        <img src="/logo.png" class="banner-logo" alt="校徽" />
      </div>
    </div>

    <!-- 访客提示：首页本来就对匿名开放，但开放的只有聚合数据。
         必须等 resolved 为真才判断，否则已登录用户会先闪一下这条 -->
    <el-alert v-if="showGuestTip" class="guest-tip" type="info" :closable="false" show-icon>
      <template #title>当前是访客浏览，只显示公开的统计数据</template>
      <div class="guest-tip-body">
        <span>查看学生信息、提交请假、下载资料、接收通知等操作需要登录。</span>
        <el-button type="primary" link @click="goLogin">去登录</el-button>
      </div>
    </el-alert>

    <!-- 顶部统计卡片 -->
    <el-row :gutter="20">
      <el-col :xs="12" :sm="6">
        <div class="stat-card card-blue">
          <div class="stat-icon"><el-icon><User /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats?.total || 0 }}</div>
            <div class="stat-label">总人数</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card card-pink">
          <div class="stat-icon"><el-icon><Female /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats?.gender?.['女'] || 0 }}</div>
            <div class="stat-label">女生人数</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card card-cyan">
          <div class="stat-icon"><el-icon><Male /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats?.gender?.['男'] || 0 }}</div>
            <div class="stat-label">男生人数</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card card-green">
          <div class="stat-icon"><el-icon><Medal /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats?.class_committee_count || 0 }}</div>
            <div class="stat-label">班委人数</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 保留的两个图表：性别 + 政治面貌 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">性别分布</h3>
          <div ref="genderChartRef" class="chart-container"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">政治面貌</h3>
          <div ref="politicalChartRef" class="chart-container"></div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { getPublicSummary } from '@/api/auth'
import { useUserStore } from '@/store/user'

const router = useRouter()
const userStore = useUserStore()

// 登录状态是 App.vue 挂载后异步恢复的（fetchMe），resolved 之前谁都说不准，
// 所以先不显示提示条，避免已登录用户看到它闪一下
const showGuestTip = computed(() => userStore.resolved && !userStore.isLogin)

function goLogin() {
  router.push({ path: '/login', query: { redirect: '/dashboard' } })
}

const stats = ref(null)

const genderChartRef = ref(null)
const politicalChartRef = ref(null)

let genderChart = null
let politicalChart = null

// 渲染环形饼图
function renderPie(refEl, data, colors) {
  const inst = echarts.init(refEl)
  inst.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c}人 ({d}%)' },
    legend: { bottom: '5%', left: 'center' },
    color: colors,
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 2 },
      label: { show: true, formatter: '{b}\n{c}人' },
      data: Object.entries(data).map(([name, value]) => ({ name, value }))
    }]
  })
  return inst
}

async function loadData() {
  // 首页走公开摘要接口：无需登录，且不含任何敏感字段
  stats.value = await getPublicSummary()
  await nextTick()
  genderChart = renderPie(genderChartRef.value, stats.value.gender || {}, ['#409EFF', '#F56C6C'])
  politicalChart = renderPie(politicalChartRef.value, stats.value.political_status || {}, ['#E6A23C', '#909399'])
}

onMounted(() => {
  loadData()
  window.addEventListener('resize', () => {
    genderChart?.resize()
    politicalChart?.resize()
  })
})
</script>

<style scoped>
.welcome-banner {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 28px 32px;
  color: #fff;
  margin-bottom: 20px;
  position: relative;
  overflow: hidden;
}

.welcome-banner::before {
  content: '';
  position: absolute;
  right: -40px;
  top: -40px;
  width: 200px;
  height: 200px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 50%;
}

.banner-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: relative;
  z-index: 1;
}

.banner-content h1 {
  font-size: 26px;
  margin: 0 0 8px 0;
  font-weight: 600;
}

.banner-content p {
  font-size: 14px;
  margin: 0;
  opacity: 0.9;
}

.banner-logo {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: #fff;
  padding: 6px;
  box-sizing: border-box;
  object-fit: cover;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

/* 访客提示：跟欢迎横幅留一样的间距，视觉上属于页面头部 */
.guest-tip {
  margin-bottom: 20px;
}

.guest-tip-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.stat-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.05);
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 20px 0 rgba(0, 0, 0, 0.1);
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30px;
  color: #fff;
}

.card-blue .stat-icon { background: linear-gradient(135deg, #409EFF, #66b1ff); }
.card-pink .stat-icon { background: linear-gradient(135deg, #F56C6C, #f89898); }
.card-cyan .stat-icon { background: linear-gradient(135deg, #1abc9c, #48c9b0); }
.card-green .stat-icon { background: linear-gradient(135deg, #67C23A, #85ce61); }

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-top: 4px;
}

.chart-container {
  width: 100%;
  height: 280px;
}

/* 手机上卡片只有半屏宽，图标和数字都收一号才放得下 */
@media (max-width: 768px) {
  .welcome-banner {
    padding: 18px 16px;
  }

  .banner-content h1 {
    font-size: 18px;
  }

  .banner-content p {
    font-size: 12px;
  }

  /* 横幅右侧校徽在窄屏上会把标题挤到换行，直接不显示 */
  .banner-logo {
    display: none;
  }

  .stat-card {
    padding: 12px;
    gap: 10px;
    margin-bottom: 12px;
  }

  .stat-icon {
    width: 40px;
    height: 40px;
    font-size: 20px;
    border-radius: 8px;
    flex-shrink: 0;
  }

  .stat-value {
    font-size: 20px;
  }

  .stat-label {
    font-size: 12px;
  }

  .chart-container {
    height: 220px;
  }
}
</style>
