<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-head">
        <img src="/logo.png" class="login-logo" alt="校徽" />
        <h1 class="login-title">示例班信息管理系统</h1>
        <p class="login-sub">示例大学示例学院示例专业系</p>
      </div>

      <el-form :model="form" @submit.prevent="handleLogin">
        <el-form-item>
          <el-input
            v-model="form.student_no"
            size="large"
            placeholder="学号"
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

        <!-- 验证码：登录失败一次后才显示，默认隐藏 -->
        <el-form-item v-if="showCaptcha">
          <div class="captcha-row">
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

async function refreshCaptcha() {
  try {
    captchaSrc.value = await getCaptcha()
  } catch (e) {
    // 验证码加载失败不影响主流程，提示一下
    console.warn('验证码加载失败', e)
  }
}

// 进入页面时先问一下后端：这个 IP 现在要不要填验证码
// （之前如果输错过，10 分钟内再进来就得显示验证码框）
onMounted(async () => {
  try {
    const res = await getCaptchaRequired()
    if (res.required) {
      showCaptcha.value = true
      await refreshCaptcha()
    }
  } catch (e) {
    // 问不到就算了，默认不显示，输错一次后端会提示要验证码
  }
})

async function handleLogin() {
  if (!form.student_no.trim()) return ElMessage.warning('请输入学号')
  if (!form.password) return ElMessage.warning('请输入密码')

  loading.value = true
  try {
    await userStore.login({
      student_no: form.student_no.trim(),
      password: form.password,
      remember: form.remember,
      captcha: showCaptcha.value ? form.captcha : undefined
    })
    ElMessage.success('登录成功')
    // 登录前想去的页面，登录后直接过去
    router.replace(route.query.redirect || '/dashboard')
  } catch (e) {
    const msg = e?.response?.data?.detail || '登录失败，请稍后重试'
    ElMessage.error(msg)

    // 登录失败后，显示验证码并刷新
    // （后端已经开始计数了，下次登录必须带验证码）
    if (!showCaptcha.value) {
      showCaptcha.value = true
    }
    await refreshCaptcha()
    form.captcha = ''
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
