<template>
  <div class="dashboard">
    <!-- 欢迎横幅：品牌信息都集中在这一块 —— 班级简称 + 一句副标题 + 学院/专业两个标签。
         配色是写死的紫蓝渐变，**刻意不跟深色模式**（同顶栏那个白底校徽） -->
    <div class="welcome-banner">
      <img :src="SITE.logoUrl" class="banner-logo" alt="校徽" />
      <div class="banner-text">
        <h1>欢迎来到{{ SITE.shortName }}</h1>
        <p v-if="SITE.subtitle" class="banner-subtitle">{{ SITE.subtitle }}</p>
        <!-- 学院、专业：各自判空，**不是拼成一句话再过滤** —— SITE 里没配就是空字符串、
             代码刻意不做兜底（utils/site.js 的口径），拼的话两个都空会渲染出一句孤零零的「 · 」 -->
        <div v-if="SITE.college || SITE.major" class="banner-chips">
          <span v-if="SITE.college" class="brand-chip">{{ SITE.college }}</span>
          <span v-if="SITE.major" class="brand-chip">{{ SITE.major }}</span>
        </div>
      </div>
    </div>

    <!-- 生日条幅：只有今天有人过生日才出现。
         匿名访客后端只下发人数（names 恒为空数组），登录后才可能带姓名 -->
    <div v-if="birthday?.count" class="birthday-banner">
      <el-icon class="birthday-icon"><Present /></el-icon>
      <span v-if="birthday.show_names">
        今天是 <strong>{{ birthday.names.join('、') }}</strong> 的生日，一起祝生日快乐！
      </span>
      <span v-else>今天有 {{ birthday.count }} 位同志生日啦</span>
    </div>

    <!-- 天气横幅：管理员在系统管理里配的广播提醒，命中条件才出现。
         和生日条幅并列，用冷色区分开；文案由后端算（和数据源同一套判断） -->
    <div v-if="weather?.banner?.active" class="weather-banner">
      <el-icon class="weather-banner-icon"><Warning /></el-icon>
      <div class="weather-banner-main">
        <span class="weather-banner-title">{{ weather.banner.title }}</span>
        <span class="weather-banner-text">{{ weather.banner.lines.join('；') }}</span>
      </div>
    </div>

    <!-- 访客提示：首页本来就对匿名开放，但开放的只有聚合数据。
         必须等 resolved 为真才判断，否则已登录用户会先闪一下这条 -->
    <el-alert v-if="showGuestTip" class="guest-tip" type="info" :closable="false" show-icon>
      <template #title>访客浏览，仅显示公开数据</template>
      <div class="guest-tip-body">
        <span>登录后可使用全部功能。</span>
        <el-button type="primary" link @click="goLogin">去登录</el-button>
      </div>
    </el-alert>

    <!-- 顶部统计卡片。
         标签一律用短词（「女生」而不是「女生人数」）：四字短语在窄屏上会被卡片宽度
         挤成两行，而这两行是卡片里唯一不会自己收窄的东西 -->
    <el-row :gutter="20">
      <el-col :xs="12" :sm="6">
        <div class="stat-card card-blue">
          <div class="stat-icon"><el-icon><User /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats?.total || 0 }}<span class="stat-unit">人</span></div>
            <div class="stat-label">总人数</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card card-pink">
          <div class="stat-icon"><el-icon><Female /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats?.gender?.['女'] || 0 }}<span class="stat-unit">人</span></div>
            <div class="stat-label">女生</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card card-cyan">
          <div class="stat-icon"><el-icon><Male /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats?.gender?.['男'] || 0 }}<span class="stat-unit">人</span></div>
            <div class="stat-label">男生</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card card-green">
          <div class="stat-icon"><el-icon><Medal /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats?.class_committee_count || 0 }}<span class="stat-unit">人</span></div>
            <div class="stat-label">班委</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 快捷入口：登录后才有（游客点进去也是被弹回来，不如不摆）。
         判据和侧边菜单同一份（utils/roles.js 的 canSee），所以这里的 role / studentOnly
         写法和路由 meta 逐字一致，改一处就得三处一起改 -->
    <div v-if="userStore.resolved && userStore.isLogin" class="page-card quick-card">
      <h3 class="page-title">快捷入口</h3>
      <div class="quick-grid">
        <router-link
          v-for="item in visibleShortcuts"
          :key="item.path"
          :to="item.path"
          class="quick-tile"
        >
          <div class="quick-icon" :class="item.theme">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>
          <span class="quick-name">{{ item.title }}</span>
        </router-link>
      </div>
    </div>

    <!-- 最新通知：接口本来就公开，游客也看得见。
         未读圆点必须绑在登录态上 —— 后端对游客恒返回 is_read=false，
         不判断的话游客页会整列都是红点 -->
    <div v-if="notices.length" class="page-card notice-card">
      <div class="card-head">
        <h3 class="page-title">最新通知</h3>
        <router-link to="/notices" class="more-link">
          更多<el-icon><ArrowRight /></el-icon>
        </router-link>
      </div>
      <ul class="notice-list">
        <li v-for="item in notices" :key="item.id">
          <!-- 点一条直接定位到那一篇（通知页认 ?id=，见 utils/notice.js） -->
          <router-link :to="`/notices?id=${item.id}`" class="notice-item">
            <span v-if="userStore.isLogin && !item.is_read" class="notice-dot" title="未读" />
            <span class="notice-title">{{ item.title }}</span>
            <span class="notice-date">{{ item.publish_date }}</span>
          </router-link>
        </li>
      </ul>
    </div>

    <!-- 性别分布 + 天气：天气卡替代了原来的政治面貌饼图 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :xs="24" :md="12">
        <div class="page-card">
          <h3 class="page-title">性别分布</h3>
          <div ref="genderChartRef" class="chart-container"></div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <!-- 整卡可点：有新窗口打开天气网站。位置名/经纬度/跳转地址全在 .env 里配 -->
        <div
          class="page-card weather-card"
          :class="{ clickable: weather?.site_url }"
          :title="weather?.site_url ? '点击打开天气网站' : ''"
          @click="openWeatherSite"
        >
          <h3 class="page-title">
            天气
            <span v-if="weather?.name" class="weather-place">{{ weather.name }}</span>
          </h3>

          <!-- 正常：温度 + 天气 + 高低温 -->
          <div v-if="weatherState === 'ok'" class="weather-body">
            <div class="weather-main">
              <el-icon class="weather-icon">
                <component :is="weather.icon || 'Cloudy'" />
              </el-icon>
              <span class="weather-temp">{{ weather.temp }}°</span>
            </div>
            <div class="weather-text">{{ weather.text }}</div>
            <div class="weather-range">
              最低 {{ weather.low }}° · 最高 {{ weather.high }}°
            </div>
            <!-- 明天的情况：和管理员配置的时段无关，固定给一行概览 -->
            <div v-if="weather.tomorrow" class="weather-tomorrow">
              <span class="wt-label">明天</span>
              <el-icon class="wt-icon"><component :is="weather.tomorrow.icon" /></el-icon>
              <span class="wt-text">{{ weather.tomorrow.text }}</span>
              <span class="wt-range">{{ weather.tomorrow.low }}°~{{ weather.tomorrow.high }}°</span>
              <span class="wt-pop">降水 {{ weather.tomorrow.pop }}%</span>
            </div>

            <div class="weather-foot">
              <span>体感 {{ weather.feels_like }}°</span>
              <span>数据：Open-Meteo</span>
            </div>
          </div>

          <!-- 加载中：骨架而不是「未配置」。弱网下这两者差得很远，
               把「还在路上」显示成「没配」会让人以为功能坏了 -->
          <div v-else-if="weatherState === 'loading'" class="weather-body" aria-busy="true">
            <div class="weather-skeleton weather-skeleton-temp"></div>
            <div class="weather-skeleton weather-skeleton-line"></div>
          </div>

          <!-- 没配 / 配错 / 取不到：说清楚是哪种，别一句「未配置」糊过去 -->
          <div v-else class="weather-body weather-empty">
            <el-icon class="weather-empty-icon"><component :is="weatherEmptyIcon" /></el-icon>
            <div class="weather-empty-title">{{ weatherEmptyText }}</div>
            <div class="weather-empty-hint">{{ weatherEmptyHint }}</div>
            <!-- 这三种状态下只要配了跳转地址，卡片照样能点开天气网站 -->
            <el-button
              v-if="weather?.site_url"
              link
              type="primary"
              size="small"
              @click.stop="openWeatherSite"
            >
              打开天气网站
            </el-button>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 逐小时预报：和天气卡同一个接口返回，不多一次请求。
         横条可横向滚动 —— 手机上 12 格塞不下，别硬压 -->
    <div v-if="weather?.hourly?.length" class="page-card hourly-card">
      <h3 class="page-title">未来 12 小时</h3>
      <div class="hourly-strip">
        <div v-for="h in weather.hourly" :key="h.time" class="hour-cell">
          <span class="hour-time">{{ h.time }}</span>
          <el-icon class="hour-icon"><component :is="h.icon" /></el-icon>
          <span class="hour-temp">{{ h.temp }}°</span>
          <span class="hour-pop" :class="{ wet: h.pop >= 30 }">{{ h.pop }}%</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { getPublicSummary } from '@/api/auth'
import { getBirthdayToday } from '@/api/birthday'
import { getWeather } from '@/api/weather'
import { getNotices } from '@/api/notice'
import { useUserStore } from '@/store/user'
import { canSee } from '@/utils/roles'
import { SITE } from '@/utils/site'

const router = useRouter()
const userStore = useUserStore()

// 登录状态是 App.vue 挂载后异步恢复的（fetchMe），resolved 之前谁都说不准，
// 所以先不显示提示条，避免已登录用户看到它闪一下
const showGuestTip = computed(() => userStore.resolved && !userStore.isLogin)

function goLogin() {
  router.push({ path: '/login', query: { redirect: '/dashboard' } })
}

const stats = ref(null)
// 今日生日条幅数据；null 表示还没取到或今天没人过生日（两种情况都不显示）
const birthday = ref(null)
// 首页只放最新几条；空数组时整块不渲染
const notices = ref([])

/** 首页「最新通知」要几条。
 *
 * 后端列表接口有 limit 参数，**只取这么多、不是取回来再切片** —— 每条通知都带着
 * 整篇 Markdown 正文，首页为 5 行标题拉回全班历来通知的全文不划算 */
const NOTICE_COUNT = 5

/** 快捷入口。
 *
 * 字段口径（public / studentOnly / role）和侧边菜单、路由 meta **完全一致**，
 * 就是为了能直接套用 utils/roles.js 那份 canSee —— 判据只剩一份，
 * 不会出现「首页摆得出来、点进去被守卫弹回首页」。
 * render.mjs 有一节比着 router/index.js 的 meta 逐条断，加项时照着改。
 */
const SHORTCUTS = [
  { path: '/notices', title: '通知公告', icon: 'Bell', theme: 'tile-blue', public: true },
  { path: '/service', title: '办事中心', icon: 'Postcard', theme: 'tile-cyan', studentOnly: true },
  { path: '/leave', title: '请假申请', icon: 'Document', theme: 'tile-green', studentOnly: true },
  { path: '/schedule', title: '我的日程', icon: 'Calendar', theme: 'tile-purple', studentOnly: true },
  { path: '/downloads', title: '资料下载', icon: 'Download', theme: 'tile-orange' },
  { path: '/students', title: '学生信息', icon: 'List', theme: 'tile-pink', role: 'committee' },
  { path: '/review', title: '审核审批', icon: 'Checked', theme: 'tile-indigo', role: 'committee' },
  { path: '/statistics', title: '分类统计', icon: 'PieChart', theme: 'tile-teal', role: 'committee' }
]

const visibleShortcuts = computed(() => SHORTCUTS.filter((item) => canSee(item, userStore)))

const genderChartRef = ref(null)

let genderChart = null

// 天气卡：null = 还在路上；回来之后由后端给的 state 决定怎么显示
const weather = ref(null)

const weatherState = computed(() => weather.value?.state || 'loading')

/** 三种「没有数据」的情况分开说，不然用户分不清是没配还是挂了 */
const weatherEmptyText = computed(
  () =>
    ({
      unconfigured: '天气未配置',
      invalid: '天气配置无效',
      error: '天气暂时获取不到'
    })[weatherState.value] || '天气暂时获取不到'
)

const weatherEmptyHint = computed(
  () =>
    ({
      unconfigured: '在 .env 里填 WEATHER_LAT / WEATHER_LON 即可开启',
      invalid: '经纬度需为有效数字：纬度 -90~90，经度 -180~180',
      error: '稍后刷新重试，或直接打开天气网站'
    })[weatherState.value] || ''
)

const weatherEmptyIcon = computed(() => (weatherState.value === 'error' ? 'Warning' : 'InfoFilled'))

/** 天气单独一路，**不 await**：最坏要等后端那 3 秒超时，不能把图表和通知拖在后面 */
async function loadWeather() {
  try {
    weather.value = await getWeather()
  } catch (e) {
    // 接口本身挂了也当作「暂时取不到」：卡片留在原处，不弹错、不影响页面上其它内容
    weather.value = { state: 'error', site_url: '' }
  }
}

/** 点整卡新开天气网站。没配 WEATHER_SITE_URL 时不可点（见模板上的 clickable） */
function openWeatherSite() {
  const url = weather.value?.site_url
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

// 图表模块。**故意不在文件顶部 import** —— 它是首屏最重的一件，
// 动态引进来才能让统计数字先出来（见下面 loadData 里那段注释）。
// 取回来的是 { default: echarts, renderDonut, ... }，环形图直接调共用的那个，
// 与分类统计页同一套配色和样式（同是「人数占比」，两页不该长成两家）
let chartKit = null

const toList = (obj) => Object.entries(obj || {}).map(([name, value]) => ({ name, value }))

/** 画/重画性别环。颜色随主题，所以切深浅模式时也要再走一遍 */
function renderCharts() {
  if (!chartKit || !genderChartRef.value) return
  genderChart?.dispose()
  genderChart = chartKit.renderDonut(genderChartRef.value, toList(stats.value?.gender))
}

async function loadData() {
  // 天气先发出去，**不等它**：它最坏要等后端 3 秒超时，
  // 串进下面的 await 链会把人数、通知、图表一起拖住
  loadWeather()

  // 首页走公开摘要接口：无需登录，且不含任何敏感字段
  stats.value = await getPublicSummary()

  // 生日条幅和最新通知都属于锦上添花：各自兜各自的异常，谁挂了都不连累首页统计
  // （后端没升级到有生日接口时也走这条）。两路一起发，别串着等
  const [today, list] = await Promise.allSettled([
    getBirthdayToday(),
    getNotices({ limit: NOTICE_COUNT })
  ])
  if (today.status === 'fulfilled') birthday.value = today.value
  if (list.status === 'fulfilled') notices.value = list.value

  await nextTick()

  // 图表库单独**动态**取一次（按需之后的体积说明见 utils/chart.js）。
  // 上面那几个 await 一到手，人数、生日条幅、最新通知就已经渲染出来了，
  // 不必等图表库；弱网下这几秒的差别就是「首页能看了」和「整页白等着」的差别
  chartKit = await import('@/utils/chart')

  // 取库的这段时间里用户可能已经离开首页、容器被卸载了，这时 init 会拿到 null
  renderCharts()
}

function onResize() {
  genderChart?.resize()
}

// 深浅模式切换时重画：ECharts 的配色是 init 时从 CSS 变量读的，不重画就停在旧主题
let themeObserver = null

onMounted(() => {
  loadData()
  window.addEventListener('resize', onResize)
  themeObserver = new MutationObserver(() => renderCharts())
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  themeObserver?.disconnect()
  genderChart?.dispose()
})
</script>

<style scoped>
.welcome-banner {
  /* 三段式紫色序列（靛蓝→薰衣草）。之前尾端的天青拿掉了 ——
     蓝交给左下那团浅蓝光斑和副色系去说，横幅本身保持纯净 */
  background: linear-gradient(135deg, #6269f0 0%, #8b7bf2 58%, #a78bfa 100%);
  border-radius: var(--app-radius);
  padding: 30px 34px;
  color: #fff;
  margin-bottom: 20px;
  box-shadow: 0 14px 36px rgba(104, 110, 240, 0.20);
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 20px;
}

/* 两团光斑对角布置（右上大、左下小），把横幅从「一块色块」变成有层次的版面。
   左下这团是浅蓝 —— 副色在品牌横幅上的一次点到为止 */
.welcome-banner::before {
  content: '';
  position: absolute;
  right: -40px;
  top: -40px;
  width: 220px;
  height: 220px;
  background: rgba(255, 255, 255, 0.09);
  border-radius: 50%;
}

.welcome-banner::after {
  content: '';
  position: absolute;
  left: -30px;
  bottom: -60px;
  width: 180px;
  height: 180px;
  background: rgba(125, 211, 252, 0.20);
  border-radius: 50%;
}

.banner-text {
  position: relative;
  z-index: 1;
  min-width: 0;
}

.banner-text h1 {
  font-size: 26px;
  margin: 0 0 8px 0;
  font-weight: 700;
  letter-spacing: 0.6px;
  /* 白字压渐变上仍带一点投影，大标题才立得住（深底浅字，明暗模式都成立） */
  text-shadow: 0 2px 10px rgba(49, 46, 129, 0.25);
}

.banner-subtitle {
  font-size: 14px;
  margin: 0;
  opacity: 0.9;
}

/* 学院 / 专业：两个半透明小胶囊。用半透明白而不是固定色，横幅换配色时不用跟着改 */
.banner-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.brand-chip {
  font-size: 12px;
  line-height: 1;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.28);
}

.banner-logo {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  /* 固定白色，不跟深色模式：所在的家园横幅是写死的紫蓝渐变，同顶栏校徽 */
  background: #fff;
  padding: 6px;
  box-sizing: border-box;
  object-fit: cover;
  /* 白描边让校徽和渐变底之间有一圈「呼吸」的留白，比投影更干净 */
  border: 3px solid rgba(255, 255, 255, 0.9);
  box-shadow: 0 6px 16px rgba(49, 46, 129, 0.22);
  flex-shrink: 0;
}

/* 生日条幅：跟在欢迎横幅后面，用暖色和它区分开。
   固定色值，不跟深色模式 —— 同 .welcome-banner / 顶栏校徽的做法。
   起手淡玫、收进暖橙：比原来的深玫红更「清晨感」，和主横幅的冷蓝正好互补 */
.birthday-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  background: linear-gradient(135deg, #f790a7 0%, #ee7c6f 100%);
  color: #fff;
  border-radius: var(--app-radius);
  padding: 14px 20px;
  margin-bottom: 20px;
  font-size: 15px;
  box-shadow: 0 12px 30px rgba(238, 124, 111, 0.20);
}

.birthday-icon {
  font-size: 22px;
  flex-shrink: 0;
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

/* 天气横幅：和生日条幅并列，用天青系和它的暖橙区分开 */
.weather-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: linear-gradient(135deg, #57a8e8 0%, #3f79d8 100%);
  color: #fff;
  border-radius: var(--app-radius);
  padding: 14px 20px;
  margin-bottom: 20px;
  font-size: 14px;
  box-shadow: 0 12px 30px rgba(63, 121, 216, 0.20);
}

.weather-banner-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.weather-banner-main {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  min-width: 0;
}

.weather-banner-title {
  font-weight: 600;
}

.weather-banner-text {
  opacity: 0.92;
}

.stat-card {
  /* 和 page-card 同一道受光面 */
  background: var(--app-surface-sheen) padding-box;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  /* 分层投影 + 顶部内高光，和 .page-card 同一套玻璃质感 */
  box-shadow: var(--app-shadow), var(--app-card-inset);
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--app-shadow-hover), var(--app-card-inset);
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30px;
  color: #fff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

/* 图标渐变调回「中调起点」：上一版压淡半档后和浅卡片糊在一起、对比不足，
   现在起点加深一档、终点保持柔，白图标始终清晰 */
.card-blue .stat-icon { background: linear-gradient(135deg, #4d84ee, #83aef7); box-shadow: 0 8px 18px rgba(77, 132, 238, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.35); }
.card-pink .stat-icon { background: linear-gradient(135deg, #ec6d8c, #f5a3b4); box-shadow: 0 8px 18px rgba(236, 109, 140, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.35); }
.card-cyan .stat-icon { background: linear-gradient(135deg, #2bb3a0, #6ed4c2); box-shadow: 0 8px 18px rgba(43, 179, 160, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.35); }
.card-green .stat-icon { background: linear-gradient(135deg, #52b864, #8cd996); box-shadow: 0 8px 18px rgba(82, 184, 100, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.35); }

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
  letter-spacing: 0.3px;
  font-variant-numeric: tabular-nums;
  /* 数字永远不换行：卡片被挤窄时「36」会被折成上下两个数字，看着像写错了。
     见下面那条 iPad 竖屏的媒体查询 —— 空间不够是根源，这里是兜底 */
  white-space: nowrap;
}

/* 「人」跟在数字后面，小一号、淡一档：标签已经说明了是什么人，
   这个字只是把「36」从裸数字变成量词 */
.stat-unit {
  font-size: 13px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
  margin-left: 3px;
}

.stat-label {
  font-size: 14px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

/* 快捷入口 / 最新通知这两块都跟在统计卡后面，间距和图表那行保持一致 */
.quick-card,
.notice-card {
  margin-top: 20px;
}

/* 磁贴的列数按屏宽分三档：手机两列、平板四列、宽屏一行八块。
   试过 auto-fill + 最小宽度那种「不用写媒体查询」的写法，但在 1280 的桌面上
   算下来是 7 列 —— 八块磁贴排成 7+1，最后一块孤零零占一整行，很难看。
   八块是上限（普通学生只有五块），一行八块、一行四块都不会有零头溢出来。 */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.quick-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 16px 8px;
  border-radius: 16px;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--app-outline);
  color: var(--el-text-color-primary);
  text-decoration: none;
  transition: all 0.2s;
}

.quick-tile:hover {
  background: var(--app-secondary-soft);
  border-color: var(--app-secondary-border);
  color: var(--app-secondary-deep);
  transform: translateY(-2px);
  box-shadow: 0 8px 18px rgba(47, 157, 228, 0.14);
}

.quick-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 21px;
  /* 白字压在彩色渐变上，明暗两种模式下都清晰，所以这几个色值写死、不跟深色模式 */
  color: #fff;
}

.quick-name {
  font-size: 13px;
}

/* 每个入口一个色，和卡片图标用的是同一套渐变 */
.tile-blue { background: linear-gradient(135deg, #409EFF, #66b1ff); }
.tile-cyan { background: linear-gradient(135deg, #1abc9c, #48c9b0); }
.tile-green { background: linear-gradient(135deg, #67C23A, #85ce61); }
.tile-purple { background: linear-gradient(135deg, #8e6bd6, #ab8ee0); }
.tile-orange { background: linear-gradient(135deg, #E6A23C, #ebb563); }
.tile-pink { background: linear-gradient(135deg, #F56C6C, #f89898); }
.tile-indigo { background: linear-gradient(135deg, #5b6ee0, #7d8ce8); }
.tile-teal { background: linear-gradient(135deg, #2f9fb5, #52b8cb); }

/* 卡片标题 + 右侧「更多」：标题自带的 margin-bottom 会把这一行撑高，
   这里交给 flex 对齐，margin 压掉 */
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.card-head .page-title {
  margin-bottom: 0;
}

.more-link {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  text-decoration: none;
  flex-shrink: 0;
}

.more-link:hover {
  color: var(--app-secondary-deep);
}

.notice-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.notice-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 10px;
  color: var(--el-text-color-primary);
  text-decoration: none;
  transition: background 0.2s;
}

/* 行与行之间一道分隔线：五条通知原本挤成一团，加线之后每条自成一行，
   扫读时眼睛有落点（线用 outline 那档，比卡片外框淡） */
.notice-list li + li {
  border-top: 1px solid var(--app-outline);
}

.notice-item:hover {
  background: var(--el-fill-color-light);
}

.notice-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--el-color-danger);
  flex-shrink: 0;
}

/* 标题占满剩下的宽度、超长省略；日期固定不缩，否则长标题会把日期挤没 */
.notice-title {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.notice-date {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.chart-container {
  width: 100%;
  height: 280px;
}

/* ============ 天气卡 ============
   占的格子原来放政治面貌饼图，所以高度要跟左边图表对齐（280px），
   否则同一行两个卡片会一高一矮 */
.weather-card {
  display: flex;
  flex-direction: column;
}

.weather-card.clickable {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.weather-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: var(--app-shadow-hover), var(--app-card-inset);
}

.weather-place {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
  margin-left: 8px;
  letter-spacing: 0;
}

.weather-body {
  flex: 1;
  min-height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.weather-main {
  display: flex;
  align-items: center;
  gap: 14px;
}

.weather-icon {
  font-size: 44px;
  color: var(--app-secondary);
}

.weather-temp {
  font-size: 46px;
  font-weight: 700;
  line-height: 1;
  color: var(--el-text-color-primary);
  /* 数字宽度固定，切个温度不会左右跳 */
  font-variant-numeric: tabular-nums;
}

.weather-text {
  font-size: 15px;
  color: var(--el-text-color-regular);
}

.weather-range {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.weather-foot {
  display: flex;
  gap: 14px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

/* 明天那一行：卡片里最下面的一条概览，淡底把它和上面的「现在」分开 */
.weather-tomorrow {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 14px;
  border-radius: 999px;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--app-outline);
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.wt-label {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.wt-icon {
  font-size: 15px;
  color: var(--app-secondary);
}

.wt-range,
.wt-pop {
  color: var(--el-text-color-secondary);
}

/* 逐小时横条 */
.hourly-card {
  margin-top: 20px;
}

.hourly-strip {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
  /* 触屏上惯性滑动，桌面上滚轮横滚也能用 */
  -webkit-overflow-scrolling: touch;
}

.hour-cell {
  flex: 0 0 auto;
  width: 64px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 10px 6px;
  border-radius: 12px;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--app-outline);
}

.hour-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.hour-icon {
  font-size: 20px;
  color: var(--app-secondary);
}

.hour-temp {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.hour-pop {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

/* 概率过 30% 才提亮：全都加粗等于强调了个寂寞 */
.hour-pop.wet {
  color: var(--app-secondary-deep);
  font-weight: 600;
}

.weather-empty {
  gap: 6px;
  text-align: center;
}

.weather-empty-icon {
  font-size: 26px;
  color: var(--el-text-color-placeholder);
}

.weather-empty-title {
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.weather-empty-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  max-width: 260px;
  line-height: 1.6;
}

/* 骨架：弱网下先占住版面，避免数据回来时整块跳一下 */
.weather-skeleton {
  border-radius: 10px;
  background: linear-gradient(
    90deg,
    var(--el-fill-color-light) 25%,
    var(--el-fill-color-lighter) 37%,
    var(--el-fill-color-light) 63%
  );
  background-size: 400% 100%;
  animation: weather-shimmer 1.4s ease-in-out infinite;
}

.weather-skeleton-temp {
  width: 120px;
  height: 46px;
}

.weather-skeleton-line {
  width: 150px;
  height: 14px;
}

@keyframes weather-shimmer {
  from {
    background-position: 100% 50%;
  }

  to {
    background-position: 0 50%;
  }
}

/* 动效敏感的用户（vestibular 障碍等）直接停掉闪烁 */
@media (prefers-reduced-motion: reduce) {
  .weather-skeleton {
    animation: none;
  }
}

/* iPad 竖屏那一段（810 / 820 / 834px）：它在 768 之上，拿不到下面那套手机尺寸，
   于是四张卡按**桌面尺寸**（图标 60px、数字 28px、内边距 20px）挤在 1/4 宽里 ——
   「36」这种两位数当场被压成上下两个数字，标签「总人数」也竖成三行。
   这里单独收一号，把 769~991 这段补齐（992 起是 md，1/4 宽够放桌面尺寸） */
@media (min-width: 769px) and (max-width: 992px) {
  .stat-card {
    padding: 14px;
    gap: 12px;
  }

  .stat-icon {
    width: 44px;
    height: 44px;
    font-size: 22px;
    border-radius: 10px;
    flex-shrink: 0;
  }

  .stat-value {
    font-size: 22px;
  }

  .stat-label {
    font-size: 12px;
  }
}

/* 手机上卡片只有半屏宽，图标和数字都收一号才放得下 */
@media (max-width: 768px) {
  .welcome-banner {
    padding: 18px 16px;
    gap: 14px;
  }

  .banner-text h1 {
    font-size: 18px;
  }

  .banner-subtitle {
    font-size: 12px;
  }

  /* 校徽在窄屏上收小而不是藏起来：它现在在标题**左边**，
     和文字抢的那点宽度收一号就够，没必要把品牌整个拿掉 */
  .banner-logo {
    width: 44px;
    height: 44px;
    padding: 4px;
  }

  .brand-chip {
    font-size: 11px;
    padding: 4px 8px;
  }

  .birthday-banner {
    padding: 12px 14px;
    font-size: 13px;
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

  .quick-grid {
    gap: 10px;
  }

  .quick-tile {
    padding: 12px 6px;
    gap: 8px;
  }

  .chart-container {
    height: 220px;
  }

  /* 天气卡跟着图表一起收，两个卡片在手机上一上一下，高度对不齐没人看得出来，
     但也别占太多屏 */
  .weather-body {
    min-height: 200px;
  }

  .weather-icon {
    font-size: 36px;
  }

  .weather-temp {
    font-size: 38px;
  }
}

/* 快捷入口的列数（配合上面 .quick-grid 那条基础规则里的注释看）：
   768 以下两列、768~1199 四列、1200 以上一行八块。
   断点跟着侧边栏走 —— 1200 减去侧栏和两边留白，八块每块还有 105px 左右 */
@media (min-width: 769px) {
  .quick-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (min-width: 1200px) {
  .quick-grid {
    grid-template-columns: repeat(8, 1fr);
  }
}
</style>
