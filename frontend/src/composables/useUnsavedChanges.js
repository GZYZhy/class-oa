import { onBeforeUnmount, onMounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/store/user'

/** 表单仍有内容或附件时，在切页、刷新和关闭前提醒。内容仅留在页面内存中。 */
export function useUnsavedChanges(snapshot) {
  const user = useUserStore()
  const owner = user.info?.student_no
  let saved = JSON.stringify(snapshot())
  const isDirty = () => user.info?.student_no === owner && JSON.stringify(snapshot()) !== saved
  function beforeUnload(event) {
    if (!isDirty()) return
    event.preventDefault()
    event.returnValue = ''
  }

  onBeforeRouteLeave(async () => {
    if (!isDirty()) return true
    try {
      await ElMessageBox.confirm('填写的内容尚未提交，离开后需要重新填写。', '离开当前页面？', {
        confirmButtonText: '离开页面', cancelButtonText: '继续填写', type: 'warning'
      })
      return true
    } catch {
      return false
    }
  })
  onMounted(() => window.addEventListener('beforeunload', beforeUnload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
  return { markSaved: () => { saved = JSON.stringify(snapshot()) } }
}
