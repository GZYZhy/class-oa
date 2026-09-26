<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-head">
        <img src="/logo.png" class="login-logo" alt="校徽" />
        <h1 class="login-title">统26-1班信息管理系统</h1>
        <p class="login-sub">北方工业大学理学院统计学系</p>
      </div>

      <el-form :model="form" @submit.prevent="handleLogin">
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
      </el-form>

      <div class="login-foot">
        <el-link type="info" :underline="false" @click="goHome">先随便看看首页 →</el-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Key } from '@element-plus/icons-vue'
import { useUserStore } from '@/store/user'
import TurnstileWidget from '@/components/TurnstileWidget.vue'
import { getCaptcha, getCaptchaRequired } from '@/api/auth'

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
const showCaptcha = ref(false)
const captchaSrc = ref('')
// 'math' = 自带的算术题；'turnstile' = Cloudflare 人机验证（由后端 .env 决定）
const captchaMode = ref('math')
const turnstileSiteKey = ref('')
const turnstileToken = ref('')
const turnstileRef = ref(null)

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
  try {
    const res = await getCaptchaRequired()
    // mode / site_key 即使这次不用也得记下来：
    // 等会儿万一输错了要显示验证码框，得知道该加载 Turnstile 还是拉算术题
    captchaMode.value = res.mode === 'turnstile' ? 'turnstile' : 'math'
    turnstileSiteKey.value = res.site_key || ''
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
    await userStore.login({
      student_no: form.student_no.trim(),
      password: form.password,
      remember: form.remember,
      captcha: showCaptcha.value && !useTurnstile ? form.captcha : undefined,
      turnstile_token: useTurnstile ? turnstileToken.value : undefined
    })
    ElMessage.success('登录成功')
    // 登录前想去的页面，登录后直接过去
    router.replace(route.query.redirect || '/dashboard')
  } catch (e) {
    const msg = e?.response?.data?.detail || '登录失败，请稍后重试'
    ElMessage.error(msg)

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
  background: #fff;
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
  color: #1f2d3d;
}

.login-sub {
  margin: 0;
  font-size: 12px;
  color: #909399;
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
  border: 1px solid #dcdfe6;
  cursor: pointer;
  flex-shrink: 0;
  background: #f5f7fa;
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

.login-foot {
  margin-top: 16px;
  text-align: center;
}
</style>
