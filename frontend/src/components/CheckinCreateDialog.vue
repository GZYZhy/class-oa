<template>
  <el-dialog append-to-body
    v-model="visible"
    :title="created ? (justCreated ? '签到已发布' : '签到链接') : '发布签到'"
    width="720px"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <!-- 发布成功 / 从考勤列表重新打开：整块换成「链接 + 二维码 + 复制」，
         避免有人以为还要再点一次 -->
    <div v-if="created" class="cc-done">
      <el-result
        icon="success"
        :title="createdTitle"
      >
        <template v-if="created.remark" #sub-title>
          {{ created.remark }}
        </template>
      </el-result>
      <!-- 签到要求：和学生打开链接看到的是同一套口径 -->
      <ul v-if="createdRequirements.length" class="cc-req-list">
        <li v-for="(item, i) in createdRequirements" :key="i">{{ item }}</li>
      </ul>
      <p v-else class="cc-req-list cc-req-empty">无需定位和照片，确认到场即可</p>
      <div class="cc-link">
        <el-input :model-value="created.link" readonly />
        <el-button type="primary" @click="copyText(created.link)">复制</el-button>
      </div>
      <!-- 投屏用的大二维码：同学在教室里直接扫，不用再去找链接 -->
      <div v-if="qrDataUrl" class="cc-qr-wrap">
        <img :src="qrDataUrl" class="cc-qr" alt="签到二维码" />
      </div>
      <p class="cc-tip">
        {{ created.start_at ? `${formatDateTime(created.start_at)} 开始，` : '' }}截止
        {{ formatDateTime(created.end_at) }} 自动结束，也可以在考勤记录里手动结束。
        {{ created.notify_on_start ? '开始时会提醒范围内的同学。' : '不发送开始提醒。' }}
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
        <el-form-item label="说明">
          <el-input
            v-model="form.remark"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            placeholder="选填，支持 Markdown"
          />
          <div class="ck-form-tip">支持 Markdown（标题、列表、加粗、链接、图片）</div>
        </el-form-item>
        <el-form-item label="开始时间" required>
          <el-date-picker
            v-model="form.start_at"
            type="datetime"
            placeholder="到这个时间才能签到"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DD HH:mm"
            style="width: 100%;"
          />
          <div class="cc-tip">默认现在；设为将来时间则到点才能签到</div>
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
          <div class="cc-tip">默认 30 分钟，到点自动结束</div>
        </el-form-item>
        <el-form-item label="签到照片">
          <el-switch v-model="form.require_photo" />
          <span class="cc-tip cc-inline">
            {{ form.require_photo ? '需上传照片才能签到' : '不要求照片' }}
          </span>
        </el-form-item>
        <el-form-item label="开始提醒">
          <el-switch
            v-model="form.notify_on_start"
            active-text="提醒"
            inactive-text="不提醒"
          />
          <div class="cc-tip">
            开启后到「开始时间」才给范围内的人发一次提醒；发布即可签时立即发
          </div>
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
        你不在本次签到范围内，仅发布
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
            :min="100"
            :max="10000"
            :step="10"
            controls-position="right"
            style="width: 130px;"
          />
          <span class="cc-tip cc-inline">米（100～10000）</span>
        </div>
        <el-form label-width="118px" class="cc-loc-name">
          <el-form-item label="地点展示名">
            <el-input
              v-model="form.location_name"
              maxlength="100"
              placeholder="在地图上选点后自动填写，也可以自己改"
              @input="nameTouched = true"
            />
          </el-form-item>
        </el-form>
        <div v-if="!point" class="cc-tip cc-warn">尚未选点，可在地图上点击或手动填写</div>
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
import { SITE } from '@/utils/site'
import { makeQrDataUrl } from '@/utils/qr'

const emit = defineEmits(['saved'])
const userStore = useUserStore()

const visible = ref(false)
const submitting = ref(false)
const rosterLoading = ref(false)
const roster = ref([])
/** 发布成功后的详情（带 link）。非空时弹窗显示结果页 */
const created = ref(null)
/** true = 刚发布成功；false = 从考勤列表重新打开的分享弹窗 */
const justCreated = ref(false)
/** 大二维码（data URL）。生成失败就只显示链接，不影响复制 */
const qrDataUrl = ref('')
/** 地图选点；和表单里的 radius/name 分开存，MapPicker 只认坐标 */
const point = ref(null)
/** 手动改过地点名之后，反查回来的地址不再覆盖它 */
const nameTouched = ref(false)

/** 把某个时刻格式化成日期选择器认的「不带时区」写法 */
function formatPicker(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 默认开始：现在（取整到分钟，和选择器一致）；默认截止：30 分钟后 */
function defaultStart() {
  return formatPicker(new Date())
}

function defaultEnd() {
  return formatPicker(new Date(Date.now() + 30 * 60 * 1000))
}

function blankForm() {
  return {
    title: '',
    remark: '',
    start_at: defaultStart(),
    end_at: defaultEnd(),
    require_photo: false,
    notify_on_start: true,
    targets: [],
    useLocation: false,
    radius_m: 500,
    location_name: ''
  }
}

const form = reactive(blankForm())

const iAmOutOfScope = computed(() => {
  const myNo = userStore.info?.student_no
  return !!myNo && form.targets.length > 0 && !form.targets.includes(myNo)
})

/** 结果页第一行：统一带「签到：」前缀，标题本身已经带了就不重复加 */
const createdTitle = computed(() => {
  const title = created.value?.title || '签到'
  return title.startsWith('签到：') ? title : `签到：${title}`
})

/** 结果页的签到要求，和签到页上的要求同一个口径 */
const createdRequirements = computed(() => {
  const items = []
  const loc = created.value?.location
  if (loc) items.push(`在「${loc.name || '指定地点'}」${loc.radius_m} 米范围内`)
  if (created.value?.require_photo) items.push('上传一张照片')
  return items
})

function open() {
  Object.assign(form, blankForm())
  roster.value = []
  point.value = null
  created.value = null
  justCreated.value = false
  qrDataUrl.value = ''
  nameTouched.value = false
  visible.value = true
  fetchRoster()
}

/** 从考勤列表的「链接」按钮打开：同一场签到的分享页，不再走表单 */
function openShare(row) {
  justCreated.value = false
  // 考勤列表把签到的截止时间放在 time 里（发布接口返回的才叫 end_at），
  // 这里统一成 end_at，结果页的「截止 …」才不会显示成一个横杠
  created.value = { ...row, end_at: row.end_at || row.time || null }
  qrDataUrl.value = ''
  visible.value = true
  makeQr(row.link)
}

function reset() {
  Object.assign(form, blankForm())
  roster.value = []
  point.value = null
  created.value = null
  justCreated.value = false
  qrDataUrl.value = ''
  nameTouched.value = false
}

/** 把链接画成带校徽的大二维码；画不出来就只保留链接 */
async function makeQr(link) {
  if (!link) return
  try {
    qrDataUrl.value = await makeQrDataUrl(link, { logoUrl: SITE.logoUrl })
  } catch (e) {
    qrDataUrl.value = ''
  }
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
  if (!form.start_at) return '请选择开始时间'
  if (!form.end_at) return '请选择截止时间'
  const start = new Date(form.start_at.replace(' ', 'T'))
  const end = new Date(form.end_at.replace(' ', 'T'))
  if (start.getTime() >= end.getTime()) return '开始时间必须早于截止时间'
  if (end.getTime() <= Date.now()) return '截止时间必须晚于当前时间'
  if (!form.targets.length) return '至少要选一名同学'
  if (form.useLocation) {
    if (!point.value) return '已打开「要求定位」，请先选择签到地点'
    if (form.radius_m < 100 || form.radius_m > 10000) return '允许半径要在 100 到 10000 米之间'
  }
  return ''
}

async function handleSubmit() {
  const problem = firstError()
  if (problem) return ElMessage.warning(problem)

  const payload = {
    title: form.title.trim(),
    remark: form.remark.trim(),
    start_at: form.start_at,
    end_at: form.end_at,
    require_photo: form.require_photo,
    notify_on_start: form.notify_on_start,
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
    justCreated.value = true
    makeQr(created.value.link)
    ElMessage.success('签到已发布')
    emit('saved')
  } catch (e) {
    ElMessage.error(errText(e, '发布失败'))
  } finally {
    submitting.value = false
  }
}

defineExpose({ open, openShare })
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

/* 结果页的要求列表：和签到页一样逐条编号，宽度收窄便于阅读 */
.cc-req-list {
  max-width: 420px;
  margin: 0 auto 12px;
  padding-left: 22px;
  color: var(--el-text-color-regular);
  font-size: 14px;
  line-height: 1.8;
}

.cc-req-empty {
  padding-left: 0;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.cc-link {
  display: flex;
  gap: 8px;
}

.cc-done .cc-tip {
  margin-top: 14px;
  text-align: center;
}

/* 投屏用：尽量大，但别在手机上顶出弹窗 */
.cc-qr-wrap {
  margin-top: 12px;
  text-align: center;
}

.cc-qr {
  width: 340px;
  max-width: 82vw;
  padding: 12px;
  box-sizing: border-box;
  background: #fff;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.ck-form-tip {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

</style>
