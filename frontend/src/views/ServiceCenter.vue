<template>
  <div class="service-center">
    <div class="page-card">
      <h3 class="page-title">办事中心</h3>

      <p class="center-intro">
        这里是班级线上办事入口，后续会持续扩展更多功能。
      </p>

      <div class="service-grid">
        <!-- 请假申请 -->
        <router-link to="/leave" class="service-card">
          <div class="service-icon leave-icon">
            <el-icon><Document /></el-icon>
          </div>
          <div class="service-info">
            <h4 class="service-title">请假申请</h4>
            <p class="service-desc">在线提交请假申请，附证明材料，管理员审核通过后可下载审批表</p>
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
            <p class="service-desc">提交行驶证等信息，管理员审核通过后可下载申请表与承诺书</p>
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
            <p class="service-desc">提出您的意见或建议，班委查阅后会给您回复</p>
          </div>
          <div class="service-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </router-link>
      </div>

      <div class="empty-tip">
        更多办事服务正在建设中…
      </div>
    </div>
  </div>
</template>

<script setup>
import { Document, ArrowRight, ChatDotRound, Van } from '@element-plus/icons-vue'
</script>

<style scoped>
.service-center {
  max-width: 720px;
  margin: 0 auto;
}

.center-intro {
  margin: 0 0 18px 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}

.service-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.service-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  color: inherit;
  text-decoration: none;
}

.service-card:hover {
  background: #ecf5ff;
  border-color: #409EFF;
  transform: translateX(2px);
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
  color: #303133;
}

.service-desc {
  margin: 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
}

.service-arrow {
  color: #c0c4cc;
  font-size: 18px;
  flex-shrink: 0;
}

.empty-tip {
  margin-top: 24px;
  text-align: center;
  font-size: 13px;
  color: #c0c4cc;
}

@media (max-width: 768px) {
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
