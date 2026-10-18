<!--
  提交办件前的「签名闸门」：系统里还没有可用签字图时，当场手写一张并保存，
  再接着提交。请假和电动车通行证共用（这两份材料上都要印本人签字）。

  用法：
    <QuickSignDialog ref="signGuard" />
    if (!(await signGuard.value.ensure())) return   // 取消或检查失败就不提交

  保存走的是学生换签字图那条接口（/sign-photos/image/{id}），所以操作日志、
  管理员提醒都和「申请修改」页里手动换图完全一致，不另开一套。
-->
<template>
  <SignaturePadDialog
    v-model="visible"
    title="还没有签名，请先手写一张"
    :signer-name="userStore.info?.name"
    :signer-no="userStore.info?.student_no"
    :submitting="submitting"
    @update:model-value="handleVisible"
    @confirm="handleConfirm"
  />
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import SignaturePadDialog from '@/components/SignaturePadDialog.vue'
import { getMySignStatus, uploadSignImage } from '@/api/signPhoto'
import { getMyInfo } from '@/api/student'
import { useUserStore } from '@/store/user'

const userStore = useUserStore()
const visible = ref(false)
const submitting = ref(false)
// ensure() 的收尾函数：签完 resolve(true)，取消 resolve(false)
let finish = null

function settle(ok) {
  const fn = finish
  finish = null
  fn?.(ok)
}

/**
 * 确认有可用签字图；没有就弹窗让人手写。
 *
 * 返回 true = 已经有 / 刚签完并保存成功，调用方可以继续提交；
 * 返回 false = 检查失败或用户取消，调用方应当中止。
 */
async function ensure() {
  try {
    const { uploaded } = await getMySignStatus()
    if (uploaded) return true
  } catch (e) {
    // 判断不了就不放行：宁可让人重试，也不悄悄提交一份没有签字的材料
    ElMessage.error('无法确认签字图状态，请稍后重试')
    return false
  }
  visible.value = true
  return new Promise((resolve) => {
    finish = resolve
  })
}

/** 签完立即上传，存进档案后自动放行提交 */
async function handleConfirm(blob) {
  submitting.value = true
  try {
    // 上传接口要学生 id，而登录信息里只有学号，这里取一次自己的档案
    const me = await getMyInfo()
    const fileName = `sign-${me.student_no || me.id}.png`
    await uploadSignImage(me.id, new File([blob], fileName, { type: 'image/png' }))
    visible.value = false
    ElMessage.success('签名已保存，正在提交申请')
    settle(true)
  } catch (e) {
    // 上传失败时弹窗不关，笔迹还在，可以直接重试或取消
    ElMessage.error(e?.response?.data?.detail || '签名保存失败，请重试')
  } finally {
    submitting.value = false
  }
}

/** 点「取消」或右上角关闭：没签成，调用方中止提交 */
function handleVisible(value) {
  if (!value) settle(false)
}

defineExpose({ ensure })
</script>
