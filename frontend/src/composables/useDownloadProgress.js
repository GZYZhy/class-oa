import { ref } from 'vue'

/**
 * 下载按钮的进度显示
 *
 * 办件里同一个列表可能有多个下载入口（请假表、申请表、承诺书……），
 * 这里用 key 区分是哪一行、哪一个按钮在下载：同一时间只跑一个，
 * 其余按钮保持原样、也不会被重复点击。
 *
 * 用法：
 *   const { percent, isDownloading, run } = useDownloadProgress()
 *   run(`leave-${row.id}`, (onProgress) => downloadLeavePdf(row.id, onProgress))
 *
 * 后端没给 Content-Length 时 total 为 0，percent 一直是 0，
 * 模板里按「没有百分比就显示原按钮文字」处理（和资料下载、公告一致）。
 */
export function useDownloadProgress() {
  const key = ref('')
  const percent = ref(0)

  function isDownloading(k) {
    return key.value === k
  }

  /** 执行一次下载。task 收到 onProgress(loaded, total)，错误抛给调用方处理 */
  async function run(k, task) {
    if (key.value) return
    key.value = k
    percent.value = 0
    try {
      return await task((loaded, total) => {
        percent.value = total ? Math.round((loaded / total) * 100) : 0
      })
    } finally {
      key.value = ''
      percent.value = 0
    }
  }

  return { key, percent, isDownloading, run }
}
