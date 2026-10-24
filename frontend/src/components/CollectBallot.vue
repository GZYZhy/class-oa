<!--
  收集答卷（整卷）

  六种题型：单选、多选、短文本、长文本、图片（最多 3 张）、评分（1–5）。
  图片选中即压缩上传，拿到签名 token 后随整卷提交；上传没完成不能交卷。
  提交后不能改（发起人允许时可撤回），所以确认框会写清楚这是第几份。
-->
<template>
  <div class="cb">
    <div v-for="(q, index) in collection.questions" :key="q.id" class="cb-q">
      <div class="cb-q-title">
        <span>{{ index + 1 }}. {{ q.title }}</span>
        <el-tag size="small" type="info" effect="plain">
          {{ QUESTION_TYPE_LABEL[q.qtype] || q.qtype }}
        </el-tag>
        <el-tag v-if="q.required" size="small" type="danger" effect="plain">必答</el-tag>
        <span v-else class="cb-sub">选答</span>
        <span v-if="q.qtype === 'multiple'" class="cb-sub">最多选 {{ q.max_choices }} 项</span>
      </div>

      <!-- 单选 -->
      <el-radio-group v-if="q.qtype === 'single'" v-model="draft[q.id]">
        <el-radio v-for="(option, oi) in q.options" :key="oi" :value="oi">
          <span class="cb-letter">{{ letters[oi] }}.</span> {{ option }}
        </el-radio>
      </el-radio-group>

      <!-- 多选 -->
      <el-checkbox-group
        v-else-if="q.qtype === 'multiple'"
        v-model="draft[q.id]"
        :max="q.max_choices"
      >
        <el-checkbox v-for="(option, oi) in q.options" :key="oi" :value="oi">
          <span class="cb-letter">{{ letters[oi] }}.</span> {{ option }}
        </el-checkbox>
      </el-checkbox-group>

      <!-- 短文本 / 长文本 -->
      <el-input
        v-else-if="q.qtype === 'short_text'"
        v-model="draft[q.id]"
        :maxlength="q.text_limit || 200"
        show-word-limit
        placeholder="请填写"
      />
      <el-input
        v-else-if="q.qtype === 'long_text'"
        v-model="draft[q.id]"
        type="textarea"
        :rows="5"
        :maxlength="q.text_limit || 2000"
        show-word-limit
        placeholder="请填写"
      />

      <!-- 评分（1–5） -->
      <el-radio-group v-else-if="q.qtype === 'rating'" v-model="draft[q.id]" class="cb-rating">
        <el-radio-button
          v-for="value in ratingValues(q)"
          :key="value"
          :value="value"
        >
          {{ value }} 分
        </el-radio-button>
      </el-radio-group>

      <!-- 图片 -->
      <div v-else-if="q.qtype === 'image'" class="cb-images">
        <div v-for="(entry, fi) in draft[q.id]" :key="entry.key" class="cb-image">
          <img :src="entry.previewUrl" class="cb-thumb" alt="待上传图片" />
          <div class="cb-image-info">
            <div class="cb-image-name">{{ entry.name }}</div>
            <el-progress
              v-if="entry.uploading"
              :percentage="entry.percent ?? 0"
              :indeterminate="entry.percent === null"
              :stroke-width="5"
            />
            <div v-else-if="entry.error" class="cb-error">
              {{ entry.error }}
              <el-button link type="primary" size="small" @click="retryUpload(q, entry)">
                重试
              </el-button>
            </div>
            <div v-else class="cb-sub">已上传</div>
          </div>
          <el-button
            link
            type="danger"
            :disabled="entry.uploading"
            @click="removeImage(q, fi)"
          >
            移除
          </el-button>
        </div>
        <el-button
          v-if="draft[q.id].length < (q.max_files || IMAGE_MAX_FILES)"
          size="small"
          :disabled="submitting"
          @click="pickFiles(q)"
        >
          添加图片（{{ draft[q.id].length }}/{{ q.max_files || IMAGE_MAX_FILES }}）
        </el-button>
        <div class="cb-sub">JPG / PNG / WebP，单张 ≤10MB，自动压缩</div>
      </div>
    </div>

    <!-- 所有图片题的选图入口共用一个原生 input：手机上点一下就能调起相册 -->
    <input
      ref="fileInput"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      multiple
      class="cb-file"
      @change="onFilesChange"
    />

    <p class="cb-hint">
      带「必答」的题必须填写，选答题可以留空。提交后不能修改
      <template v-if="collection.allow_withdraw">；发起人允许撤回，提交后可在本页撤回</template>
    </p>

    <div class="cb-actions">
      <el-button type="primary" size="large" :loading="submitting" @click="handleSubmit">
        提交这份答卷
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { uploadCollectionFile } from '@/api/collection'
import { compressImage } from '@/utils/imageCompress'
import {
  IMAGE_MAX_FILES,
  QUESTION_TYPE_LABEL,
  RATING_MAX,
  RATING_MIN,
  TEXT_LIMITS
} from '@/utils/collection'
import { POLL_LETTERS as letters } from '@/utils/poll'
import { errText } from '@/utils/request'

const props = defineProps({
  collection: { type: Object, required: true },
  submitting: { type: Boolean, default: false }
})
const emit = defineEmits(['submit'])

const draft = reactive({})
const fileInput = ref(null)
/** 正在选图的是哪道题 */
let activeQuestion = null
let entrySeq = 0

function blankValue(question) {
  if (question.qtype === 'single') return null
  if (question.qtype === 'multiple') return []
  if (question.qtype === 'image') return []
  if (question.qtype === 'rating') return null
  return ''
}

function resetDraft() {
  Object.keys(draft).forEach((key) => {
    revokeImages(draft[key])
    delete draft[key]
  })
  ;(props.collection?.questions || []).forEach((question) => {
    draft[question.id] = blankValue(question)
  })
}

function revokeImages(entries) {
  if (!Array.isArray(entries)) return
  entries.forEach((entry) => {
    if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl)
  })
}

watch(() => props.collection?.id, resetDraft, { immediate: true })
onBeforeUnmount(() => {
  Object.values(draft).forEach(revokeImages)
})

function ratingValues(question) {
  const min = question.rating_min || RATING_MIN
  const max = question.rating_max || RATING_MAX
  return Array.from({ length: max - min + 1 }, (_, index) => min + index)
}

// ---------- 图片上传 ----------

function pickFiles(question) {
  activeQuestion = question
  if (fileInput.value) {
    // 清空上一次的选择，否则同一张图再选一次不会触发 change
    fileInput.value.value = ''
    fileInput.value.click()
  }
}

async function onFilesChange(event) {
  const question = activeQuestion
  const picked = Array.from(event.target.files || [])
  event.target.value = ''
  if (!question || !picked.length) return

  const maxFiles = question.max_files || IMAGE_MAX_FILES
  const slots = maxFiles - draft[question.id].length
  if (slots <= 0) return ElMessage.warning(`这题最多 ${maxFiles} 张图片`)
  const files = picked.slice(0, slots)
  if (picked.length > slots) {
    ElMessage.warning(`这题最多 ${maxFiles} 张图片，已选择前 ${slots} 张`)
  }

  for (const file of files) {
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      ElMessage.warning(`${file.name} 不是 JPG/PNG/WebP 图片`)
      continue
    }
    const entry = reactive({
      key: `img-${entrySeq++}`,
      file,
      previewUrl: URL.createObjectURL(file),
      name: file.name,
      token: '',
      uploading: true,
      percent: null,
      error: ''
    })
    draft[question.id].push(entry)
    await uploadEntry(question, entry)
  }
}

async function uploadEntry(question, entry) {
  entry.uploading = true
  entry.percent = null
  entry.error = ''
  try {
    // 压缩是优化：失败会退回原文件（见 imageCompress.js）
    const compressed = await compressImage(entry.file)
    if (compressed.size > 10 * 1024 * 1024) {
      entry.error = '图片超过 10MB，请换一张'
      return
    }
    entry.file = compressed
    const res = await uploadCollectionFile(
      props.collection.id,
      compressed,
      (loaded, total) => {
        entry.percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : null
      }
    )
    entry.token = res.token
    entry.name = res.name || entry.name
  } catch (e) {
    entry.error = errText(e, '上传失败，请重试')
  } finally {
    entry.uploading = false
  }
}

function retryUpload(question, entry) {
  if (!entry.file) return
  uploadEntry(question, entry)
}

function removeImage(question, index) {
  const [entry] = draft[question.id].splice(index, 1)
  if (entry?.previewUrl) URL.revokeObjectURL(entry.previewUrl)
}

// ---------- 校验与提交 ----------

function isEmpty(question, value) {
  if (question.qtype === 'multiple') return !value.length
  if (question.qtype === 'image') return !value.length
  if (question.qtype === 'rating' || question.qtype === 'single') return value == null || value === ''
  return !String(value || '').trim()
}

function buildAnswers() {
  const answers = []
  for (const question of props.collection.questions) {
    const value = draft[question.id]
    if (isEmpty(question, value)) continue
    if (question.qtype === 'single' || question.qtype === 'multiple') {
      answers.push({
        question_id: question.id,
        choices: (Array.isArray(value) ? [...value] : [value]).sort((a, b) => a - b)
      })
    } else if (question.qtype === 'image') {
      answers.push({
        question_id: question.id,
        files: value.map((entry) => entry.token)
      })
    } else if (question.qtype === 'rating') {
      answers.push({ question_id: question.id, rating: Number(value) })
    } else {
      answers.push({ question_id: question.id, text: String(value).trim() })
    }
  }
  return answers
}

async function handleSubmit() {
  if (props.submitting) return
  const questions = props.collection.questions || []

  for (let index = 0; index < questions.length; index += 1) {
    const question = questions[index]
    const value = draft[question.id]
    if (!question.required) continue
    if (isEmpty(question, value)) {
      return ElMessage.warning(`第 ${index + 1} 题是必答题，还没填写`)
    }
  }

  // 图片必须先传出 token；有还在传或失败的，整卷先别交
  for (let index = 0; index < questions.length; index += 1) {
    const question = questions[index]
    if (question.qtype !== 'image') continue
    const entries = draft[question.id]
    if (entries.some((entry) => entry.uploading)) {
      return ElMessage.warning(`第 ${index + 1} 题的图片还在上传，请稍候`)
    }
    if (entries.some((entry) => !entry.token)) {
      return ElMessage.warning(`第 ${index + 1} 题有图片没上传成功，请重试或移除`)
    }
  }

  for (let index = 0; index < questions.length; index += 1) {
    const question = questions[index]
    if (question.qtype === 'multiple' && draft[question.id].length > (question.max_choices || 0)) {
      return ElMessage.warning(`第 ${index + 1} 题最多选 ${question.max_choices} 项`)
    }
    if (question.qtype === 'short_text' || question.qtype === 'long_text') {
      const limit = question.text_limit || TEXT_LIMITS[question.qtype]
      if (String(draft[question.id] || '').length > limit) {
        return ElMessage.warning(`第 ${index + 1} 题最多 ${limit} 字`)
      }
    }
  }

  const answers = buildAnswers()
  if (!answers.length) return ElMessage.warning('至少填写一道题')

  const quota = props.collection.submit_quota || 1
  const nth = (props.collection.my_submitted_count || 0) + 1
  const withdrawTip = props.collection.allow_withdraw
    ? '发起人允许撤回，提交后可以在本页撤回。'
    : '提交后不能修改。'
  try {
    await ElMessageBox.confirm(
      quota > 1
        ? `这是你的第 ${nth} 份答卷，每人最多 ${quota} 份。${withdrawTip}确定提交吗？`
        : `每人只能填 1 份。${withdrawTip}确定提交吗？`,
      '提交确认',
      { type: 'warning', confirmButtonText: '确定提交', cancelButtonText: '再检查一下' }
    )
  } catch {
    return
  }

  emit('submit', answers)
}
</script>

<style scoped>
.cb-q {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.cb-q:last-of-type {
  border-bottom: none;
}

.cb-q-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.cb-sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.cb-letter {
  display: inline-block;
  min-width: 1.5em;
}

.cb-q :deep(.el-radio-group),
.cb-q :deep(.el-checkbox-group) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

/* 评分是横排按钮，不跟着上面的纵向排列 */
.cb-q :deep(.el-radio-group.cb-rating) {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 0;
}

.cb-images {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.cb-image {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  max-width: 460px;
  padding: 6px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.cb-thumb {
  width: 54px;
  height: 54px;
  flex: none;
  object-fit: cover;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.cb-image-info {
  flex: 1;
  min-width: 0;
}

.cb-image-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.cb-error {
  font-size: 12px;
  color: var(--el-color-danger);
}

.cb-file {
  display: none;
}

.cb-hint {
  margin: 4px 0 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.cb-actions {
  display: flex;
  justify-content: center;
  padding-top: 8px;
}
</style>
