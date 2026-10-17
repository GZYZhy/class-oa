<template>
  <el-container class="layout-container">
    <el-header class="layout-header">
      <div class="header-left">
        <!-- 手机上才显示：点开左侧菜单抽屉 -->
        <el-icon class="menu-toggle" @click="drawerOpen = true"><Menu /></el-icon>
        <img src="/logo.png" class="logo-img" alt="校徽" />
        <div class="title-group">
          <span class="app-title">{{ SITE.name }}</span>
          <span class="app-subtitle">{{ SITE.subtitle }}</span>
        </div>
      </div>
      <div class="header-right">
        <span class="class-badge">
          <el-icon><UserFilled /></el-icon>
          共 {{ userStore.totalStudents }} 人
        </span>

        <!-- 已登录：头像 + 姓名，点击跳转到账户设置 -->
        <div v-if="userStore.isLogin" class="user-box" @click="router.push('/my-info?tab=account')">
          <el-avatar :size="34" :src="userStore.info.avatar || ''" class="user-avatar">
            {{ userStore.initial }}
          </el-avatar>
          <span class="user-name">{{ userStore.info.name }}</span>
        </div>

        <el-button v-else type="primary" plain size="small" @click="router.push('/login')">
          登录
        </el-button>
      </div>
    </el-header>

    <el-container>
      <el-aside width="220px" class="layout-aside" :class="{ 'is-open': drawerOpen }">
        <div class="aside-inner">
          <el-menu
            :default-active="activeMenu"
            router
            class="side-menu"
            background-color="#1f2d3d"
            text-color="#bfcbd9"
            active-text-color="#409EFF"
            @select="drawerOpen = false"
          >
            <!-- 首页不归组，单独摆最上面 -->
            <el-menu-item :index="HOME.path">
              <el-icon><component :is="HOME.icon" /></el-icon>
              <span>{{ HOME.title }}</span>
            </el-menu-item>

            <el-menu-item-group v-for="group in visibleGroups" :key="group.title" :title="group.title">
              <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.title }}</span>
                <span v-if="badgeOf(item)" class="menu-item-badge">{{ badgeOf(item) }}</span>
              </el-menu-item>
            </el-menu-item-group>
          </el-menu>

          <!-- 底部：已登录时显示退出登录 -->
          <div v-if="userStore.isLogin" class="aside-footer">
            <div class="logout-item" @click="handleLogout">
              <el-icon><SwitchButton /></el-icon>
              <span>退出登录</span>
            </div>
          </div>
        </div>
      </el-aside>

      <!-- 手机上菜单展开时的遮罩，点一下收起（桌面端永远不显示） -->
      <div v-if="drawerOpen" class="aside-mask" @click="drawerOpen = false"></div>

      <el-main class="layout-main">
        <router-view />
      </el-main>
    </el-container>

    <!-- 版权脚栏：所有登录后的页面都带，登录页是整屏布局、没有脚栏。
         内容是 HTML（.env 的 SITE_FOOTER，运维自己写，可以放链接），所以用 v-html；
         包一层 span 是因为 v-html 写在组件上会作用到它的根元素，容易踩坑 -->
    <el-footer class="layout-footer">
      <span v-html="COPYRIGHT_HTML"></span>
    </el-footer>

    <!-- 首次登录强制设置密码：不允许关闭 -->
    <!-- 此时用户刚用默认密码登录过一遍，因此不再要求输入原密码 -->
    <el-dialog
      v-model="pwdVisible"
      title="首次登录，请设置新密码"
      width="420px"
      :show-close="false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
    >
      <el-alert
        title="当前使用的是默认密码（身份证号后6位），为保障信息安全，请先设置新密码。"
        type="warning"
        :closable="false"
        style="margin-bottom: 16px;"
      />
      <el-form :model="pwdForm" label-width="90px">
        <el-form-item label="新密码">
          <el-input
            v-model="pwdForm.new_password"
            type="password"
            show-password
            placeholder="6-32 位，需同时包含字母和数字"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="pwdForm.confirm" type="password" show-password @keyup.enter="handleSetInitialPassword" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="primary" :loading="pwdLoading" @click="handleSetInitialPassword">
          确认设置
        </el-button>
      </template>
    </el-dialog>

    <!-- iOS 装到主屏的引导：进站 3 秒后自己升起，不需要 ref。
         ⚠️ 必须留在 el-container 内部：它 v-else 掉的就是登录页，
         这样才有「登录之后才弹」。挪到外面登录页也会弹。 -->
    <IosInstallGuide />
  </el-container>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { setInitialPassword } from '@/api/auth'
import IosInstallGuide from '@/components/IosInstallGuide.vue'
import { useUserStore } from '@/store/user'
import { useBadgeStore } from '@/store/badge'
import { canSee } from '@/utils/roles'
import { SITE, COPYRIGHT_HTML } from '@/utils/site'

/**
 * 登录后的整站布局（顶栏 + 侧边菜单 + 主区 + 脚栏）
 *
 * 单独拆成一个组件、由 App.vue 按需加载：签到页和登录页都是整屏布局
 * （meta.bare），不用为它们下载菜单、对话框这一整套。弱网下这点差别很实在。
 */
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const badgeStore = useBadgeStore()

const activeMenu = computed(() => route.path)

// 手机端的菜单抽屉：桌面端侧边栏常驻，这个开关不起作用
const drawerOpen = ref(false)

// 换页时顺手把红点重算一次（一次 COUNT 查询的代价），同时收起手机端抽屉
watch(() => route.path, () => {
  drawerOpen.value = false
  if (userStore.isLogin && !userStore.isBootstrap) badgeStore.refresh()
})

// 首页不归组，单独拎出来，模板里直接渲染（它游客也看得见，摆最上面）
const HOME = { path: '/dashboard', title: '首页', icon: 'HomeFilled', public: true }

// 侧边菜单，**按组排**：15 项平铺时一眼看不出哪些是自己的、哪些是管理的，
// 分组标题就是给这件事用的。组的先后 = 从「我的」到「管理」，越往下管得越宽。
//
// 组名只影响显示，不参与权限判断；组内可见项一个都没有时整组连标题一起不渲染
// （比如游客只看得到「班级事务」里的通知公告，其余三组直接不出现）。
//
// 单项字段：role = 可见的最低角色，不写则登录即可见；public = 未登录也可见；
// studentOnly = 只有学生账号可见（域外账号没有学生记录，这些页面用不了）；
// badge = 右上角红点取哪个计数，键名对应后端 /api/badges 的返回字段。
// 和 router 的 meta 保持一致（那里是防手敲地址，这里是控制显示）
const MENU_GROUPS = [
  {
    title: '我的',
    items: [
      { path: '/my-info', title: '我的信息', icon: 'UserFilled', studentOnly: true },
      { path: '/schedule', title: '我的日程', icon: 'Calendar', studentOnly: true },
      { path: '/inbox', title: '我的消息', icon: 'Message', badge: 'inbox_unread' },
      { path: '/downloads', title: '资料下载', icon: 'Download' },
      { path: '/about', title: '关于班级', icon: 'InfoFilled' }
    ]
  },
  {
    title: '班级事务',
    items: [
      { path: '/notices', title: '通知公告', icon: 'Bell', public: true, badge: 'notice_unread' },
      { path: '/vote', title: '投票表决', icon: 'Tickets' },
      { path: '/announcements', title: '文件公开', icon: 'Files' },
      { path: '/service', title: '办事中心', icon: 'Postcard', studentOnly: true }
    ]
  },
  {
    title: '班级管理',
    items: [
      { path: '/students', title: '学生信息', icon: 'List', role: 'committee' },
      { path: '/statistics', title: '分类统计', icon: 'PieChart', role: 'committee' },
      { path: '/attendance', title: '考勤记录', icon: 'Calendar', role: 'committee' },
      { path: '/grades', title: '成绩管理', icon: 'Histogram', role: 'committee' },
      { path: '/review', title: '审核审批', icon: 'Checked', role: 'committee', badge: 'review_pending' }
    ]
  },
  {
    title: '系统管理',
    items: [
      { path: '/admin', title: '系统管理', icon: 'Setting', role: 'admin' }
    ]
  }
]

/** 菜单项右上角要显示的红点文字；不显示时返回空串
 *
 * 未登录一律不显示（游客逛通知公告时不该被提示有未读），
 * 0 也不显示，超过 99 收成 99+ 免得把菜单项撑变形。
 */
function badgeOf(item) {
  if (!item.badge || !userStore.isLogin) return ''
  const count = badgeStore.counts[item.badge] || 0
  if (!count) return ''
  return count > 99 ? '99+' : String(count)
}

// 先按账号过滤组内各项，再把空组整个丢掉（连标题一起）。
// 判据本体在 utils/roles.js —— 首页的快捷入口用的是同一份
const visibleGroups = computed(() =>
  MENU_GROUPS
    .map((group) => ({
      title: group.title,
      items: group.items.filter((item) => canSee(item, userStore))
    }))
    .filter((group) => group.items.length > 0)
)

// 首次登录强制设置密码
const pwdVisible = ref(false)
const pwdLoading = ref(false)
const pwdForm = reactive({ new_password: '', confirm: '' })

// 登录用户带 must_change_password 标记时，自动弹出设置密码
watch(
  () => userStore.info?.must_change_password,
  (need) => {
    if (need) {
      pwdForm.new_password = ''
      pwdForm.confirm = ''
      pwdVisible.value = true
    }
  },
  { immediate: true }
)

// 首次设置密码：不校验原密码（用户刚用它登录过）
async function handleSetInitialPassword() {
  if (pwdForm.new_password.length < 6 || pwdForm.new_password.length > 32) {
    return ElMessage.warning('新密码长度需为 6-32 位')
  }
  if (!/[A-Za-z]/.test(pwdForm.new_password) || !/\d/.test(pwdForm.new_password)) {
    return ElMessage.warning('新密码必须同时包含字母和数字')
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    return ElMessage.warning('两次输入的新密码不一致')
  }

  pwdLoading.value = true
  try {
    await setInitialPassword({ new_password: pwdForm.new_password })
    userStore.markPasswordChanged()
    pwdVisible.value = false
    ElMessage.success('密码设置成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '设置失败')
  } finally {
    pwdLoading.value = false
  }
}

async function handleLogout() {
  drawerOpen.value = false
  try {
    await ElMessageBox.confirm('确定退出登录吗？', '退出确认', { type: 'warning' })
  } catch (e) {
    return // 取消
  }
  await userStore.logout()
  ElMessage.success('已退出登录')
  router.push('/dashboard')
}

onMounted(async () => {
  // 「首页」「通知公告」是免登录页面，路由守卫走到它们就直接放行、
  // 不会去问后端登录状态，右上角会错显示成「登录」按钮。
  // 这里统一确认一次（未登录时后端返回 401，store 里会吞掉）
  if (!userStore.resolved) await userStore.fetchMe()

  // 班级人数取自公开摘要，未登录也能正常显示。
  // 增删学生之后由学生名单页再调一次 store 里的 refreshTotal()
  await userStore.refreshTotal()
})
</script>

<style scoped>
.layout-container {
  height: 100vh;
  /* dvh 会随手机浏览器地址栏的收放变化，避免底部被地址栏压掉一截 */
  height: 100dvh;
}

/* 汉堡按钮：只在手机上出现（见文件末尾的媒体查询） */
.menu-toggle {
  display: none;
  font-size: 22px;
  color: #fff;
  cursor: pointer;
}

/* 手机端抽屉展开时的遮罩，桌面端不显示 */
.aside-mask {
  display: none;
}

.layout-header {
  background: linear-gradient(90deg, #1f2d3d 0%, #2c3e50 50%, #1f2d3d 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 30px;
  box-shadow: 0 2px 8px rgba(0, 21, 41, 0.15);
  z-index: 10;
  height: 64px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.logo-img {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid rgba(64, 158, 255, 0.5);
  /* 固定白色，不跟深色模式：顶栏是写死的深色，这层白底是给校徽图片垫的衬底，
     翻成深色的话校徽自己反倒糊在底上了 */
  background: #fff;
  padding: 2px;
  box-sizing: border-box;
}

.title-group {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.app-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 1px;
  background: linear-gradient(90deg, #409EFF, #fff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.app-subtitle {
  font-size: 12px;
  color: #8492a6;
  margin-top: 2px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.class-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #409EFF;
  background: rgba(64, 158, 255, 0.12);
  padding: 6px 14px;
  border-radius: 20px;
  border: 1px solid rgba(64, 158, 255, 0.2);
}

.user-box {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 10px;
  border-radius: 20px;
  transition: background 0.2s;
}

.user-box:hover {
  background: rgba(255, 255, 255, 0.1);
}

.user-avatar {
  background: #409EFF;
  color: #fff;
  font-size: 14px;
}

.user-name {
  font-size: 14px;
  color: #fff;
}

.layout-aside {
  background: #1f2d3d;
  overflow-x: hidden;
}

/* aside 内部纵向布局：菜单占满剩余空间，底部退出登录固定在下方 */
.aside-inner {
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* 高度交给 flex 分配（aside 是 el-container 的行内子项，默认拉伸到满高）。
   原来写的 calc(100vh - 64px) 在加了脚栏之后会比实际可用高度多出一截 */
.side-menu {
  border-right: none;
  flex: 1;
  overflow-y: auto;
}

/* 分组标题：Element 默认是 12px / 行高 36px 的浅灰，摆在深色侧栏上又高又飘。
   压成 11px 小字 + 偏白低透明度，更像一个分区标签；上下留白也收窄，
   四项标题省下的高度够多放一个菜单项 */
.side-menu :deep(.el-menu-item-group__title) {
  padding: 12px 0 4px 20px;
  font-size: 11px;
  line-height: 16px;
  color: rgba(255, 255, 255, 0.38);
  letter-spacing: 0.5px;
}

/* 底部退出登录项，跟菜单项同高同风格 */
.aside-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}

.logout-item {
  height: 50px;
  line-height: 50px;
  padding: 0 20px;
  color: #bfcbd9;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: background 0.2s, color 0.2s;
}

.logout-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}

:deep(.el-menu-item) {
  height: 50px;
  line-height: 50px;
}

:deep(.el-menu-item.is-active) {
  background: rgba(64, 158, 255, 0.1) !important;
  border-left: 3px solid #409EFF;
}

/* 菜单项右端的未读红点。手写一个 span 而不是用 el-badge：el-badge 的小红点节点
   在组件内部，scoped 样式得写 :deep() 才生效，还得操心它套在图标上会不会
   挤压 50px 的行高。el-menu-item 本身是 display:flex，margin-left:auto
   就能把这个 span 推到最右端 */
.menu-item-badge {
  margin-left: auto;
  flex-shrink: 0;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  box-sizing: border-box;
  border-radius: 9px;
  background: #f56c6c;
  color: #fff;
  font-size: 12px;
  line-height: 18px;
  text-align: center;
}

.layout-main {
  background: var(--el-bg-color-page);
  padding: 20px;
  overflow-y: auto;
}

/* 版权脚栏。高度写 auto：el-footer 默认 60px，中文一行放得下，
   压到 60px 反而把外层容器撑高、把主区挤出一截滚动条 */
.layout-footer {
  height: auto;
  padding: 10px 12px;
  text-align: center;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-lighter);
  flex-shrink: 0;
}

/* ============ 手机适配（≤768px）============
   侧边栏改成从左侧滑出的抽屉，靠汉堡按钮开关；
   头部只留必要信息，标题过长时省略号截断，不把头像挤出去。 */
@media (max-width: 768px) {
  .layout-header {
    padding: 0 12px;
    gap: 8px;
  }

  .menu-toggle {
    display: block;
    flex-shrink: 0;
  }

  .header-left {
    gap: 10px;
    min-width: 0;
  }

  .header-right {
    gap: 8px;
    flex-shrink: 0;
  }

  .logo-img {
    width: 34px;
    height: 34px;
    flex-shrink: 0;
  }

  .app-title {
    font-size: 15px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* 副标题和班级人数在手机上让位给标题，学生名单页里有更详细的统计 */
  .app-subtitle,
  .class-badge {
    display: none;
  }

  .layout-aside {
    position: fixed;
    top: 64px;
    bottom: 0;
    left: 0;
    z-index: 2001;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }

  .layout-aside.is-open {
    transform: translateX(0);
  }

  .aside-mask {
    display: block;
    position: fixed;
    inset: 64px 0 0 0;
    z-index: 2000;
    background: rgba(0, 0, 0, 0.35);
  }

  .layout-main {
    padding: 12px;
  }

  /* 手机上版权那行字小一号、上下留白收紧，少占高度 */
  .layout-footer {
    padding: 8px 6px;
    font-size: 11px;
  }
}

/* 更窄的屏幕（多数手机竖屏）：头像旁的名字也收起来，只留头像 */
@media (max-width: 480px) {
  .user-name {
    display: none;
  }
}
</style>
