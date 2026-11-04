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

    <!--
      夜间时段：一个设置管两件事。原先这里是「忽略夜间天气」开关、下面另有一个
      「免打扰」时段，两个开关讲的是同一件事的两半（别半夜吵我 / 凌晨的雨不算数），
      已合并成时段一个口径：设了时段就两件事一起生效，起止相等 = 关闭。
      官方预警不受这段影响 —— 它是「现在正生效」的权威信息。
    -->
    <el-form-item v-if="showQuiet" :label="quietLabel">
      <el-select v-model="rule.quiet_start" size="small" style="width: 92px;">
        <el-option v-for="h in hours" :key="h" :label="`${h}:00`" :value="h" />
      </el-select>
      <span class="rule-unit">至</span>
      <el-select v-model="rule.quiet_end" size="small" style="width: 92px;">
        <el-option v-for="h in hours" :key="h" :label="`${h}:00`" :value="h" />
      </el-select>
      <span class="rule-unit">{{ quietHint }}</span>
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

  </el-form>
</template>

<script setup>
/**
 * 天气规则表单：个人提醒和管理员横幅共用一份
 *
 * 两边的字段与取值范围完全一致（后端也是同一套判断），各写一份必然对不上。
 * 「夜间时段」两边都有，只是叫法不同（个人叫免打扰，横幅叫夜间时段），
 * 说明文字用 quietLabel / quietHint 传，默认那套是个人提醒的口径。
 *
 * 传进来的 rule 是父组件持有的 reactive 对象，这里**直接改它的字段**，
 * 不再往外 emit 一份副本：父组件保存时读到的就是同一份数据，少一层同步。
 */
defineProps({
  rule: { type: Object, required: true },
  meta: { type: Object, default: () => ({ conditions: [], windows: [] }) },
  showQuiet: { type: Boolean, default: false },
  quietLabel: { type: String, default: '夜间免打扰' },
  quietHint: {
    type: String,
    default: '之间不推送；其中的降水 / 降雪 / 雷暴也不算数（官方预警不受影响）'
  },
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
