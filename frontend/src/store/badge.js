import { defineStore } from 'pinia'
import { getBadges } from '@/api/badge'

/**
 * 侧边菜单的红点计数
 *
 * 不做定时轮询：登录时、每换一次页面时各刷一次就够（见 App.vue 的两个 watch），
 * 代价是一次 COUNT 查询。轮询反而会让手机一直耗电，而通知本来就是「下次打开看到」。
 */
export const useBadgeStore = defineStore('badge', {
  state: () => ({
    // 键名与后端 /api/badges 的返回保持一致，App.vue 里按菜单项的 badge 字段取值
    counts: { notice_unread: 0, review_pending: 0 }
  }),

  actions: {
    /** 重新拉一次计数 */
    async refresh() {
      try {
        const data = await getBadges()
        // 逐字段兜底而不是直接赋值：万一某次返回缺字段，模板里的 counts.xxx
        // 会变成 undefined，红点就渲染成一个空白的小圆球
        this.counts = {
          notice_unread: data?.notice_unread || 0,
          review_pending: data?.review_pending || 0
        }
      } catch (e) {
        /* 静默：红点只是提示，拉不到就保持原值（同 store/user.js 的 refreshTotal） */
      }
    },

    /** 退出登录时清空，免得下一个登录的人一眼看到上一个人的红点 */
    clear() {
      this.counts = { notice_unread: 0, review_pending: 0 }
    }
  }
})
