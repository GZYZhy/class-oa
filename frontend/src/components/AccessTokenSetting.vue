<template>
  <div class="channel-block">
    <!-- 默认折叠：这是给懂行的人用的（脚本 / MCP），绝大多数同学不该被它吸引注意力
         —— 和 WebhookSetting 同一个理由，展开状态也不记住 -->
    <el-collapse v-model="active">
      <el-collapse-item name="tokens">
        <template #title>
          <span class="collapse-title">访问令牌</span>
          <span class="collapse-badge" v-if="activeCount">{{ activeCount }} 个生效中</span>
        </template>

        <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 16px;">
          <template #title>令牌等同于你的账号，不要外传</template>
          它是给脚本、MCP 这类外部程序用的长期凭据。拿到它的人能以你的身份读数据、提交申请，
          直到令牌过期或被吊销。普通同学不需要用到它。
        </el-alert>

        <el-form :model="form" label-width="100px" :disabled="busy">
          <el-form-item label="备注名">
            <el-input
              v-model="form.name"
              maxlength="50"
              placeholder="例如：我的记账脚本"
              clearable
            />
          </el-form-item>
          <el-form-item label="有效期">
            <el-select v-model="form.days" style="width: 160px;">
              <el-option
                v-for="opt in DAY_OPTIONS"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="登录密码">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              placeholder="输入当前登录密码"
              @keyup.enter="handleCreate"
            />
          </el-form-item>
        </el-form>

        <div class="actions">
          <el-button
            type="primary"
            size="small"
            :loading="creating"
            :disabled="atLimit"
            @click="handleCreate"
          >
            创建令牌
          </el-button>
          <span v-if="atLimit" class="desc">
            最多同时持有 {{ maxCount }} 个生效中的令牌，请先吊销不用的
          </span>
        </div>

        <div class="list-title">我的令牌</div>
        <el-table v-loading="loading" :data="items" size="small" stripe border style="width: 100%;">
          <el-table-column prop="name" label="备注名" min-width="120" show-overflow-tooltip />
          <el-table-column label="前缀" width="160" align="center">
            <template #default="{ row }">
              <!-- 列表里永远看不到明文和摘要，只能靠这一小段前缀认出是哪把 -->
              <span class="mono">{{ row.prefix }}…</span>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="150" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="过期时间" width="150" align="center">
            <template #default="{ row }">
              <span v-if="!row.expires_at">不限期</span>
              <span v-else :class="{ expired: isExpired(row) }">
                {{ formatDateTime(row.expires_at) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="最后使用" width="150" align="center">
            <template #default="{ row }">
              <span v-if="row.last_used_at">{{ formatDateTime(row.last_used_at) }}</span>
              <span v-else class="dim">从未使用</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="statusOf(row).type" size="small">{{ statusOf(row).text }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button
                v-if="!row.revoked_at"
                link
                type="danger"
                size="small"
                @click="handleRevoke(row)"
              >
                吊销
              </el-button>
              <span v-else class="dim">—</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty
          v-if="!loading && !items.length"
          description="还没有创建过令牌"
          :image-size="60"
        />
      </el-collapse-item>
    </el-collapse>

    <!--
      一次性明文。刻意把「点遮罩关」「按 Esc 关」「右上角 ×」三个出口全堵死：
      这是唯一一次能看到明文的机会，误触关掉就真没了（库里只存摘要）。
    -->
    <el-dialog
      v-model="showToken"
      title="请立刻复制这串令牌"
      width="560px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="false"
      append-to-body
    >
      <el-alert type="error" :closable="false" show-icon style="margin-bottom: 12px;">
        <template #title>这串令牌只显示这一次</template>
        关掉这个框之后就再也看不到了，丢了只能吊销后重建。
      </el-alert>
      <div v-if="created.name" class="token-name">备注名：{{ created.name }}</div>
      <div class="token-box">{{ created.token }}</div>
      <template #footer>
        <el-button type="primary" @click="copyText(created.token)">复制</el-button>
        <el-button @click="showToken = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createAccessToken, getAccessTokens, revokeAccessToken } from '@/api/auth'
import { copyText } from '@/utils/clipboard'
import { formatDateTime } from '@/utils/format'

// 取值要和后端对上：天数档位见 schemas/auth.py 的 AccessTokenCreate.check_days，
// 上限见 api/auth.py 的 MAX_ACCESS_TOKENS。两处不一致会出现「页面能选、接口报错」
const DAY_OPTIONS = [
  { label: '30 天', value: 30 },
  { label: '90 天', value: 90 },
  { label: '1 年', value: 365 },
  { label: '不限期', value: 0 }
]

const active = ref([])
const items = ref([])
const maxCount = ref(10)
const loading = ref(false)
const creating = ref(false)
const busy = ref(false)
const showToken = ref(false)
// 刚创建出来的明文，只在这一处存着，关掉弹框就不再有引用
const created = reactive({ name: '', token: '' })
const form = reactive({ name: '', days: 90, password: '' })

// 后端返回的是不带时区的本地时间字符串，new Date() 也按本地解析，两边口径一致
function isExpired(row) {
  return !!row.expires_at && new Date(row.expires_at) < new Date()
}

const activeCount = computed(
  () => items.value.filter((r) => !r.revoked_at && !isExpired(r)).length
)
const atLimit = computed(() => activeCount.value >= maxCount.value)

function statusOf(row) {
  if (row.revoked_at) return { text: '已吊销', type: 'info' }
  if (isExpired(row)) return { text: '已过期', type: 'warning' }
  return { text: '生效中', type: 'success' }
}

async function load() {
  loading.value = true
  try {
    const data = await getAccessTokens()
    items.value = data.items || []
    maxCount.value = data.max_count || 10
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取令牌列表失败')
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写备注名')
    return
  }
  if (!form.password) {
    ElMessage.warning('请输入登录密码')
    return
  }
  creating.value = true
  busy.value = true
  try {
    const res = await createAccessToken({
      name: form.name.trim(),
      days: form.days,
      password: form.password
    })
    created.name = res.name
    created.token = res.token
    showToken.value = true
    // 密码用完即弃，不留在内存里
    form.password = ''
    form.name = ''
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
    busy.value = false
  }
}

async function handleRevoke(row) {
  try {
    await ElMessageBox.confirm(
      `吊销后，正在用这把令牌的程序会立刻失效。确定吊销「${row.name}」吗？`,
      '吊销令牌',
      { type: 'warning', confirmButtonText: '吊销', cancelButtonText: '取消' }
    )
  } catch {
    return // 点了取消
  }
  try {
    await revokeAccessToken(row.id)
    ElMessage.success('已吊销')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '吊销失败')
  }
}

onMounted(load)
</script>

<style scoped>
/* 父组件 MyInfo.vue 的样式是 scoped 的，跨组件不生效，所以这里自带一份
   （同 WebhookSetting.vue 那份注释的由来） */
.collapse-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.collapse-badge {
  margin-left: 8px;
  padding: 1px 8px;
  border-radius: 10px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 12px;
  font-weight: 400;
}

.desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.list-title {
  margin: 20px 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0 0 0;
}

.mono {
  font-family: monospace;
  font-size: 12px;
}

.dim {
  color: var(--el-text-color-disabled);
}

.expired {
  color: var(--el-color-danger);
}

.token-name {
  margin-bottom: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

/* 可选中：万一复制按钮没生效，用户还能自己划选 */
.token-box {
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-family: monospace;
  font-size: 13px;
  word-break: break-all;
  line-height: 1.6;
  user-select: all;
}
</style>
