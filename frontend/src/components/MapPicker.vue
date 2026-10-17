<template>
  <div class="map-picker">
    <!-- 配了高德 Key：地图点选（或拖动标记），半径用圆实时预览 -->
    <div v-if="useMap" ref="mapEl" class="mp-map" :class="{ 'mp-map-readonly': readonly }"></div>

    <!-- 没配 Key：降级成手填经纬度。只读场景（公开页）只显示数字 -->
    <div v-else-if="readonly" class="mp-plain">
      <template v-if="modelValue">
        纬度 {{ modelValue.lat }}，经度 {{ modelValue.lng }}
      </template>
      <template v-else>未设置签到地点</template>
    </div>
    <div v-else class="mp-inputs">
      <el-input-number
        v-model="latInput"
        :min="-90"
        :max="90"
        :precision="6"
        :controls="false"
        placeholder="纬度"
        style="width: 150px;"
        @change="onInputChange"
      />
      <el-input-number
        v-model="lngInput"
        :min="-180"
        :max="180"
        :precision="6"
        :controls="false"
        placeholder="经度"
        style="width: 150px;"
        @change="onInputChange"
      />
      <span class="mp-tip">未配置高德地图，可直接填写经纬度</span>
    </div>

    <div v-if="!readonly" class="mp-actions">
      <el-button size="small" :loading="locating" @click="useCurrent">使用当前位置</el-button>
      <span v-if="accuracy" class="mp-tip">定位精度约 {{ accuracy }} 米</span>
      <span v-else-if="useMap && modelValue" class="mp-tip">点击地图可以调整地点</span>
    </div>
    <div v-if="loading" class="mp-tip">地图加载中…</div>
    <div v-else-if="locating && !modelValue" class="mp-tip">
      正在获取你的位置…（也可以直接在地图上点选）
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { hasAmap, loadAmap, reverseGeocode } from '@/utils/amap'
import { getCurrentLocation } from '@/utils/geolocation'

/**
 * 地图选点
 *
 * v-model 是 { lat, lng }（GCJ-02），null = 还没选。
 * 半径不在这里存，只通过 radius 传进来画圆 —— 它是发布人单独填的数字。
 * 选完点会尽力反查地名，通过 place 事件抛给父组件填到地点名输入框里。
 */
const props = defineProps({
  modelValue: { type: Object, default: null },
  radius: { type: Number, default: 100 },
  readonly: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'place'])

const mapEl = ref(null)
const loading = ref(false)
const mapError = ref(false)
const locating = ref(false)
const accuracy = ref(0)
const latInput = ref(null)
const lngInput = ref(null)

/** 地图可用 = 配了 Key 且真的加载成功；失败后自动落到手填那一路 */
const useMap = computed(() => hasAmap() && !mapError.value)

// 高德的对象和实例只活在这个组件里，不需要响应式
let AMapRef = null
let map = null
let marker = null
let circle = null

function round6(value) {
  return Number(Number(value).toFixed(6))
}

/** 把坐标同步到地图上的标记和半径圆（父组件改值、地图点选都经过这里） */
function syncOverlays() {
  if (!map || !AMapRef) return
  const point = props.modelValue
  if (!point) {
    marker?.setMap(null)
    circle?.setMap(null)
    return
  }

  if (!marker) {
    marker = new AMapRef.Marker({
      position: [point.lng, point.lat],
      draggable: !props.readonly
    })
    if (!props.readonly) {
      // 拖动落点也算选点：手机上手点地图不太准，拖一下更好对
      marker.on('dragend', () => {
        const pos = marker.getPosition()
        applyPoint(pos.getLat(), pos.getLng(), true)
      })
    }
  }
  marker.setPosition([point.lng, point.lat])
  if (!marker.getMap()) marker.setMap(map)

  if (!circle) {
    circle = new AMapRef.Circle({
      center: [point.lng, point.lat],
      radius: props.radius,
      strokeColor: '#409eff',
      strokeOpacity: 0.9,
      strokeWeight: 1.5,
      fillColor: '#409eff',
      fillOpacity: 0.15
    })
  }
  circle.setCenter([point.lng, point.lat])
  circle.setRadius(props.radius || 0)
  if (!circle.getMap()) circle.setMap(map)
}

/** 落一个点：更新 v-model，并尽力反查地名 */
async function applyPoint(lat, lng, geocode) {
  const point = { lat: round6(lat), lng: round6(lng) }
  emit('update:modelValue', point)
  latInput.value = point.lat
  lngInput.value = point.lng
  if (geocode && AMapRef) {
    const name = await reverseGeocode(AMapRef, point.lat, point.lng)
    if (name) emit('place', name)
  }
}

async function useCurrent() {
  locating.value = true
  try {
    const pos = await getCurrentLocation()
    accuracy.value = pos.accuracy
    await applyPoint(pos.lat, pos.lng, true)
    centerOn(pos)
    ElMessage.success('已定位到你当前位置')
  } catch (e) {
    ElMessage.error(e?.message || '定位失败，请重试')
  } finally {
    locating.value = false
  }
}

/** 把地图移到某个点并放大到街区级别，让半径圈看得清 */
function centerOn(pos) {
  map?.setZoomAndCenter?.(16, [pos.lng, pos.lat])
}

/**
 * 打开地图时的默认位置 = 发布人当前定位
 *
 * 没选过点时自动定位一次，发布人只需要微调（或直接点地图改）；
 * 拒绝授权 / 定不到就静默跳过，不弹错 —— 手点地图、手填经纬度照样能发。
 */
async function autoLocate() {
  if (props.modelValue) return
  locating.value = true
  try {
    const pos = await getCurrentLocation()
    accuracy.value = pos.accuracy
    await applyPoint(pos.lat, pos.lng, true)
    centerOn(pos)
  } catch {
    // 保持空白，由发布人点「使用当前位置」重试或自己选点
  } finally {
    locating.value = false
  }
}

/** 手填经纬度：两个都填了才算一个点 */
function onInputChange() {
  if (latInput.value == null || lngInput.value == null) return
  const inRange =
    latInput.value >= -90 && latInput.value <= 90 &&
    lngInput.value >= -180 && lngInput.value <= 180
  if (!inRange) return
  emit('update:modelValue', { lat: round6(latInput.value), lng: round6(lngInput.value) })
}

watch(
  () => props.modelValue,
  (point) => {
    latInput.value = point?.lat ?? null
    lngInput.value = point?.lng ?? null
    syncOverlays()
  }
)

watch(
  () => props.radius,
  (radius) => circle?.setRadius(radius || 0)
)

onMounted(async () => {
  if (hasAmap()) {
    loading.value = true
    try {
      AMapRef = await loadAmap()
      const point = props.modelValue
      map = new AMapRef.Map(mapEl.value, {
        zoom: point ? 16 : 11,
        center: point ? [point.lng, point.lat] : [116.397, 39.909],
        // 只读场景把缩放控件也收掉，页面上就是个安静的小地图
        zoomControl: !props.readonly
      })
      if (!props.readonly) {
        map.on('click', (e) => applyPoint(e.lnglat.getLat(), e.lnglat.getLng(), true))
      }
      syncOverlays()
    } catch {
      // 加载失败就降级成手填，不弹错：签到本身不依赖地图
      mapError.value = true
    } finally {
      loading.value = false
    }
  }

  // 发布端的默认地点 = 发布人当前位置（只读页不定：那是发布人定的地点，与访问者无关）
  if (!props.readonly) autoLocate()
})
</script>

<style scoped>
.map-picker {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mp-map {
  height: 260px;
  border-radius: 4px;
  overflow: hidden;
}

.mp-map-readonly {
  height: 200px;
}

.mp-plain {
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
}

.mp-inputs {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.mp-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.mp-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
