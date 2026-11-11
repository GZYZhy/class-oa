<template>
  <section class="workbench" aria-label="我的事务">
    <div class="work-summary">
      <router-link to="/inbox" class="summary-link">
        <el-icon><Message /></el-icon>
        <span>我的消息</span>
        <strong v-if="badges.counts.inbox_unread">{{ badges.counts.inbox_unread }} 条未读</strong>
        <span v-else class="summary-muted">查看消息</span>
        <el-icon><ArrowRight /></el-icon>
      </router-link>
      <router-link v-if="user.isCommittee" to="/review" class="summary-link">
        <el-icon><Checked /></el-icon>
        <span>审核审批</span>
        <strong v-if="badges.counts.review_pending">{{ badges.counts.review_pending }} 项待处理</strong>
        <span v-else class="summary-muted">查看申请</span>
        <el-icon><ArrowRight /></el-icon>
      </router-link>
      <router-link v-else-if="!user.isExternal" to="/my-info?tab=workspace" class="summary-link">
        <el-icon><Document /></el-icon><span>我的办件</span>
        <span class="summary-muted">查看进度</span><el-icon><ArrowRight /></el-icon>
      </router-link>
    </div>

    <div class="work-columns" :class="{ 'no-quote': !quote?.text }">
      <section class="work-section">
        <header class="work-heading">
          <h2>近期事项</h2>
          <router-link to="/vote">投票与收集<el-icon><ArrowRight /></el-icon></router-link>
        </header>
        <div v-if="loading" class="work-skeleton" aria-label="正在加载近期事项" aria-busy="true">
          <span v-for="n in 3" :key="n" />
        </div>
        <ListFeedback v-else-if="tasksError" :error="tasksError" @retry="load" />
        <ul v-else-if="tasks.length" class="work-list">
          <li v-for="task in tasks.slice(0, 5)" :key="task.key" class="work-task">
            <span class="task-kind" :class="{ 'task-correction': task.kind === '补正' }">{{ task.kind }}</span>
            <div class="task-main">
              <a v-if="task.share" :href="task.path" target="_blank" rel="noopener noreferrer" class="task-title">{{ task.title }}</a>
              <router-link v-else :to="task.path" class="task-title">{{ task.title }}</router-link>
              <span class="task-time">{{ task.hint }}</span>
            </div>
            <a v-if="task.share" :href="task.path" target="_blank" rel="noopener noreferrer" class="task-action">{{ task.action }}</a>
            <router-link v-else :to="task.path" class="task-action">{{ task.action }}</router-link>
          </li>
        </ul>
        <div v-else class="work-empty">
          <el-icon><CircleCheck /></el-icon>
          <strong>近期没有需要参与的事项</strong>
          <span>进行中的投票、收集和需要补正的申请会显示在这里。</span>
        </div>
        <router-link v-if="tasks.length > 5" to="/vote" class="work-more">查看其他事项</router-link>
        <p v-if="hasMore" class="work-note">这里只汇总最近发布的事项，历史记录可在对应页面查看。</p>
        <figure v-if="quote?.enabled && quote.text" class="work-quote">
          <blockquote>{{ quote.text }}</blockquote>
          <figcaption>—— {{ quote.from_who || quote.from || '一言' }}</figcaption>
        </figure>
      </section>

      <section class="work-section agenda-section">
        <header class="work-heading">
          <h2>今日日程</h2>
          <router-link to="/schedule">打开日程<el-icon><ArrowRight /></el-icon></router-link>
        </header>
        <div v-if="loading" class="work-skeleton" aria-label="正在加载今日日程" aria-busy="true">
          <span v-for="n in 3" :key="n" />
        </div>
        <ListFeedback v-else-if="agendaError" :error="agendaError" @retry="load" />
        <ul v-else-if="agenda.length" class="agenda-list">
          <li v-for="event in agenda.slice(0, 4)" :key="`${event.id}-${event.instance_date}`">
            <time>{{ event.all_day ? '全天' : formatDateTime(event.start_time).slice(11, 16) }}</time>
            <div>
              <router-link to="/schedule">{{ event.title }}</router-link>
              <span v-if="event.location">{{ event.location }}</span>
            </div>
          </li>
        </ul>
        <div v-else class="work-empty">
          <el-icon><Calendar /></el-icon>
          <strong>今天暂无日程安排</strong>
          <router-link to="/schedule">查看本周日程</router-link>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useUserStore } from '@/store/user'
import { useBadgeStore } from '@/store/badge'
import { useLatestRequest } from '@/composables/useLatestRequest'
import { getPolls } from '@/api/vote'
import { getCollections } from '@/api/collection'
import { getMySubmitted } from '@/api/workspace'
import { getDailyQuote } from '@/api/auth'
import { listExternalSchedules, listSchedules } from '@/api/schedule'
import { formatDateTime } from '@/utils/format'
import { sharePath } from '@/utils/share-url'
import ListFeedback from '@/components/ListFeedback.vue'

const user = useUserStore()
const badges = useBadgeStore()
const latest = useLatestRequest()
const quoteLatest = useLatestRequest()
const tasks = ref([])
const agenda = ref([])
const quote = ref(null)
const loading = ref(true)
const tasksError = ref('')
const agendaError = ref('')
const hasMore = ref(false)
const PAGE_SIZE = 20

async function load() {
  const id = latest.start()
  loading.value = true
  tasksError.value = ''
  agendaError.value = ''
  loadQuote()
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const [polls, collections, cases, schedules] = await Promise.allSettled([
    getPolls({ status: 'open', page: 1, page_size: PAGE_SIZE }),
    getCollections({ status: 'open', page: 1, page_size: PAGE_SIZE }),
    user.isExternal ? Promise.resolve([]) : getMySubmitted(),
    user.isExternal ? listExternalSchedules(today, today) : listSchedules(today, today)
  ])
  if (!latest.isCurrent(id)) return

  // 一路失败时明确提示，避免把不完整的汇总展示为「没有待办」。
  if ([polls, collections, cases].some((result) => result.status === 'rejected')) {
    tasksError.value = '近期事项暂时无法完整加载'
  } else {
    const votes = (polls.value.items || []).filter((row) => row.can_vote).map((row) => ({
      key: `vote-${row.id}`, kind: '投票', title: row.title, action: '去投票',
      path: row.share_token ? sharePath('vote', row.share_token) : '/#/vote',
      share: true, hint: `${formatDateTime(row.end_at)} 截止`, deadline: row.end_at
    }))
    const fills = (collections.value.items || []).filter((row) => row.can_submit).map((row) => ({
      key: `collect-${row.id}`, kind: '收集', title: row.title, action: '去填写',
      path: row.share_token ? sharePath('collect', row.share_token) : '/#/vote?tab=collect',
      share: true, hint: `${formatDateTime(row.end_at)} 截止`, deadline: row.end_at
    }))
    const corrections = cases.value.filter((row) => row.status === 'correcting').map((row) => ({
      key: `${row.type}-${row.id}`, kind: '补正', title: row.title, action: '补充材料',
      path: row.detail_url, share: false, hint: row.reason || row.status_label, deadline: ''
    }))
    tasks.value = [...corrections, ...votes, ...fills].sort((a, b) => (a.deadline || '').localeCompare(b.deadline || ''))
    hasMore.value = polls.value.total > PAGE_SIZE || collections.value.total > PAGE_SIZE
  }
  if (schedules.status === 'rejected') agendaError.value = '今日日程加载失败'
  else agenda.value = [...schedules.value].sort((a, b) => a.start_time.localeCompare(b.start_time))
  loading.value = false
}

async function loadQuote() {
  const id = quoteLatest.start()
  quote.value = null
  try {
    const data = await getDailyQuote()
    if (quoteLatest.isCurrent(id)) quote.value = data
  } catch {
    // 一言只是点缀，失败不打扰用户
  }
}

onMounted(load)
watch(() => user.info?.student_no, load)
</script>

<style scoped>
.workbench {
  margin-bottom: 24px;
  border: 1px solid var(--app-line);
  border-radius: 20px;
  overflow: hidden;
  background: var(--app-surface-solid);
}
.work-summary {
  display: grid;
  /* 和下面两栏同一条分隔线，否则「审核审批」会比「今日日程」偏左 */
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
  border-bottom: 1px solid var(--app-outline);
  background: var(--app-inset-bg);
}
.summary-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 24px;
  color: var(--el-text-color-primary);
  text-decoration: none;
  font-size: 14px;
}
.summary-link + .summary-link {
  border-left: 1px solid var(--app-outline);
}
.summary-link > .el-icon:first-child {
  color: var(--el-color-primary);
  font-size: 19px;
}
.summary-link > .el-icon:last-child {
  margin-left: auto;
  color: var(--el-text-color-secondary);
}
.summary-link strong {
  font-size: 13px;
  color: var(--el-color-primary);
  margin-left: auto;
}
.summary-muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: auto;
}
.work-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
}
.work-columns.no-quote {
  align-items: start;
}
.work-section {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 22px 24px;
}
.agenda-section {
  border-left: 1px solid var(--app-outline);
}
.work-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.work-heading h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 650;
}
.work-heading a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--el-color-primary);
  text-decoration: none;
  font-size: 12px;
  flex-shrink: 0;
}
.work-list, .agenda-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.work-task {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 15px 0;
  border-bottom: 1px solid var(--app-outline);
}
.work-task:first-child {
  padding-top: 0;
}
.work-task:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}
.task-kind {
  align-self: flex-start;
  padding: 4px 7px;
  border-radius: 6px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 11px;
  flex-shrink: 0;
}
.task-correction {
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
}
.task-main {
  display: grid;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.task-title {
  font-size: 14px;
  font-weight: 550;
  color: var(--el-text-color-primary);
  text-decoration: none;
  overflow-wrap: anywhere;
}
.task-title:hover, .agenda-list a:hover {
  color: var(--el-color-primary);
}
.task-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  overflow-wrap: anywhere;
}
.task-action {
  color: var(--el-color-primary);
  text-decoration: none;
  font-size: 12px;
  flex-shrink: 0;
  padding: 8px 0 8px 8px;
}
.work-empty {
  min-height: 130px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 10px;
}
.work-empty > .el-icon {
  color: var(--el-color-primary);
  font-size: 25px;
}
.work-empty strong {
  font-size: 14px;
  font-weight: 550;
}
.work-empty span, .work-empty a {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.8;
  text-decoration: none;
}
.agenda-list li {
  display: flex;
  gap: 16px;
  padding: 0 0 20px;
}
.agenda-list time {
  width: 42px;
  flex-shrink: 0;
  padding-top: 1px;
  font-size: 13px;
  color: var(--el-color-primary);
  font-variant-numeric: tabular-nums;
}
.agenda-list li > div {
  border-left: 2px solid var(--app-outline);
  padding-left: 14px;
  display: grid;
  gap: 7px;
}
.agenda-list a {
  color: var(--el-text-color-primary);
  font-size: 14px;
  text-decoration: none;
}
.agenda-list span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.work-more, .work-note {
  display: block;
  margin: 14px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-decoration: none;
  line-height: 1.7;
}
.work-quote {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  min-height: 120px;
  margin: 18px 0 0;
  padding: 18px 0 0;
  border-top: 1px solid var(--app-outline);
}
.work-quote blockquote {
  margin: 0;
  color: var(--el-text-color-regular);
  font-size: 16px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}
.work-quote figcaption {
  margin-top: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-align: right;
}

.work-skeleton {
  display: grid;
  gap: 14px;
}
.work-skeleton span {
  height: 36px;
  background: var(--el-fill-color-light);
  border-radius: 7px;
}
@media (max-width: 900px) {
  .work-columns {
    grid-template-columns: 1fr;
  }
  .agenda-section {
    border-left: 0;
    border-top: 1px solid var(--app-outline);
  }
  .work-empty {
    min-height: 100px;
  }
}
@media (max-width: 520px) {
  .work-summary {
    grid-template-columns: 1fr;
  }
  .summary-link {
    padding: 14px 16px;
  }
  .summary-link + .summary-link {
    border-left: 0;
    border-top: 1px solid var(--app-outline);
  }
  .work-section {
    padding: 19px 16px;
  }
  .work-quote {
    min-height: 96px;
  }
  .work-quote blockquote {
    font-size: 15px;
  }
  .work-heading {
    margin-bottom: 18px;
  }
  .workbench {
    border-radius: 16px;
  }
}
</style>
