<template>
  <div class="login-page">
    <!-- 校徽纹样：与登录后各页复用同一个全局类（位置、透明度、深浅模式一套规则） -->
    <img
      :src="SITE.logoUrl"
      class="app-emblem"
      alt=""
      aria-hidden="true"
      @error="$event.target.style.display = 'none'"
    />

    <div class="login-card">
      <div class="login-head">
        <img :src="SITE.logoUrl" class="login-logo" alt="校徽" />
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
            验证码已发送到 <b>{{ twoFactor.masked_email || '你的邮箱' }}</b>
            <!-- 邮箱长短不一，有效期单独起一行，别跟着地址一起被挤成半截 -->
            <span class="twofa-validity">10 分钟内有效</span>
          </template>
          <template v-else>
            请输入身份验证器 App 中显示的 6 位动态码。
          </template>
          <span class="twofa-sub">
            邮箱进不去或手机丢了，可以输入一次性恢复码。
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
          <!-- autocomplete="username webauthn" 是条件式 UI 的开关：
               登记过钥匙的人聚焦这里时，系统会把钥匙列进自动填充；
               没登记过的人看到的就是一个普通输入框，没有任何额外提示 -->
          <el-input
            v-model="form.student_no"
            size="large"
            placeholder="学号 / 账号"
            name="username"
            autocomplete="username webauthn"
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
             用哪种由后台 / 环境变量决定（captcha 字符图 / slider 拼图 / turnstile）；
             选了 Turnstile 就不退回另外两种，加载失败只提示重试 -->
        <el-form-item v-if="showCaptcha">
          <div v-if="captchaMode === 'turnstile' && !captchaReady" class="captcha-error">
            人机验证配置不完整，请联系管理员
          </div>

          <template v-else-if="captchaMode === 'turnstile'">
            <TurnstileWidget
              ref="turnstileRef"
              :site-key="turnstileSiteKey"
              @success="onTurnstileToken"
              @failed="onTurnstileFailed"
            />
            <div v-if="turnstileError" class="captcha-error">
              <span>{{ turnstileError }}</span>
              <el-button text type="primary" @click="retryTurnstile">重试</el-button>
            </div>
          </template>

          <SliderCaptcha
            v-else-if="captchaMode === 'slider'"
            ref="sliderRef"
            v-model="form.captcha"
          />

          <!-- 默认：字符图 + 语音（无障碍） -->
          <div v-else class="captcha-char">
            <div class="captcha-media">
              <img
                v-if="!audioMode && captchaSrc"
                :src="captchaSrc"
                class="captcha-img"
                alt="验证码图片：4 位数字"
                title="点击换一张"
                @click="refreshCaptcha"
              />
              <div v-else-if="audioMode" class="captcha-audio-note">
                语音验证已启用，请听写 4 位数字
              </div>
              <span v-else class="captcha-loading">验证码加载中…</span>
            </div>

            <div class="captcha-line">
              <el-input
                v-model="form.captcha"
                size="large"
                inputmode="numeric"
                maxlength="4"
                placeholder="输入图中的 4 位数字"
                aria-label="验证码，4 位数字"
                @keyup.enter="handleLogin"
              />
              <el-button text type="primary" @click="refreshCaptcha">换一张</el-button>
              <el-button
                v-if="captchaAudioEnabled"
                text
                type="primary"
                @click="toggleAudio"
              >
                {{ audioMode ? '改用图像' : '听语音' }}
              </el-button>
            </div>

            <div class="captcha-a11y-tip">
              看不清图片？点「听语音」用播放器听这 4 位数字。
            </div>

            <audio
              v-if="audioUrl"
              :src="audioUrl"
              class="captcha-audio"
              controls
              autoplay
            ></audio>
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
             不需要先填学号：钥匙里带着账号，点按钮后由系统列出本机的钥匙 -->
        <div v-if="passkeyReady" class="passkey-row">
          <el-divider>或</el-divider>
          <el-button
            size="large"
            class="login-btn passkey-btn"
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
import {
  getCaptchaAudio,
  getCaptchaImage,
  getCaptchaRequired,
  resendTwoFactorCode
} from '@/api/auth'
import SliderCaptcha from '@/components/SliderCaptcha.vue'
import { isPasskeySupported, isConditionalPasskeyAvailable } from '@/utils/passkey'
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

// 条件式 UI（聚焦账号框时自动填充钥匙）挂起的请求。
// **绝大多数同学没登记过钥匙**，所以这条路径全程静默：不弹窗、不提示、不占位，
// 没钥匙的人看到的登录页和以前一模一样。白底按钮才是人人可用的入口。
let conditionalAbort = null
let conditionalStopped = false

const showCaptcha = ref(false)
const sliderRef = ref(null)
// 'captcha'（字符图 + 语音，默认）/ 'slider'（拖动拼图）/ 'turnstile'
// 由后台「运维」或 CAPTCHA_MODE 决定；选了 turnstile 就不会退回另外两种
const captchaMode = ref('captcha')
// 后端说这一种方式提不提供语音（只有字符图有）
const captchaAudioEnabled = ref(false)
// Turnstile 的 Key 是否齐全。不齐时不渲染控件，直接提示联系管理员
const captchaReady = ref(true)
const turnstileSiteKey = ref('')
const turnstileToken = ref('')
const turnstileRef = ref(null)
const turnstileError = ref('')

// 字符图 / 语音
const captchaSrc = ref('')
const audioUrl = ref('')
const audioMode = ref(false)

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

function releaseImage() {
  if (captchaSrc.value) URL.revokeObjectURL(captchaSrc.value)
  captchaSrc.value = ''
}

function releaseAudio() {
  if (audioUrl.value) URL.revokeObjectURL(audioUrl.value)
  audioUrl.value = ''
}

/** 换一张字符图（也会从语音切回图像） */
async function refreshCaptcha() {
  if (captchaMode.value !== 'captcha') return
  audioMode.value = false
  releaseAudio()
  form.captcha = ''
  try {
    const url = await getCaptchaImage()
    releaseImage()
    captchaSrc.value = url
  } catch (e) {
    // 加载失败不影响主流程：用户可以再点「换一张」
    console.warn('验证码加载失败', e)
    captchaSrc.value = ''
  }
}

/** 听语音：会换一组新数字，所以把图藏起来，以语音这组为准 */
async function playAudio() {
  try {
    const url = await getCaptchaAudio()
    releaseAudio()
    audioUrl.value = url
    audioMode.value = true
    form.captcha = ''
  } catch (e) {
    ElMessage.error('语音验证码加载失败，请稍后重试')
  }
}

function toggleAudio() {
  if (audioMode.value) refreshCaptcha()
  else playAudio()
}

function onTurnstileToken(token) {
  turnstileToken.value = token || ''
  if (token) turnstileError.value = ''
}

/** Turnstile 加载/渲染失败：只报错 + 让用户重试，**不切换到别的方式** */
function onTurnstileFailed(message) {
  turnstileToken.value = ''
  turnstileError.value = message || '人机验证加载失败，请重试'
}

function retryTurnstile() {
  turnstileError.value = ''
  turnstileRef.value?.retry()
}

// 进入页面时先问一下后端：这个 IP 现在要不要人机验证、用哪一种
// （之前如果输错过，10 分钟内再进来就得显示验证码框）
onMounted(async () => {
  passkeyReady.value = isPasskeySupported()
  try {
    const res = await getCaptchaRequired()
    // mode / site_key 即使这次不用也得记下来：
    // 等会儿万一输错了要显示验证码框，得知道渲染哪一种
    captchaMode.value = ['captcha', 'slider', 'turnstile'].includes(res.mode)
      ? res.mode
      : 'captcha'
    captchaAudioEnabled.value = !!res.audio
    captchaReady.value = res.ready !== false
    turnstileSiteKey.value = res.site_key || ''
    // 已被封禁就不用显示表单和验证码了 —— 反正提交上去也是 403
    if (res.banned) {
      banMessage.value = res.ban_message || '本机 IP 已被封禁，请联系管理员'
      return
    }
    if (res.required) {
      showCaptcha.value = true
      // 字符图要主动拉一张；拼图和 Turnstile 的组件挂载时自己加载
      if (captchaMode.value === 'captcha') await refreshCaptcha()
    }
  } catch (e) {
    // 问不到就算了，默认不显示，输错一次后端会提示要验证码
  }

  if (!banMessage.value) startConditionalPasskey()
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
      // 字符图交文本、拼图交拖动位置（原图坐标）；空的就原样交上去，
      // 后端按当前模式给出「请输入验证码 / 请拖动滑块」的提示
      captcha: showCaptcha.value && !useTurnstile ? String(form.captcha ?? '') : undefined,
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

    // 登录失败后，显示人机验证并换一份新的
    // （后端已经开始计数了，下次登录必须带验证码；答案都是一次性的）
    if (!showCaptcha.value) {
      showCaptcha.value = true
      if (captchaMode.value === 'captcha') await refreshCaptcha()
    } else if (captchaMode.value === 'turnstile') {
      turnstileRef.value?.reset()
      turnstileToken.value = ''
      turnstileError.value = ''
    } else if (captchaMode.value === 'slider') {
      sliderRef.value?.reset()
      form.captcha = ''
    } else if (audioMode.value) {
      // 刚才听的那组数字也作废了，重新念一组
      await playAudio()
    } else {
      await refreshCaptcha()
    }
  } finally {
    loading.value = false
  }
}

/**
 * 用通行密钥登录
 *
 * 不校验验证码：通行密钥本身就是第二因素，后端也只做了封禁检查。
 * 也不需要学号：登记时钥匙里存了账号，浏览器会列出本机属于本站的钥匙，
 * 用户挑一把、过指纹 / 面容 / PIN 即可，服务器按凭据反查持有人。
 */
async function handlePasskeyLogin() {
  // 自动填充和按钮不能同时挂起：两边都会在服务端会话里存挑战，后发起的会覆盖先前的
  stopConditionalPasskey()
  passkeyLoading.value = true
  try {
    await userStore.loginWithPasskey({ remember: form.remember })
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || '/dashboard')
  } catch (e) {
    // 用户点了「取消」、等待超时，或本机没有可用的钥匙：都是 NotAllowedError
    if (e?.name === 'NotAllowedError') {
      ElMessage.info('未选择通行密钥，或本机没有可用的钥匙')
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

/**
 * 让钥匙出现在账号框的自动填充里（条件式 UI）
 *
 * 不 popup：页面加载后只是挂起一次 get(mediation:'conditional')，
 * 用户聚焦账号框、从自动填充里选了钥匙，系统才弹指纹 / 面容。
 * 没登记过钥匙的人不会看到任何变化；任何失败都静默，绝不打扰正要输密码的人。
 */
async function startConditionalPasskey() {
  if (!(await isConditionalPasskeyAvailable()) || conditionalStopped) return

  const controller = new AbortController()
  conditionalAbort = controller
  try {
    await userStore.loginWithPasskey({
      remember: form.remember,
      mediation: 'conditional',
      signal: controller.signal
    })
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || '/dashboard')
  } catch (e) {
    // 一律不提示：没选、没钥匙、挑战过期、网络抖动，甚至我们主动中止（AbortError）。
    // 这里多弹一个字，全班每个人都会在打开登录页时看到它
  } finally {
    if (conditionalAbort === controller) conditionalAbort = null
  }
}

/** 中止挂起的自动填充。按钮、二次验证、离开页面时都要调用 */
function stopConditionalPasskey() {
  conditionalStopped = true
  if (conditionalAbort) {
    conditionalAbort.abort()
    conditionalAbort = null
  }
}

// ---------- 二次验证 ----------

function enterTwoFactor(data) {
  // 表单要整个换成验证码输入框，挂起的自动填充已经无处可显示；
  // 不停掉的话，用户在验证码那一步选钥匙会绕过二次验证
  stopConditionalPasskey()
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

onBeforeUnmount(() => {
  stopResendCooldown()
  stopConditionalPasskey()
  // blob URL 不会自己回收，离开页面时手动放掉
  releaseImage()
  releaseAudio()
})

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
  /* 背景交给 #app 的全局蓝紫渐变 */
  background: transparent;
  padding: 20px;
  box-sizing: border-box;
}

.login-card {
  width: 380px;
  /* 手机上留出左右边距，卡片不会顶到屏幕边 */
  max-width: 92%;
  padding: 38px 34px 26px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 24px;
  box-shadow: var(--app-shadow-hover), var(--app-card-inset);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  /* 校徽纹样是 fixed + z-index:0 的底层装饰，卡片抬到它上面
     （登录页不在 .layout-main 里，拿不到那条统一的 z-index 规则） */
  position: relative;
  z-index: 1;
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
  /* 校徽本身多为深色线条，垫一层白底，深色模式下也看得清 */
  background: #fff;
  padding: 4px;
  box-sizing: border-box;
  box-shadow: 0 8px 20px rgba(88, 84, 214, 0.16);
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

/* ---------- 字符图 + 语音验证码 ---------- */
.captcha-char {
  width: 100%;
}

.captcha-media {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60px;
  margin-bottom: 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
}

.captcha-img {
  height: 60px;
  width: auto;
  max-width: 100%;
  border-radius: 5px;
  cursor: pointer;
}

.captcha-loading,
.captcha-audio-note {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.captcha-audio-note {
  padding: 18px 12px;
  text-align: center;
}

.captcha-line {
  display: flex;
  align-items: center;
  gap: 4px;
}

.captcha-a11y-tip {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.captcha-audio {
  width: 100%;
  height: 36px;
  margin-top: 6px;
}

.captcha-error {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-color-danger);
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
  /* 两种方式都整段居中，下面的恢复码提示也跟着对齐 */
  text-align: center;
}

.twofa-validity {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.twofa-sub {
  display: block;
  margin-top: 6px;
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
}

/* 和「登 录」同宽同高，只是白底次要按钮；字距不跟主按钮走，太长会挤出卡片 */
.passkey-btn {
  letter-spacing: 1px;
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
