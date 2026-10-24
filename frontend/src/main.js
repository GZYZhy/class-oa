import { createApp } from 'vue'
import { createPinia } from 'pinia'

// Element Plus 改成**按需引入**了（构建配置在 vite.config.js 里那个 Components 插件）：
// 模板里真正写到的 <el-xxx> 和 v-loading 由它在打包时挨个引进来，各组件自己的样式、
// 以及提供 --el-* 那批 CSS 变量的 base.css 都会跟着带上。
//
// 所以原来那句 `import 'element-plus/dist/index.css'`（整包 354KB）删掉了 ——
// 以后**加新组件也不用再引样式**，按需插件自己会带。只剩深色主题变量还要手动引：
// 它挂在 .dark 类下，不属于任何一个组件的样式。
import 'element-plus/theme-chalk/dark/css-vars.css'

// 但这三样的样式**必须手动引**：按需插件只认模板里出现的 <el-xxx>，
// 它们要么是函数调用、要么是全局指令，插件看不见。
// 漏掉的后果是「功能在、外观没了」：退出确认框会变成一行裸文字加两个按钮，
// 消息提示也没有底色和定位 —— 只有到生产构建里才看得出来，开发时整包样式兜着。
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/loading/style/css'

// 这三样还要自己装：
//   · ElMessage / ElMessageBox 是当函数调出来的，模板里根本没有对应的标签；
//   · ElLoading 是全局指令 v-loading 的本体。
// 装它们不只是为了「能用」—— 这几个 install 里有一句 fn._context = app._context，
// 把 app 的上下文记下来。弹窗和遮罩是脱离组件树单独渲染的，靠这句话才知道
// 自己属于哪个应用、才拿得到全局配置（正文里的中文文案就是这么来的）。
//
// 另外：包在 exports 里把 'element-plus' 和 'element-plus/es' 指向了同一个文件，
// 所以这里拿到的和按需插件生成的那些 import 是同一个对象，上下文不会两头对不上。
import { ElLoading, ElMessage, ElMessageBox, provideGlobalConfig } from 'element-plus'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

// 图标**按需**引入。原来写的是 `import * as ElementPlusIconsVue` 再循环注册 ——
// 那样打包器的 tree-shaking 会完全失效：图标包 293 个图标整包进首屏产物，
// 而全站真正用到的只有下面这六十来个。弱网下首页等这一份纯属白等。
import {
  Aim, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Avatar, Bell,
  BellFilled, Bottom, Calendar, ChatDotRound, Checked, CircleCheck,
  CopyDocument, Delete, Document, Download, EditPen, Female,
  Files, FolderOpened, Grid, Histogram, HomeFilled, InfoFilled,
  Key, Link, List, Loading, Lock, Male,
  Medal, Menu, Message, Monitor, Moon, MoreFilled, Notification, Paperclip,
  Picture, PieChart, Plus, Pointer, Postcard, Present,
  Refresh, RefreshLeft, RefreshRight, Right, Search, Select, Setting,
  Sort, Star, Sunny, SwitchButton, Tickets, Top, Upload,
  UploadFilled, User, UserFilled, Van, Warning, ZoomIn,
  ZoomOut
} from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import { initTheme } from '@/composables/useTheme'
import './styles/main.css'

// 主题：自动（跟随系统）/ 浅色 / 深色，三档在顶栏那个小按钮里循环切换，
// 选择记在 cookie 里。规则和 cookie 读写在 composables/useTheme.js。
//
// 必须在挂载前先调一次：先把 <html> 的 .dark 定好，否则会先闪一下浅色。
// Element Plus 的深色变量挂在 .dark 类上（不在媒体查询里），项目自己的样式
// 统一用 var(--el-*)，于是这一个类就能带着整站翻。
initTheme()

const app = createApp(App)

// 模板里的 <el-icon><Bell /></el-icon> 靠这份注册；App.vue 侧边菜单、首页快捷入口
// 里 `icon: 'Bell'` 那种字符串最后也走 <component :is>，同样得在这里登记。
//
// **两张表要同步改**：漏登记不会报错，Vue 只在控制台留一句「Failed to resolve
// component」，页面上那个位置就是空的 —— 图标尤其难发现（本来就小）。
// tests/render.mjs 有一节会扫全站用到的图标名，和这份清单逐个对。
const ICONS = {
  Aim, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Avatar, Bell,
  BellFilled, Bottom, Calendar, ChatDotRound, Checked, CircleCheck,
  CopyDocument, Delete, Document, Download, EditPen, Female,
  Files, FolderOpened, Grid, Histogram, HomeFilled, InfoFilled,
  Key, Link, List, Loading, Lock, Male,
  Medal, Menu, Message, Monitor, Moon, MoreFilled, Notification, Paperclip,
  Picture, PieChart, Plus, Pointer, Postcard, Present,
  Refresh, RefreshLeft, RefreshRight, Right, Search, Select, Setting,
  Sort, Star, Sunny, SwitchButton, Tickets, Top, Upload,
  UploadFilled, User, UserFilled, Van, Warning, ZoomIn,
  ZoomOut
}

for (const [key, component] of Object.entries(ICONS)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)

// 上面「自己引、自己装」的那三样
app.use(ElMessage)
app.use(ElMessageBox)
app.use(ElLoading)

// 中文文案。原来是 `app.use(ElementPlus, { locale: zhCn })` 顺手带的，
// 现在改用 config-provider 的公开入口 provideGlobalConfig，它一次管两件事：
//   1）provide 一份配置给整棵组件树 —— 页面上的日期选择器、分页器、上传框取的就是它；
//   2）第三个参数传 true，同时把这配置写进模块级的**后备值** ——
//      上面那些「用函数弹出来、不在组件树上」的弹窗拿不到 provide，走的正是这条后备路。
//      少写这一句，弹窗按钮就会退回英文的 OK / Cancel。
provideGlobalConfig({ locale: zhCn }, app, true)

app.mount('#app')
