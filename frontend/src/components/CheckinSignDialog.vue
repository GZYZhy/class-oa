<template>
  <el-dialog
    v-model="visible"
    title="签到"
    width="480px"
    :close-on-click-modal="false"
  >
    <div class="cs-body">
      <h4 class="cs-title">{{ info.title }}</h4>
      <div v-if="info.remark" class="cs-remark">{{ info.remark }}</div>

      <div class="cs-line">
        <span class="cs-label">截止时间</span>
        <span>{{ formatDateTime(info.end_at) }}</span>
      </div>
      <!-- 有请假的学生也能签到：签了按「到」算，这是用户定的口径 -->
      <div v-if="info.on_leave" class="cs-tip cs-warn">
        你在这次签到时段有已批准的请假。现在签到仍会记为「到」；不签则记为「请假」
      </div>

      <!-- ---------- 定位 ---------- -->
      <div v-if="info.location" class="cs-block">
        <div class="cs-block-head">
          <span class="cs-label">签到地点</span>
          <span>{{ info.location.name || '指定地点' }}</span>
        </div>
        <div class="cs-line">
          <span class="cs-label">我的位置</span>
          <template v-if="locating">定位中…</template>
          <template v-else-if="position">
            <span :class="{ 'cs-warn': !withinRadius }">
              距签到地点约 {{ distance }} 米（允许 {{ info.location.radius_m }} 米）
            </span>
          </template>
          <span v-else class="cs-warn">还没有定位</span>
          <el-button link type="primary" :loading="locating" @click="locate">
            {{ position ? '重新定位' : '获取位置' }}
          </el-button>
        </div>
        <div v-if="position && !withinRadius" class="cs-tip cs-warn">
          当前位置超出允许范围，请到签到地点附近再试
        </div>
      </div>

      <!-- ---------- 照片 ---------- -->
      <div v-if="info.require_photo" class="cs-block">
        <div class="cs-block-head">
          <span class="cs-label">照片</span>
          <span>本次签到需要一张照片</span>
        </div>
        <!-- 用原生 input：手机点一下就能调起相机，比套一层上传组件轻 -->
        <input
          ref="fileInput"
          type="file"
          accept="image/*"
          capture="environment"
          class="cs-file"
          @change="onFileChange"
        />
        <div class="cs-line">
          <span class="cs-tip">
            {{ file ? `已选择：${file.name}` : '请拍照或从相册选一张' }}
          </span>
          <el-button link type="primary" :loading="compressing" @click="fileInput?.click()">
            {{ file ? '重新选择' : '选择照片' }}
          </el-button>
        </div>
      </div>

      <div v-if="!info.location && !info.require_photo" class="cs-tip">
        确认你已到场，点下面的按钮完成签到
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">确认签到</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { signCheckin } from '@/api/checkin'
import { compressImage } from '@/utils/imageCompress'
import { distanceMeters, getCurrentLocation } from '@/utils/geolocation'
import { formatDateTime } from '@/utils/format'
import { errText } from '@/utils/request'

const emit = defineEmits(['signed'])

const visible = ref(false)
const info = ref({})
const position = ref(null)
const locating = ref(false)
const file = ref(null)
const compressing = ref(false)
const submitting = ref(false)
const fileInput = ref(null)

/** 当前位置到签到地点的距离（米），没定位或没有地点时为 null */
const distance = computed(() => {
  const loc = info.value.location
  if (!loc || !position.value) return null
  return Math.round(distanceMeters(loc.lat, loc.lng, position.value.lat, position.value.lng))
})

/** 是否在允许范围内。没要求定位时永远算「在范围内」 */
const withinRadius = computed(() => {
  const loc = info.value.location
  if (!loc) return true
  if (distance.value == null) return false
  return distance.value <= loc.radius_m
})

function open(checkin) {
  info.value = checkin
  position.value = null
  file.value = null
  visible.value = true
  if (fileInput.value) fileInput.value.value = ''
  // 需要定位的签到一打开就去要位置：这一步本来就是用户点按钮触发的，
  // 浏览器不会因为「非用户手势」而拒绝
  if (checkin.location) locate()
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
  if (info.value.location && !position.value) {
    return ElMessage.warning('请先获取位置')
  }
  if (info.value.location && !withinRadius.value) {
    return ElMessage.warning('你不在允许的签到范围内')
  }
  if (info.value.require_photo && !file.value) {
    return ElMessage.warning('本次签到需要上传一张照片')
  }

  submitting.value = true
  try {
    const result = await signCheckin(info.value.code, {
      lat: position.value?.lat,
      lng: position.value?.lng,
      photo: file.value
    })
    visible.value = false
    ElMessage.success('签到成功')
    emit('signed', result)
  } catch (e) {
    ElMessage.error(errText(e, '签到失败'))
  } finally {
    submitting.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
.cs-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cs-title {
  margin: 0;
  font-size: 16px;
  color: var(--el-text-color-primary);
}

.cs-remark {
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  line-height: 1.5;
}

.cs-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 14px;
}

.cs-label {
  color: var(--el-text-color-secondary);
}

.cs-block {
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.cs-block-head {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 14px;
}

.cs-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.cs-warn {
  color: var(--el-color-warning);
}

/* 原生的文件选择框藏起来，用按钮去触发它 */
.cs-file {
  display: none;
}
</style>
