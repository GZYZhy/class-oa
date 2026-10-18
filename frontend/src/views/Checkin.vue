<template>
  <!-- 公开页：从链接或站内信直接进来，不套侧边栏（路由 meta.bare）。
       没登录也能看到这次签到是什么；真正签到要登录，登录后自动回到这里。
       签到表单直接长在这张卡片里，不再另开弹窗 —— 入口只有一个，样子也一致 -->
  <div class="checkin-page">
    <div class="ck-card">
      <div class="ck-head">
        <img :src="SITE.logoUrl" class="ck-logo" alt="校徽" />
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
          <!-- 弱网下一次超时很常见，给一个明确的重新加载，不用让用户自己刷新 -->
          <el-button v-if="!notFound" type="primary" @click="load()">重新加载</el-button>
          <a href="#/" class="ck-plain-link">回首页</a>
        </template>
      </el-result>

      <template v-else-if="info">
        <div class="ck-title-row">
          <h2 class="ck-title">{{ info.title }}</h2>
          <el-tag :type="statusTag" size="small">{{ statusText }}</el-tag>
        </div>
        <p v-if="info.remark" class="ck-remark">{{ info.remark }}</p>

        <div class="ck-meta">
          <span>{{ info.created_by_name }} 发布</span>
          <span v-if="info.status === 'pending' && info.start_at">
            开始 {{ formatDateTime(info.start_at) }}
          </span>
          <span>截止 {{ formatDateTime(info.end_at) }}</span>
          <span>应到 {{ info.target_count }} 人</span>
        </div>

        <!-- 签到要求逐条编号列出：地点和照片各是一条 -->
        <ol v-if="requirements.length" class="ck-req">
          <li v-for="(item, i) in requirements" :key="i">{{ item }}</li>
        </ol>
        <p v-else class="ck-req">无需定位和照片，确认到场即可</p>

        <!-- 只读地图：地图没配就显示经纬度，不影响签到本身。
             截止之后链接仍可打开，这里也照常展示 -->
        <div v-if="info.location" class="ck-location">
          <MapPicker
            :model-value="{ lat: info.location.lat, lng: info.location.lng }"
            :radius="info.location.radius_m"
            readonly
          />
        </div>

        <!-- ---------- 未开始：只说明几时开始，到点刷新即可 ---------- -->
        <div v-if="info.status === 'pending'" class="ck-actions">
          <div class="ck-center">
            <p class="ck-tip">
              签到将于 {{ formatDateTime(info.start_at) }} 开始，到时间后刷新本页即可签到
            </p>
          </div>
        </div>

        <!-- ---------- 进行中；或已结束但页面是截止前打开的（补签宽限） ---------- -->
        <div v-else-if="info.status === 'ongoing' || info.grace_until" class="ck-actions">
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
            <a href="#/my-info?tab=attendance">
              <el-button size="large">查看考勤情况</el-button>
            </a>
          </div>

          <!-- ---------- 签到表单（就在页面里） ---------- -->
          <template v-else>
            <p v-if="info.on_leave" class="ck-tip">
              你在这次签到时段有已批准的请假。现在签到会记为「到」；不签则记为「请假」
            </p>

            <!-- 地点在上面的要求里已经写明，这里只报本人位置，不重复地点名 -->
            <div v-if="info.location" class="ck-line">
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

            <template v-if="info.require_photo">
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
                <span class="ck-label">照片</span>
                <span class="ck-tip" :class="{ 'ck-warn': uploadError }">
                  <template v-if="compressing">正在压缩照片…</template>
                  <template v-else-if="uploading">正在上传照片…</template>
                  <template v-else-if="uploadError">{{ uploadError }}</template>
                  <template v-else-if="photoToken">已上传：{{ photoName }}</template>
                  <template v-else-if="photoFile">照片还没有上传成功</template>
                  <template v-else>请拍照或从相册选一张</template>
                </span>
                <el-button
                  v-if="uploadError && photoFile && !uploading"
                  link
                  type="primary"
                  @click="uploadPhoto"
                >
                  重试上传
                </el-button>
                <el-button
                  link
                  type="primary"
                  :loading="compressing"
                  :disabled="uploading"
                  @click="fileInput?.click()"
                >
                  {{ photoFile ? '重新选择' : '选择照片' }}
                </el-button>
              </div>
              <!-- 选中就传，进度条立刻出现；传完之前「确认签到」点不了 -->
              <el-progress
                v-if="uploading"
                class="ck-upload"
                :percentage="uploadPercent ?? 0"
                :indeterminate="uploadPercent === null"
                :stroke-width="6"
              />
            </template>
            <!-- 唯一的主按钮居中，和登录、已签到两个状态的按钮对齐 -->
            <div class="ck-center">
              <el-button
                type="primary"
                size="large"
                :loading="submitting"
                :disabled="compressing || uploading"
                @click="handleSubmit"
              >
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
            <a href="#/my-info?tab=attendance">
              <el-button size="large">查看考勤情况</el-button>
            </a>
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
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import MapPicker from '@/components/MapPicker.vue'
import { getCheckinPublic, signCheckin, uploadCheckinPhoto } from '@/api/checkin'
import { compressImage } from '@/utils/imageCompress'
import { distanceMeters, getCurrentLocation } from '@/utils/geolocation'
import { formatDateTime } from '@/utils/format'
import { errText } from '@/utils/request'
import { SITE } from '@/utils/site'

const route = useRoute()

const loading = ref(true)
const error = ref('')
// 404 = 链接不对，或这次签到已经被发布人删了：页面不显示「读取失败」，而是明说链接失效
const notFound = ref(false)
const info = ref(null)

const statusText = computed(() => {
  if (info.value?.status === 'pending') return '未开始'
  return info.value?.status === 'ongoing' ? '进行中' : '已结束'
})
const statusTag = computed(() => {
  if (info.value?.status === 'pending') return 'warning'
  return info.value?.status === 'ongoing' ? 'success' : 'info'
})

/** 签到要求逐条列出：有就编号，一条都没有时说「确认到场即可」 */
const requirements = computed(() => {
  const items = []
  const loc = info.value?.location
  if (loc) items.push(`在「${loc.name || '指定地点'}」${loc.radius_m} 米范围内`)
  if (info.value?.require_photo) items.push('上传一张照片')
  return items
})

// 签到表单的状态。签到成功后整块被「已签到」替换，这些值不用再清
const position = ref(null)
const locating = ref(false)
// 照片选中就上传：photoFile 是压缩后的文件，photoToken 是上传成功拿到的凭证
const photoFile = ref(null)
const photoName = ref('')
const photoToken = ref('')
const compressing = ref(false)
const uploading = ref(false)
const uploadPercent = ref(null)
const uploadError = ref('')
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

// ---------- 照片凭证的本地暂存 ----------
// 照片传完后如果页面刷新，内存里的 token 会丢。按签到 code 存一份到 sessionStorage，
// 刷新后仍能直接提交签到，不用在弱网下再传一次照片。token 本身是服务端签的，
// 有截止时间约束，存储它不会扩大权限。

function photoStorageKey() {
  return `checkin-photo-${info.value?.code || route.query.code || ''}`
}

function savePhotoToken() {
  if (!photoToken.value) return
  try {
    sessionStorage.setItem(photoStorageKey(), JSON.stringify({
      token: photoToken.value,
      name: photoName.value
    }))
  } catch (e) {
    /* 隐私模式等写不进去：不影响本次提交 */
  }
}

function restorePhotoToken() {
  try {
    const raw = sessionStorage.getItem(photoStorageKey())
    if (!raw) return
    const saved = JSON.parse(raw)
    if (saved?.token) {
      photoToken.value = saved.token
      photoName.value = saved.name || '已上传的照片'
    }
  } catch (e) {
    clearPhotoToken()
  }
}

function clearPhotoToken() {
  try {
    sessionStorage.removeItem(photoStorageKey())
  } catch (e) {
    /* 忽略 */
  }
}

// 连续点「重新加载」时只认最后一次请求，避免先发的慢响应把新结果盖掉
let loadSeq = 0

async function load({ retry = true } = {}) {
  const seq = ++loadSeq
  if (!route.query.code) {
    loading.value = false
    error.value = '链接不完整，请向发布人重新要一次签到链接'
    return
  }
  loading.value = true
  error.value = ''
  notFound.value = false
  // 不再单独问一次登录态：公开信息接口凭 Cookie 自己带上 is_login / is_target，
  // 弱网下少一个来回。真需要用户存储的页面（登录后的布局）挂载时会自己拉
  try {
    const data = await getCheckinPublic(route.query.code)
    if (seq !== loadSeq) return
    info.value = data
    applyShareMeta(data)
    // 已经签过 / 不需要照片时，本地那份 token 没有用了
    if (data.signed_at || !data.require_photo) clearPhotoToken()
    else restorePhotoToken()
    // 能签且要求定位：进页面就去要位置，少点一次「获取位置」
    if (data.can_sign && data.location) locate()
  } catch (e) {
    if (seq !== loadSeq) return
    const status = e?.response?.status
    // 纯网络错误 / 超时 / 服务端 5xx：自动再试一次，弱网下很多是瞬时失败
    if (retry && (!status || status >= 500)) {
      await new Promise((resolve) => setTimeout(resolve, 800))
      if (seq !== loadSeq) return
      return load({ retry: false })
    }
    // 签到被删后链接就查不到了：单独给一句能看懂的话，不暴露「读取失败」
    notFound.value = status === 404
    error.value = notFound.value
      ? '这次签到不存在或已被删除。如确实有这次签到，请向发布人重新要一次链接。'
      : errText(e, '读取签到信息失败')
  } finally {
    if (seq === loadSeq) loading.value = false
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

/** 把压缩好的照片立刻传上去。失败时保留 photoFile，可以点「重试上传」 */
async function uploadPhoto() {
  if (!photoFile.value || !info.value) return
  uploading.value = true
  uploadPercent.value = null
  uploadError.value = ''
  photoToken.value = ''
  try {
    const res = await uploadCheckinPhoto(info.value.code, photoFile.value, {
      onProgress: (loaded, total) => {
        uploadPercent.value = total ? Math.min(100, Math.round((loaded / total) * 100)) : null
      }
    })
    photoToken.value = res.token
    savePhotoToken()
  } catch (e) {
    uploadError.value = errText(e, '照片上传失败，请重试')
    ElMessage.error(uploadError.value)
  } finally {
    uploading.value = false
  }
}

async function onFileChange(event) {
  const picked = event.target.files?.[0]
  if (!picked) return
  // 清空 value：再选同一张图时 change 才会重新触发
  event.target.value = ''
  compressing.value = true
  uploadError.value = ''
  photoToken.value = ''
  clearPhotoToken()
  try {
    // 手机直出的照片好几 MB，压缩是优化；失败时原样上传（见 imageCompress.js）
    photoFile.value = await compressImage(picked)
    photoName.value = photoFile.value.name || picked.name
  } finally {
    compressing.value = false
  }
  // 选完立即传，不等点「签到」—— 传完可能已经过截止，后端按「开始上传」的时刻算
  await uploadPhoto()
}

async function handleSubmit() {
  const loc = info.value?.location
  if (loc && !position.value) {
    return ElMessage.warning('请先获取位置')
  }
  if (loc && !withinRadius.value) {
    return ElMessage.warning('你不在允许的签到范围内')
  }
  if (compressing.value || uploading.value) {
    return ElMessage.warning('照片还在上传，请稍候')
  }
  if (info.value?.require_photo && !photoToken.value) {
    return ElMessage.warning('本次签到需要上传一张照片')
  }

  submitting.value = true
  try {
    // 后端在最后一个人签完时会立即结束并结算，返回的 status 已经是 ended
    info.value = await signCheckin(info.value.code, {
      lat: position.value?.lat,
      lng: position.value?.lng,
      photoToken: photoToken.value
    })
    applyShareMeta(info.value)
    clearPhotoToken()
    ElMessage.success('签到成功')
  } catch (e) {
    // 上一次请求其实已经成功、只是响应在弱网下丢了：再点时后端会说「已签到」。
    // 这不是失败，按成功处理并刷新页面状态，别让人以为没签上。
    const detail = e?.response?.data?.detail
    if (e?.response?.status === 400 && typeof detail === 'string' && detail.includes('已签到')) {
      clearPhotoToken()
      ElMessage.success('你已经签过到了')
      await load()
      return
    }
    ElMessage.error(errText(e, '签到失败'))
  } finally {
    submitting.value = false
  }
}

// ---------- 分享卡片：<head> 里的 OG 标签 ----------
// 真链接是后端的 /api/checkins/share/{code}（服务端先把 OG 写给微信爬虫）；
// 这里再补一份，给会执行 JS 的客户端，以及从站内信直接进到 hash 页的情况。
const OG_FLAG = 'data-checkin-og'
let originalRobots = null

function setOgMeta(property, content) {
  let el = document.head.querySelector(`meta[property="${property}"][${OG_FLAG}]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute('property', property)
    el.setAttribute(OG_FLAG, '1')
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

/** 标题固定用签到标题：转发出去的卡片就是这一场的名字 */
function applyShareMeta(data) {
  if (!data) return
  const title = data.title || '签到'
  document.title = title
  const tail = `应到 ${data.target_count} 人 · 截止 ${formatDateTime(data.end_at)}`
  const desc = data.remark ? `${data.remark}｜${tail}` : tail
  const pairs = {
    'og:title': title,
    'og:description': desc,
    'og:type': 'website',
    'og:url': data.link || location.href,
    'og:site_name': SITE.name,
    'og:image': new URL(SITE.logoUrl, location.origin).href,
    'og:locale': 'zh_CN'
  }
  for (const [key, value] of Object.entries(pairs)) setOgMeta(key, value)

  // 全站默认 noindex；签到分享页要允许抓取，离开时恢复
  const robots = document.head.querySelector('meta[name="robots"]')
  if (robots) {
    if (originalRobots === null) originalRobots = robots.getAttribute('content') || ''
    robots.setAttribute('content', 'index,follow')
  }
}

function clearShareMeta() {
  document.querySelectorAll(`meta[${OG_FLAG}]`).forEach((el) => el.remove())
  const robots = document.head.querySelector('meta[name="robots"]')
  if (robots && originalRobots !== null) robots.setAttribute('content', originalRobots)
  originalRobots = null
}

onMounted(load)
onUnmounted(clearShareMeta)
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
  margin: 12px 0 0;
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-size: 14px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}

/* 签到的两项要求各占一条，按 1. 2. 编号 */
ol.ck-req {
  padding-left: 32px;
  list-style: decimal;
}

.ck-location {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
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

.ck-upload {
  margin-top: 8px;
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
