<template>
  <div class="channel-block">
    <!-- 默认折叠：这是给懂行的人用的，绝大多数同学不该被它吸引注意力 -->
    <el-collapse v-model="active">
      <el-collapse-item name="webhook">
        <template #title>
          <span class="collapse-title">自定义 Webhook</span>
          <!-- 折叠着就能看出这条渠道现在发不发。没有地址时什么也不显示 ——
               那时开关必然是关的（后端保存时就归一了），再挂个「已关闭」
               只会让人以为是有人手动关的 -->
          <span
            class="collapse-badge"
            v-if="saved.url"
            :class="{ off: !saved.enabled }"
          >{{ saved.enabled ? '已开启' : '已关闭' }}</span>
        </template>

        <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 16px;">
          <template #title>如果你不知道这是啥，请不要动哦</template>
          填了之后，本站的通知会以 POST 请求发到你填的地址。只有你自己清楚那是个什么服务时才填。
        </el-alert>

        <el-form :model="form" label-width="100px" :disabled="busy">
          <el-form-item label="接收地址">
            <el-input
              v-model="form.url"
              placeholder="https://…"
              clearable
            />
          </el-form-item>
          <el-form-item label="请求体模板">
            <el-input
              v-model="form.template"
              type="textarea"
              :rows="6"
              :placeholder="defaultTemplate"
            />
          </el-form-item>
          <el-form-item label="开启通知">
            <el-switch v-model="form.enabled" />
            <span class="desc" style="margin-left: 12px;">打开后才会往这个地址发</span>
          </el-form-item>
        </el-form>

        <div class="hint-note" v-pre>
          模板是一段 JSON。里面可以写 {{title}}、{{content}}、{{page}}、{{time}}
          四个占位符，发送时会被替换成通知的标题、正文、站内链接和时间。
          清空则用默认模板（就是上面输入框里灰字显示的那份），那种写法可以直接贴到
          企业微信 / 钉钉 / 飞书机器人里。
        </div>

        <div class="actions">
          <el-button size="small" :loading="testing" @click="handleTest">发送测试</el-button>
          <el-button type="primary" size="small" :loading="saving" @click="handleSave">保存</el-button>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getWebhookSetting, saveWebhookSetting, testWebhook } from '@/api/notifyChannels'

// 空数组 = 全部收起。每次进页面都是折叠的，展开状态不记住是有意的：
// 这东西不该成为「顺手点开看看」的入口。
const active = ref([])
const form = reactive({ url: '', template: '', enabled: false })
const defaultTemplate = ref('')
// 库里已存的开关和地址，只用来显示标题右边那个状态角标，不参与提交
// （提交一律用输入框里的值）。不用 form 里的值：那是用户正在编辑、还没保存的东西，
// 拿它当角标会在用户一拨开关时就说「已开启」，而库里其实还没变
const saved = reactive({ url: '', enabled: false })
const saving = ref(false)
const testing = ref(false)
const busy = ref(false)

async function load() {
  try {
    const data = await getWebhookSetting()
    form.url = data.url || ''
    form.template = data.template || ''
    form.enabled = !!data.enabled
    defaultTemplate.value = data.default_template || ''
    saved.url = data.url || ''
    saved.enabled = !!data.enabled
  } catch (e) {
    // 接口探测失败时父组件根本不会渲染本组件，能走到这里说明是别的原因（比如断网）
    ElMessage.error(e?.response?.data?.detail || '读取 Webhook 设置失败')
  }
}

async function doSave() {
  // 没填地址就没有「开着」的意义，后端保存时也是这么归一的（见 set_webhook）。
  // 这里跟着算一遍，免得保存完开关还亮着、库里其实已经是关的了
  const enabled = form.enabled && !!form.url.trim()
  const res = await saveWebhookSetting(form.url.trim(), form.template, enabled)
  form.enabled = enabled
  saved.url = form.url.trim()
  saved.enabled = enabled
  return res
}

async function handleSave() {
  saving.value = true
  busy.value = true
  try {
    const res = await doSave()
    ElMessage.success(res.message || '已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
    busy.value = false
  }
}

async function handleTest() {
  testing.value = true
  busy.value = true
  try {
    // 先存再测：测试端点只发库里已存的地址（它不接受请求体传地址，
    // 否则就成了一个人人可用的「往任意地址发 POST」的接口）。和 Bark 那边同一套顺序
    await doSave()
    const res = await testWebhook()
    ElMessage.success(res.message || '已发送')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发送失败')
  } finally {
    testing.value = false
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped>
/* 父组件 MyInfo.vue 的样式是 scoped 的，跨组件不生效，所以这里自带一份。
   同 .pagination-wrap 那份注释的由来 */
.collapse-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.collapse-badge {
  margin-left: 8px;
  padding: 1px 8px;
  border-radius: 10px;
  background: #ecf5ff;
  color: #409eff;
  font-size: 12px;
  font-weight: 400;
}

/* 配了地址但开关关着：灰色，和「已开启」的蓝色区分开 */
.collapse-badge.off {
  background: #f4f4f5;
  color: #909399;
}

.desc {
  font-size: 12px;
  color: #909399;
}

.hint-note {
  font-size: 12px;
  color: #909399;
  margin-top: 8px;
  line-height: 1.6;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0 0 0;
}
</style>
