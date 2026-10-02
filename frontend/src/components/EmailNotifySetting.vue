<template>
  <div class="channel-block">
    <div class="section-title">电子邮件通知</div>
    <div class="section-sub">发到你的邮箱，不用装 App，也不用打开浏览器</div>

    <!-- 管理员没把 SMTP 配齐时全站没人能收到邮件。与其让用户对着一个存得下、
         按钮也点得动、就是不来信的开关，不如直接说清楚并置灰 -->
    <el-alert v-if="!smtpEnabled" type="info" :closable="false" show-icon style="margin-bottom: 16px;">
      <template #title>管理员还没有配置发信服务（SMTP），此渠道暂不可用</template>
      等管理员配好之后，这里的开关会自动变成可用的，你到时再打开就行。
    </el-alert>

    <el-form :model="form" label-width="100px" :disabled="!smtpEnabled || busy">
      <el-form-item label="接收邮箱">
        <el-input v-model="form.email" :placeholder="emailPlaceholder" clearable />
      </el-form-item>
      <el-form-item label="开启通知">
        <el-switch v-model="form.enabled" />
        <span class="desc" style="margin-left: 12px;">打开后才会给你发邮件</span>
      </el-form-item>
    </el-form>

    <div class="hint-note" v-if="effectiveAddress">
      当前会发到 <b>{{ effectiveAddress }}</b>{{ form.email ? '（你填的地址）' : '（来自学生档案）' }}
    </div>
    <div class="hint-note">
      这里填的邮箱只用来收通知，<b>不会改动学生档案</b>。要改档案里的邮箱，请走「基本信息 → 修改」申请。
    </div>

    <div class="actions">
      <el-button size="small" :disabled="!smtpEnabled" :loading="testing" @click="handleTest">
        发送测试
      </el-button>
      <el-button type="primary" size="small" :disabled="!smtpEnabled" :loading="saving" @click="handleSave">
        保存
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'
import { getEmailNotifySetting, saveEmailNotifySetting, testEmailNotify } from '@/api/notifyChannels'

const userStore = useUserStore()

const form = reactive({ email: '', enabled: false })
// 学生档案里**可用**的邮箱，留空时回退到它。域外账号没有档案，后端回空串
const defaultEmail = ref('')
const smtpEnabled = ref(false)
const saving = ref(false)
const testing = ref(false)
const busy = ref(false)

const emailPlaceholder = computed(() => {
  if (defaultEmail.value) return `留空则用学生档案里的 ${defaultEmail.value}`
  // 空串有两种来由，提示得分开说：域外账号压根没有档案；
  // 学生则是档案里那个邮箱格式坏了（真实库里有 2 个缺 @ 的），填了也发不出去
  return userStore.isExternal
    ? '请填一个邮箱（你的账号没有学生档案）'
    : '学生档案里的邮箱不可用，请自己填一个'
})

// 真正会被发到的地址：填了覆盖值就用它，否则用档案里的
const effectiveAddress = computed(() => form.email.trim() || defaultEmail.value)

async function load() {
  try {
    const data = await getEmailNotifySetting()
    form.email = data.email || ''
    form.enabled = !!data.enabled
    defaultEmail.value = data.default_email || ''
    smtpEnabled.value = !!data.smtp_enabled
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取邮件通知设置失败')
  }
}

async function handleSave() {
  saving.value = true
  busy.value = true
  try {
    const res = await saveEmailNotifySetting(form.email.trim(), form.enabled)
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
    // 先存再测：测试端点发的是**库里已存的地址**，不接受请求体传地址
    // （否则它就成了一个人人可用的发信接口）。和 Bark 那边同一套顺序
    await saveEmailNotifySetting(form.email.trim(), form.enabled)
    const res = await testEmailNotify()
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
/* 父组件 MyInfo.vue 的样式是 scoped 的，跨组件不生效，所以这里自带一份 */
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.section-sub {
  margin: 2px 0 12px;
  font-size: 12px;
  color: #909399;
}

.desc {
  font-size: 12px;
  color: #909399;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0 0 0;
}

.hint-note {
  font-size: 12px;
  color: #909399;
  margin-top: 8px;
  line-height: 1.6;
}
</style>
