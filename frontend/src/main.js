import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// Element Plus 的深色主题变量（定义在 .dark 类下，由下面那段同步到 <html>）
import 'element-plus/theme-chalk/dark/css-vars.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './styles/main.css'

// 深色模式：跟随设备的当前设置自动切换，站内不提供开关
//
// prefers-color-scheme 是「原生」做法 —— 设备切到深色，浏览器就把这个查询变成 true，
// 用户改系统设置时还会实时触发 change，不用刷新页面。
// 但光有媒体查询不够：Element Plus 的深色变量挂在 .dark 类上（不在媒体查询里），
// 所以还得把这个类同步到 <html>。项目自己的样式统一用 var(--el-*)，跟着一起翻。
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)')
const syncTheme = ({ matches }) => document.documentElement.classList.toggle('dark', matches)
syncTheme(darkQuery) // 首次进入就按当前设置定好，避免先闪一下浅色
darkQuery.addEventListener('change', syncTheme)

const app = createApp(App)

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
