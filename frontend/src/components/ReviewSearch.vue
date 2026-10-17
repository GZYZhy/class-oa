<script setup>
/**
 * 审核页七个 tab 共用的搜索栏：提交人（姓名/学号）+ 提交日期
 *
 * 只负责收字和发 `search` 事件，拉哪个列表由调用方决定（各 tab 的接口和分页不同）。
 * 日期范围给的是 YYYY-MM-DD，后端按自然日算、含首尾两天。
 */
import { computed } from 'vue'

const props = defineProps({
  keyword: { type: String, default: '' },
  range: { type: Array, default: null }
})
const emit = defineEmits(['update:keyword', 'update:range', 'search'])

// el-input / el-date-picker 要可写的 v-model，这里转成对外的 update 事件
const keywordValue = computed({
  get: () => props.keyword,
  set: (value) => emit('update:keyword', value)
})
const rangeValue = computed({
  get: () => props.range,
  set: (value) => emit('update:range', value)
})

function reset() {
  emit('update:keyword', '')
  emit('update:range', null)
  emit('search')
}
</script>

<template>
  <div class="review-search">
    <el-input
      v-model="keywordValue"
      placeholder="提交人姓名或学号"
      clearable
      style="width: 170px"
      @keyup.enter="emit('search')"
      @clear="emit('search')"
    />
    <el-date-picker
      v-model="rangeValue"
      type="daterange"
      range-separator="至"
      start-placeholder="提交开始"
      end-placeholder="提交结束"
      value-format="YYYY-MM-DD"
      style="width: 240px"
      @change="emit('search')"
    />
    <!-- 两个按钮包在一起：窄屏换行时「查询」留在上一行、「重置」掉到下一行，
         会被当成两个不相干的按钮 -->
    <span class="review-search-actions">
      <el-button type="primary" @click="emit('search')">查询</el-button>
      <el-button @click="reset">重置</el-button>
    </span>
  </div>
</template>

<style scoped>
.review-search {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.review-search-actions {
  display: inline-flex;
  gap: 8px;
}
</style>
