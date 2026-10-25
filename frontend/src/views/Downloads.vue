<template>
  <div>
    <div class="page-card" v-loading="loading">
      <h3 class="page-title">资料下载</h3>

      <!-- 按分类展示资料 -->
      <div v-for="group in groups" :key="group.category" class="resource-group">
        <div class="group-title">
          <el-icon><FolderOpened /></el-icon>
          {{ group.category }}
          <span class="group-count">{{ group.items.length }} 份</span>
        </div>

        <div class="resource-grid">
          <div v-for="item in group.items" :key="item.name" class="resource-card">
            <div class="resource-icon" :class="getFileType(item)">
              <el-icon><component :is="getFileIcon(item)" /></el-icon>
            </div>
            <div class="resource-info">
              <div class="resource-name" :title="item.name">{{ item.name }}</div>
              <div class="resource-meta">
                <span class="meta-size">{{ formatSize(item.size) }}</span>
                <span class="meta-downloads">下载 {{ item.download_count || 0 }} 次</span>
              </div>
            </div>
            <el-button
              type="primary"
              size="small"
              :disabled="!item.url"
              :loading="downloadingId === item.id"
              @click="download(item)"
            >
              <el-icon v-if="downloadingId !== item.id"><Download /></el-icon>
              <!-- 下大文件时把进度写在按钮上：网络差的时候看着数字涨，
                   总比一个转圈转到人以为卡死了强 -->
              {{ downloadingId === item.id && progress ? progress + '%' : '下载' }}
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'
import { downloadFile, blobErrorDetail } from '@/utils/download'

const groups = ref([])
const loading = ref(false)
// 正在下载的那条：按钮转圈 + 显示百分比。一次只可能有一个（按钮上带了 loading，
// 下着的时候点不动）
const downloadingId = ref(null)
const progress = ref(0)

// 根据扩展名判断文件类型
function getFileType(item) {
  const file = item.file || ''
  if (/\.(jpe?g|png|gif)$/.test(file)) return 'type-image'
  if (/\.pdf$/.test(file)) return 'type-pdf'
  if (/\.xlsx?$/.test(file)) return 'type-excel'
  if (/\.docx?$/.test(file)) return 'type-word'
  return 'type-file'
}

// 文件类型对应图标
function getFileIcon(item) {
  if (getFileType(item) === 'type-image') return 'Picture'
  if (getFileType(item) === 'type-pdf') return 'Document'
  if (getFileType(item) === 'type-excel') return 'Grid'
  if (getFileType(item) === 'type-word') return 'EditPen'
  return 'Files'
}

function formatSize(bytes) {
  if (!bytes) return '文件缺失'
  if (bytes < 1024) return bytes + ' B'
  const kb = bytes / 1024
  if (kb < 1024) return kb.toFixed(1) + ' KB'
  const mb = kb / 1024
  if (mb < 1024) return mb.toFixed(1) + ' MB'
  return (mb / 1024).toFixed(1) + ' GB'
}

// 下载：经 axios 取回再存盘，这样会话失效时能被 401 拦截器接住（见 utils/download.js）
async function download(item) {
  if (!item.url) {
    ElMessage.warning('文件暂不可用')
    return
  }
  downloadingId.value = item.id
  progress.value = 0
  try {
    // 存盘名用后端的 download_name（展示名 + 扩展名），**不是** item.file ——
    // 那是磁盘上的 UUID 名，管理员后台上传的资料会存成 4cc9f361....docx
    await downloadFile(item.url, item.download_name || item.name, (loaded, total) => {
      // 后端没给 Content-Length 时 total 是 0，那就先不显示百分比
      progress.value = total ? Math.round((loaded / total) * 100) : 0
    })
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e))
  } finally {
    downloadingId.value = null
  }
}

onMounted(async () => {
  loading.value = true
  try {
    groups.value = await request({ url: '/resources', method: 'get' })
  } catch (e) {
    ElMessage.error('资料清单加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.resource-group {
  margin-bottom: 28px;
}

.resource-group:last-child {
  margin-bottom: 0;
}

.group-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.group-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: normal;
  margin-left: 4px;
}

/* 按内容区实际宽度自动排，而不是按视口断点：
   侧栏把内容区压缩后，iPad 竖屏上原来的 sm=8（三列）会把每张卡挤到
   一百多像素，文件名和大小都没地方放。auto-fill + 最小 300px 在
   iPad 竖屏落到 1 列、横向落到 2 列，桌面仍是 3 列。 */
.resource-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
  gap: 16px;
}

.resource-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  min-width: 0;
  background: var(--el-fill-color-light);
  /* 补一道描边：原来只有浅底和圆角，和卡片的淡紫底几乎融在一起，
     条目之间看不出是一张张独立的卡 */
  border: 1px solid var(--app-line);
  border-radius: 12px;
  transition: background 0.2s, border-color 0.2s;
}

.resource-card:hover {
  background: var(--el-color-primary-light-9);
  border-color: var(--app-secondary-border);
}

.resource-icon {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: #fff;
  flex-shrink: 0;
}

.type-image { background: linear-gradient(135deg, #9b59b6, #b07cc6); }
.type-pdf { background: linear-gradient(135deg, #e74c3c, #ec7063); }
.type-excel { background: linear-gradient(135deg, #27ae60, #58d68d); }
.type-word { background: linear-gradient(135deg, #2980b9, #5dade2); }
.type-file { background: linear-gradient(135deg, #7f8c8d, #a6b3b4); }

.resource-info {
  flex: 1;
  min-width: 0;
}

.resource-name {
  font-size: 14px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.resource-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 8px;
  margin-top: 3px;
  min-width: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* 大小和下载次数是两个完整信息块：窄下来时换行也不会把「12.3 KB」
   和它后面的单位拆开，分隔点跟着后一块走 */
.meta-size,
.meta-downloads {
  white-space: nowrap;
}

.meta-downloads::before {
  content: '·';
  margin-right: 8px;
  color: var(--el-border-color);
}

.resource-card .el-button {
  flex-shrink: 0;
}

/* 很窄的手机：按钮换到下一行占满，别继续挤文件名 */
@media (max-width: 480px) {
  .resource-card {
    flex-wrap: wrap;
  }

  .resource-info {
    flex: 1 1 calc(100% - 54px);
  }

  .resource-card .el-button {
    width: 100%;
    margin-top: 6px;
  }

  .group-title {
    font-size: 14px;
  }
}
</style>
