<template>
  <div>
    <div class="page-card">
      <h3 class="page-title">办事中心</h3>

      <div class="service-grid">
        <!-- 请假申请 -->
        <router-link to="/leave" class="service-card">
          <div class="service-icon leave-icon">
            <el-icon><Document /></el-icon>
          </div>
          <div class="service-info">
            <h4 class="service-title">请假申请</h4>
            <p class="service-desc">提交请假信息与证明，审批后可下载审批表</p>
          </div>
          <div class="service-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </router-link>

        <!-- 电动车通行证补办 -->
        <router-link to="/ev-pass" class="service-card">
          <div class="service-icon evpass-icon">
            <el-icon><Van /></el-icon>
          </div>
          <div class="service-info">
            <h4 class="service-title">电动车通行证补办</h4>
            <p class="service-desc">提交行驶证信息，审批后可下载申请表与承诺书</p>
          </div>
          <div class="service-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </router-link>

        <!-- 证明开具 -->
        <router-link to="/certificate" class="service-card">
          <div class="service-icon certificate-icon">
            <el-icon><Document /></el-icon>
          </div>
          <div class="service-info">
            <h4 class="service-title">证明开具</h4>
            <p class="service-desc">提交开具申请与依据材料，审批后下载成品 PDF</p>
          </div>
          <div class="service-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </router-link>

        <!-- 意见反馈 -->
        <router-link to="/feedback" class="service-card">
          <div class="service-icon feedback-icon">
            <el-icon><ChatDotRound /></el-icon>
          </div>
          <div class="service-info">
            <h4 class="service-title">意见反馈</h4>
            <p class="service-desc">提交意见或建议，班委会回复</p>
          </div>
          <div class="service-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Document, ArrowRight, ChatDotRound, Van } from '@element-plus/icons-vue'
</script>

<style scoped>
/* 自适应网格：宽屏自动排成多列，窄屏自然退回一列。
   删掉原先那层 720px 的壳之后，若还按 flex 竖着一列排，四张卡在宽屏上
   会各自拉成一条横幅 —— 左边一个图标、右边一个箭头，中间一大片空白。
   auto-fit（而不是 auto-fill）会把空轨道收掉，卡片正好把宽度匀开 */
.service-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}

.service-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  background: var(--el-fill-color-light);
  /* 描边走 --app-line：原来的 --el-border-color-lighter 在淡紫底上几乎看不见，
     卡片之间没有边界，看着像一整块 */
  border: 1px solid var(--app-line);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.2s;
  color: inherit;
  text-decoration: none;
}

.service-card:hover {
  background: var(--el-color-primary-light-9);
  border-color: var(--app-secondary-border);
  transform: translateX(2px);
  box-shadow: var(--app-shadow-hover);
}

.service-icon {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #fff;
  flex-shrink: 0;
}

.leave-icon {
  background: linear-gradient(135deg, #409EFF, #36cfc9);
}

.evpass-icon {
  background: linear-gradient(135deg, #67c23a, #409eff);
}

.certificate-icon {
  background: linear-gradient(135deg, #9b59b6, #3498db);
}

.feedback-icon {
  background: linear-gradient(135deg, #e6a23c, #f56c6c);
}

.service-info {
  flex: 1;
  min-width: 0;
}

.service-title {
  margin: 0 0 4px 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.service-desc {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.service-arrow {
  color: var(--el-text-color-disabled);
  font-size: 18px;
  flex-shrink: 0;
}

@media (max-width: 768px) {
  /* 手机上定死一列：320px 的下限在 700 出头的宽度里正好挤下两列，
     但那时卡片只剩图标和标题，两列并排反而更难扫 */
  .service-grid {
    grid-template-columns: 1fr;
  }

  .service-card {
    padding: 14px 16px;
    gap: 12px;
  }

  .service-icon {
    width: 40px;
    height: 40px;
    font-size: 20px;
  }

  .service-desc {
    display: none;
  }
}
</style>
