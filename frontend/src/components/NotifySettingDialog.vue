<template>
  <!-- 通知设置：两个渠道合并成一个入口，上半部分是浏览器通知，下半部分是 Bark -->
  <el-dialog
    v-model="visible"
    title="通知设置"
    width="520px"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <!-- 安装到桌面：Chrome/Edge/Android 能触发原生安装横幅，iOS 没有 -->
    <el-alert
      v-if="!standalone && canInstall"
      type="success"
      :closable="false"
      show-icon
      style="margin-bottom: 16px;"
    >
      <template #title>把这个应用装到桌面</template>
      <div class="install-row">
        <span>装进桌面后像原生应用一样打开，全屏显示，没有地址栏。</span>
        <el-button type="primary" size="small" :loading="installing" @click="handleInstall">
          安装应用
        </el-button>
      </div>
    </el-alert>

    <!-- ==================== 浏览器通知 ==================== -->
    <div class="section-title">浏览器通知</div>
    <div class="section-sub">用本机浏览器直接收，不用装任何东西</div>

    <!-- 不支持 / 环境限制 -->
    <el-alert v-if="webState === 'blocked'" type="warning" :closable="false" show-icon>
      <template #title>当前环境用不了浏览器通知</template>
      {{ webNote }}
    </el-alert>

    <!-- iPhone：普通标签页里连权限弹窗都弹不出来，必须先添加到主屏 -->
    <el-alert v-else-if="webState === 'ios-tab'" type="info" :closable="false" show-icon>
      <template #title>iPhone 上需要先「添加到主屏」</template>
      在 Safari 里点底部的分享按钮 →「添加到主屏」，然后<b>从主屏图标打开</b>本应用，
      再回到这里开启通知。普通标签页里收不到网页通知，这是 iOS 的限制。
    </el-alert>

    <!-- 浏览器记住了「不允许」 -->
    <el-alert v-else-if="webState === 'denied'" type="warning" :closable="false" show-icon>
      <template #title>本站的通知被浏览器拒绝了</template>
      点地址栏左侧的站点设置，把「通知」改回「允许」，然后重新开启。
    </el-alert>

    <template v-else>
      <div class="status-row">
        <el-tag v-if="webState === 'on'" type="success" size="small">已开启</el-tag>
        <el-tag v-else type="info" size="small">未开启</el-tag>
        <span class="desc">
          {{ webState === 'on' ? '本机浏览器已订阅' : '开启后本机能收到站内通知' }}
        </span>
      </div>

      <div v-if="webCount > 0" class="desc count">
        本账号共有 {{ webCount }} 台设备已开启浏览器通知
      </div>

      <div class="actions">
        <el-button
          v-if="webState === 'off'"
          type="primary"
          size="small"
          :loading="webBusy"
          @click="handleWebEnable"
        >
          开启通知
        </el-button>
        <template v-else>
          <el-button size="small" :loading="webTesting" @click="handleWebTest">
            发送测试
          </el-button>
          <el-button size="small" :loading="webBusy" @click="handleWebDisable">
            关闭通知
          </el-button>
        </template>
      </div>
    </template>

    <el-divider />

    <!-- ==================== Bark 推送 ==================== -->
    <div class="section-title">Bark 推送</div>
    <div class="section-sub">手机上装 Bark App，填一个设备 ID 就能收</div>

    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px;">
      <template #title>怎么拿到设备 ID</template>
      在手机上装好 Bark App，打开后首页显示的那串字符就是设备 ID。
      复制粘贴到下面即可（粘整条链接也行，会自动识别）。
    </el-alert>

    <el-form :model="form" label-width="80px">
      <el-form-item label="设备 ID">
        <el-input
          v-model="form.bark_key"
          placeholder="留空并保存 = 关闭推送"
          clearable
          @keyup.enter="handleSave"
        />
      </el-form-item>
    </el-form>

    <!-- 校徽就是推送通知里显示的图标，让用户提前看到长什么样。
         浏览器能看到不代表手机能看到，所以措辞上不把话说死 -->
    <div v-if="iconUrl" class="icon-preview">
      <img :src="iconUrl" alt="校徽" />
      <span>通知里的头像就是这枚校徽（以手机实际收到为准）</span>
    </div>

    <div class="hint">
      <div class="hint-title">会推到手机的情况</div>
      <ul>
        <li>自己的请假、信息修改有了审核结果 —— <b>时效性通知</b>，能穿透专注模式</li>
        <li>有新的请假、信息修改等自己审核 —— <b>时效性通知</b></li>
        <li>发布了新通知、上传了新公告 —— 普通通知</li>
      </ul>
      <div class="hint-note">
        没填设备 ID 就不会收到任何推送，站内功能照常使用。
        若手机开了专注模式或关掉了本应用的通知权限，通知可能不显示提醒。
      </div>
    </div>

    <div class="actions">
      <el-button size="small" :loading="testing" @click="handleTest">发送测试推送</el-button>
      <el-button type="primary" size="small" :loading="saving" @click="handleSave">保存</el-button>
      <el-button v-if="savedKey" link type="danger" size="small" @click="handleUnbind">
        解除绑定
      </el-button>
    </div>

    <div class="hint-note footnote">
      两个渠道都开着的话，同一台设备会收到两条通知（浏览器一条、Bark 一条）。
      只想要其中一种，把另一种关掉即可。
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { getBarkSetting, saveBarkSetting, testBarkPush } from '@/api/bark'
import {
  getWebpushState,
  saveWebpushSubscription,
  removeWebpushSubscription,
  testWebpush
} from '@/api/webpush'
import {
  isSupported,
  isIos,
  isStandalone as checkIsStandalone,
  canInstall as checkCanInstall,
  triggerInstallPrompt,
  currentSubscription,
  subscribe,
  unsubscribe
} from '@/utils/webpush'

const visible = ref(false)
const installing = ref(false)
// 是否已经装好了（独立应用模式运行）
const standalone = ref(false)
// 能不能弹安装提示
const canInstall = ref(false)

async function handleInstall() {
  installing.value = true
  try {
    const ok = await triggerInstallPrompt()
    if (ok) {
      ElMessage.success('已添加到桌面')
      canInstall.value = false
    }
  } catch (e) {
    ElMessage.error('安装失败')
  } finally {
    installing.value = false
  }
}

// ---------- 浏览器通知 ----------
// off=未开启 · on=已开启 · denied=浏览器拒绝 · ios-tab=需先添加到主屏 · blocked=环境不支持
const webState = ref('off')
const webNote = ref('')
const webBusy = ref(false)
const webTesting = ref(false)
// 服务端记的「本账号有几台设备订阅了」，仅供参考
const webCount = ref(0)
// 订阅用的公钥，打开弹窗时就取好：点「开启」的那一刻不能再等网络
const vapidKey = ref('')

// ---------- Bark ----------
const saving = ref(false)
const testing = ref(false)
// 服务端已保存的 key：用来决定要不要显示「解除绑定」
const savedKey = ref('')
const iconUrl = ref('')
const form = reactive({ bark_key: '' })

// 与后端 auth.py 的 _BARK_KEY_PATTERN 保持一致，先在本地拦一道给出即时提示
const KEY_PATTERN = /^[A-Za-z0-9_-]{5,128}$/

/**
 * 把用户粘进来的各种形式削成纯设备 ID
 *
 * 和后端 auth.py 的 _clean_bark_key 是同一套规则：Bark App 首页的「复制」
 * 给出的是整条链接（https://api.day.app/xxxx/），用户多半直接粘过来。
 * 前端必须先削再校验，否则上面那条 PATTERN 会把正常用户拦在门外，
 * 后端的归一化根本没机会生效。
 */
function cleanKey(raw) {
  let text = (raw || '').trim()
  if (text.includes('://')) {
    text = text.split('://')[1]
    text = text.includes('/') ? text.split('/')[1] : ''
  }
  return text.split('/')[0].split('?')[0].trim()
}

/** 判断浏览器通知当前处于哪种状态（纯本地判断 + 读一次已有订阅） */
async function refreshWebState() {
  if (!isSupported()) {
    webState.value = 'blocked'
    webNote.value = '这个浏览器没有提供网页通知能力，可以改用下面的 Bark 推送，或换 Chrome / Edge / Safari 打开本站。'
    return
  }
  // iOS 的普通标签页里就算对象都在也不能用，先按「需添加到主屏」引导
  if (isIos() && !checkIsStandalone()) {
    webState.value = 'ios-tab'
    return
  }
  if (Notification.permission === 'denied') {
    webState.value = 'denied'
    return
  }
  try {
    webState.value = (await currentSubscription()) ? 'on' : 'off'
  } catch (e) {
    // 非安全上下文（http 或局域网 IP）注册不了 Service Worker，
    // 但 serviceWorker / Notification 这些对象在那种页面里照样存在，
    // 所以只能在这里兜住，给出比「网络错误」有用的提示
    webState.value = 'blocked'
    webNote.value = '浏览器通知要求以 HTTPS 打开本站，用 http 或局域网 IP 访问时用不了。'
  }
}

/** 读服务端记录：公钥 + 本账号订阅数；顺便修一次不一致的账 */
async function loadServerState() {
  const data = await getWebpushState()
  vapidKey.value = data.vapid_public_key || ''
  webCount.value = data.count || 0

  // 对账：本机明明有订阅，服务端却一条都没有 —— 多半是数据重置过，
  // 或换了账号后改绑没成功。既然订阅信息就在手边，顺手补登记一次。
  const sub = await currentSubscription().catch(() => null)
  if (sub && webCount.value === 0) {
    await saveWebpushSubscription(sub.toJSON())
    webCount.value = 1
  }
}

async function open() {
  reset()
  visible.value = true

  // 每次打开弹窗时重新检查：deferredPrompt 可能在页面加载后才触发
  standalone.value = checkIsStandalone()
  canInstall.value = checkCanInstall()

  try {
    await refreshWebState()
    await loadServerState()
  } catch (e) {
    // 读不到状态不影响「关闭本机订阅」这件事，只提示一下
    ElMessage.error(e?.response?.data?.detail || '读取通知状态失败')
  }

  try {
    const data = await getBarkSetting()
    savedKey.value = data.bark_key || ''
    // 没配 public_base_url 时后端返回 null，这里就不显示预览
    iconUrl.value = data.icon_url || ''
    form.bark_key = savedKey.value
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取设置失败')
  }
}

function reset() {
  webState.value = 'off'
  webNote.value = ''
  webCount.value = 0
  vapidKey.value = ''
  form.bark_key = ''
  savedKey.value = ''
  iconUrl.value = ''
}

// ---------- 浏览器通知的几个动作 ----------

async function handleWebEnable() {
  if (!vapidKey.value) return ElMessage.error('还没取到推送公钥，请稍后重试')

  webBusy.value = true
  try {
    // 这中间不能插入任何 await：Safari 要求权限弹窗直接由这次点击触发，
    // 先发一个网络请求再申请就静默失败了（公钥因此是打开弹窗时就取好的）
    const sub = await subscribe(vapidKey.value)
    await saveWebpushSubscription(sub.toJSON())
    await refreshWebState()
    await loadServerState()
    ElMessage.success('已开启，本机会收到浏览器通知')
  } catch (e) {
    await refreshWebState()
    ElMessage.error(e?.response?.data?.detail || e?.message || '开启失败')
  } finally {
    webBusy.value = false
  }
}

async function handleWebDisable() {
  webBusy.value = true
  try {
    const sub = await currentSubscription()
    if (sub) {
      // 顺序很重要：先让服务端删掉这条记录，再解除浏览器订阅。
      // 反过来的话本地已经没有 endpoint 了，服务端那行会永远留着
      await removeWebpushSubscription(sub.endpoint)
      await unsubscribe()
    }
    await refreshWebState()
    await loadServerState()
    ElMessage.success('已关闭浏览器通知')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '操作失败')
  } finally {
    webBusy.value = false
  }
}

async function handleWebTest() {
  webTesting.value = true
  try {
    const res = await testWebpush()
    ElMessage.success(res.message || '已发送，请查看本机通知')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发送失败')
  } finally {
    webTesting.value = false
  }
}

// ---------- Bark 的几个动作 ----------

/** 取出干净的设备 ID 并校验；不合法时提示并返回 null */
function checkedKey() {
  const raw = form.bark_key.trim()
  const key = cleanKey(raw)
  // 填了东西却削不出一段 ID，说明粘错了，不要当成「解绑」静默处理
  if (raw && !key) {
    ElMessage.warning('没能从里面认出设备 ID，请从 Bark App 首页复制')
    return null
  }
  if (key && !KEY_PATTERN.test(key)) {
    ElMessage.warning('设备 ID 格式不对，请从 Bark App 首页完整复制')
    return null
  }
  return key
}

async function handleSave() {
  const key = checkedKey()
  if (key === null) return
  saving.value = true
  try {
    const res = await saveBarkSetting(key)
    savedKey.value = key
    // 回填削好的 ID，让用户看到实际存下来的是什么（粘整条链接时尤其重要）
    form.bark_key = key
    ElMessage.success(res.message || '设置成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

// 先存再测：用户往往刚粘贴一个新 ID，直接测的应该是框里这个。
// 注意服务端只发库里存的 ID，不接受请求体传的，所以必须先 PUT 再 POST
async function handleTest() {
  const key = checkedKey()
  if (key === null) return
  if (!key) return ElMessage.warning('请先填入设备 ID')

  testing.value = true
  try {
    await saveBarkSetting(key)
    savedKey.value = key
    form.bark_key = key
    const res = await testBarkPush()
    ElMessage.success(res.message || '已发送，请查看手机')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '推送失败')
  } finally {
    testing.value = false
  }
}

async function handleUnbind() {
  saving.value = true
  try {
    const res = await saveBarkSetting('')
    savedKey.value = ''
    form.bark_key = ''
    ElMessage.success(res.message || '已解除绑定')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    saving.value = false
  }
}

// 让父组件通过 ref 调用 open()
defineExpose({ open })
</script>

<style scoped>
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.section-sub {
  margin: 2px 0 12px;
  font-size: 12px;
  color: #909399;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.desc {
  font-size: 12px;
  color: #909399;
}

.count {
  margin-bottom: 8px;
}

/* 两个 section 的操作按钮都靠左，跟各自的说明对齐 */
.actions {
  display: flex;
  align-items: center;
  margin: 12px 0 0 90px;
}

/* 校徽预览：和说明文字区分开，一眼看到推送里会显示什么 */
.icon-preview {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 16px 90px;
  font-size: 12px;
  color: #909399;
}

.icon-preview img {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  object-fit: contain;
  border: 1px solid #ebeef5;
  background: #fff;
}

.hint {
  margin: 0 0 8px 90px;
  padding: 10px 12px;
  border-radius: 6px;
  background: #f5f7fa;
  font-size: 12px;
  color: #606266;
  line-height: 1.7;
}

.hint-title {
  font-weight: 600;
  margin-bottom: 2px;
}

.hint ul {
  margin: 0;
  padding-left: 18px;
}

.hint-note {
  color: #909399;
}

.footnote {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #ebeef5;
  line-height: 1.6;
}

/* 安装应用的横幅里的按钮和文字同行 */
.install-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
