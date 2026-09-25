import { defineStore } from 'pinia'
import { getStatistics, getFilterOptions, getStudentList } from '@/api/student'

export const useStudentStore = defineStore('student', {
  state: () => ({
    statistics: null,
    filterOptions: null,
    loading: false
  }),

  actions: {
    async fetchStatistics() {
      this.loading = true
      try {
        this.statistics = await getStatistics()
        return this.statistics
      } finally {
        this.loading = false
      }
    },

    // 获取全部学生（不分页），用于班委/团学会名单
    async fetchAllStudents() {
      const res = await getStudentList({ page: 1, page_size: 500 })
      return res.items
    },

    async fetchFilterOptions() {
      try {
        this.filterOptions = await getFilterOptions()
        return this.filterOptions
      } catch (e) {
        console.error('获取筛选选项失败', e)
      }
    }
  }
})
