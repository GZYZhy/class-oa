<template>
  <!-- 公开页：从链接直接进来，不套侧边栏（路由 meta.bare）。
       没登录也能看到这次签到是什么；真正签到要登录，登录后自动回到这里 -->
  <div class="checkin-page">
    <div class="ck-card">
      <div class="ck-head">
        <img src="/logo.png" class="ck-logo" alt="校徽" />
        <h1 class="ck-site">{{ SITE.name }}</h1>
      </div>

      <div v-if="loading" class="ck-loading">正在读取签到信息…</div>

      <el-result
        v-else-if="error"
        icon="warning"
        title="打不开这次签到"
        :sub-title="error"
      >
        <template #extra>
          <a href="#/" class="ck-plain-link">回首页</a>
        </template>
      </el-result>

      <template v-else-if="info">
        <div class="ck-title-row">
          <h2 class="ck-title">{{ info.title }}</h2>
          <el-tag :type="info.status === 'ongoing' ? 'success' : 'info'" size="small">
            {{ info.status === 'ongoing' ? '进行中' : '已结束' }}
          </el-tag>
        </div>
        <p v-if="info.remark" class="ck-remark">{{ info.remark }}</p>

        <div class="ck-meta">
          <span>{{ info.created_by_name }} 发布</span>
          <span>截止 {{ formatDateTime(info.end_at) }}</span>
          <span>应到 {{ info.target_count }} 人</span>
        </div>

        <!-- 只读地图：地图没配就显示经纬度，不影响签到本身 -->
        <div v-if="info.location" class="ck-location">
          <div class="ck-loc-head">
            签到地点：{{ info.location.name || '指定地点' }}
            <span class="ck-sub">（允许半径 {{ info.location.radius_m }} 米）</span>
          </div>
          <MapPicker
            :model-value="{ lat: info.location.lat, lng: info.location.lng }"
            :radius="info.location.radius_m"
            readonly
          />
        </div>

        <!-- ---------- 进行中 ---------- -->
        <div v-if="info.status === 'ongoing'" class="ck-actions">
          <template v-if="!info.is_login">
            <!-- 未登录是这一页唯一的行动号召，提示和按钮都居中放 -->
            <div class="ck-login">
              <p class="ck-tip">登录后即可签到。本次签到仅限范围内的同学</p>
              <a :href="loginHref"><el-button type="primary" size="large">登录后签到</el-button></a>
            </div>
          </template>
          <p v-else-if="!info.is_target" class="ck-tip ck-warn">
            你不在本次签到范围内，不需要签到
          </p>
          <p v-else-if="info.signed_at" class="ck-tip ck-ok">
            你已于 {{ formatDateTime(info.signed_at) }} 签到
            <template v-if="info.my_distance_m != null">
              ，距签到地点约 {{ info.my_distance_m }} 米
            </template>
          </p>
          <template v-else>
            <p v-if="info.on_leave" class="ck-tip">
              你在这次签到时段有已批准的请假。现在签到会记为「到」；不签则记为「请假」
            </p>
            <el-button type="primary" size="large" @click="signRef.open(info)">
              立即签到
            </el-button>
          </template>
        </div>

        <!-- ---------- 已结束：给本人一个最终说法 ---------- -->
        <div v-else class="ck-actions">
          <p v-if="info.signed_at" class="ck-tip ck-ok">
            你已于 {{ formatDateTime(info.signed_at) }} 签到，记为「到」
          </p>
          <p v-else-if="!info.is_login" class="ck-tip">这次签到已经结束</p>
          <p v-else-if="info.on_leave" class="ck-tip">
            你没有签到，但截止时持有已批准的请假，记为「请假」
          </p>
          <p v-else class="ck-tip ck-warn">你没有签到，记为「无应答」</p>
        </div>
      </template>
    </div>

    <CheckinSignDialog ref="signRef" @signed="onSigned" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import CheckinSignDialog from '@/components/CheckinSignDialog.vue'
import MapPicker from '@/components/MapPicker.vue'
import { getCheckinPublic } from '@/api/checkin'
import { useUserStore } from '@/store/user'
import { formatDateTime } from '@/utils/format'
import { errText } from '@/utils/request'
import { SITE } from '@/utils/site'

const route = useRoute()
const userStore = useUserStore()

const loading = ref(true)
const error = ref('')
const info = ref(null)
const signRef = ref(null)

const loginHref = computed(() => {
  const back = `/checkin?code=${encodeURIComponent(route.query.code || '')}`
  return `#/login?redirect=${encodeURIComponent(back)}`
})

async function load() {
  if (!route.query.code) {
    loading.value = false
    error.value = '链接不完整，请向发布人重新要一次签到链接'
    return
  }
  loading.value = true
  error.value = ''
  // 公开页的路由守卫不会去问后端登录状态，这里补一次，才能知道 is_login 和 is_target
  if (!userStore.resolved) await userStore.fetchMe()
  try {
    info.value = await getCheckinPublic(route.query.code)
    // 能签就直接弹出来 —— 用户点链接进来就是为了签到，少点一次
    if (info.value.can_sign) signRef.value?.open(info.value)
  } catch (e) {
    error.value = errText(e, '签到不存在或链接已失效')
  } finally {
    loading.value = false
  }
}

function onSigned(result) {
  info.value = result
}

onMounted(load)
</script>

<style scoped>
.checkin-page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 32px 12px;
  box-sizing: border-box;
  background: linear-gradient(135deg, #1f2d3d 0%, #2c3e50 55%, #3a5169 100%);
}

.ck-card {
  width: 520px;
  max-width: 100%;
  padding: 28px 28px 24px;
  background: var(--el-bg-color);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 21, 41, 0.3);
}

.ck-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}

.ck-logo {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  object-fit: cover;
}

.ck-site {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.ck-loading {
  padding: 40px 0;
  text-align: center;
  color: var(--el-text-color-secondary);
}

.ck-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.ck-title {
  margin: 0;
  font-size: 20px;
  color: var(--el-text-color-primary);
}

.ck-remark {
  margin: 10px 0 0;
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  line-height: 1.6;
}

.ck-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-top: 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.ck-location {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ck-loc-head {
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.ck-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.ck-actions {
  margin-top: 22px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}

.ck-login {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
}

.ck-actions .el-button {
  min-width: 160px;
}

.ck-tip {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

.ck-warn {
  color: var(--el-color-warning);
}

.ck-ok {
  color: var(--el-color-success);
  font-weight: 600;
}

.ck-plain-link {
  color: var(--el-color-primary);
  text-decoration: none;
}
</style>
