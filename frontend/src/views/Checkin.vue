<template>
  <!-- 公开页：从链接或站内信直接进来，不套侧边栏（路由 meta.bare）。
       没登录也能看到这次签到是什么；真正签到要登录，登录后自动回到这里。
       签到表单直接长在这张卡片里，不再另开弹窗 —— 入口只有一个，样子也一致 -->
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
        :title="notFound ? '链接已失效' : '打不开这次签到'"
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

        <!-- 要求对所有人公开：没登录、已结束都能看到；地点地图也照常展示 -->
        <div class="ck-req">
          <span class="ck-label">签到要求</span>
          <span v-if="info.location">
            在「{{ info.location.name || '指定地点' }}」{{ info.location.radius_m }} 米范围内
          </span>
          <span v-if="info.location && info.require_photo">、</span>
          <span v-if="info.require_photo">上传一张照片</span>
          <span v-if="!info.location && !info.require_photo">
            无需定位和照片，确认到场即可
          </span>
        </div>

        <!-- 只读地图：地图没配就显示经纬度，不影响签到本身。
             截止之后链接仍可打开，这里也照常展示 -->
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
            <div class="ck-center">
              <p class="ck-tip">登录后即可签到。本次签到仅限范围内的同学</p>
              <a :href="loginHref"><el-button type="primary" size="large">登录后签到</el-button></a>
            </div>
          </template>
          <p v-else-if="!info.is_target" class="ck-tip ck-warn">
            你不在本次签到范围内，不需要签到
          </p>
          <div v-else-if="info.signed_at" class="ck-center">
            <p class="ck-tip ck-ok">
              你已于 {{ formatDateTime(info.signed_at) }} 签到
              <template v-if="info.my_distance_m != null">
                ，距签到地点约 {{ info.my_distance_m }} 米
              </template>
            </p>
            <a href="#/"><el-button size="large">回首页</el-button></a>
          </div>

          <!-- ---------- 签到表单（就在页面里） ---------- -->
          <template v-else>
            <p v-if="info.on_leave" class="ck-tip">
              你在这次签到时段有已批准的请假。现在签到会记为「到」；不签则记为「请假」
            </p>

            <div v-if="info.location" class="ck-block">
              <div class="ck-block-head">
                <span class="ck-label">签到地点</span>
                <span>{{ info.location.name || '指定地点' }}</span>
              </div>
              <div class="ck-line">
                <span class="ck-label">我的位置</span>
                <template v-if="locating">定位中…</template>
                <template v-else-if="position">
                  <span :class="{ 'ck-warn': !withinRadius }">
                    距签到地点约 {{ distance }} 米（允许 {{ info.location.radius_m }} 米）
                  </span>
                </template>
                <span v-else class="ck-warn">还没有定位</span>
                <el-button link type="primary" :loading="locating" @click="locate">
                  {{ position ? '重新定位' : '获取位置' }}
                </el-button>
              </div>
              <p v-if="position && !withinRadius" class="ck-tip ck-warn">
                当前位置超出允许范围，请到签到地点附近再试
              </p>
            </div>

            <div v-if="info.require_photo" class="ck-block">
              <div class="ck-block-head">
                <span class="ck-label">照片</span>
                <span>本次签到需要一张照片</span>
              </div>
              <!-- 用原生 input：手机点一下就能调起相机，比套一层上传组件轻 -->
              <input
                ref="fileInput"
                type="file"
                accept="image/*"
                capture="environment"
                class="ck-file"
                @change="onFileChange"
              />
              <div class="ck-line">
                <span class="ck-tip">
                  {{ file ? `已选择：${file.name}` : '请拍照或从相册选一张' }}
                </span>
                <el-button link type="primary" :loading="compressing" @click="fileInput?.click()">
                  {{ file ? '重新选择' : '选择照片' }}
                </el-button>
              </div>
            </div>

            <p v-if="!info.location && !info.require_photo" class="ck-tip">
              确认你已到场，点下面的按钮完成签到
            </p>
            <!-- 唯一的主按钮居中，和登录、已签到两个状态的按钮对齐 -->
            <div class="ck-center">
              <el-button type="primary" size="large" :loading="submitting" @click="handleSubmit">
                确认签到
              </el-button>
            </div>
          </template>
        </div>

        <!-- ---------- 已结束：给本人一个最终说法 ---------- -->
        <div v-else class="ck-actions">
          <div v-if="info.signed_at" class="ck-center">
            <p class="ck-tip ck-ok">
              你已于 {{ formatDateTime(info.signed_at) }} 签到，记为「到」
            </p>
            <a href="#/"><el-button size="large">回首页</el-button></a>
          </div>
          <p v-else-if="!info.is_login" class="ck-tip">这次签到已经结束</p>
          <p v-else-if="info.on_leave" class="ck-tip">
            你没有签到，但截止时持有已批准的请假，记为「请假」
          </p>
          <p v-else class="ck-tip ck-warn">你没有签到，记为「无应答」</p>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import MapPicker from '@/components/MapPicker.vue'
import { getCheckinPublic, signCheckin } from '@/api/checkin'
import { useUserStore } from '@/store/user'
import { compressImage } from '@/utils/imageCompress'
import { distanceMeters, getCurrentLocation } from '@/utils/geolocation'
import { formatDateTime } from '@/utils/format'
import { errText } from '@/utils/request'
import { SITE } from '@/utils/site'

const route = useRoute()
const userStore = useUserStore()

const loading = ref(true)
const error = ref('')
// 404 = 链接不对，或这次签到已经被发布人删了：页面不显示「读取失败」，而是明说链接失效
const notFound = ref(false)
const info = ref(null)

// 签到表单的状态。签到成功后整块被「已签到」替换，这些值不用再清
const position = ref(null)
const locating = ref(false)
const file = ref(null)
const compressing = ref(false)
const submitting = ref(false)
const fileInput = ref(null)

const loginHref = computed(() => {
  const back = `/checkin?code=${encodeURIComponent(route.query.code || '')}`
  return `#/login?redirect=${encodeURIComponent(back)}`
})

/** 当前位置到签到地点的距离（米），没定位或没有地点时为 null */
const distance = computed(() => {
  const loc = info.value?.location
  if (!loc || !position.value) return null
  return Math.round(distanceMeters(loc.lat, loc.lng, position.value.lat, position.value.lng))
})

/** 是否在允许范围内。没要求定位时永远算「在范围内」 */
const withinRadius = computed(() => {
  const loc = info.value?.location
  if (!loc) return true
  if (distance.value == null) return false
  return distance.value <= loc.radius_m
})

async function load() {
  if (!route.query.code) {
    loading.value = false
    error.value = '链接不完整，请向发布人重新要一次签到链接'
    return
  }
  loading.value = true
  error.value = ''
  notFound.value = false
  // 公开页的路由守卫不会去问后端登录状态，这里补一次，才能知道 is_login 和 is_target
  if (!userStore.resolved) await userStore.fetchMe()
  try {
    info.value = await getCheckinPublic(route.query.code)
    // 能签且要求定位：进页面就去要位置，少点一次「获取位置」
    if (info.value.can_sign && info.value.location) locate()
  } catch (e) {
    // 签到被删后链接就查不到了：单独给一句能看懂的话，不暴露「读取失败」
    notFound.value = e?.response?.status === 404
    error.value = notFound.value
      ? '这次签到不存在或已被删除。如确实有这次签到，请向发布人重新要一次链接。'
      : errText(e, '读取签到信息失败')
  } finally {
    loading.value = false
  }
}

async function locate() {
  locating.value = true
  try {
    position.value = await getCurrentLocation()
  } catch (e) {
    position.value = null
    ElMessage.error(e?.message || '定位失败，请重试')
  } finally {
    locating.value = false
  }
}

async function onFileChange(event) {
  const picked = event.target.files?.[0]
  if (!picked) return
  compressing.value = true
  try {
    // 手机直出的照片好几 MB，压缩是优化；失败时原样上传（见 imageCompress.js）
    file.value = await compressImage(picked)
  } finally {
    compressing.value = false
  }
}

async function handleSubmit() {
  const loc = info.value?.location
  if (loc && !position.value) {
    return ElMessage.warning('请先获取位置')
  }
  if (loc && !withinRadius.value) {
    return ElMessage.warning('你不在允许的签到范围内')
  }
  if (info.value?.require_photo && !file.value) {
    return ElMessage.warning('本次签到需要上传一张照片')
  }

  submitting.value = true
  try {
    // 后端在最后一个人签完时会立即结束并结算，返回的 status 已经是 ended
    info.value = await signCheckin(info.value.code, {
      lat: position.value?.lat,
      lng: position.value?.lng,
      photo: file.value
    })
    ElMessage.success('签到成功')
  } catch (e) {
    ElMessage.error(errText(e, '签到失败'))
  } finally {
    submitting.value = false
  }
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

.ck-req {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  margin-top: 12px;
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-size: 14px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
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

.ck-center {
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

.ck-block {
  width: 100%;
  padding-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.ck-block-head {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 14px;
}

.ck-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 14px;
}

.ck-label {
  color: var(--el-text-color-secondary);
}

/* 原生的文件选择框藏起来，用按钮去触发它 */
.ck-file {
  display: none;
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
