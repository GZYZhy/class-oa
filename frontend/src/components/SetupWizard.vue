<template>
  <!-- 初始化浮层：临时账号登录后整屏接管，不给关、不给绕过。
       用的是 v-if 换掉整个应用外壳（见 App.vue），而不是盖一层弹窗 ——
       盖弹窗的话底下的路由页面照样挂载、照样请求接口，然后撞一堵 403 墙。 -->
  <div class="setup-screen">
    <div class="setup-card">
      <div class="setup-head">
        <h2 class="setup-title">首次初始化</h2>
        <el-button link type="info" size="small" @click="handleLogout">退出登录</el-button>
      </div>

      <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 20px;">
        <template #title>你现在用的是初始化临时账号</template>
        <div class="setup-tip">
          它只用来完成第一次初始化。做完下面两步，这个账号会被立即删除，
          你需要用指定出来的那个管理员账号重新登录。
        </div>
      </el-alert>

      <!-- 第一步：把学生弄进来。两条路，走通任意一条即可 -->
      <div class="setup-block" :class="{ done: state.has_students }">
        <div class="step-head">
          <span class="step-no">{{ state.has_students ? '✓' : '1' }}</span>
          <span class="step-title">准备学生名单</span>
          <span v-if="state.has_students" class="step-note">
            已有 {{ state.students.length }} 名学生
          </span>
        </div>

        <div class="step-body">
          <div class="two-ways">
            <el-button type="primary" plain @click="importRef?.open()">
              <el-icon><Upload /></el-icon>
              导入 Excel 名单
            </el-button>
            <el-button plain @click="manualOpen = !manualOpen">
              <el-icon><Plus /></el-icon>
              手工新增一名学生
            </el-button>
          </div>

          <!-- 手工新增：只是救急用，正常还是导 Excel -->
          <div v-if="manualOpen" class="manual-form">
            <el-form :model="manualForm" label-width="60px" size="default">
              <el-form-item label="学号">
                <el-input v-model="manualForm.student_no" placeholder="必填" @keyup.enter="handleManualAdd" />
              </el-form-item>
              <el-form-item label="姓名">
                <el-input v-model="manualForm.name" placeholder="必填" @keyup.enter="handleManualAdd" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="manualLoading" @click="handleManualAdd">
                  新增
                </el-button>
                <el-button @click="manualOpen = false">收起</el-button>
              </el-form-item>
            </el-form>
            <div class="hint">
              新增时会同时开通登录账号，初始密码是学号后 6 位（有身份证号则是身份证后 6 位）。
            </div>
          </div>
        </div>
      </div>

      <!-- 第二步：指定谁是管理员 -->
      <div class="setup-block" :class="{ done: false }">
        <div class="step-head">
          <span class="step-no">2</span>
          <span class="step-title">指定一名管理员</span>
        </div>

        <div class="step-body">
          <el-alert v-if="!state.has_students" type="info" :closable="false">
            先把上面那步做完，这里才能选人。
          </el-alert>

          <template v-else>
            <el-select
              v-model="adminStudentNo"
              filterable
              placeholder="输入姓名或学号搜索"
              style="width: 100%;"
            >
              <el-option
                v-for="s in state.students"
                :key="s.student_no"
                :label="`${s.name}（${s.student_no}）`"
                :value="s.student_no"
              />
            </el-select>

            <div class="hint" style="margin-top: 12px;">
              这个人会成为系统里第一个管理员，之后可以在「系统管理 → 账号管理」里
              调整其他人的角色。他的账号初始密码是身份证号后 6 位（没填身份证号的
              则是学号后 6 位），首次登录必须改密。
            </div>
          </template>
        </div>
      </div>

      <el-button
        type="primary"
        size="large"
        class="setup-submit"
        :disabled="!state.has_students || !adminStudentNo"
        :loading="submitLoading"
        @click="handleFinish"
      >
        完成初始化
      </el-button>
    </div>

    <!-- 导入弹窗与学生名单页共用同一个组件；导完刷新一下状态 -->
    <StudentImportDialog ref="importRef" @done="refresh" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSetupState, finishSetup } from '@/api/setup'
import { createStudent } from '@/api/student'
import { useUserStore } from '@/store/user'
import { errText } from '@/utils/request'
import StudentImportDialog from '@/components/StudentImportDialog.vue'

const router = useRouter()
const userStore = useUserStore()

const state = reactive({ has_students: false, students: [] })
const adminStudentNo = ref('')
const submitLoading = ref(false)

const importRef = ref(null)
const manualOpen = ref(false)
const manualLoading = ref(false)
const manualForm = reactive({ student_no: '', name: '' })

async function refresh() {
  try {
    const data = await getSetupState()
    state.has_students = data.has_students
    state.students = data.students || []
    // 刚导进来的名单里可能已经没了他选的那个学号，清掉免得提交时才报错
    if (adminStudentNo.value && !state.students.some((s) => s.student_no === adminStudentNo.value)) {
      adminStudentNo.value = ''
    }
  } catch (e) {
    // 拦截器不弹错，这里自己说一句：拿不到状态就没法往下走
    ElMessage.error(errText(e, '读取初始化状态失败，请刷新页面重试'))
  }
}

async function handleManualAdd() {
  const studentNo = manualForm.student_no.trim()
  const name = manualForm.name.trim()
  if (!studentNo || !name) {
    return ElMessage.warning('学号和姓名都要填')
  }
  manualLoading.value = true
  try {
    const res = await createStudent({ student_no: studentNo, name })
    manualForm.student_no = ''
    manualForm.name = ''
    manualOpen.value = false
    // 后端在没身份证号时会把初始密码回带（见 api/students.py 的 create_student_api）
    ElMessage.success(
      `已新增 ${name}，登录账号 ${studentNo} 已开通` +
      (res?.password ? `，初始密码 ${res.password}` : '')
    )
    await refresh()
  } catch (e) {
    ElMessage.error(errText(e, '新增失败'))
  } finally {
    manualLoading.value = false
  }
}

async function handleFinish() {
  if (!adminStudentNo.value) return
  submitLoading.value = true
  try {
    const res = await finishSetup(adminStudentNo.value)
    // 后端此时已经删掉临时账号了，手里这个会话随之作废。
    // 先把要说的话讲完，再清登录态回去登录
    await ElMessageBox.alert(
      `${res.admin_name}（${res.admin_student_no}）已设为管理员。\n\n` +
      '初始化临时账号已删除，请用它重新登录。',
      '初始化完成',
      { type: 'success', confirmButtonText: '去登录' }
    ).catch(() => {})
    userStore.info = null
    router.push('/login')
  } catch (e) {
    ElMessage.error(errText(e, '初始化失败'))
  } finally {
    submitLoading.value = false
  }
}

async function handleLogout() {
  userStore.info = null
  router.push('/login')
}

onMounted(refresh)
</script>

<style scoped>
.setup-screen {
  position: fixed;
  inset: 0;
  overflow-y: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 16px;
  box-sizing: border-box;
  background: linear-gradient(135deg, #1f2d3d 0%, #2c3e50 50%, #1f2d3d 100%);
}

.setup-card {
  width: 100%;
  max-width: 560px;
  background: var(--el-bg-color);
  border-radius: 10px;
  padding: 24px 28px 28px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
}

.setup-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.setup-title {
  margin: 0;
  font-size: 20px;
  color: var(--el-text-color-primary);
}

.setup-tip {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.6;
}

.setup-block {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 14px;
}

.setup-block.done {
  border-color: var(--el-color-success-light-5);
  background: var(--el-color-success-light-9);
}

.step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.step-no {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 13px;
  line-height: 22px;
  text-align: center;
}

.setup-block.done .step-no {
  background: var(--el-color-success);
}

.step-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.step-note {
  margin-left: auto;
  font-size: 13px;
  color: var(--el-color-success);
}

.two-ways {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.manual-form {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.hint {
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.setup-submit {
  width: 100%;
  margin-top: 4px;
}

/* 手机上收窄留白：卡片本身够窄，多出来的空间给内容 */
@media (max-width: 480px) {
  .setup-card {
    padding: 18px 16px 20px;
  }
}
</style>
