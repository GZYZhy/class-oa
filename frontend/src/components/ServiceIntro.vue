<script setup>
/**
 * 办件页面顶部的说明块。三个办件共用这一套写法：
 * 办件详情（办件介绍 / 办结时限 / 注意事项）、提交材料、办结材料。
 *
 * 各页各写一份的话，改一次措辞得动三处、还容易漏一处，所以只把每项的话传进来。
 * 没传的项按「未指定」显示 —— 办件介绍和办结时限眼下就是空着的，等内容定了再传。
 */
defineProps({
  intro: { type: String, default: '' },      // 办件介绍
  deadline: { type: String, default: '' },   // 办结时限
  notice: { type: String, default: '' },     // 注意事项
  submitted: { type: String, default: '' },  // 提交材料
  finished: { type: String, default: '' }    // 办结材料
})
</script>

<template>
  <div class="service-intro">
    <section class="intro-block">
      <h4 class="intro-title">办件详情</h4>
      <div
        v-for="row in [
          { label: '办件介绍', value: intro },
          { label: '办结时限', value: deadline },
          { label: '注意事项', value: notice }
        ]"
        :key="row.label"
        class="intro-row"
      >
        <span class="intro-label">{{ row.label }}</span>
        <span class="intro-value" :class="{ blank: !row.value }">{{ row.value || '未指定' }}</span>
      </div>
    </section>

    <section class="intro-block">
      <h4 class="intro-title">提交材料</h4>
      <p class="intro-value" :class="{ blank: !submitted }">{{ submitted || '未指定' }}</p>
    </section>

    <section class="intro-block">
      <h4 class="intro-title">办结材料</h4>
      <p class="intro-value" :class="{ blank: !finished }">{{ finished || '未指定' }}</p>
    </section>
  </div>
</template>

<style scoped>
.service-intro {
  margin-bottom: 20px;
  padding: 16px 18px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.7;
}

.intro-block + .intro-block {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.intro-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.intro-row {
  display: flex;
  gap: 10px;
}

.intro-row + .intro-row {
  margin-top: 4px;
}

/* 三个名目都是四个字，钉住宽度右边的值才左对齐（跟着字数走就会参差） */
.intro-label {
  flex: 0 0 56px;
  color: var(--el-text-color-secondary);
}

.intro-value {
  flex: 1;
  min-width: 0;
  margin: 0;
  color: var(--el-text-color-regular);
  /* 传进来的话里有换行就照换行排，长句在窄屏上也能正常折 */
  white-space: pre-line;
}

/* 还没定的项淡一档，跟写好的内容区分开 */
.blank {
  color: var(--el-text-color-placeholder);
}

@media (max-width: 768px) {
  .service-intro {
    padding: 14px;
  }
}
</style>
