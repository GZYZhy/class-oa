<template>
  <!--
    iOS「装到主屏」引导

    为什么要主动弹：iPhone 上 Safari 只有把站点添加到主屏、并从主屏图标启动，
    才允许申请通知权限（见 index.html 顶部的注释）。而这段说明目前只藏在
    「通知设置」弹窗里 —— 没人会主动去点，等于没有。

    这个组件是**自发的**：进站 3 秒后自己升起，不需要父组件调 open()，
    所以不像另外三个 Dialog 那样 defineExpose。挂在 App.vue 的 el-container 里。

    挂载位置有讲究：必须在 App.vue 的 <el-container> **内部**。
    那个容器是 `v-else`（相对的 `v-if` 是 meta.bare 的登录页），所以登录页
    根本不渲染它 —— 这就是「登录之后才弹」的实现方式。
    别为了「登录页也提示一下」把它挪到外面去：链接是发到班级群里的，
    点开先看到的是登录页，在那儿弹安装引导会挤在登录框旁边，
    而且人还没决定要不要用这个系统。等他登进来再说不迟。
    （它同时天然避开了「未登录时刷新会闪一下引导」的问题。）

    Teleport 到 body：卡片是 position:fixed，留在 el-container 的 flex 布局里
    会受 100dvh 约束，提到 body 下最干净。挪挂载位置不影响渲染位置。
  -->
  <Teleport to="body">
    <Transition name="ig-fade">
      <div v-if="visible" class="ig-mask" @click="dismissLater"></div>
    </Transition>

    <Transition name="ig-rise">
      <div v-if="visible" class="ig-sheet" role="dialog" aria-modal="true">
        <div class="ig-grabber"></div>

        <!-- 正路：iOS Safari，给完整三步 -->
        <template v-if="mode === 'sheet'">
          <!-- 用主屏图标本体，而不是 /logo.png —— 让「现在看到的」和
               「待会儿桌面上多出来的那个」形成对应。
               ?v=1 是 PWA 图标的版本串约定（nginx 给 png 打了一年 immutable） -->
          <img class="ig-icon" src="/icons/apple-touch-icon.png?v=1" alt="" />

          <h3 class="ig-title">把「{{ SITE.shortName }}」装到主屏</h3>
          <p class="ig-sub">装好后能收通知，打开也没有地址栏</p>

          <ol class="ig-steps">
            <li class="ig-step">
              <span class="ig-num">1</span>
              <span>点工具栏上的</span>
              <!--
                自绘内联 SVG：Element Plus 的 Share 是「三个点连成线」的通用分享图标，
                不是 iOS 那个「方框 + 向上箭头」。iOS 用户认的是后者，用错了反而让人犯迷糊。
                全项目的图标资源要么是 EP 组件、要么是 <img>，这里是唯一一处内联 SVG。
              -->
              <svg
                class="ig-share"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M12 15V3.5" />
                <path d="M8 7.5l4-4 4 4" />
                <path
                  d="M8 11H5.5A1.5 1.5 0 0 0 4 12.5v7A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5v-7A1.5 1.5 0 0 0 18.5 11H16"
                />
              </svg>
              <span>分享按钮</span>
            </li>
            <!-- 不写「底部」：Safari 的工具栏位置跟着用户的标签栏设置走，写死会错 -->
            <li class="ig-step"><span class="ig-num">2</span><span>选「添加到主屏幕」</span></li>
            <li class="ig-step"><span class="ig-num">3</span><span>点右上角「添加」</span></li>
          </ol>
        </template>

        <!-- 微信等 App 内浏览器、iOS 上的非 Safari：这里根本装不了，别给错步骤 -->
        <template v-else>
          <h3 class="ig-title">用 Safari 打开本页</h3>
          <p class="ig-sub">{{ hintText }}</p>
        </template>

        <div class="ig-actions">
          <!-- 用原生 button 而不是 el-button：iOS 系统弹层的按钮尺寸和圆角
               跟 EP 的一套差得远，套 el-button 要写一堆覆盖样式，不如原生干净 -->
          <button class="ig-primary" @click="dismissLater">我知道了</button>
          <button class="ig-link" @click="dismissNever">不再显示</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { isIos, isIosSafari, isInAppBrowser, isStandalone } from '@/utils/webpush'
import { SITE } from '@/utils/site'

// 「不再显示」= 永久，记 localStorage；「我知道了」= 只压本次会话，记 sessionStorage
const NEVER_KEY = 'oa.iosInstallGuide.never'
const LATER_KEY = 'oa.iosInstallGuide.later'

// 3 秒：让人先看清这站是干什么的，再看到引导。一进来就糊脸最招人烦
const DELAY_MS = 3000

// 被人家的弹窗挡住时的重试节奏。上限 5 分钟：留足时间让人改完初始密码
// （那是必填项，改不动就关不掉），又不至于永远挂着一个定时器
const RETRY_MS = 2000
const MAX_WAIT_MS = 5 * 60 * 1000

const visible = ref(false)
// sheet = 完整三步指引；hint = 只提一句「用 Safari 打开」
const mode = ref('sheet')

const hintText = computed(() =>
  isInAppBrowser()
    ? '点右上角的「···」，选「在浏览器打开」，就能装到主屏了'
    : '复制本页网址，在 Safari 里打开，就能装到主屏了'
)

/**
 * 读写标记。Safari 无痕模式、或用户关掉站点数据时这两个 API 会直接抛异常，
 * 所以一律兜住：读失败当作「没标记」（无非是多提示一次），写失败静默
 * （顶多下次还提示）。绝不能因为一个提示条把整个应用带崩。
 */
function hasFlag(store, key) {
  try {
    return store.getItem(key) === '1'
  } catch (e) {
    return false
  }
}

function setFlag(store, key) {
  try {
    store.setItem(key, '1')
  } catch (e) {
    /* 存不了就算了 */
  }
}

let timer = null

onMounted(() => {
  if (!isIos()) return
  // 已经装好了就别再打扰 —— 从主屏图标进来时走的就是这一条
  if (isStandalone()) return
  if (hasFlag(localStorage, NEVER_KEY)) return
  if (hasFlag(sessionStorage, LATER_KEY)) return

  // 不是 Safari 的（微信内置、iOS 上的 Chrome/Firefox）只能给一句提示
  mode.value = isIosSafari() ? 'sheet' : 'hint'

  const startedAt = Date.now()

  function tryShow() {
    // 有别的浮层开着就让路，过会儿再来。最典型的场景：新生第一次登录用的是
    // 初始密码，App.vue 会立刻自动弹出强制改密框 —— 两张浮层叠在一起太挤。
    //
    // 关键是「等它关掉」而不是「放弃」：这条路径覆盖的是绝大多数新生，
    // 让一次就永久不再提示，等于整个引导白做。所以只要还没超时就一直重试。
    if (document.querySelector('.el-overlay')) {
      if (Date.now() - startedAt < MAX_WAIT_MS) {
        timer = setTimeout(tryShow, RETRY_MS)
      }
      return
    }
    visible.value = true
  }

  timer = setTimeout(tryShow, DELAY_MS)
})

onUnmounted(() => clearTimeout(timer))

function dismissLater() {
  visible.value = false
  setFlag(sessionStorage, LATER_KEY)
}

function dismissNever() {
  visible.value = false
  setFlag(localStorage, NEVER_KEY)
}
</script>

<style scoped>
/* ============ 遮罩 ============
   z-index 取 3000/3001：项目自己的手机端抽屉占了 2000/2001，
   Element Plus 的弹层也从 2000 起自增，往上让开一段最省心 */
.ig-mask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  background: rgba(0, 0, 0, 0.4);
}

/* ============ 底部卡片 ============
   不加 viewport-fit=cover（项目本来也没有）：Safari 会把视口收在
   Home Indicator 之上，bottom:0 的卡片天然不会被挡住。
   真加了 cover 反而要自己处理 safe-area-inset，还会改动全站的视口行为 */
.ig-sheet {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 3001;
  padding: 8px 20px 20px;
  background: var(--el-bg-color);
  border-radius: 14px 14px 0 0;
  box-shadow: 0 -2px 20px rgba(0, 0, 0, 0.12);
  /* 项目的字体栈以 -apple-system 打头，在 iOS 上本来就是 SF，
     不用另外指定字体 */
}

/* 顶部那根下拉条。不做滑动手势（要处理整串 touch 事件，不值），
   它纯粹是让这张卡片看起来像 iOS 从底下抽出来的系统面板 */
.ig-grabber {
  width: 36px;
  height: 5px;
  margin: 0 auto 14px;
  border-radius: 3px;
  background: #c7c7cc;
}

.ig-icon {
  display: block;
  width: 64px;
  height: 64px;
  margin: 0 auto 12px;
  border-radius: 14px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

.ig-title {
  margin: 0 0 4px;
  text-align: center;
  font-size: 18px;
  font-weight: 600;
  color: #1c1c1e;
}

.ig-sub {
  margin: 0 0 18px;
  text-align: center;
  font-size: 13px;
  line-height: 1.5;
  color: #8e8e93;
}

/* ============ 三步 ============
   浅灰底 + 细分隔线，是 iOS「分组列表」的长相 */
.ig-steps {
  margin: 0 0 18px;
  padding: 0;
  list-style: none;
  background: var(--el-fill-color-light);
  border-radius: 12px;
  overflow: hidden;
}

.ig-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  font-size: 15px;
  color: #1c1c1e;
}

.ig-step + .ig-step {
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}

.ig-num {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #007aff;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}

.ig-share {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  color: #007aff;
}

/* ============ 按钮 ============ */
.ig-primary {
  display: block;
  width: 100%;
  padding: 14px;
  border: none;
  border-radius: 12px;
  /* iOS 系统蓝。这里是全项目唯一一处不用主题色 #409EFF 的地方 ——
     模拟系统原生就得用系统色，否则一眼假 */
  background: #007aff;
  color: #fff;
  font-family: inherit;
  font-size: 17px;
  font-weight: 600;
  cursor: pointer;
}

.ig-primary:active {
  background: #0069d9;
}

.ig-link {
  display: block;
  width: 100%;
  margin-top: 8px;
  padding: 8px;
  border: none;
  background: none;
  color: #8e8e93;
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
}

/* ============ 进出场 ============
   项目里没有 <Transition> 先例，但这是 Vue 内置的，比手写
   三阶段 class 切换简单得多。时长沿用项目既有的 0.25s */
.ig-fade-enter-active,
.ig-fade-leave-active {
  transition: opacity 0.25s ease;
}

.ig-fade-enter-from,
.ig-fade-leave-to {
  opacity: 0;
}

/* 缓动是 iOS 面板的经典曲线：起步快、收尾长 */
.ig-rise-enter-active,
.ig-rise-leave-active {
  transition: transform 0.32s cubic-bezier(0.32, 0.72, 0, 1);
}

.ig-rise-enter-from,
.ig-rise-leave-to {
  transform: translateY(100%);
}

/* ============ 深色模式 ============
   这张卡片整个是照 iOS 系统面板画的，卡片底走的是 var(--el-bg-color)（会跟主题变深），
   所以文字也不能再写死 iOS 浅色模式的色值 —— 系统自己就是这么定义的：
   label 浅色是近黑、深色是纯白。下面这些是 iOS 深色模式的对应值。 */
@media (prefers-color-scheme: dark) {
  .ig-grabber {
    background: #48484a;
  }
  .ig-title,
  .ig-step {
    color: #fff;
  }
  .ig-sub,
  .ig-link {
    color: rgba(235, 235, 245, 0.6);
  }
  /* 系统蓝在深色模式下本身就更亮一档 */
  .ig-primary {
    background: #0a84ff;
  }
  .ig-step + .ig-step {
    border-top-color: rgba(255, 255, 255, 0.08);
  }
}
</style>
