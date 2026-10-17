<template>
  <el-dialog
    v-model="visible"
    title="发布签到"
    width="720px"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <!-- 发布成功后整个弹窗换成「链接 + 复制」，避免有人以为还要再点一次 -->
    <div v-if="created" class="cc-done">
      <el-result icon="success" title="签到已发布">
        <template #sub-title>
          范围内的 {{ created.target_count }} 名同学已收到站内信。
          把下面的链接发到群里，同学打开就能签到
        </template>
      </el-result>
      <div class="cc-link">
        <el-input :model-value="created.link" readonly />
        <el-button type="primary" @click="copyText(created.link)">链接</el-button>
      </div>
      <p class="cc-tip">
        截止 {{ formatDateTime(created.end_at) }} 自动结束，也可以在考勤记录里手动结束。
        结算后会生成一条普通考勤记录
      </p>
    </div>

    <div v-else class="cc-body">
      <!-- ---------- 一、基本信息 ---------- -->
      <h4 class="cc-h">一、基本信息</h4>
      <el-form label-width="88px">
        <el-form-item label="标题" required>
          <el-input
            v-model="form.title"
            maxlength="100"
            show-word-limit
            placeholder="例如：周六晚点名"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input
            v-model="form.remark"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            placeholder="选填。写清集合地点、注意事项"
          />
        </el-form-item>
        <el-form-item label="截止时间" required>
          <el-date-picker
            v-model="form.end_at"
            type="datetime"
            placeholder="到点自动结束并结算"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DD HH:mm"
            style="width: 100%;"
          />
          <div class="cc-tip">默认 30 分钟后。到点自动结算，不用守着</div>
        </el-form-item>
        <el-form-item label="签到照片">
          <el-switch v-model="form.require_photo" />
          <span class="cc-tip cc-inline">
            {{ form.require_photo ? '每人必须上传一张照片才能签到' : '不要求照片' }}
          </span>
        </el-form-item>
      </el-form>

      <!-- ---------- 二、签到范围 ---------- -->
      <h4 class="cc-h">
        二、签到范围
        <span class="cc-count">已选 {{ form.targets.length }} / 共 {{ roster.length }} 人</span>
      </h4>
      <div class="cc-btns">
        <el-button size="small" @click="selectAll">全选</el-button>
        <el-button size="small" @click="form.targets = []">全不选</el-button>
        <el-button size="small" @click="selectCommittee">仅班委</el-button>
        <el-button size="small" @click="selectLeague">仅团员</el-button>
      </div>
      <div v-if="iAmOutOfScope" class="cc-tip cc-warn">
        你自己不在这次签到范围内（只发布，不签到）
      </div>
      <div v-loading="rosterLoading" class="cc-roster">
        <el-checkbox-group v-model="form.targets">
          <el-checkbox v-for="s in roster" :key="s.student_no" :value="s.student_no">
            {{ s.name }}<span class="cc-no">{{ s.student_no }}</span>
          </el-checkbox>
        </el-checkbox-group>
        <p v-if="!rosterLoading && !roster.length" class="cc-empty">没有可选择的同学</p>
      </div>

      <!-- ---------- 三、地点（可选） ---------- -->
      <h4 class="cc-h">三、签到地点（选填）</h4>
      <el-switch
        v-model="form.useLocation"
        active-text="要求定位"
        inactive-text="不限制地点"
      />
      <div v-if="form.useLocation" class="cc-location">
        <MapPicker
          v-model="point"
          :radius="form.radius_m"
          @place="onPlace"
        />
        <div class="cc-loc-row">
          <span class="cc-label">允许半径</span>
          <el-input-number
            v-model="form.radius_m"
            :min="10"
            :max="5000"
            :step="10"
            controls-position="right"
            style="width: 130px;"
          />
          <span class="cc-tip cc-inline">米（10～5000）</span>
        </div>
        <el-form label-width="88px" class="cc-loc-name">
          <el-form-item label="地点名称">
            <el-input
              v-model="form.location_name"
              maxlength="100"
              placeholder="在地图上选点后自动填写，也可以自己改"
              @input="nameTouched = true"
            />
          </el-form-item>
        </el-form>
        <div v-if="!point" class="cc-tip cc-warn">还没有选点：在地图上点一下，或手填经纬度</div>
      </div>
    </div>

    <template #footer>
      <template v-if="created">
        <el-button type="primary" @click="visible = false">完成</el-button>
      </template>
      <template v-else>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">发布签到</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import MapPicker from '@/components/MapPicker.vue'
import { createCheckin } from '@/api/checkin'
import { getRoster } from '@/api/vote'
import { copyText } from '@/utils/clipboard'
import { formatDateTime } from '@/utils/format'
import { isLeagueMember } from '@/utils/roster'
import { errText } from '@/utils/request'
import { useUserStore } from '@/store/user'

const emit = defineEmits(['saved'])
const userStore = useUserStore()

const visible = ref(false)
const submitting = ref(false)
const rosterLoading = ref(false)
const roster = ref([])
/** 发布成功后的详情（带 link）。非空时弹窗显示结果页 */
const created = ref(null)
/** 地图选点；和表单里的 radius/name 分开存，MapPicker 只认坐标 */
const point = ref(null)
/** 手动改过地点名之后，反查回来的地址不再覆盖它 */
const nameTouched = ref(false)

/** 默认截止：30 分钟后，四舍五入到分钟 */
function defaultEnd() {
  const d = new Date(Date.now() + 30 * 60 * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function blankForm() {
  return {
    title: '',
    remark: '',
    end_at: defaultEnd(),
    require_photo: false,
    targets: [],
    useLocation: false,
    radius_m: 100,
    location_name: ''
  }
}

const form = reactive(blankForm())

const iAmOutOfScope = computed(() => {
  const myNo = userStore.info?.student_no
  return !!myNo && form.targets.length > 0 && !form.targets.includes(myNo)
})

function open() {
  Object.assign(form, blankForm())
  roster.value = []
  point.value = null
  created.value = null
  nameTouched.value = false
  visible.value = true
  fetchRoster()
}

function reset() {
  Object.assign(form, blankForm())
  roster.value = []
  point.value = null
  created.value = null
  nameTouched.value = false
}

async function fetchRoster() {
  rosterLoading.value = true
  try {
    const { items } = await getRoster()
    roster.value = items
    form.targets = items.map((s) => s.student_no) // 默认全选
  } catch (e) {
    roster.value = []
    form.targets = []
    ElMessage.error(errText(e, '读取学生名单失败'))
  } finally {
    rosterLoading.value = false
  }
}

function selectAll() {
  form.targets = roster.value.map((s) => s.student_no)
}

function selectCommittee() {
  form.targets = roster.value.filter((s) => s.committee).map((s) => s.student_no)
}

function selectLeague() {
  form.targets = roster.value.filter(isLeagueMember).map((s) => s.student_no)
}

/** 地图反查到的地址：没手动改过就填进去 */
function onPlace(name) {
  if (!nameTouched.value) form.location_name = name
}

/** 提交前校验，一条条报。后端仍会再验一遍（它才是唯一的闸） */
function firstError() {
  if (!form.title.trim()) return '请填写标题'
  if (!form.end_at) return '请选择截止时间'
  const end = new Date(form.end_at.replace(' ', 'T'))
  if (end.getTime() <= Date.now()) return '截止时间必须晚于当前时间'
  if (!form.targets.length) return '至少要选一名同学'
  if (form.useLocation) {
    if (!point.value) return '已打开「要求定位」，请先选择签到地点'
    if (form.radius_m < 10 || form.radius_m > 5000) return '允许半径要在 10 到 5000 米之间'
  }
  return ''
}

async function handleSubmit() {
  const problem = firstError()
  if (problem) return ElMessage.warning(problem)

  const payload = {
    title: form.title.trim(),
    remark: form.remark.trim(),
    end_at: form.end_at,
    require_photo: form.require_photo,
    targets: [...form.targets]
  }
  if (form.useLocation && point.value) {
    payload.location = {
      lat: point.value.lat,
      lng: point.value.lng,
      radius_m: form.radius_m,
      name: form.location_name.trim()
    }
  }

  submitting.value = true
  try {
    created.value = await createCheckin(payload)
    ElMessage.success('签到已发布')
    emit('saved')
  } catch (e) {
    ElMessage.error(errText(e, '发布失败'))
  } finally {
    submitting.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
/* 名单加地图，弹窗会很高：限高滚动 */
.cc-body {
  max-height: 62vh;
  overflow-y: auto;
  padding-right: 6px;
}

.cc-h {
  margin: 18px 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.cc-body > .cc-h:first-child {
  margin-top: 0;
}

.cc-count {
  margin-left: 8px;
  font-weight: 400;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.cc-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.cc-inline {
  margin-left: 8px;
}

.cc-warn {
  color: var(--el-color-warning);
}

.cc-btns {
  margin-bottom: 8px;
}

.cc-roster {
  max-height: 160px;
  overflow-y: auto;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

.cc-no {
  margin-left: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cc-empty {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.cc-location {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cc-loc-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cc-label {
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.cc-loc-name {
  margin-top: 4px;
}

.cc-done {
  padding: 0 12px 8px;
}

.cc-link {
  display: flex;
  gap: 8px;
}

.cc-done .cc-tip {
  margin-top: 14px;
  text-align: center;
}
</style>
