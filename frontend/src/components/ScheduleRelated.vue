<template>
  <section v-if="editable || modelValue.length" class="schedule-related" aria-label="关联内容">
    <el-collapse v-model="expanded">
      <el-collapse-item name="related" :title="`关联内容${modelValue.length ? `（${modelValue.length}）` : '（选填）'}`">
        <p v-if="editable" class="related-note">选择已有内容，按下方顺序展示。各项沿用原参与范围和权限，请核对范围是否与日程一致。</p>
        <ListFeedback :error="loadError" :loading="loading" @retry="load" />
        <ul v-if="!loading" class="related-list">
          <li v-for="(item, index) in items" :key="`${item.kind}-${item.id}`">
            <div class="related-main">
              <span class="related-kind">{{ item.kind_label }}</span>
              <strong>{{ item.title }}</strong>
              <span class="related-meta">{{ [item.hint, item.scope_label, item.progress].filter(Boolean).join(' · ') }}</span>
              <span v-if="item.scope_warning" class="related-warning">参与范围与日程分配范围不同</span>
              <span v-if="item.end_at" class="related-meta">{{ formatDateTime(item.end_at) }} 截止</span>
            </div>
            <div v-if="editable" class="related-actions">
              <el-button link :disabled="index === 0" :aria-label="`上移${item.title}`" @click="move(index, -1)">上移</el-button>
              <el-button link :disabled="index === items.length - 1" :aria-label="`下移${item.title}`" @click="move(index, 1)">下移</el-button>
              <el-button link type="danger" :aria-label="`移除${item.title}`" @click="remove(index)">移除</el-button>
            </div>
            <div v-else class="related-actions">
              <el-button v-if="item.download_name && item.url" link type="primary" @click="download(item)">下载</el-button>
              <a v-else-if="item.url" :href="item.url" target="_blank" rel="noopener noreferrer">查看</a>
              <a v-if="item.manage_url" :href="item.manage_url" target="_blank" rel="noopener noreferrer">管理</a>
              <el-button v-if="item.checkin_id" link type="primary" @click="checkinDetail?.open({ id: item.checkin_id })">明细与催办</el-button>
            </div>
          </li>
        </ul>
        <template v-if="editable">
          <div class="related-search">
            <el-select v-model="kind" aria-label="关联类型" @change="search">
              <el-option v-for="(label, value) in kinds" :key="value" :label="label" :value="value" />
            </el-select>
            <el-input v-model="keyword" placeholder="按标题搜索" maxlength="200" clearable @keyup.enter="search" @clear="search" />
            <el-button :loading="searching" @click="search">查找</el-button>
          </div>
          <ListFeedback :error="searchError" :loading="searching" @retry="search" />
          <ul v-if="searched && !searching && !searchError" class="related-list related-results">
            <li v-for="item in results" :key="`${item.kind}-${item.id}`">
              <div class="related-main">
                <strong>{{ item.title }}</strong>
                <span class="related-meta">{{ [item.hint, item.scope_label].filter(Boolean).join(' · ') }}</span>
              </div>
              <el-button link type="primary" :disabled="selected(item) || modelValue.length >= 30" @click="add(item)">{{ selected(item) ? '已添加' : '添加' }}</el-button>
            </li>
            <li v-if="!results.length" class="related-note">没有找到可关联的内容</li>
          </ul>
          <p v-if="hasMore" class="related-note">仅显示最近 20 条，请输入更具体的标题继续查找。</p>
        </template>
      </el-collapse-item>
    </el-collapse>
    <CheckinDetailDialog v-if="!editable" ref="checkinDetail" @updated="load" />
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getScheduleRelated, searchScheduleRelated } from '@/api/schedule'
import { useLatestRequest } from '@/composables/useLatestRequest'
import { formatDateTime } from '@/utils/format'
import { downloadFile } from '@/utils/download'
import { errText } from '@/utils/request'
import ListFeedback from '@/components/ListFeedback.vue'
import CheckinDetailDialog from '@/components/CheckinDetailDialog.vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  editable: Boolean,
  scheduleId: { type: Number, default: null },
  viewStudentId: { type: Number, default: null }
})
const emit = defineEmits(['update:modelValue'])
const kinds = { notice: '通知', vote: '投票', collect: '收集', checkin: '签到', resource: '资料' }
const expanded = ref(props.modelValue.length ? ['related'] : [])
const kind = ref('notice')
const keyword = ref('')
const details = ref([])
const results = ref([])
const loading = ref(false)
const searching = ref(false)
const searched = ref(false)
const hasMore = ref(false)
const loadError = ref('')
const searchError = ref('')
const checkinDetail = ref(null)
const latestLoad = useLatestRequest()
const latestSearch = useLatestRequest()
const cache = ref({})
const keyOf = (item) => `${item.kind}-${item.id}`
const items = computed(() => props.modelValue.map((ref) => details.value.find((item) => keyOf(item) === keyOf(ref))
  || cache.value[keyOf(ref)] || { ...ref, title: loadError.value ? '内容加载失败' : '关联内容', kind_label: kinds[ref.kind] }))

async function load() {
  const id = latestLoad.start()
  details.value = []
  loadError.value = ''
  loading.value = false
  if (!props.scheduleId || !props.modelValue.length) return
  loading.value = true
  try {
    const data = await getScheduleRelated(props.scheduleId, props.viewStudentId)
    if (latestLoad.isCurrent(id)) details.value = data
  } catch (error) {
    if (latestLoad.isCurrent(id)) loadError.value = errText(error, '关联内容加载失败')
  } finally {
    if (latestLoad.isCurrent(id)) loading.value = false
  }
}

async function search() {
  const id = latestSearch.start()
  searching.value = true
  searched.value = true
  searchError.value = ''
  hasMore.value = false
  try {
    const data = await searchScheduleRelated(kind.value, keyword.value)
    if (!latestSearch.isCurrent(id)) return
    results.value = data.items
    hasMore.value = data.has_more
  } catch (error) {
    if (latestSearch.isCurrent(id)) searchError.value = errText(error, '查找失败')
  } finally {
    if (latestSearch.isCurrent(id)) searching.value = false
  }
}

const selected = (item) => props.modelValue.some((ref) => keyOf(ref) === keyOf(item))
function add(item) {
  if (selected(item) || props.modelValue.length >= 30) return
  cache.value[keyOf(item)] = item
  emit('update:modelValue', [...props.modelValue, { kind: item.kind, id: item.id }])
}
function remove(index) {
  emit('update:modelValue', props.modelValue.filter((_, i) => i !== index))
}
function move(index, delta) {
  const refs = [...props.modelValue]
  const other = index + delta
  if (other < 0 || other >= refs.length) return
  const item = refs[index]
  refs[index] = refs[other]
  refs[other] = item
  emit('update:modelValue', refs)
}
async function download(item) {
  try {
    await downloadFile(item.url, item.download_name)
  } catch (error) {
    ElMessage.error(errText(error, '下载失败'))
  }
}
watch(() => [props.scheduleId, props.viewStudentId], load, { immediate: true })
</script>

<style scoped>
.schedule-related { margin-top: 16px; width: 100%; }
.related-note, .related-meta { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
.related-list { list-style: none; padding: 0; margin: 0; }
.related-list li { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.related-main { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.related-main strong, .related-meta { display: block; }
.related-warning { display: block; color: var(--el-color-warning-dark-2); font-size: 12px; }
.related-kind { font-size: 12px; color: var(--el-text-color-secondary); }
.related-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.related-actions .el-button + .el-button { margin-left: 0; }
.related-search { display: flex; gap: 8px; margin-top: 12px; }
.related-search .el-select { width: 90px; flex-shrink: 0; }
.related-results { max-height: 240px; overflow-y: auto; }
@media (max-width: 540px) {
  .related-list li { align-items: flex-start; flex-wrap: wrap; }
  .related-actions { width: 100%; }
}
</style>
