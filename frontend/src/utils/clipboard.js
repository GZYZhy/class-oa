/**
 * 复制文本到剪贴板
 *
 * 为什么要有降级分支：navigator.clipboard 只在 secure context（https 或 localhost）
 * 下可用，而本站完全可能跑在内网 http 上 —— 那条路是真会被走到的，不能省。
 *
 * 成功提示由本函数自己弹，调用方不用管。
 */
import { ElMessage } from 'element-plus'

export function copyText(text) {
  if (!text) return
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    // 降级方案：临时塞一个 textarea 进去选中再复制
    const textarea = document.createElement('textarea')
    textarea.value = text
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    ElMessage.success('已复制到剪贴板')
  })
}
