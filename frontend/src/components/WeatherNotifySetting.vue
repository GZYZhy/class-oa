<template>
  <div class="channel-block">
    <div class="section-title">天气提醒</div>
    <div class="section-sub">
      按你选的条件，每几小时看一次预报，命中就推给你（站内信一定会有）
    </div>

    <div v-loading="loading">
      <el-form label-width="96px">
        <el-form-item label="开启提醒">
          <el-switch v-model="rule.enabled" />
          <span class="rule-hint">关掉就什么都不会推</span>
        </el-form-item>
      </el-form>

      <WeatherRuleForm :rule="rule" :meta="meta" show-quiet :disabled="!rule.enabled" />

      <div class="actions">
        <el-button type="primary" size="small" :loading="saving" @click="handleSave">
          保存
        </el-button>
      </div>

      <div class="rule-note">
        预报来自 Open-Meteo，是概率型数据：写着「可能有雨」不代表一定下。
        位置由管理员在站点配置里指定（当前是本班级所在地）。
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getWeatherNotify, saveWeatherNotify } from '@/api/weather'
import WeatherRuleForm from '@/components/WeatherRuleForm.vue'

const loading = ref(false)
const saving = ref(false)

// 字段名和后端一一对应；未加载完成时给一份保守默认值，避免表单项闪成空
const rule = reactive({
  enabled: false,
  conditions: ['rain'],
  rain_threshold: 60,
  heat_threshold: 35,
  cold_threshold: 0,
  wind_threshold: 39,
  window: 'tomorrow',
  quiet_start: 22,
  quiet_end: 7
})

// 可选条件 / 时段的中文标签由后端给，前端不另写一份
const meta = reactive({ conditions: [], windows: [] })

async function load() {
  loading.value = true
  try {
    const data = await getWeatherNotify()
    rule.enabled = !!data.enabled
    rule.conditions = data.conditions || []
    rule.rain_threshold = data.rain_threshold
    rule.heat_threshold = data.heat_threshold
    rule.cold_threshold = data.cold_threshold
    rule.wind_threshold = data.wind_threshold
    rule.window = data.window || 'tomorrow'
    rule.quiet_start = data.quiet_start
    rule.quiet_end = data.quiet_end
    meta.conditions = data.available_conditions || []
    meta.windows = data.windows || []
  } catch (e) {
    ElMessage.error('天气提醒设置加载失败')
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  if (rule.enabled && !rule.conditions.length) {
    return ElMessage.warning('至少要选一种天气')
  }
  saving.value = true
  try {
    await saveWeatherNotify({ ...rule })
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.rule-hint {
  margin-left: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.rule-note {
  margin-top: 12px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-placeholder);
}
</style>
