<template>
  <div class="channel-block">
    <el-collapse v-model="active">
      <el-collapse-item name="two-factor">
        <template #title>
          <span class="collapse-title">二次验证</span>
          <span class="collapse-badge" :class="{ on: status.enabled }">
            {{ status.enabled ? '已开启' : '未开启' }}
          </span>
        </template>

        <p class="desc">
          开启后，密码登录时还要再输一个验证码。默认关闭；忘记带手机时可以用一次性恢复码，
          通行密钥登录不受影响。
        </p>

        <!-- ==================== 已开启 ==================== -->
        <template v-if="status.enabled">
          <div class="status-row">
            <el-tag type="success" size="small">
              当前方式：{{ methodLabel }}
            </el-tag>
            <template v-if="status.method === 'email'">
              <span class="desc">验证码发到 {{ status.email || '（没有可用邮箱）' }}</span>
            </template>
            <span class="desc">剩余恢复码 {{ status.recovery_codes_left }} 个</span>
          </div>

          <div class="actions">
            <el-button size="small" :loading="busy" @click="handleRegenerate">
              重新生成恢复码
            </el-button>
            <el-button size="small" type="danger" plain :loading="busy" @click="handleDisable">
              关闭二次验证
            </el-button>
          </div>
          <p v-if="status.recovery_codes_left === 0" class="warn">
            恢复码已经用完，建议重新生成一组并保存好。
          </p>
        </template>

        <!-- ==================== 未开启 ==================== -->
        <template v-else>
          <!-- 方式一：电子邮件验证码 -->
          <div class="setup-block">
            <div class="setup-head">
              <span class="setup-title">电子邮件验证码</span>
              <el-tag v-if="!status.smtp_enabled" type="info" size="small">不可用</el-tag>
            </div>
            <p class="desc">
              和「通知设置」用同一个邮箱：<b>{{ status.email || '还没有可用邮箱' }}</b>。
              不需要另外填写地址，改通知邮箱就等于改收件地址。
            </p>
            <el-alert
              v-if="!status.smtp_enabled"
              type="info"
              :closable="false"
              show-icon
              title="管理员还没配置发信服务，暂时不能用这种方式"
            />
            <el-alert
              v-else-if="!status.email"
              type="warning"
              :closable="false"
              show-icon
              title="没有可用的邮箱"
              description="请先在「通知设置」里填一个邮箱，或请管理员在档案里补上。"
            />
            <template v-else>
              <div class="actions">
                <el-button
                  size="small"
                  type="primary"
                  :loading="emailSending"
                  :disabled="emailSent"
                  @click="handleSendEmail"
                >
                  {{ emailSent ? '验证码已发送' : '发送验证码' }}
                </el-button>
                <span v-if="emailSent" class="desc">
                  已发到 {{ emailMasked }}，10 分钟内有效
                </span>
              </div>
              <div v-if="emailSent" class="code-row">
                <el-input
                  v-model="emailCode"
                  size="small"
                  maxlength="6"
                  placeholder="6 位验证码"
                  @keyup.enter="handleConfirmEmail"
                />
                <el-button
                  size="small"
                  type="primary"
                  :loading="busy"
                  @click="handleConfirmEmail"
                >
                  确认开启
                </el-button>
              </div>
            </template>
          </div>

          <!-- 方式二：身份验证器 -->
          <div class="setup-block">
            <div class="setup-head">
              <span class="setup-title">身份验证器（TOTP）</span>
            </div>
            <p class="desc">
              用 Google Authenticator、微软 Authenticator 等 App 生成动态码，不依赖邮箱。
              开启需要先输一次登录密码。
            </p>

            <template v-if="!totp">
              <div class="actions">
                <el-button size="small" :loading="busy" @click="handleBeginTotp">
                  开始设置
                </el-button>
              </div>
            </template>

            <template v-else>
              <p class="desc">
                在 App 里选择「手动输入密钥」，填入下面这串，账号名填你的学号：
              </p>
              <div class="secret-box">{{ totp.secret }}</div>
              <p class="desc">
                也可以在手机上点
                <el-link type="primary" :underline="false" :href="totp.otpauth_uri">
                  这个链接
                </el-link>
                直接唤起验证器。
              </p>
              <div class="code-row">
                <el-input
                  v-model="totpCode"
                  size="small"
                  maxlength="6"
                  placeholder="App 里显示的 6 位码"
                  @keyup.enter="handleConfirmTotp"
                />
                <el-button
                  size="small"
                  type="primary"
                  :loading="busy"
                  @click="handleConfirmTotp"
                >
                  确认开启
                </el-button>
                <el-button size="small" link @click="resetTotp">取消</el-button>
              </div>
            </template>
          </div>
        </template>
      </el-collapse-item>
    </el-collapse>

    <!-- 恢复码只出现这一次，**关掉弹窗就再也看不到**，所以按钮写「我已保存」 -->
    <el-dialog
      v-model="codesVisible"
      title="一次性恢复码"
      width="520px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
    >
      <el-alert type="warning" :closable="false" show-icon>
        <template #title>这些码只显示这一次</template>
        每一行只能用一次。请现在抄下来或存到密码管理器；丢了只能让管理员清除二次验证。
      </el-alert>
      <div class="code-grid">
        <code v-for="item in recoveryCodes" :key="item">{{ item }}</code>
      </div>
      <template #footer>
        <el-button @click="copyCodes">复制全部</el-button>
        <el-button type="primary" @click="codesVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  beginTotpSetup,
  confirmTotpSetup,
  disableTwoFactor,
  getTwoFactorStatus,
  regenerateRecoveryCodes,
  sendTwoFactorEmailCode,
  confirmTwoFactorEmail
} from '@/api/auth'

const active = ref([])
const status = ref({
  enabled: false,
  method: '',
  email: '',
  masked_email: '',
  smtp_enabled: false,
  recovery_codes_left: 0
})
const busy = ref(false)

// 邮箱方式
const emailSending = ref(false)
const emailSent = ref(false)
const emailCode = ref('')
const emailMasked = ref('')

// 身份验证器方式
const totp = ref(null)   // { secret, otpauth_uri }
const totpCode = ref('')

// 恢复码弹窗
const codesVisible = ref(false)
const recoveryCodes = ref([])

const methodLabel = computed(() =>
  status.value.method === 'email' ? '电子邮件验证码' : '身份验证器'
)

async function load() {
  try {
    status.value = await getTwoFactorStatus()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取二次验证状态失败')
  }
}

/** 统一弹密码框：开启 / 关闭都是会改变以后登录方式的敏感操作 */
async function askPassword(title, message) {
  try {
    const { value } = await ElMessageBox.prompt(message, title, {
      inputType: 'password',
      inputPlaceholder: '请输入登录密码',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      // 空密码不必往后端送
      inputValidator: (v) => (v ? true : '请输入密码')
    })
    return value
  } catch {
    return null // 取消
  }
}

function showCodes(codes) {
  recoveryCodes.value = codes || []
  codesVisible.value = true
}

async function handleSendEmail() {
  const password = await askPassword('开启邮箱验证码', '发送前请确认一次登录密码')
  if (!password) return
  emailSending.value = true
  try {
    const res = await sendTwoFactorEmailCode({ password })
    emailSent.value = true
    emailMasked.value = res.masked_email || status.value.masked_email
    emailCode.value = ''
    ElMessage.success(res.message || '验证码已发送')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发送失败')
  } finally {
    emailSending.value = false
  }
}

async function handleConfirmEmail() {
  if (!emailCode.value.trim()) return ElMessage.warning('请输入验证码')
  busy.value = true
  try {
    const res = await confirmTwoFactorEmail({ code: emailCode.value.trim() })
    ElMessage.success(res.message || '已开启')
    showCodes(res.recovery_codes)
    emailSent.value = false
    emailCode.value = ''
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '验证失败')
    emailCode.value = ''
  } finally {
    busy.value = false
  }
}

async function handleBeginTotp() {
  const password = await askPassword('开启身份验证器', '开始设置前请确认一次登录密码')
  if (!password) return
  busy.value = true
  try {
    totp.value = await beginTotpSetup({ password })
    totpCode.value = ''
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '设置失败')
  } finally {
    busy.value = false
  }
}

async function handleConfirmTotp() {
  if (!totpCode.value.trim()) return ElMessage.warning('请输入 App 里的验证码')
  busy.value = true
  try {
    const res = await confirmTotpSetup({ code: totpCode.value.trim() })
    ElMessage.success(res.message || '已开启')
    showCodes(res.recovery_codes)
    resetTotp()
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '验证失败')
    totpCode.value = ''
  } finally {
    busy.value = false
  }
}

function resetTotp() {
  totp.value = null
  totpCode.value = ''
}

async function handleDisable() {
  const password = await askPassword(
    '关闭二次验证',
    '关闭后登录只需要密码。确定关闭吗？'
  )
  if (!password) return
  busy.value = true
  try {
    const res = await disableTwoFactor({ password })
    ElMessage.success(res.message || '已关闭')
    emailSent.value = false
    resetTotp()
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '关闭失败')
  } finally {
    busy.value = false
  }
}

async function handleRegenerate() {
  const password = await askPassword(
    '重新生成恢复码',
    '旧的恢复码会全部作废。请输入登录密码确认。'
  )
  if (!password) return
  busy.value = true
  try {
    const res = await regenerateRecoveryCodes({ password })
    ElMessage.success(res.message || '已重新生成')
    showCodes(res.recovery_codes)
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '生成失败')
  } finally {
    busy.value = false
  }
}

async function copyCodes() {
  const text = recoveryCodes.value.join('\n')
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制，记得存好')
  } catch {
    ElMessage.warning('浏览器不允许自动复制，请手动抄下来')
  }
}

onMounted(load)
</script>

<style scoped>
/* 父组件 MyInfo.vue 的样式是 scoped 的，跨组件不生效，所以这里自带一份 */
.collapse-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.collapse-badge {
  margin-left: 8px;
  padding: 1px 8px;
  border-radius: 10px;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 400;
}

.collapse-badge.on {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
}

.desc {
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.warn {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--el-color-warning);
}

.status-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.setup-block {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--el-border-color-light);
}

.setup-block:first-of-type {
  border-top: none;
  padding-top: 0;
}

.setup-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.setup-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0 0;
  flex-wrap: wrap;
}

.code-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.code-row :deep(.el-input) {
  width: 180px;
}

.secret-box {
  margin: 8px 0;
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  font-family: 'Courier New', monospace;
  font-size: 16px;
  letter-spacing: 2px;
  word-break: break-all;
  user-select: all;
}

.code-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  margin-top: 16px;
}

.code-grid code {
  padding: 6px 10px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-family: 'Courier New', monospace;
  font-size: 14px;
  letter-spacing: 1px;
  user-select: all;
}
</style>
