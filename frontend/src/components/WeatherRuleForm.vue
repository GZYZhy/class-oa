<template>
  <el-form :model="rule" label-width="96px" :disabled="disabled">
    <el-form-item label="关注天气">
      <el-checkbox-group v-model="rule.conditions">
        <el-checkbox v-for="c in meta.conditions" :key="c.code" :value="c.code">
          {{ c.label }}
        </el-checkbox>
      </el-checkbox-group>
    </el-form-item>

    <el-form-item label="关注时段">
      <el-radio-group v-model="rule.window">
        <el-radio-button v-for="w in meta.windows" :key="w.code" :value="w.code">
          {{ w.label }}
        </el-radio-button>
      </el-radio-group>
    </el-form-item>

    <!-- 夜间天气：过滤的是天气发生的时间，不是推送时间（推送另有免打扰） -->
    <el-form-item label="夜间天气">
      <el-switch v-model="rule.ignore_night" />
      <span class="rule-unit">
        忽略 22:00–06:00 的降水 / 降雪 / 雷暴；高温、低温、大风仍按全天判断
      </span>
    </el-form-item>

    <!-- 阈值：可定制化主要就体现在这四个数上，默认值给的是「一般人有感的线」 -->
    <el-form-item label="降雨概率">
      <el-input-number v-model="rule.rain_threshold" :min="10" :max="100" :step="10" size="small" />
      <span class="rule-unit">% 及以上</span>
    </el-form-item>
    <el-form-item label="高温阈值">
      <el-input-number v-model="rule.heat_threshold" :min="20" :max="45" size="small" />
      <span class="rule-unit">℃ 及以上</span>
    </el-form-item>
    <el-form-item label="低温阈值">
      <el-input-number v-model="rule.cold_threshold" :min="-40" :max="15" size="small" />
      <span class="rule-unit">℃ 及以下</span>
    </el-form-item>
    <el-form-item label="大风阈值">
      <el-input-number v-model="rule.wind_threshold" :min="10" :max="120" :step="5" size="small" />
      <span class="rule-unit">km/h（39 约 6 级）</span>
    </el-form-item>

    <!-- 只有个人提醒有「免打扰」：横幅是页面上的东西，不存在打扰 -->
    <el-form-item v-if="showQuiet" label="免打扰">
      <el-select v-model="rule.quiet_start" size="small" style="width: 92px;">
        <el-option v-for="h in hours" :key="h" :label="`${h}:00`" :value="h" />
      </el-select>
      <span class="rule-unit">至</span>
      <el-select v-model="rule.quiet_end" size="small" style="width: 92px;">
        <el-option v-for="h in hours" :key="h" :label="`${h}:00`" :value="h" />
      </el-select>
      <span class="rule-unit">之间不推送</span>
    </el-form-item>
  </el-form>
</template>

<script setup>
/**
 * 天气规则表单：个人提醒和管理员横幅共用一份
 *
 * 两边的字段与取值范围完全一致（后端也是同一套判断），各写一份必然对不上。
 * 「免打扰」只有个人提醒需要，用 showQuiet 控制。
 *
 * 传进来的 rule 是父组件持有的 reactive 对象，这里**直接改它的字段**，
 * 不再往外 emit 一份副本：父组件保存时读到的就是同一份数据，少一层同步。
 */
defineProps({
  rule: { type: Object, required: true },
  meta: { type: Object, default: () => ({ conditions: [], windows: [] }) },
  showQuiet: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})

const hours = Array.from({ length: 24 }, (_, i) => i)
</script>

<style scoped>
.rule-unit {
  margin-left: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
