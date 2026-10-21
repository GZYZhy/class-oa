<!--
  一份收集答卷的只读展示

  管理端「答卷详情」展开行和答题人回显自己的答卷共用这一份，
  避免两处把题型、选项字母、图片下标各写一遍。

  图片下标是**按题目顺序展开的全局下标**：后端读取接口会跳过没有图片的题，
  前端必须用同一套顺序算，不能直接用 answers 数组里的位置。
-->
<template>
  <div class="ca">
    <div v-for="(question, index) in questions" :key="question.id" class="ca-q">
      <div class="ca-title">
        <span>{{ index + 1 }}. {{ question.title }}</span>
        <el-tag size="small" type="info" effect="plain">
          {{ QUESTION_TYPE_LABEL[question.qtype] || question.qtype }}
        </el-tag>
        <el-tag v-if="question.required" size="small" type="danger" effect="plain">必答</el-tag>
      </div>

      <template v-if="CHOICE_TYPES.has(question.qtype)">
        <div
          v-for="picked in choiceTexts(question)"
          :key="picked"
          class="ca-line"
        >
          {{ picked }}
        </div>
        <div v-if="!choiceTexts(question).length" class="ca-empty">未填写</div>
      </template>

      <template v-else-if="question.qtype === 'image'">
        <div v-if="filesOf(question).length" class="ca-files">
          <el-button
            v-for="(file, fileIndex) in filesOf(question)"
            :key="file.name"
            link
            type="primary"
            @click="openFile(question, file, fileIndex)"
          >
            {{ file.original || file.name }}
          </el-button>
        </div>
        <div v-else class="ca-empty">未上传</div>
      </template>

      <template v-else-if="question.qtype === 'rating'">
        <div v-if="answerOf(question)?.rating != null" class="ca-line">
          {{ answerOf(question).rating }} / {{ question.rating_max || 5 }} 分
        </div>
        <div v-else class="ca-empty">未填写</div>
      </template>

      <template v-else>
        <div v-if="answerOf(question)?.text" class="ca-line ca-text">
          {{ answerOf(question).text }}
        </div>
        <div v-else class="ca-empty">未填写</div>
      </template>
    </div>

    <FileViewer
      v-model="viewer.visible"
      :file-url="viewer.url"
      :file-name="viewer.name"
      title="答卷图片"
    />
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'
import FileViewer from '@/components/FileViewer.vue'
import { CHOICE_TYPES, QUESTION_TYPE_LABEL } from '@/utils/collection'
import { POLL_LETTERS as letters } from '@/utils/poll'

const props = defineProps({
  questions: { type: Array, default: () => [] },
  answers: { type: Array, default: () => [] },
  /** 拼图片地址用；三个都给了才显示可点击的文件 */
  collectionId: { type: [Number, String], default: null },
  responseId: { type: [Number, String], default: null }
})

const viewer = reactive({ visible: false, url: '', name: '' })

const answerMap = computed(() =>
  Object.fromEntries((props.answers || []).map((answer) => [answer.question_id, answer]))
)

/** `${题目 ID}:${题内第几张}` → 全局下标（和后端文件接口一致） */
const fileIndexes = computed(() => {
  const indexes = new Map()
  let offset = 0
  for (const question of props.questions || []) {
    const files = answerMap.value[question.id]?.files || []
    files.forEach((_, index) => indexes.set(`${question.id}:${index}`, offset + index))
    offset += files.length
  }
  return indexes
})

function answerOf(question) {
  return answerMap.value[question.id]
}

function choiceTexts(question) {
  const choices = answerOf(question)?.choices || []
  return choices.map((index) => `${letters[index]}. ${question.options?.[index] ?? ''}`)
}

function filesOf(question) {
  return answerOf(question)?.files || []
}

function openFile(question, file, fileIndex) {
  const globalIndex = fileIndexes.value.get(`${question.id}:${fileIndex}`)
  if (globalIndex == null || !props.collectionId || !props.responseId) return
  viewer.url = `/api/collections/${props.collectionId}/responses/${props.responseId}/files/${globalIndex}`
  viewer.name = file.original || file.name
  viewer.visible = true
}
</script>

<style scoped>
.ca-q {
  padding: 8px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.ca-q:last-of-type {
  border-bottom: none;
}

.ca-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 4px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.ca-line {
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

.ca-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.ca-empty {
  color: var(--el-text-color-placeholder);
}

.ca-files {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
}
</style>
