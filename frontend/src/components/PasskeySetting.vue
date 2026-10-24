<template>
  <div class="channel-block">
    <!-- 和访问令牌一样默认折叠：普通同学用密码登录就够了，
         通行密钥是给有条件的设备准备的，不该占满整个页面 -->
    <el-collapse v-model="active">
      <el-collapse-item name="passkeys">
        <template #title>
          <span class="collapse-title">通行密钥</span>
          <span class="collapse-badge" v-if="items.length">{{ items.length }} 把</span>
        </template>

        <template v-if="supported">
          <p class="desc">
            用手机指纹、面容或电脑的 Windows Hello 直接登录，不用再输密码。
            钥匙存在你自己的设备里，服务器只保存公钥；密码始终有效，钥匙丢了也能用密码进来。
          </p>

          <el-form :model="form" label-width="100px" :disabled="busy">
            <el-form-item label="备注名">
              <el-input
                v-model="form.label"
                maxlength="50"
                placeholder="例如：我的 iPhone"
                clearable
              />
            </el-form-item>
            <el-form-item label="登录密码">
              <el-input
                v-model="form.password"
                type="password"
                show-password
                placeholder="输入当前登录密码"
                @keyup.enter="handleRegister"
              />
            </el-form-item>
          </el-form>

          <div class="actions">
            <el-button
              type="primary"
              size="small"
              :loading="registering"
              :disabled="atLimit"
              @click="handleRegister"
            >
              添加通行密钥
            </el-button>
            <span v-if="atLimit" class="desc">
              最多登记 {{ maxCount }} 把，请先删掉不用的
            </span>
          </div>
        </template>

        <!-- 不支持的浏览器（或 HTTP 访问）仍然能看到已有钥匙并删除，
             只是不能再添加新的 -->
        <el-alert v-else type="info" :closable="false" show-icon style="margin-bottom: 12px;">
          <template #title>当前浏览器不支持通行密钥</template>
          需要较新的 Chrome / Edge / Safari，并且通过 HTTPS 访问。
        </el-alert>

        <div class="list-title">我的通行密钥</div>
        <el-table v-loading="loading" :data="items" size="small" stripe border style="width: 100%;">
          <el-table-column label="备注名" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ row.label || '未命名' }}</template>
          </el-table-column>
          <el-table-column label="类型" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="row.backed_up ? 'success' : 'info'" size="small">
                {{ row.backed_up ? '已同步' : '仅本机' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="添加时间" width="150" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="最后使用" width="150" align="center">
            <template #default="{ row }">
              <span v-if="row.last_used_at">{{ formatDateTime(row.last_used_at) }}</span>
              <span v-else class="dim">从未使用</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button link type="danger" size="small" @click="handleDelete(row)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty
          v-if="!loading && !items.length"
          description="还没有添加过通行密钥"
          :image-size="60"
        />
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deletePasskey,
  getPasskeys,
  getPasskeyRegisterOptions,
  verifyPasskeyRegistration
} from '@/api/auth'
import { createPasskey, isPasskeySupported } from '@/utils/passkey'
import { formatDateTime } from '@/utils/format'

// 上限要和后端 api/passkeys.py 的 MAX_PASSKEYS 对上
const FALLBACK_MAX = 10

const active = ref([])
const supported = ref(false)
const items = ref([])
const maxCount = ref(FALLBACK_MAX)
const loading = ref(false)
const registering = ref(false)
const busy = ref(false)
const form = reactive({ label: '', password: '' })

const atLimit = computed(() => items.value.length >= maxCount.value)

async function load() {
  loading.value = true
  try {
    const data = await getPasskeys()
    items.value = data.items || []
    maxCount.value = data.max_count || FALLBACK_MAX
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取通行密钥失败')
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  if (!form.label.trim()) {
    ElMessage.warning('给这把钥匙起个名字，方便以后认出来')
    return
  }
  if (!form.password) {
    ElMessage.warning('请输入登录密码')
    return
  }
  registering.value = true
  busy.value = true
  try {
    const payload = { label: form.label.trim(), password: form.password }
    // 第一步：拿选项（含一次性挑战），第二步：浏览器弹系统验证框，
    // 第三步：把结果交回服务器验签。密码在第三步还要再传一次，验完就清掉
    const options = await getPasskeyRegisterOptions(payload)
    const credential = await createPasskey(options)
    await verifyPasskeyRegistration({ ...payload, credential })
    ElMessage.success('已添加，下次登录可以不再输密码')
    form.label = ''
    await load()
  } catch (e) {
    if (e?.name === 'NotAllowedError') {
      ElMessage.info('已取消')
    } else if (e?.name === 'InvalidStateError') {
      // 浏览器发现这把钥匙在这个账号名下已经登记过
      ElMessage.warning('这台设备已经添加过本账号的通行密钥')
    } else {
      ElMessage.error(e?.response?.data?.detail || '添加失败，请重试')
    }
  } finally {
    // 无论成败都不留在内存里
    form.password = ''
    registering.value = false
    busy.value = false
  }
}

async function handleDelete(row) {
  const name = row.label || '未命名'
  try {
    await ElMessageBox.confirm(
      `删除后这把钥匙就不能再用来登录了，密码仍然可以登录。确定删除「${name}」吗？`,
      '删除通行密钥',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return // 点了取消
  }
  try {
    await deletePasskey(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

onMounted(() => {
  supported.value = isPasskeySupported()
  load()
})
</script>

<style scoped>
/* 父组件 MyInfo.vue 的样式是 scoped 的，跨组件不生效，所以这里自带一份 */
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
  line-height: 1.6;
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
  margin: 12px 0 0;
}

.dim {
  color: var(--el-text-color-disabled);
}
</style>
