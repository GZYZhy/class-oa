<template>
  <!-- 主动修改密码：需要验证原密码（与首次登录设置密码是两条独立流程） -->
  <el-dialog
    v-model="visible"
    title="修改密码"
    width="420px"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <el-form :model="form" label-width="90px">
      <el-form-item label="原密码">
        <el-input v-model="form.old_password" type="password" show-password />
      </el-form-item>
      <el-form-item label="新密码">
        <el-input
          v-model="form.new_password"
          type="password"
          show-password
          placeholder="6-32 位，需同时包含字母和数字"
        />
      </el-form-item>
      <el-form-item label="确认密码">
        <el-input
          v-model="form.confirm"
          type="password"
          show-password
          @keyup.enter="handleSubmit"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">确认修改</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { changePassword } from '@/api/auth'

const visible = ref(false)
const loading = ref(false)
const form = reactive({ old_password: '', new_password: '', confirm: '' })

function open() {
  reset()
  visible.value = true
}

function reset() {
  form.old_password = ''
  form.new_password = ''
  form.confirm = ''
}

async function handleSubmit() {
  if (!form.old_password) return ElMessage.warning('请输入原密码')
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
    await changePassword({
      old_password: form.old_password,
      new_password: form.new_password
    })
    visible.value = false
    ElMessage.success('密码修改成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  } finally {
    loading.value = false
  }
}

// 让父组件通过 ref 调用 open()
defineExpose({ open })
</script>
