import { defineStore } from 'pinia'
import {
  login as loginApi,
  logout as logoutApi,
  getMe,
  getPublicSummary,
  getPasskeyLoginOptions,
  verifyPasskeyLogin,
  verifyTwoFactorLogin
} from '@/api/auth'
import { getPasskey } from '@/utils/passkey'
import { rankOf } from '@/utils/roles'

export const useUserStore = defineStore('user', {
  state: () => ({
    // 已登录用户信息：{ student_no, name, avatar, class_name, role, must_change_password, is_external }
    info: null,
    // 是否已经向后端确认过一次登录状态（避免刷新时误判为未登录）
    resolved: false,
    // 班级人数，顶栏「共 N 人」用它。放在 store 里是因为新增/删除学生之后
    // 学生名单页要把顶栏那个数字一起刷新，不能各拿各的
    totalStudents: 0
  }),

  getters: {
    isLogin: (state) => !!state.info,
    /** 姓名字首，用于没有照片时的头像占位 */
    initial: (state) => (state.info?.name || '?').charAt(0),
    /** 域外账号（老师、协助人员）：没有学生记录，看不到「我的信息」「办事中心」这些入口 */
    isExternal: (state) => !!state.info?.is_external,
    /**
     * 初始化临时账号：只在「库里还没有管理员」的引导期存在，用完即删。
     *
     * 判定**只看后端给的 is_bootstrap**，绝不看登录名是不是 admin ——
     * 将来完全可能有真的域外账号就叫 admin，按名字认会把无辜的人锁进初始化浮层。
     */
    isBootstrap: (state) => !!state.info?.is_bootstrap,
    /** 管理员：全站读写，另有系统管理（改角色、重置密码、查操作日志） */
    isAdmin: (state) => state.info?.role === 'admin',
    /** 班委及以上（管理员也算）：学生名单、分类统计、审核、发布通知与文件 */
    isCommittee: (state) => rankOf(state.info?.role) >= rankOf('committee'),
    /** 非班委（含未登录）：看不到备注，也不给文件下载按钮 */
    isStudent: (state) => rankOf(state.info?.role) < rankOf('committee')
  },

  actions: {
    async login(payload) {
      const res = await loginApi(payload)
      // 密码对了但开了二次验证：后端还没写会话，这里也不能把 info 设上，
      // 只把标记和挑战信息交给登录页，让它切到第二步的输入框
      if (res?.two_factor_required) return res
      this.info = res
      this.resolved = true
      return this.info
    },

    /** 登录第二步：验证码 / 恢复码通过后服务端才写会话 */
    async verifyTwoFactor(code) {
      this.info = await verifyTwoFactorLogin({ code })
      this.resolved = true
      return this.info
    },

    /**
     * 用通行密钥登录
     *
     * 和密码登录走两个接口，但登录成功后的状态处理一模一样：
     * 后端校验通过时已经写好会话，这里只要把用户信息接过来。
     * 浏览器取消 / 超时的异常原样往外抛，由登录页决定怎么提示。
     */
    async loginWithPasskey({ student_no, remember }) {
      const options = await getPasskeyLoginOptions({ student_no, remember })
      const credential = await getPasskey(options)
      this.info = await verifyPasskeyLogin({ student_no, remember, credential })
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
    },

    /** 重新拉一次班级人数（新增 / 删除学生之后调，让顶栏那个数字跟上） */
    async refreshTotal() {
      try {
        const summary = await getPublicSummary()
        this.totalStudents = summary.total || 0
      } catch (e) {
        /* 静默：人数只是展示，拉不到就保持原值 */
      }
    }
  }
})
