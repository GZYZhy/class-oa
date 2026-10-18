<template>
  <div class="about">
    <!-- 班级概况 -->
    <div class="page-card">
      <div class="about-header">
        <img :src="SITE.logoUrl" class="about-logo" alt="校徽" />
        <div>
          <h2 style="margin: 0 0 6px 0;">{{ SITE.shortName }}</h2>
          <p style="margin: 0; color: var(--el-text-color-secondary); font-size: 14px;">
            {{ SITE.subtitle }}
          </p>
        </div>
      </div>

      <el-descriptions :column="isMobile ? 1 : 2" border style="margin-top: 20px;">
        <el-descriptions-item label="班级名称">{{ SITE.shortName }}</el-descriptions-item>
        <el-descriptions-item label="学生人数">{{ stats?.total || '-' }} 人</el-descriptions-item>
        <el-descriptions-item label="所属学院">{{ SITE.college }}</el-descriptions-item>
        <el-descriptions-item label="所属专业">{{ SITE.major }}</el-descriptions-item>
        <el-descriptions-item label="男生人数">{{ stats?.gender?.['男'] || 0 }} 人</el-descriptions-item>
        <el-descriptions-item label="女生人数">{{ stats?.gender?.['女'] || 0 }} 人</el-descriptions-item>
        <!-- 版本号来自后端 app_version，接口没返回时显示 - 而不是空着 -->
        <el-descriptions-item label="系统版本">{{ stats?.version || '-' }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 班委成员（不展示手机号） -->
    <div class="page-card" style="margin-top: 20px;">
      <h3 class="page-title">班委成员</h3>
      <el-table :data="committeeList" size="default" stripe border>
        <el-table-column type="index" label="序号" width="70" align="center" />
        <el-table-column prop="name" label="姓名" align="center" />
        <el-table-column prop="position" label="职务" align="center" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAbout } from '@/api/about'
import { useIsMobile } from '@/composables/useIsMobile'
import { SITE } from '@/utils/site'

// 手机上两列太挤，收成一列
const isMobile = useIsMobile()

// 原来这里是拉全量学生名单在前端筛班委，学生名单已收口到班委，
// 普通学生打开本页会 403，所以改走后端专门的 /api/about（只吐人数和班委姓名职务）
const stats = ref(null)
const committeeList = ref([])

onMounted(async () => {
  try {
    const data = await getAbout()
    stats.value = data
    committeeList.value = data.committee || []
  } catch (e) {
    ElMessage.error('班级概况加载失败')
  }
})
</script>

<style scoped>
.about-header {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.about-logo {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid var(--el-border-color-lighter);
  /* 固定白色，跟顶栏、家园横幅的校徽保持一致：白底圈是校徽的一部分 */
  background: #fff;
  padding: 4px;
  box-sizing: border-box;
}

/* 手机上校徽小一号，给标题留出宽度 */
@media (max-width: 768px) {
  .about-header {
    gap: 12px;
  }

  .about-logo {
    width: 52px;
    height: 52px;
  }
}
</style>
