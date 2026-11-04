<!--
  收集答卷（整卷）

  七种题型：单选、多选、短文本、长文本、图片（最多 3 张）、附件（最多 3 个）、
  评分（1–5）。上传题选中即传（图片先压缩），拿到签名 token 后随整卷提交；
  上传没完成不能交卷。
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

      <!-- 图片 / 附件 -->
      <div v-else-if="UPLOAD_TYPES.has(q.qtype)" class="cb-images">
        <div v-for="(entry, fi) in draft[q.id]" :key="entry.key" class="cb-image">
          <!-- 图片给缩略图；附件给一个后缀角标（pdf/zip 之类没法当图看） -->
          <img
            v-if="entry.previewUrl"
            :src="entry.previewUrl"
            class="cb-thumb"
            alt="待上传图片"
          />
          <div v-else class="cb-thumb cb-file-badge">{{ entry.badge }}</div>
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
            @click="removeFile(q, fi)"
          >
            移除
          </el-button>
        </div>
        <el-button
          v-if="draft[q.id].length < maxFilesOf(q)"
          size="small"
          :disabled="submitting"
          @click="pickFiles(q)"
        >
          {{ q.qtype === 'image' ? '添加图片' : '添加附件' }}（{{ draft[q.id].length }}/{{ maxFilesOf(q) }}）
        </el-button>
        <div class="cb-sub">{{ uploadHint(q) }}</div>
      </div>
    </div>

    <!-- 所有上传题的选文件入口共用一个原生 input：手机上点一下就能调起相册/文件管理 -->
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
  ATTACH_ACCEPT,
  ATTACH_SUFFIXES,
  FILE_MAX_FILES,
  FILE_MAX_MB,
  IMAGE_MAX_FILES,
  IMAGE_MAX_MB,
  QUESTION_TYPE_LABEL,
  RATING_MAX,
  RATING_MIN,
  TEXT_LIMITS,
  UPLOAD_TYPES
} from '@/utils/collection'
import { POLL_LETTERS as letters } from '@/utils/poll'
import { errText } from '@/utils/request'

const props = defineProps({
  collection: { type: Object, required: true },
  submitting: { type: Boolean, default: false },
  /** 管理员代填时的目标学号；图片凭证要绑到这个人 */
  studentNo: { type: String, default: '' },
  /** 管理员代填时的目标姓名，用于确认文案 */
  proxyName: { type: String, default: '' }
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
  if (UPLOAD_TYPES.has(question.qtype)) return []
  if (question.qtype === 'rating') return null
  return ''
}

function maxFilesOf(question) {
  if (question.qtype === 'image') return question.max_files || IMAGE_MAX_FILES
  return question.max_files || FILE_MAX_FILES
}

/** 上传区下面那行小字：说清能传什么、多大、会不会被压缩 */
function uploadHint(question) {
  if (question.qtype === 'image') {
    return `JPG / PNG / WebP，单张 ≤${IMAGE_MAX_MB}MB，自动压缩`
  }
  return `图片 / 视频 / 音频 / 文档 / 压缩包，单个 ≤${FILE_MAX_MB}MB`
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

// ---------- 图片 / 附件上传 ----------

function pickFiles(question) {
  activeQuestion = question
  if (fileInput.value) {
    // 图片题只让选图片；附件题放开到整份白名单
    fileInput.value.accept = question.qtype === 'image'
      ? 'image/jpeg,image/png,image/webp'
      : ATTACH_ACCEPT
    // 清空上一次的选择，否则同一个文件再选一次不会触发 change
    fileInput.value.value = ''
    fileInput.value.click()
  }
}

/** 小写后缀（含点） */
function fileExt(name) {
  const text = String(name || '')
  const index = text.lastIndexOf('.')
  return index >= 0 ? text.slice(index).toLowerCase() : ''
}

async function onFilesChange(event) {
  const question = activeQuestion
  const picked = Array.from(event.target.files || [])
  event.target.value = ''
  if (!question || !picked.length) return

  const isImage = question.qtype === 'image'
  const maxFiles = maxFilesOf(question)
  const unit = isImage ? '张图片' : '个附件'
  const slots = maxFiles - draft[question.id].length
  if (slots <= 0) return ElMessage.warning(`这题最多 ${maxFiles} ${unit}`)
  const files = picked.slice(0, slots)
  if (picked.length > slots) {
    ElMessage.warning(`这题最多 ${maxFiles} ${unit}，已选择前 ${slots} 个`)
  }

  for (const file of files) {
    if (isImage) {
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
        ElMessage.warning(`${file.name} 不是 JPG/PNG/WebP 图片`)
        continue
      }
    } else {
      // 前端先拦一道，后端还会按白名单再验一次（真正算数的在后端）
      if (!ATTACH_SUFFIXES.includes(fileExt(file.name))) {
        ElMessage.warning(`${file.name} 的类型不支持`)
        continue
      }
      if (file.size > FILE_MAX_MB * 1024 * 1024) {
        ElMessage.warning(`${file.name} 超过 ${FILE_MAX_MB}MB`)
        continue
      }
    }
    const entry = reactive({
      key: `up-${entrySeq++}`,
      file,
      previewUrl: isImage ? URL.createObjectURL(file) : '',
      // 附件没有缩略图，用后缀当角标（PDF / ZIP / DOCX）
      badge: (fileExt(file.name).replace('.', '') || '文件').toUpperCase().slice(0, 5),
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
  const isImage = question.qtype === 'image'
  try {
    let file = entry.file
    if (isImage) {
      // 压缩是优化：失败会退回原文件（见 imageCompress.js）
      file = await compressImage(entry.file)
      if (file.size > IMAGE_MAX_MB * 1024 * 1024) {
        entry.error = `图片超过 ${IMAGE_MAX_MB}MB，请换一张`
        return
      }
      entry.file = file
    } else if (file.size > FILE_MAX_MB * 1024 * 1024) {
      entry.error = `附件超过 ${FILE_MAX_MB}MB，请换一个`
      return
    }
    // kind 交给后端选白名单和大小上限：图片题和附件题的限制不一样
    const res = await uploadCollectionFile(
      props.collection.id,
      file,
      (loaded, total) => {
        entry.percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : null
      },
      props.studentNo,
      question.qtype
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

function removeFile(question, index) {
  const [entry] = draft[question.id].splice(index, 1)
  if (entry?.previewUrl) URL.revokeObjectURL(entry.previewUrl)
}

// ---------- 校验与提交 ----------

function isEmpty(question, value) {
  if (question.qtype === 'multiple') return !value.length
  if (UPLOAD_TYPES.has(question.qtype)) return !value.length
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
    } else if (UPLOAD_TYPES.has(question.qtype)) {
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

  // 图片/附件必须先传出 token；有还在传或失败的，整卷先别交
  for (let index = 0; index < questions.length; index += 1) {
    const question = questions[index]
    if (!UPLOAD_TYPES.has(question.qtype)) continue
    const entries = draft[question.id]
    const thing = question.qtype === 'image' ? '图片' : '附件'
    if (entries.some((entry) => entry.uploading)) {
      return ElMessage.warning(`第 ${index + 1} 题的${thing}还在上传，请稍候`)
    }
    if (entries.some((entry) => !entry.token)) {
      return ElMessage.warning(`第 ${index + 1} 题有${thing}没上传成功，请重试或移除`)
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
  const owner = props.proxyName ? `${props.proxyName}的` : '你的'
  const withdrawTip = props.collection.allow_withdraw
    ? '发起人允许撤回，提交后可以在本页撤回。'
    : '提交后不能修改。'
  try {
    await ElMessageBox.confirm(
      quota > 1
        ? `这是${owner}第 ${nth} 份答卷，每人最多 ${quota} 份。${withdrawTip}确定提交吗？`
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

/* 附件没有缩略图：同一个 54×54 的方块里写后缀，和图片列表对齐 */
.cb-file-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  letter-spacing: 0.5px;
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
