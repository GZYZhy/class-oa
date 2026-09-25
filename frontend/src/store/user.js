import { defineStore } from 'pinia'
import { login as loginApi, logout as logoutApi, getMe } from '@/api/auth'
import { rankOf } from '@/utils/roles'

export const useUserStore = defineStore('user', {
  state: () => ({
    // 已登录用户信息：{ student_no, name, avatar, class_name, role, must_change_password }
    info: null,
    // 是否已经向后端确认过一次登录状态（避免刷新时误判为未登录）
    resolved: false
  }),

  getters: {
    isLogin: (state) => !!state.info,
    /** 姓名字首，用于没有照片时的头像占位 */
    initial: (state) => (state.info?.name || '?').charAt(0),
    /** 管理员：全站读写，另有系统管理（改角色、重置密码、查操作日志） */
    isAdmin: (state) => state.info?.role === 'admin',
    /** 班委及以上（管理员也算）：学生名单、分类统计、审核、发布通知与文件 */
    isCommittee: (state) => rankOf(state.info?.role) >= rankOf('committee'),
    /** 非班委（含未登录）：看不到备注，也不给文件下载按钮 */
    isStudent: (state) => rankOf(state.info?.role) < rankOf('committee')
  },

  actions: {
    async login(payload) {
      this.info = await loginApi(payload)
      this.resolved = true
      return this.info
    },

    /** 刷新页面时用 Cookie 恢复登录状态 */
    async fetchMe() {
      try {
        this.info = await getMe()
      } catch (e) {
        this.info = null
      } finally {
        this.resolved = true
      }
      return this.info
    },

    async logout() {
      try {
        await logoutApi()
      } finally {
        // 无论后端是否成功，前端状态一律清空
        this.info = null
      }
    },

    /** 密码修改成功后，服务端已解除强制改密标记 */
    markPasswordChanged() {
      if (this.info) this.info.must_change_password = false
    }
  }
})
