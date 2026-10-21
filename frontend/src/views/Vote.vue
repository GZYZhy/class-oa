<template>
  <div class="vote">
    <!-- 整页都是表决内容（谁投了什么、谁还没投），盖一层「谁在看」的水印 -->
    <Watermark :text="watermarkText" />

    <!-- 和审核审批一样整页一张卡片：标题、筛选、列表都在里面 -->
    <div class="page-card">
      <!-- 「发起投票」跟标题同一行：放在筛选区右边的话，窄屏上会孤零零地
           顶在第一行，和下面的控件错开 -->
      <div class="vt-head">
        <h3 class="page-title">投票收集</h3>
        <!-- 权限在按钮一级：普通学生进来只有表决和看结果，后端 committee_required 兜底 -->
        <el-button v-if="userStore.isCommittee" type="primary" @click="handleCreate">
          <el-icon><Plus /></el-icon>{{ activeTab === 'vote' ? '发起投票' : '发起收集' }}
        </el-button>
      </div>

      <!-- 投票和收集分开两个 Tab，各自搜索/分页；都保持挂载，切换不丢条件 -->
      <el-tabs v-model="activeTab" class="vt-tabs">
        <el-tab-pane label="投票" name="vote">
      <div class="vt-bar">
        <el-form :inline="true" size="default" class="vt-filter">
          <el-form-item label="标题">
            <el-input
              v-model="keyword"
              placeholder="搜索投票标题"
              clearable
              style="width: 200px"
              @keyup.enter="handleSearch"
              @clear="handleSearch"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="status" style="width: 130px" @change="handleSearch">
              <el-option label="全部" value="" />
              <el-option label="未开始" value="pending" />
              <el-option label="进行中" value="open" />
              <el-option label="已结束" value="closed" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="handleSearch">
              <el-icon><Search /></el-icon>查询
            </el-button>
            <el-button @click="handleReset">
              <el-icon><Refresh /></el-icon>重置
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- 列表 -->
      <el-table
        v-loading="loading"
        :data="rows"
        stripe
        style="margin-top: 16px;"
        empty-text="还没有投票。班委发起一场，范围内的同学就会收到站内信"
      >
        <el-table-column label="标题" min-width="220">
          <template #default="{ row }">
            <div class="vt-title">
              <span>{{ row.title }}</span>
              <!-- 记名不标注、不记名要标出来（用户口径） -->
              <el-tag v-if="row.anonymous" type="warning" size="small" effect="plain">不记名</el-tag>
            </div>
            <div v-if="row.description" class="vt-sub">{{ markdownPreview(row.description) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="题数" width="70" align="center">
          <template #default="{ row }">{{ row.question_count }}</template>
        </el-table-column>
        <el-table-column label="截止时间" width="160">
          <template #default="{ row }">
            <div>{{ formatDateTime(row.end_at) }}</div>
            <div v-if="row.closed_at" class="vt-sub">已于 {{ formatDateTime(row.closed_at) }} 结束</div>
          </template>
        </el-table-column>
        <el-table-column label="投票情况" width="110" align="center">
          <template #default="{ row }">
            <!-- 看不到结果的人也不显示投票率（参与者要等结束了才看得到） -->
            <span v-if="row.results_visible">{{ row.voted_count }} / {{ row.target_count }}</span>
            <span v-else class="vt-sub">—</span>
          </template>
        </el-table-column>
        <el-table-column label="我的状态" width="100" align="center">
          <template #default="{ row }">
            <span :class="{ 'vt-warn': row.is_target && !row.has_voted }">{{ myStateText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <!-- 普通参与者进统一的外链整页；发起人/管理员看实时票数仍用旧的结果弹窗 -->
            <el-button link type="primary" @click="openMainAction(row)">
              {{ row.can_manage ? '实时预览' : actionText(row) }}
            </el-button>
            <!-- 管理动作收进下拉：行内五个按钮太挤，也容易误点「立即结束」 -->
            <el-dropdown
              v-if="row.can_manage"
              trigger="click"
              @command="(cmd) => handleCommand(cmd, row)"
            >
              <el-button link type="primary">
                管理<el-icon><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item command="roster">投票名单</el-dropdown-item>
                  <!-- 管理入口走弹窗后，仍要从这里去到统一的投票页（自己也要投的时候用） -->
                  <el-dropdown-item command="openSharePage">
                    {{ row.can_vote ? '去投票' : '打开投票页' }}
                  </el-dropdown-item>
                  <el-dropdown-item command="share">分享</el-dropdown-item>
                  <!-- 一个入口两用，文案跟着状态走。暂停不是结束：解锁后照样能投 -->
                  <el-dropdown-item command="toggleLock" :disabled="!canToggleLock(row)">
                    {{ row.status === 'locked' ? '恢复投票' : '暂停投票' }}
                  </el-dropdown-item>
                  <el-dropdown-item command="extend" :disabled="!canExtendPoll(row)">
                    延长5分钟
                  </el-dropdown-item>
                  <el-dropdown-item command="close" :disabled="row.status === 'closed'">
                    立即结束
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        background
        class="vt-pager"
        @size-change="handleSizeChange"
        @current-change="fetchList"
      />
        </el-tab-pane>

        <el-tab-pane label="收集" name="collect">
          <CollectPanel ref="collectRef" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- ========== 结果 / 名单弹窗（管理入口：投票名单） ========== -->
    <el-dialog
      v-model="resultVisible"
      :title="resultPoll.title || '投票'"
      width="720px"
      @closed="stopPolling"
    >
      <!-- 票数标签页和投票名单标签页都在这个弹窗里，名单里是「谁投了谁没投」，盖一层 -->
      <Watermark :text="watermarkText" />
      <div v-loading="resultLoading" class="vt-body">
        <div class="vt-meta">
          <el-tag :type="statusTag(resultPoll.status)" size="small">
            {{ statusLabel(resultPoll.status) }}
          </el-tag>
          <el-tag v-if="resultPoll.anonymous" type="warning" size="small">不记名</el-tag>
          <span class="vt-sub">
            {{ formatDateTime(resultPoll.start_at) }} 起，{{ formatDateTime(resultPoll.end_at) }} 截止
          </span>
        </div>

        <el-tabs v-model="resultTab">
          <el-tab-pane label="票数" name="tally">
            <template v-if="resultPoll.results_visible">
              <div class="vt-tally-head">
                <p class="vt-hint">
                  已投 {{ resultPoll.voted_count }} / {{ resultPoll.target_count }} 人。
                  多选题每人可选的项数不止一个，所以一道题的票数之和会大于人数
                </p>
                <!-- 纯前端重排，不改后端也不动票数：只是换个看的角度（选举时先看谁领先） -->
                <el-button size="small" @click="tallySorted = !tallySorted">
                  {{ tallySorted ? '按选项顺序' : '按得票排序' }}
                </el-button>
              </div>
              <div v-for="(q, i) in resultPoll.questions" :key="q.id" class="vt-rq">
                <div class="vt-q-title">
                  <span>{{ i + 1 }}. {{ q.title }}</span>
                  <el-tag v-if="q.multiple" size="small" type="info" effect="plain">多选</el-tag>
                  <span class="vt-sub">共 {{ sumOf(q) }} 项选择</span>
                </div>
                <!-- j 是**选项的原始下标**：排了序也只是行的先后变了，字母、票数、进度条都还各就各位 -->
                <div v-for="j in tallyOrder(q, tallySorted)" :key="j" class="vt-opt">
                  <span class="vt-opt-name">
                    <span class="vt-opt-letter">{{ letters[j] }}.</span> {{ q.options[j] }}
                  </span>
                  <el-progress
                    :percentage="percentOf(q, j)"
                    :stroke-width="14"
                    :show-text="false"
                    class="vt-bar"
                  />
                  <span class="vt-opt-num">{{ q.tallies?.[j] ?? 0 }} 票</span>
                </div>
              </div>
            </template>
            <el-empty v-else description="投票结束后才能看到结果" :image-size="80" />
          </el-tab-pane>

          <el-tab-pane v-if="resultPoll.can_manage" label="投票名单" name="roster">
            <div class="vt-roster-head">
              <span>
                已投 {{ ballots.voted_count }} / {{ ballots.total }} 人
                <span class="vt-sub">（冻结的账号投不了票，催票也会跳过）</span>
              </span>
              <!-- 这个数字必须和后端催票跳过的口径一致，所以直接用名单里的行算 -->
              <el-button
                size="small"
                type="primary"
                :loading="reminding"
                :disabled="unvotedCount === 0 || resultPoll.status !== 'open'"
                @click="handleRemind"
              >
                催还没投的人（{{ unvotedCount }}）
              </el-button>
            </div>
            <el-table :data="ballots.rows" max-height="380" stripe>
              <el-table-column label="姓名" width="100">
                <template #default="{ row }">{{ row.name || '—' }}</template>
              </el-table-column>
              <el-table-column prop="student_no" label="学号" width="130" />
              <el-table-column label="状态" width="96">
                <template #default="{ row }">
                  <el-tag v-if="row.voted" type="success" size="small">已投</el-tag>
                  <el-tag v-else-if="row.frozen" type="info" size="small">已冻结</el-tag>
                  <el-tag v-else type="warning" size="small">未投</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="投票时间" width="150">
                <template #default="{ row }">
                  {{ row.voted_at ? formatDateTime(row.voted_at) : '—' }}
                </template>
              </el-table-column>
              <!-- 不记名的连这一列都不出现（后端返回的 choices 本来就是 null） -->
              <el-table-column v-if="!resultPoll.anonymous" label="选择" min-width="150">
                <template #default="{ row }">{{ choicesText(row) }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
      <template #footer>
        <el-button @click="resultVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <PollCreateDialog ref="createRef" @saved="handleSaved" />
    <VoteShareDialog v-model="shareVisible" :link="shareLink" :poll="sharePoll" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import PollCreateDialog from '@/components/PollCreateDialog.vue'
import VoteShareDialog from '@/components/VoteShareDialog.vue'
import Watermark from '@/components/Watermark.vue'
import CollectPanel from '@/views/CollectPanel.vue'
import {
  closePoll,
  deletePoll,
  extendPoll,
  getBallots,
  getPoll,
  getPolls,
  lockPoll,
  remindPoll,
  unlockPoll
} from '@/api/vote'
import { useWatermark } from '@/composables/useWatermark'
import { SITE } from '@/utils/site'
import { errText } from '@/utils/request'
import { formatDateTime } from '@/utils/format'
import {
  POLL_LETTERS as letters,
  actionText,
  canToggleLock,
  myStateText,
  percentOf,
  statusLabel,
  statusTag,
  sumOf,
  tallyOrder
} from '@/utils/poll'
import { applyShareMeta, resetShareMeta } from '@/utils/share-meta'
import {
  attachSharePath,
  detachSharePath,
  openShareInNewTab,
  shareUrl
} from '@/utils/share-url'
import { markdownPreview } from '@/utils/collection'
import { useUserStore } from '@/store/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
/** 页面和两个弹窗共用同一份字样 */
const watermarkText = useWatermark()

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const status = ref('')
// 标题搜索。空串 = 不过滤（后端把空关键词当作没传）
const keyword = ref('')
const createRef = ref(null)
const collectRef = ref(null)
/** 当前 Tab；?tab=collect 刷新后仍停在收集 */
const activeTab = ref(route.query.tab === 'collect' ? 'collect' : 'vote')

const reminding = ref(false)

const shareVisible = ref(false)
const shareLink = ref('')
const sharePoll = ref({})
const resultVisible = ref(false)
const resultLoading = ref(false)
const resultPoll = ref({})
const resultTab = ref('tally')
/** 票数页是不是按得票从多到少排。只是个看的习惯，换一场投票不用重设 */
const tallySorted = ref(false)
const ballots = ref({ total: 0, voted_count: 0, rows: [] })

// ---------- 列表 ----------

async function fetchList() {
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (status.value) params.status = status.value
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const res = await getPolls(params)
    rows.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error(errText(e, '读取投票列表失败'))
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
  fetchList()
}

function handleReset() {
  status.value = ''
  keyword.value = ''
  handleSearch()
}

function handleSizeChange() {
  currentPage.value = 1
  fetchList()
}

/** 页面头部按钮：当前在哪个 Tab 就发起哪一类 */
function handleCreate() {
  if (activeTab.value === 'collect') collectRef.value?.openCreate()
  else createRef.value?.open()
}

/** 投票截止前可反复延长 5 分钟；未开始/已结束不给点 */
function canExtendPoll(row) {
  return row.status === 'open' || row.status === 'locked'
}

// ---------- 站内外统一入口 ----------

/**
 * 列表主按钮：普通参与者在新标签页打开整页分享页；发起人/管理员仍看旧的实时结果弹窗
 *
 * 站内站外是同一张页面（/share/vote/{token}）。后端每一场都会现算 token，
 * 所以正常情况下一定有；真遇到老数据没有 token，就退回原来的查看方式。
 */
function openMainAction(row) {
  if (row.can_manage) return openDetail(row, 'tally')
  openSharePage(row)
}

/** 新标签页打开统一的投票页（管理下拉里的「去投票 / 打开投票页」也走这里） */
function openSharePage(row) {
  if (!row.share_token) return openDetail(row)
  if (openShareInNewTab('vote', row.share_token)) return
  return openDetail(row)
}

// ---------- 结果与名单 ----------

/** 管理入口：谁投了谁没投（主按钮已经不走这里了） */
async function openDetail(row, tab = 'tally') {
  resultPoll.value = { ...row, questions: [] } // 先占位，标题立刻就有
  return loadResult(row.id, tab)
}

async function loadResult(id, tab = 'tally') {
  resultTab.value = tab
  resultVisible.value = true
  resultLoading.value = true
  try {
    await refreshResult()
    startPolling()
  } catch (e) {
    ElMessage.error(errText(e, '读取投票失败'))
  } finally {
    resultLoading.value = false
  }
}

/** 重取详情（和名单）。轮询时 silent，别把偶发的网络抖动刷成一片红 */
async function refreshResult(silent = false) {
  const id = resultPoll.value.id
  if (!id) return
  try {
    const detail = await getPoll(id)
    resultPoll.value = detail
    applyPollShareMeta(detail)
    ballots.value = detail.can_manage
      ? await getBallots(id)
      : { total: 0, voted_count: 0, rows: [] }
  } catch (e) {
    if (!silent) throw e
  }
}

// 轮询看的是后端的 results_visible（而不是「我是发起人」）—— 可见性只有后端一处口径。
// 已结束的不用再轮询，票数不会再变了
let timer = null

function startPolling() {
  stopPolling()
  if (resultPoll.value.results_visible && resultPoll.value.status !== 'closed') {
    timer = setInterval(() => refreshResult(true), 5000)
  }
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

/** 未投的人数。冻结的账号投不了票、催票也会跳过，所以这里也要排除掉 ——
 *  这个数字要和后端催票跳过的口径一致，不然会出现「按钮说 3 人、提示说已提醒 1 人」 */
const unvotedCount = computed(
  () => ballots.value.rows.filter((r) => !r.voted && !r.frozen).length
)

/** 记名投票里某人选了哪些：「1.A 2.BC」，题目多的时候比一整张表紧凑 */
function choicesText(row) {
  const choices = row.choices
  if (!choices) return '—'
  const parts = []
  ;(resultPoll.value.questions || []).forEach((q, i) => {
    const indexes = choices[String(q.id)] || []
    if (indexes.length) parts.push(`${i + 1}.${indexes.map((j) => letters[j]).join('')}`)
  })
  return parts.length ? parts.join('  ') : '—'
}

async function handleRemind() {
  const n = unvotedCount.value
  if (!n) return
  try {
    await ElMessageBox.confirm(
      `会给还没投票的 ${n} 人各推一条提醒，可能打扰到他们。确定催票吗？`,
      '催票确认',
      { type: 'warning', confirmButtonText: '催票', cancelButtonText: '取消' }
    )
  } catch {
    return // 点了取消
  }

  reminding.value = true
  try {
    const { reminded } = await remindPoll(resultPoll.value.id)
    ElMessage.success(`已提醒 ${reminded} 人`)
    await refreshResult()
  } catch (e) {
    ElMessage.error(errText(e, '催票失败'))
  } finally {
    reminding.value = false
  }
}

// ---------- 管理动作 ----------

/**
 * 分享链接：真实路径 /share/vote/{token}
 *
 * 不能用 /#/vote?id=…：`#` 后面的内容不会到达服务器，微信爬虫读不到这一场的
 * meta。真实路径由 nginx 返回 index.html 并在同一次响应里注入 head 片段。
 * 没拿到 token（老数据）时退回原来的 hash 链接，功能不断。
 */
function voteShareLink(poll) {
  const id = poll?.id ?? poll
  if (poll?.share_token) {
    return shareUrl('vote', poll.share_token)
  }
  return `${window.location.origin}/#/vote?id=${id}`
}

/** 卡片摘要：和分享页、服务端 meta 用同一套口径 */
function pollCard(poll) {
  const title = `投票：${poll.title || '投票表决'}`
  const tail = [
    statusLabel(poll.status),
    poll.anonymous ? '不记名' : '记名',
    `应投 ${poll.target_count ?? 0} 人`,
    `截止 ${formatDateTime(poll.end_at)}`
  ]
    .filter(Boolean)
    .join(' · ')
  const description = poll.description ? `${poll.description.slice(0, 60)}｜${tail}` : tail
  return { title, description, url: voteShareLink(poll) }
}

/** 打开分享弹窗：把这一场的标题和摘要写进 head，并保留真实分享路径 */
function applyPollShareMeta(poll) {
  if (!poll?.id) return
  applyShareMeta({ ...pollCard(poll), index: !!poll.share_token })
  if (poll.share_token) {
    try {
      attachSharePath(new URL(voteShareLink(poll), window.location.origin).pathname)
    } catch (e) {
      /* 地址栏保持不动也能用 */
    }
  }
}

/** 关闭分享弹窗：head 和地址栏都回到列表页 */
function clearPollShareMeta() {
  resetShareMeta()
  document.title = `投票收集 - ${SITE.shortName}`
  detachSharePath('/share/vote/')
}

/** 「管理 → 分享」：链接 + 复制 + 二维码，链接是 /share/vote/{token} 真实路径 */
function openShare(row) {
  applyPollShareMeta(row)
  sharePoll.value = { ...row }
  shareLink.value = voteShareLink(row)
  shareVisible.value = true
}

function handleCommand(command, row) {
  if (command === 'share') return openShare(row)
  if (command === 'openSharePage') return openSharePage(row)
  if (command === 'edit') return handleEdit(row)
  if (command === 'roster') return openDetail(row, 'roster')
  if (command === 'toggleLock') return handleToggleLock(row)
  if (command === 'extend') return handleExtend(row)
  if (command === 'close') return handleClose(row)
  if (command === 'delete') return handleDelete(row)
}

/** 编辑：题目在列表行里没有，得先拉一次详情，弹窗才填得上 */
async function handleEdit(row) {
  try {
    createRef.value?.openForEdit(await getPoll(row.id))
  } catch (e) {
    ElMessage.error(errText(e, '读取投票失败'))
  }
}

/** 出卷/编辑保存后：列表要重拉；正好开着这场的结果弹窗的话，标题也得跟着变 */
function handleSaved() {
  fetchList()
  // silent：这里失败了不用再弹一次错，上面那条已经提示过保存的结果了
  if (resultVisible.value) refreshResult(true)
}

/**
 * 暂停 / 恢复收票。**暂停不是结束**：解锁后照样能投，到点没解开则照常自动结束
 *
 * 两条路径共用这一个函数，文案和请求都跟着当前状态走 —— 分成两个函数的话，
 * 「结果弹窗正开着要刷新、轮询要跟着停/起」这段就得抄两遍。
 */
async function handleToggleLock(row) {
  const locking = row.status !== 'locked'
  const tip = locking
    ? '暂停期间谁都不能投票，结果和名单照常能看。到截止时间还没恢复的话，会照常自动结束。'
    : '恢复后范围内的人又能接着投。'
  try {
    await ElMessageBox.confirm(`${tip}确定${locking ? '暂停' : '恢复'}「${row.title}」吗？`,
      locking ? '暂停投票' : '恢复投票',
      { type: 'warning', confirmButtonText: locking ? '暂停' : '恢复', cancelButtonText: '取消' }
    )
  } catch {
    return // 点了取消
  }
  try {
    await (locking ? lockPoll : unlockPoll)(row.id)
    ElMessage.success(locking ? '已暂停' : '已恢复')
    fetchList()
    if (resultVisible.value && resultPoll.value.id === row.id) {
      await refreshResult()
      // startPolling 不在 refreshResult 里，所以这里得自己管一次：暂停期间票数不会
      // 再变，让定时器空转纯属白发请求；解锁了票数又能变，照 handleClose 的反面接上
      if (locking) stopPolling()
      else startPolling()
    }
  } catch (e) {
    ElMessage.error(errText(e, locking ? '暂停失败' : '恢复失败'))
  }
}

/** 和签到一样：点一下就延 5 分钟，不弹确认 */
async function handleExtend(row) {
  try {
    await extendPoll(row.id)
    ElMessage.success('已延长5分钟')
    fetchList()
    if (resultVisible.value && resultPoll.value.id === row.id) await refreshResult()
  } catch (e) {
    ElMessage.error(errText(e, '延长失败'))
  }
}

async function handleClose(row) {  try {
    await ElMessageBox.confirm(
      '结束后所有人立刻能看到结果，还没投的人也不能再投。确定现在结束吗？',
      '立即结束',
      { type: 'warning', confirmButtonText: '结束投票', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const res = await closePoll(row.id)
    ElMessage.success(`已结束，共 ${res.voted_count} 人投票`)
    fetchList()
    if (resultVisible.value && resultPoll.value.id === row.id) {
      stopPolling() // 结束了票数不会再变，不用再轮询
      await refreshResult()
    }
  } catch (e) {
    ElMessage.error(errText(e, '结束失败'))
  }
}

async function handleDelete(row) {
  // 已投人数只有看得到结果的人（发起人/管理员）才有值，而能删的正是他们
  const extra = row.voted_count
    ? `已有 ${row.voted_count} 人投票，这些作答会跟着一起删掉，不可恢复。`
    : '删除后不可恢复。'
  try {
    await ElMessageBox.confirm(`${extra}确定删除「${row.title}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deletePoll(row.id)
    ElMessage.success('已删除')
    if (resultVisible.value && resultPoll.value.id === row.id) resultVisible.value = false
    fetchList()
  } catch (e) {
    ElMessage.error(errText(e, '删除失败'))
  }
}

/** 站内信里的旧「新投票」深链会带 ?id=：查到 token 后跳到统一的分享页
 *  （照 StudentList.vue 读 route.query.open 的做法） */
async function openFromQuery() {
  const id = Number(route.query.id)
  if (!id) return
  try {
    const detail = await getPoll(id)
    if (detail.share_token) {
      // replace 不新增历史记录：返回时回到消息列表，而不是绕回这个中转地址
      router.replace({ name: 'SharePage', params: { kind: 'vote', token: detail.share_token } })
    } else {
      resultPoll.value = detail
      await loadResult(id, detail.can_manage ? 'roster' : 'tally')
    }
  } catch (e) {
    // 后端对「已删除」和「无权查看」统一回 404，所以提示语也按同一口径中性写。
    // 不能完全静默：点通知进来却停在列表页，用户只会以为通知点错了。
    if (e?.response?.status === 404) {
      ElMessage.warning('这场投票不存在或你无权查看')
    }
  }
}

onMounted(async () => {
  await fetchList()
  openFromQuery()
})

// Tab 写进地址；切回投票时顺手刷新，收集面板自己管自己的数据
watch(activeTab, (tab) => {
  const query = { ...route.query }
  if (tab === 'collect') query.tab = 'collect'
  else delete query.tab
  router.replace({ query })
  if (tab === 'vote') fetchList()
  else collectRef.value?.refresh()
})

onUnmounted(stopPolling)
onUnmounted(clearPollShareMeta)

// 结果弹窗和分享弹窗都关掉后，标题和 OG 回到列表页
watch(
  [resultVisible, shareVisible],
  ([result, share]) => {
    if (!result && !share) clearPollShareMeta()
  }
)
</script>

<style scoped>
.vote {
  /* 水印的定位基准：水印铺满整个投票页 */
  position: relative;
}

/* 标题和「发起投票」同一行 */
.vt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 16px;
}

.vt-head .page-title {
  margin-bottom: 0;
}

/* Tab 栏自带下边距，去掉标题与标签之间多出来的一截 */
.vt-tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.vt-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.vt-filter {
  margin-bottom: 0; /* el-form 自带下边距，留着会把下面的表格顶远 */
}

/* 手机上控件占满整行，标签挪到左边跟控件并排，别一行标签一行控件 */
@media (max-width: 768px) {
  .vt-filter {
    width: 100%;
  }

  .vt-filter :deep(.el-form-item) {
    display: flex;
    width: 100%;
    margin-right: 0;
    margin-bottom: 10px;
  }

  .vt-filter :deep(.el-form-item__label) {
    width: 44px;
    padding-right: 8px;
    flex-shrink: 0;
    justify-content: flex-start;
  }

  .vt-filter :deep(.el-form-item__content) {
    flex: 1;
    min-width: 0;
  }

  .vt-filter :deep(.el-input),
  .vt-filter :deep(.el-select) {
    width: 100% !important;
  }
}

.vt-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.vt-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.vt-warn {
  color: var(--el-color-warning);
}

.vt-pager {
  margin-top: 14px;
  justify-content: flex-end;
}

/* 弹窗里的长内容限高滚动 */
.vt-body {
  max-height: 60vh;
  overflow-y: auto;
  padding-right: 6px;
}

.vt-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.vt-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

/* 说明那行很长，排序按钮跟它并排、靠右，免得单独再占一行 */
.vt-tally-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.vt-tally-head .vt-hint {
  flex: 1;
}

.vt-rq {
  margin-bottom: 16px;
}

.vt-q-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-weight: 600;
}

.vt-opt {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.vt-opt-name {
  width: 190px;
  flex: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 字母单占一格定宽。
   字母是比例字形，「I.」只有两三个像素宽、「M.」有十几个，而字母和选项名本来是
   同一条行内文本 —— 名字的起点就跟着「这行的字母多宽」左右跳（一列十六行看过去
   就是歪的）。钉住这一格的宽度，名字才落在同一列上（和出卷弹窗的 .pc-opt-label 一个路子）。 */
.vt-opt-letter {
  display: inline-block;
  min-width: 1.5em;
}

.vt-bar {
  flex: 1;
}

.vt-opt-num {
  width: 52px;
  flex: none;
  text-align: right;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.vt-roster-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
</style>
