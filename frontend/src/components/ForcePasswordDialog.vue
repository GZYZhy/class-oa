<!--
  首次登录 / 管理员重置后强制改密。

  挂在 App.vue 这一层，而不是 AppLayout 里：签到、登录这些整屏页（meta.bare）
  根本不渲染布局，放在布局里的话，从签到深链进来的人会绕过改密直接签到。
  改完密码不跳页 —— 用户是从哪条链接来的，就留在哪里继续。
-->
<template>
  <el-dialog
    v-model="visible"
    title="首次登录，请设置新密码"
    width="420px"
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
  >
    <el-alert
      title="当前使用的是默认密码（身份证号后6位），为保障信息安全，请先设置新密码。"
      type="warning"
      :closable="false"
      style="margin-bottom: 16px;"
    />
    <el-form :model="form" label-width="90px">
      <el-form-item label="新密码">
        <el-input
          v-model="form.new_password"
          type="password"
          show-password
          placeholder="6-32 位，需同时包含字母和数字"
        />
      </el-form-item>
      <el-form-item label="确认密码">
        <el-input v-model="form.confirm" type="password" show-password @keyup.enter="submit" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button type="primary" :loading="loading" @click="submit">确认设置</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { setInitialPassword } from '@/api/auth'
import { useUserStore } from '@/store/user'

const userStore = useUserStore()
const visible = ref(false)
const loading = ref(false)
const form = reactive({ new_password: '', confirm: '' })

// 登录用户带 must_change_password 标记时，自动弹出设置密码
watch(
  () => userStore.info?.must_change_password,
  (need) => {
    if (!need) return
    form.new_password = ''
    form.confirm = ''
    visible.value = true
  },
  { immediate: true }
)

/** 首次设置密码：刚用默认密码登录过，不再校验原密码 */
async function submit() {
  if (form.new_password.length < 6 || form.new_password.length > 32) {
    return ElMessage.warning('新密码长度需为 6-32 位')
  }
  if (!/[A-Za-z]/.test(form.new_password) || !/\d/.test(form.new_password)) {
    return ElMessage.warning('新密码必须同时包含字母和数字')
  }
  if (form.new_password !== form.confirm) {
    return ElMessage.warning('两次输入的新密码不一致')
  }

  loading.value = true
  try {
    await setInitialPassword({ new_password: form.new_password })
    userStore.markPasswordChanged()
    visible.value = false
    ElMessage.success('密码设置成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '设置失败')
  } finally {
    loading.value = false
  }
}
</script>
