<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-head">
        <img src="/logo.png" class="login-logo" alt="校徽" />
        <h1 class="login-title">{{ SITE.name }}</h1>
        <p class="login-sub">{{ SITE.subtitle }}</p>
      </div>

      <!-- 本机 IP 被封禁：直接把表单换成提示，不让用户白填一遍再吃 403 -->
      <div v-if="banMessage" class="login-banned">
        <el-alert type="error" :closable="false" show-icon>
          <template #title>{{ banMessage }}</template>
          <div class="login-banned-tip">
            若认为这是误封，请联系管理员解封。
          </div>
        </el-alert>
      </div>

      <!-- 第二步：密码已通过，等第二因素。这里还没有登录态，
           成功后才由 store 写入用户信息并跳转 -->
      <div v-else-if="twoFactor" class="twofa-block">
        <p class="twofa-tip">
          <template v-if="twoFactor.method === 'email'">
            验证码已发送到 <b>{{ twoFactor.masked_email || '你的邮箱' }}</b>，10 分钟内有效。
          </template>
          <template v-else>
            请输入身份验证器 App 中显示的 6 位动态码。
          </template>
          <span class="twofa-sub">
            邮箱进不去或手机丢了，可以输入一次性恢复码（XXXX-XXXX）。
          </span>
        </p>
        <el-input
          v-model="twoFactorCode"
          size="large"
          maxlength="20"
          placeholder="6 位验证码，或恢复码"
          :prefix-icon="Key"
          clearable
          @keyup.enter="handleTwoFactor"
        />
        <el-button
          type="primary"
          size="large"
          class="login-btn twofa-btn"
          :loading="verifying"
          @click="handleTwoFactor"
        >
          验 证
        </el-button>
        <div class="twofa-actions">
          <el-button
            v-if="twoFactor.method === 'email'"
            link
            type="primary"
            :disabled="resendLeft > 0 || resending"
            :loading="resending"
            @click="handleResend"
          >
            {{ resendLeft > 0 ? `重新发送（${resendLeft} 秒）` : '重新发送验证码' }}
          </el-button>
          <el-button link type="info" @click="cancelTwoFactor">返回重新登录</el-button>
        </div>
        <p v-if="twoFactor.message" class="twofa-warn">{{ twoFactor.message }}</p>
      </div>

      <el-form v-else :model="form" @submit.prevent="handleLogin">
        <el-form-item>
          <el-input
            v-model="form.student_no"
            size="large"
            placeholder="学号 / 账号"
            :prefix-icon="User"
            clearable
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            size="large"
            placeholder="密码（默认身份证号后6位）"
            :prefix-icon="Lock"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>

        <!-- 人机验证：登录失败一次后才显示，默认隐藏。
             配了 Turnstile 就用它，加载不出来自动退回下面的算术题 -->
        <el-form-item v-if="showCaptcha">
          <TurnstileWidget
            v-if="captchaMode === 'turnstile'"
            ref="turnstileRef"
            :site-key="turnstileSiteKey"
            @success="onTurnstileToken"
            @unavailable="fallbackToMath"
          />
          <div v-else class="captcha-row">
            <el-input
              v-model="form.captcha"
              size="large"
              placeholder="请输入计算结果"
              :prefix-icon="Key"
              @keyup.enter="handleLogin"
              style="flex: 1;"
            />
            <!-- 点图片换一张 -->
            <img
              :src="captchaSrc"
              class="captcha-img"
              alt="验证码"
              title="点击刷新"
              @click="refreshCaptcha"
            />
          </div>
        </el-form-item>

        <div class="login-options">
          <el-checkbox v-model="form.remember">保持登录（7天）</el-checkbox>
        </div>

        <el-button
          type="primary"
          size="large"
          class="login-btn"
          :loading="loading"
          @click="handleLogin"
        >
          登 录
        </el-button>

        <!-- 通行密钥登录：浏览器不支持或不是 HTTPS 时整行不出现。
             需要先填学号 —— 服务器要靠它找出这个账号名下有哪些钥匙 -->
        <div v-if="passkeyReady" class="passkey-row">
          <el-divider>或</el-divider>
          <el-button
            link
            type="primary"
            :loading="passkeyLoading"
            @click="handlePasskeyLogin"
          >
            使用通行密钥登录
          </el-button>
        </div>
      </el-form>

      <div class="login-foot">
        <el-link type="info" :underline="false" @click="goHome">先随便看看首页 →</el-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Key } from '@element-plus/icons-vue'
import { useUserStore } from '@/store/user'
import TurnstileWidget from '@/components/TurnstileWidget.vue'
import { getCaptcha, getCaptchaRequired, resendTwoFactorCode } from '@/api/auth'
import { isPasskeySupported } from '@/utils/passkey'
import { SITE } from '@/utils/site'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const loading = ref(false)
const form = reactive({
  student_no: '',
  password: '',
  remember: true,   // 默认勾选保持登录
  captcha: ''
})

// 验证码相关
// 通行密钥：只有浏览器支持且是 HTTPS（localhost 除外）时才露出那个按钮。
// 服务端渲染 / 老浏览器里 isPasskeySupported() 返回 false，页面和以前一样
const passkeyReady = ref(false)
const passkeyLoading = ref(false)

const showCaptcha = ref(false)
const captchaSrc = ref('')
// 'math' = 自带的算术题；'turnstile' = Cloudflare 人机验证（由后端 .env 决定）
const captchaMode = ref('math')
const turnstileSiteKey = ref('')
const turnstileToken = ref('')
const turnstileRef = ref(null)

// 非空表示本机 IP 正被封禁：整个表单换成这段提示
const banMessage = ref('')

// 二次验证第二步：null = 还在密码阶段；有值 = 密码已通过，等验证码
// 值形如 { method, masked_email, email_sent, message }
const twoFactor = ref(null)
const twoFactorCode = ref('')
const verifying = ref(false)
const resending = ref(false)
const resendLeft = ref(0)
let resendTimer = null

async function refreshCaptcha() {
  try {
    captchaSrc.value = await getCaptcha()
  } catch (e) {
    // 验证码加载失败不影响主流程，提示一下
    console.warn('验证码加载失败', e)
  }
}

/** Turnstile 控件起不来（内地网络下会），退回算术题
 *
 * 单向降级：同一个页面里不再回头试 Turnstile，免得两种界面来回跳
 * （每次 mount 失败都会重新走一遍脚本加载 + 8 秒超时）。
 */
function fallbackToMath() {
  if (captchaMode.value === 'math') return
  captchaMode.value = 'math'
  turnstileToken.value = ''
  refreshCaptcha()
}

function onTurnstileToken(token) {
  turnstileToken.value = token || ''
}

// 进入页面时先问一下后端：这个 IP 现在要不要人机验证、用哪一种
// （之前如果输错过，10 分钟内再进来就得显示验证码框）
onMounted(async () => {
  passkeyReady.value = isPasskeySupported()
  try {
    const res = await getCaptchaRequired()
    // mode / site_key 即使这次不用也得记下来：
    // 等会儿万一输错了要显示验证码框，得知道该加载 Turnstile 还是拉算术题
    captchaMode.value = res.mode === 'turnstile' ? 'turnstile' : 'math'
    turnstileSiteKey.value = res.site_key || ''
    // 已被封禁就不用显示表单和验证码了 —— 反正提交上去也是 403
    if (res.banned) {
      banMessage.value = res.ban_message || '本机 IP 已被封禁，请联系管理员'
      return
    }
    if (res.required) {
      showCaptcha.value = true
      // Turnstile 的控件由组件自己挂载时加载；算术题这里就得去拉 SVG
      if (captchaMode.value === 'math') await refreshCaptcha()
    }
  } catch (e) {
    // 问不到就算了，默认不显示，输错一次后端会提示要验证码
  }
})

async function handleLogin() {
  if (!form.student_no.trim()) return ElMessage.warning('请输入学号或账号')
  if (!form.password) return ElMessage.warning('请输入密码')

  loading.value = true
  // 两套人机验证只交一个字段，后端靠「哪个有值」判断走的哪条路
  const useTurnstile = showCaptcha.value && captchaMode.value === 'turnstile'
  try {
    const res = await userStore.login({
      student_no: form.student_no.trim(),
      password: form.password,
      remember: form.remember,
      captcha: showCaptcha.value && !useTurnstile ? form.captcha : undefined,
      turnstile_token: useTurnstile ? turnstileToken.value : undefined
    })
    // 密码对了但还要第二因素：不跳转，切到验证码输入框
    if (res?.two_factor_required) {
      enterTwoFactor(res)
      return
    }
    ElMessage.success('登录成功')
    // 登录前想去的页面，登录后直接过去
    router.replace(route.query.redirect || '/dashboard')
  } catch (e) {
    const status = e?.response?.status
    const msg = e?.response?.data?.detail || '登录失败，请稍后重试'
    ElMessage.error(msg)

    // 403 = 本机 IP 已被封禁。直接换成封禁提示并**就此打住**：
    // 再弹一张验证码框会让人以为「再试一次就能进」，而这张验证码根本没机会用上
    if (status === 403) {
      banMessage.value = msg
      return
    }

    // 登录失败后，显示人机验证并换一张
    // （后端已经开始计数了，下次登录必须带验证码）
    if (!showCaptcha.value) {
      showCaptcha.value = true
    }
    if (captchaMode.value === 'turnstile') {
      // token 是一次性的，刚才那个已经被后端用掉了，必须换一个新的
      turnstileRef.value?.reset()
      turnstileToken.value = ''
    } else {
      await refreshCaptcha()
      form.captcha = ''
    }
  } finally {
    loading.value = false
  }
}

/**
 * 用通行密钥登录
 *
 * 不校验验证码：通行密钥本身就是第二因素，后端也只做了封禁检查。
 * 学号必须自己填 —— 浏览器里的钥匙是按 RP ID 存的，服务器得先知道
 * 该拿谁的钥匙名单去点名。
 */
async function handlePasskeyLogin() {
  if (!form.student_no.trim()) return ElMessage.warning('请先填写学号或账号')

  passkeyLoading.value = true
  try {
    await userStore.loginWithPasskey({
      student_no: form.student_no.trim(),
      remember: form.remember
    })
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || '/dashboard')
  } catch (e) {
    // 用户点了「取消」或者等超时：浏览器抛 NotAllowedError，不是系统故障
    if (e?.name === 'NotAllowedError') {
      ElMessage.info('已取消通行密钥验证')
      return
    }
    const status = e?.response?.status
    const msg = e?.response?.data?.detail || '通行密钥登录失败，请重试'
    if (status === 403) {
      banMessage.value = msg
      return
    }
    ElMessage.error(msg)
  } finally {
    passkeyLoading.value = false
  }
}

// ---------- 二次验证 ----------

function enterTwoFactor(data) {
  twoFactor.value = data
  twoFactorCode.value = ''
  // 密码已经用完，不留在内存里
  form.password = ''
  if (data.message) ElMessage.warning(data.message)
  if (data.method === 'email') startResendCooldown()
}

function startResendCooldown() {
  stopResendCooldown()
  resendLeft.value = 60
  resendTimer = setInterval(() => {
    resendLeft.value -= 1
    if (resendLeft.value <= 0) stopResendCooldown()
  }, 1000)
}

function stopResendCooldown() {
  if (resendTimer) {
    clearInterval(resendTimer)
    resendTimer = null
  }
  resendLeft.value = 0
}

async function handleTwoFactor() {
  const code = twoFactorCode.value.trim()
  if (!code) return ElMessage.warning('请输入验证码或恢复码')

  verifying.value = true
  try {
    await userStore.verifyTwoFactor(code)
    stopResendCooldown()
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || '/dashboard')
  } catch (e) {
    const msg = e?.response?.data?.detail || '验证失败，请重试'
    ElMessage.error(msg)
    // 挑战过期 / 次数用尽 / 设置被管理员改了：都只能从头输密码
    if (msg.includes('重新登录') || msg.includes('重新输入密码')) {
      resetTwoFactor()
    } else {
      twoFactorCode.value = ''
    }
  } finally {
    verifying.value = false
  }
}

async function handleResend() {
  resending.value = true
  try {
    const res = await resendTwoFactorCode()
    ElMessage.success(res.message || '已重新发送')
    twoFactorCode.value = ''
    startResendCooldown()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '重新发送失败')
  } finally {
    resending.value = false
  }
}

function resetTwoFactor() {
  twoFactor.value = null
  twoFactorCode.value = ''
  stopResendCooldown()
}

async function cancelTwoFactor() {
  // 把服务端那条待验证的挑战清掉，避免留一条没人用的记录
  await userStore.logout()
  resetTwoFactor()
}

onBeforeUnmount(stopResendCooldown)

function goHome() {
  router.push('/dashboard')
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #2c3e50 55%, #3a5169 100%);
}

.login-card {
  width: 380px;
  /* 手机上留出左右边距，卡片不会顶到屏幕边 */
  max-width: 92%;
  padding: 36px 34px 24px;
  background: var(--el-bg-color);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 21, 41, 0.3);
}

/* 手机上屏幕矮，卡片内边距和校徽都收一点 */
@media (max-width: 768px) {
  .login-card {
    padding: 28px 20px 20px;
  }

  .login-logo {
    width: 52px;
    height: 52px;
  }

  .login-title {
    font-size: 18px;
  }
}

.login-head {
  text-align: center;
  margin-bottom: 24px;
}

.login-logo {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  object-fit: cover;
}

.login-title {
  margin: 12px 0 4px;
  font-size: 20px;
  /* 卡片底色是 var(--el-bg-color)（会跟主题），标题就不能再写死近黑色 */
  color: var(--el-text-color-primary);
}

.login-sub {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.login-banned-tip {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.captcha-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.captcha-img {
  width: 120px;
  height: 40px;
  border-radius: 4px;
  border: 1px solid var(--el-border-color);
  cursor: pointer;
  flex-shrink: 0;
  background: var(--el-fill-color-light);
}

.login-options {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 14px;
  font-size: 14px;
}

.login-btn {
  width: 100%;
  letter-spacing: 4px;
}

.twofa-block {
  margin-top: 4px;
}

.twofa-tip {
  margin: 0 0 14px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

.twofa-sub {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.twofa-btn {
  margin-top: 14px;
}

.twofa-actions {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
}

.twofa-warn {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-color-warning);
}

.passkey-row {
  margin-top: 6px;
  text-align: center;
}

/* 「或」两侧留得比默认窄一点，别把登录卡片撑长 */
.passkey-row :deep(.el-divider) {
  margin: 14px 0 10px;
}

.login-foot {
  margin-top: 16px;
  text-align: center;
}
</style>
