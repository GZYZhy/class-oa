<template>
  <div>
    <div class="page-card" v-loading="loading">
      <div class="inbox-head">
        <div>
          <h3 class="page-title">站内信</h3>
          <p class="inbox-sub">
            所有推送给你的消息都在这里 —— 通知公告、办件进度、审核结果、生日祝福。
            手机推送没开也漏不掉。
          </p>
        </div>
        <el-button
          v-if="unread > 0"
          :loading="markingAll"
          @click="readAll"
        >
          全部标为已读（{{ unread }}）
        </el-button>
      </div>

      <el-empty v-if="!loading && !items.length" description="还没有收到任何消息" />

      <div v-else class="msg-list">
        <div
          v-for="item in items"
          :key="item.id"
          class="msg-card"
          :class="{ 'is-unread': !item.read_at }"
          @click="toggle(item)"
        >
          <!-- 未读的圆点。已读的占同样宽度但透明，免得整列文字左右跳 -->
          <span class="msg-dot" :class="{ on: !item.read_at }"></span>
          <div class="msg-main">
            <div class="msg-title-row">
              <span class="msg-title">{{ item.title }}</span>
              <el-tag v-if="item.level === 'timeSensitive'" size="small" type="warning" effect="plain">
                重要
              </el-tag>
              <span class="msg-time">{{ formatDateTime(item.created_at) }}</span>
            </div>
            <div class="msg-body" :class="{ expanded: expandedId === item.id }">{{ item.body }}</div>
            <div v-if="expandedId === item.id && item.page" class="msg-actions">
              <el-button type="primary" link size="small" @click.stop="go(item)">
                前往查看 →
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="total > pageSize" class="inbox-pager">
        <el-pagination
          layout="prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getInbox, markInboxRead, markAllInboxRead } from '@/api/inbox'
import { formatDateTime } from '@/utils/format'
import { useBadgeStore } from '@/store/badge'

const router = useRouter()
const badgeStore = useBadgeStore()

const items = ref([])
const total = ref(0)
const unread = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const markingAll = ref(false)
// 当前展开的那条。一次只开一条：收件箱是流水，同时摊开一堆正文反而找不到刚看的那条
const expandedId = ref(null)

async function load() {
  loading.value = true
  try {
    const data = await getInbox({ page: page.value, page_size: pageSize })
    items.value = data.items || []
    total.value = data.total || 0
    unread.value = data.unread || 0
    syncBadge()
  } catch (e) {
    ElMessage.error('收件箱加载失败')
  } finally {
    loading.value = false
  }
}

function onPageChange(next) {
  page.value = next
  expandedId.value = null
  load()
}

/**
 * 点开一条：展开正文，是未读就顺手标记已读
 *
 * 标记失败**不打断用户**：内容已经展开了，为了一个红点弹个错误框不值当；
 * 下次进来它还是未读，也就再标一次而已。
 */
async function toggle(item) {
  if (expandedId.value === item.id) {
    expandedId.value = null
    return
  }
  expandedId.value = item.id
  if (item.read_at) return
  try {
    await markInboxRead(item.id)
    item.read_at = new Date().toISOString()
    unread.value = Math.max(0, unread.value - 1)
    syncBadge()
  } catch (e) {
    /* 见上 */
  }
}

async function readAll() {
  try {
    await ElMessageBox.confirm(
      '会把全部消息标为已读，菜单上的红点清零。消息本身不会删除。',
      '全部标为已读',
      { type: 'info', confirmButtonText: '标记', cancelButtonText: '取消' }
    )
  } catch {
    return // 点了取消
  }

  markingAll.value = true
  try {
    await markAllInboxRead()
    const now = new Date().toISOString()
    items.value.forEach((item) => {
      if (!item.read_at) item.read_at = now
    })
    unread.value = 0
    syncBadge()
  } catch (e) {
    ElMessage.error('操作失败')
  } finally {
    markingAll.value = false
  }
}

function go(item) {
  router.push(item.page)
}

/**
 * 就地标记已读后把红点同步过去
 *
 * 不调 badgeStore.refresh()：那会把通知、待办几个数字一起重查一遍，
 * 而这里变的只有站内信一个数。
 */
function syncBadge() {
  badgeStore.setInboxUnread(unread.value)
}

onMounted(load)
</script>

<style scoped>
.inbox-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.inbox-sub {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.msg-card {
  display: flex;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  margin-bottom: 10px;
  cursor: pointer;
  transition: background 0.2s;
}

.msg-card:hover {
  background: var(--el-color-primary-light-9);
}

/* 未读的底色比已读的亮一点，扫一眼就知道哪些是新的 */
.msg-card.is-unread {
  background: var(--el-color-primary-light-9);
}

.msg-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 7px;
  flex-shrink: 0;
  background: transparent;
}

.msg-dot.on {
  background: var(--el-color-primary);
}

.msg-main {
  flex: 1;
  min-width: 0;
}

.msg-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.msg-title {
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.is-unread .msg-title {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.msg-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.msg-body {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
  /* 正文里有换行（有的标题就是多行拼的），原样保留 */
  white-space: pre-wrap;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.msg-body.expanded {
  display: block;
  overflow: visible;
}

.msg-actions {
  margin-top: 6px;
}

.inbox-pager {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}

/* 手机端：标题和时间挤一行会折得很乱，改成竖排 */
@media (max-width: 768px) {
  .inbox-head {
    flex-direction: column;
    align-items: stretch;
  }

  .msg-title-row {
    flex-wrap: wrap;
  }

  .msg-time {
    margin-left: 0;
    width: 100%;
  }
}
</style>
