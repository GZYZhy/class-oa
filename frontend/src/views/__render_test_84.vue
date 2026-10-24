<template>
  <div class="page-card" v-loading="loading">
    <!-- 这里全是同学的家庭地址、邮箱这类信息，盖一层「谁在看」的水印 -->
    <Watermark :text="watermarkText" />

    <h3 class="page-title" style="margin-bottom: 12px;">审核审批</h3>

    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <!-- ============ 信息修改申请 ============ -->
      <!-- 标签用 #label 插槽写而不是 label 属性：属性里放不下红点这个元素 -->
      <el-tab-pane name="change">
        <template #label>信息修改申请<span v-if="tabBadge('change')" class="tab-badge">{{ tabBadge('change') }}</span></template>
        <div class="tab-toolbar">
          <ReviewSearch
            v-model:keyword="changeKeyword"
            v-model:range="changeRange"
            @search="fetchChangeList"
          />
          <el-radio-group v-model="changeStatus" size="small" @change="fetchChangeList">
            <el-radio-button value="pending">待审核</el-radio-button>
            <el-radio-button value="approved">已通过</el-radio-button>
            <el-radio-button value="rejected">已驳回</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="changeList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" width="150" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column label="申请时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>

          <!-- 新旧值对照：左边是学生现在库里的值，右边是申请改成什么 -->
          <el-table-column label="修改内容（原值 → 新值）" min-width="340">
            <template #default="{ row }">
              <div v-for="(next, key) in row.changes" :key="key" class="diff-line">
                <span class="diff-label">{{ FIELD_LABELS[key] || key }}</span>

                <!-- 照片这一项存的是文件名，打出来谁看都没用：待审时并排两张缩略图。
                     处理完之后不再画图 —— 旧图已经删了、新图也归到学生档案名下，
                     这两个地址取到的已经不是「当时那两张」 -->
                <template v-if="key === PHOTO_FIELD.prop">
                  <template v-if="row.status === 'pending'">
                    <img
                      v-if="row.current?.[key]"
                      :src="reviewPhotoUrl(row.id, 'old')"
                      class="diff-photo diff-photo-click"
                      alt="原证件照"
                      title="点击放大预览"
                      @click="openChangePhoto(row, 'old')"
                      @error="onImgError"
                    />
                    <span v-else class="diff-old">（无）</span>
                    <el-icon class="diff-arrow"><Right /></el-icon>
                    <img
                      :src="reviewPhotoUrl(row.id, 'new')"
                      class="diff-photo diff-photo-click"
                      alt="新证件照"
                      title="点击放大预览"
                      @click="openChangePhoto(row, 'new')"
                      @error="onImgError"
                    />
                  </template>
                  <span v-else class="diff-new">已上传新照片</span>
                </template>

                <template v-else>
                  <span class="diff-old">{{ row.current?.[key] || '（空）' }}</span>
                  <el-icon class="diff-arrow"><Right /></el-icon>
                  <span class="diff-new">{{ next || '（清空）' }}</span>
                </template>
              </div>
              <span v-if="!Object.keys(row.changes || {}).length" style="color: var(--el-text-color-disabled);">-</span>
            </template>
          </el-table-column>

          <el-table-column label="状态" width="120" align="center">
            <template #default="{ row }">
              <el-tag :type="STATUS_TYPES[row.status]" size="small">
                {{ STATUS_LABELS[row.status] || row.status }}
              </el-tag>
              <div v-if="row.reviewer_name" style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px;">
                {{ row.reviewer_name }}
                <div>{{ formatDateTime(row.reviewed_at) }}</div>
              </div>
              <div v-if="row.reason" style="font-size: 12px; color: #f56c6c; margin-top: 4px;">
                {{ row.reason }}
              </div>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="150" align="center">
            <template #default="{ row }">
              <!-- 与后端一致：修改申请班委就能批（change_requests.py 用的是
                   committee_required）。能进这个页面的人本来就都是班委及以上 -->
              <template v-if="row.status === 'pending'">
                <el-button type="success" link @click="handleApproveChange(row)">通过</el-button>
                <el-button type="danger" link @click="handleRejectChange(row)">驳回</el-button>
              </template>
              <span v-else style="color: var(--el-text-color-disabled);">已处理</span>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !changeList.length" description="没有修改申请" style="margin-top: 20px;" />
      </el-tab-pane>

      <!-- ============ 请假申请 ============ -->
      <el-tab-pane name="leave">
        <template #label>请假申请<span v-if="tabBadge('leave')" class="tab-badge">{{ tabBadge('leave') }}</span></template>
        <div class="tab-toolbar">
          <ReviewSearch
            v-model:keyword="leaveKeyword"
            v-model:range="leaveRange"
            @search="fetchLeaveList"
          />
          <el-radio-group v-model="leaveStatus" size="small" @change="fetchLeaveList">
            <!-- 四档：待处理（= 待受理 + 已受理，红点数的那一档）/ 待补正 / 已办结（通过 + 驳回）/
                 全部。具体是哪个状态看行上的 tag，不靠筛选按钮一个个摆出来；默认「全部」，
                 进来先看见所有的，要收窄再自己点 -->
            <el-radio-button value="open">待处理</el-radio-button>
            <el-radio-button value="correcting">待补正</el-radio-button>
            <el-radio-button value="closed">已办结</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="leaveList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" width="150" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="leave_type" label="类型" width="70" align="center" />
          <el-table-column label="请假时间" width="160" align="center">
            <template #default="{ row }">
              <div>{{ formatDateTime(row.start_at) }}</div>
              <div class="time-sep">至</div>
              <div>{{ formatDateTime(row.end_at) }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="事由" min-width="160" show-overflow-tooltip align="left" />
          <el-table-column label="状态" width="110" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'pending'" type="warning" size="small">待受理</el-tag>
              <el-tag v-else-if="row.status === 'accepted'" type="primary" size="small">已受理</el-tag>
              <el-tag v-else-if="row.status === 'correcting'" type="warning" size="small">待补正</el-tag>
              <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
              <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
              <el-tag v-else-if="row.status === 'revoked'" type="info" size="small">已撤销</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="班导师签字" width="120" align="center">
            <template #default="{ row }">
              <!-- 签字是批准那一步定的，待审核 / 已驳回的单子无所谓签没签 -->
              <span v-if="row.status !== 'approved'" style="color: var(--el-text-color-disabled);">—</span>
              <span v-else-if="row.has_advisor_sign" style="color: #67c23a;">
                {{ row.advisor_sign_name }} 已签
              </span>
              <span v-else style="color: var(--el-text-color-secondary);">暂不签字</span>
            </template>
          </el-table-column>
          <el-table-column label="申请时间" width="150" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="460" align="center">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="viewLeaveProof(row)">
                证明材料
              </el-button>
              <!-- 申请人本人走学生端那个入口，这里只给管理员（班委点了必然 403） -->
              <el-button
                v-if="row.status === 'approved' && userStore.isAdmin"
                size="small"
                link
                type="success"
                :loading="isDownloading(`leave-${row.id}`)"
                @click="handleDownloadLeavePdf(row)"
              >
                {{ isDownloading(`leave-${row.id}`) && downloadPercent
                  ? `${downloadPercent}%` : '下载请假表' }}
              </el-button>
              <!-- 只有「已批准但当初选了暂不签字」才有得补。已签过的后端也会 400 -->
              <el-button
                v-if="row.status === 'approved' && !row.has_advisor_sign && userStore.isAdmin"
                size="small"
                link
                type="warning"
                @click="openLeaveDialog('sign', row)"
              >
                补签字
              </el-button>
              <!-- 撤销是终态：撤了就不再提供请假表、不能编辑。二次确认在 handler 里 -->
              <el-button
                v-if="row.status === 'approved' && userStore.isAdmin"
                size="small"
                link
                type="danger"
                @click="handleRevokeLeave(row)"
              >
                撤销
              </el-button>
              <!-- 受理 = 管理员看过这份材料了。打开「证明材料」预览也会自动受理一次，这个按钮是兜底 -->
              <el-button
                v-if="userStore.isAdmin && row.status === 'pending'"
                size="small"
                link
                type="primary"
                @click="handleAcceptLeave(row)"
              >
                受理
              </el-button>
              <!-- 受理点错了的回头路；退回补正是「材料不对，打回让申请人补齐」 -->
              <template v-if="userStore.isAdmin && row.status === 'accepted'">
                <el-button size="small" link type="warning" @click="handleUnacceptLeave(row)">撤回受理</el-button>
                <el-button size="small" link type="warning" @click="handleCorrectLeave(row)">退回补正</el-button>
              </template>
              <!-- 待受理时按钮亮着但点不动，逼着人先看过材料 -->
              <template v-if="row.status === 'pending' || row.status === 'accepted'">
                <el-button
                  v-if="userStore.isAdmin"
                  size="small"
                  link
                  type="success"
                  :disabled="row.status === 'pending'"
                  @click="openLeaveDialog('approve', row)"
                >
                  通过
                </el-button>
                <el-button
                  v-if="userStore.isAdmin"
                  size="small"
                  link
                  type="danger"
                  :disabled="row.status === 'pending'"
                  @click="handleRejectLeave(row)"
                >
                  驳回
                </el-button>
                <span v-if="userStore.isAdmin && row.status === 'pending'" style="color: var(--el-text-color-secondary); font-size: 12px;">需先受理</span>
                <span v-if="!userStore.isAdmin" style="color: var(--el-text-color-secondary); font-size: 12px;">需管理员审批</span>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !leaveList.length" description="没有请假申请" style="margin-top: 20px;" />
      </el-tab-pane>

      <!-- ============ 电动车通行证 ============ -->
      <el-tab-pane name="evpass">
        <template #label>电动车通行证<span v-if="tabBadge('evpass')" class="tab-badge">{{ tabBadge('evpass') }}</span></template>
        <div class="tab-toolbar">
          <ReviewSearch
            v-model:keyword="evPassKeyword"
            v-model:range="evPassRange"
            @search="fetchEvPassList"
          />
          <el-radio-group v-model="evPassStatus" size="small" @change="fetchEvPassList">
            <el-radio-button value="open">待处理</el-radio-button>
            <el-radio-button value="correcting">待补正</el-radio-button>
            <el-radio-button value="closed">已办结</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="evPassList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" min-width="140" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="brand" label="品牌" min-width="120" align="center" />
          <el-table-column prop="plate_number" label="牌照号" min-width="140" align="center" />
          <el-table-column label="申请时间" min-width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" min-width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'pending'" type="warning" size="small">待受理</el-tag>
              <el-tag v-else-if="row.status === 'accepted'" type="primary" size="small">已受理</el-tag>
              <el-tag v-else-if="row.status === 'correcting'" type="warning" size="small">待补正</el-tag>
              <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
              <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
              <el-tag v-else-if="row.status === 'revoked'" type="info" size="small">已撤销</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="经办班委签字" min-width="130" align="center">
            <template #default="{ row }">
              <!-- 签字是批准那一步定的，待审核 / 已驳回的单子无所谓签没签 -->
              <span v-if="row.status !== 'approved'" style="color: var(--el-text-color-disabled);">—</span>
              <span v-else-if="row.has_sign" style="color: #67c23a;">{{ row.sign_name }} 已签</span>
              <span v-else style="color: var(--el-text-color-secondary);">暂不签署</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="530" align="center">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="viewEvLicense(row)">行驶证</el-button>
              <!-- 生成的文档：班委和管理员都能下（留档、报学院盖章用）。
                   后端 _pdf_target 只在「本人或班委及以上」放行，且要已通过 -->
              <template v-if="row.status === 'approved'">
                <el-button
                  size="small"
                  link
                  type="success"
                  :loading="isDownloading(`evpass-pass-${row.id}`)"
                  @click="downloadEvPassDoc(row, 'pass')"
                >
                  {{ isDownloading(`evpass-pass-${row.id}`) && downloadPercent
                    ? `${downloadPercent}%` : '申请表' }}
                </el-button>
                <el-button
                  size="small"
                  link
                  type="success"
                  :loading="isDownloading(`evpass-promise-${row.id}`)"
                  @click="downloadEvPassDoc(row, 'promise')"
                >
                  {{ isDownloading(`evpass-promise-${row.id}`) && downloadPercent
                    ? `${downloadPercent}%` : '承诺书' }}
                </el-button>
              </template>
              <!-- 只有「已批准但当初选了暂不签署」才有得补。已签过的后端也会 400 -->
              <el-button
                v-if="row.status === 'approved' && !row.has_sign && userStore.isAdmin"
                size="small"
                link
                type="warning"
                @click="openEvPassDialog('sign', row)"
              >
                补签字
              </el-button>
              <!-- 撤销是终态：撤了就不再提供申请表和承诺书、不能编辑。二次确认在 handler 里 -->
              <el-button
                v-if="row.status === 'approved' && userStore.isAdmin"
                size="small"
                link
                type="danger"
                @click="handleRevokeEvPass(row)"
              >
                撤销
              </el-button>
              <!-- 受理 = 管理员看过这份材料了。打开「行驶证」预览也会自动受理一次，这个按钮是兜底 -->
              <el-button
                v-if="userStore.isAdmin && row.status === 'pending'"
                size="small"
                link
                type="primary"
                @click="handleAcceptEvPass(row)"
              >
                受理
              </el-button>
              <template v-if="userStore.isAdmin && row.status === 'accepted'">
                <el-button size="small" link type="warning" @click="handleUnacceptEvPass(row)">撤回受理</el-button>
                <el-button size="small" link type="warning" @click="handleCorrectEvPass(row)">退回补正</el-button>
              </template>
              <!-- 审批仅管理员；班委只读。待受理时按钮置灰，逼着人先看过材料 -->
              <template v-if="userStore.isAdmin && (row.status === 'pending' || row.status === 'accepted')">
                <el-button
                  size="small"
                  link
                  type="success"
                  :disabled="row.status === 'pending'"
                  @click="openEvPassDialog('approve', row)"
                >通过</el-button>
                <el-button
                  size="small"
                  link
                  type="danger"
                  :disabled="row.status === 'pending'"
                  @click="handleRejectEvPass(row)"
                >驳回</el-button>
                <!-- 灰按钮得说一句为什么点不动（与请假那边同一句话） -->
                <span v-if="row.status === 'pending'" style="color: var(--el-text-color-secondary); font-size: 12px;">需先受理</span>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !evPassList.length" description="暂无申请" style="margin-top: 20px;" />
      </el-tab-pane>

      <!-- ============ 证明开具 ============ -->
      <el-tab-pane name="certificate">
        <template #label>证明开具<span v-if="tabBadge('certificate')" class="tab-badge">{{ tabBadge('certificate') }}</span></template>
        <div class="tab-toolbar">
          <ReviewSearch
            v-model:keyword="certificateKeyword"
            v-model:range="certificateRange"
            @search="fetchCertificateList"
          />
          <el-radio-group v-model="certificateStatus" size="small" @change="fetchCertificateList">
            <el-radio-button value="open">待处理</el-radio-button>
            <el-radio-button value="correcting">待补正</el-radio-button>
            <el-radio-button value="closed">已办结</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="certificateList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" width="140" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="证明标题" min-width="160" show-overflow-tooltip align="left" />
          <el-table-column prop="recipient" label="收文单位" min-width="140" show-overflow-tooltip align="left" />
          <el-table-column label="申请时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'pending'" type="warning" size="small">待受理</el-tag>
              <el-tag v-else-if="row.status === 'accepted'" type="primary" size="small">已受理</el-tag>
              <el-tag v-else-if="row.status === 'correcting'" type="warning" size="small">待补正</el-tag>
              <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
              <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
              <el-tag v-else-if="row.status === 'revoked'" type="info" size="small">已撤销</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="420" align="center">
            <template #default="{ row }">
              <template v-if="row.attachments?.length">
                <el-button size="small" link type="primary" @click="viewCertAttachment(row)">
                  查看附件
                </el-button>
              </template>
              <!-- 成品 PDF：仅管理员可见下载，班委不能下 -->
              <template v-if="row.status === 'approved'">
                <el-button
                  v-if="userStore.isAdmin && row.result_original_name"
                  size="small"
                  link
                  type="success"
                  :loading="isDownloading(`cert-${row.id}`)"
                  @click="downloadCertResult(row)"
                >
                  {{ isDownloading(`cert-${row.id}`) && downloadPercent
                    ? `${downloadPercent}%` : '成品 PDF' }}
                </el-button>
                <span v-if="userStore.isAdmin && !row.result_original_name" style="color: #e6a23c; font-size: 12px;">
                  待上传成品
                </span>
              </template>
              <!-- 撤销是终态：撤了就再也不提供成品、不能编辑。二次确认在 handler 里 -->
              <el-button
                v-if="row.status === 'approved' && userStore.isAdmin"
                size="small"
                link
                type="danger"
                @click="handleRevokeCertificate(row)"
              >
                撤销
              </el-button>
              <!-- 受理 = 管理员看过这份材料了。证明的附件是可选的，没有附件的单子
                   只能靠这个按钮受理，所以它不是装饰 -->
              <el-button
                v-if="userStore.isAdmin && row.status === 'pending'"
                size="small"
                link
                type="primary"
                @click="handleAcceptCertificate(row)"
              >
                受理
              </el-button>
              <template v-if="userStore.isAdmin && row.status === 'accepted'">
                <el-button size="small" link type="warning" @click="handleUnacceptCertificate(row)">撤回受理</el-button>
                <el-button size="small" link type="warning" @click="handleCorrectCertificate(row)">退回补正</el-button>
              </template>
              <!-- 审批仅管理员；班委只读。待受理时按钮置灰，逼着人先看过材料 -->
              <template v-if="userStore.isAdmin && (row.status === 'pending' || row.status === 'accepted')">
                <el-button
                  size="small"
                  link
                  type="success"
                  :disabled="row.status === 'pending'"
                  @click="handleApproveCertificate(row)"
                >通过</el-button>
                <el-button
                  size="small"
                  link
                  type="danger"
                  :disabled="row.status === 'pending'"
                  @click="handleRejectCertificate(row)"
                >驳回</el-button>
                <!-- 灰按钮得说一句为什么点不动（与请假那边同一句话） -->
                <span v-if="row.status === 'pending'" style="color: var(--el-text-color-secondary); font-size: 12px;">需先受理</span>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !certificateList.length" description="暂无申请" style="margin-top: 20px;" />
      </el-tab-pane>

      <!-- ============ 签字查看申请（仅管理员）============ -->
      <!-- 整个 tab 只给管理员：别的几个 tab 班委进来至少还能看列表，
           签字这条的列表接口本身是 admin_required —— 让班委点进来看一个红叉更糟 -->
      <el-tab-pane v-if="userStore.isAdmin" name="signphoto">
        <template #label>签字查看申请<span v-if="tabBadge('signphoto')" class="tab-badge">{{ tabBadge('signphoto') }}</span></template>
        <div class="tab-toolbar">
          <ReviewSearch
            v-model:keyword="signKeyword"
            v-model:range="signRange"
            @search="fetchSignList"
          />
          <el-radio-group v-model="signStatus" size="small" @change="fetchSignList">
            <el-radio-button value="pending">待审核</el-radio-button>
            <el-radio-button value="approved">已通过</el-radio-button>
            <el-radio-button value="rejected">已驳回</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="signList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" width="140" align="center">
            <template #default="{ row }">
              {{ row.applicant_name }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.applicant_no }}</div>
            </template>
          </el-table-column>
          <el-table-column label="被查看学生" width="140" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column label="申请时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'pending'" type="warning" size="small">待审核</el-tag>
              <el-tag v-else-if="row.status === 'approved'" type="success" size="small">已通过</el-tag>
              <el-tag v-else-if="row.status === 'rejected'" type="danger" size="small">已驳回</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="审批人 / 驳回理由" min-width="160" show-overflow-tooltip align="left">
            <template #default="{ row }">
              {{ row.status === 'rejected' ? (row.reason || '') : (row.reviewer_name || '-') }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" align="center">
            <template #default="{ row }">
              <!-- 签字图本身也在这里给管理员看一眼：批之前总得知道批的是什么。
                   管理员看签字不受审批限制（取图接口直接放行） -->
              <el-button size="small" link type="primary" @click="viewSignImage(row)">查看签字</el-button>
              <template v-if="row.status === 'pending'">
                <el-button size="small" link type="success" @click="handleApproveSign(row)">通过</el-button>
                <el-button size="small" link type="danger" @click="handleRejectSign(row)">驳回</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !signList.length" description="暂无申请" style="margin-top: 20px;" />
      </el-tab-pane>

      <!-- ============ 导出申请 ============ -->
      <el-tab-pane name="export">
        <template #label>导出申请<span v-if="tabBadge('export')" class="tab-badge">{{ tabBadge('export') }}</span></template>
        <div class="tab-toolbar">
          <ReviewSearch
            v-model:keyword="exportKeyword"
            v-model:range="exportRange"
            @search="fetchExportList"
          />
          <el-radio-group v-model="exportStatus" size="small" @change="fetchExportList">
            <el-radio-button value="pending">待审核</el-radio-button>
            <el-radio-button value="generated">已通过</el-radio-button>
            <el-radio-button value="rejected">已驳回</el-radio-button>
            <el-radio-button value="failed">生成失败</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="exportList" v-loading="exportLoading" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="申请人" min-width="150" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column label="类型" min-width="140" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.export_type === 'excel_list' ? '' : 'primary'">
                {{ row.export_type === 'excel_list' ? '名单 Excel' : '个人信息表 PDF' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="范围" min-width="120" align="center">
            <template #default="{ row }">{{ scopeLabel(row.scope_type) }}</template>
          </el-table-column>
          <el-table-column label="字段数" min-width="90" align="center">
            <template #default="{ row }">
              {{ row.export_type === 'excel_list' ? (row.fields?.length || 0) : '全部' }}
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="110" align="center">
            <template #default="{ row }">
              <el-tag :type="exportStatusTag(row.status)" size="small">
                {{ exportStatusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="申请时间" min-width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="260" align="center">
            <template #default="{ row }">
              <template v-if="(row.status === 'generated' || row.status === 'approved') && (userStore.isAdmin || row.student_no === userStore.userInfo?.student_no)">
                <el-button
                  size="small"
                  link
                  type="success"
                  :loading="exportDownloadingId === row.id"
                  @click="handleDownloadExport(row)"
                >
                  {{ exportDownloadingId === row.id && exportDownloadPercent
                      ? exportDownloadPercent + '%' : '下载' }}
                </el-button>
              </template>
              <template v-if="row.status === 'failed'">
                <el-tooltip :content="row.error_msg" placement="top">
                  <span style="font-size: 12px; color: var(--el-text-color-secondary); cursor: help;">失败原因</span>
                </el-tooltip>
              </template>
              <template v-if="row.status === 'rejected'">
                <el-tooltip :content="row.reject_reason" placement="top">
                  <span style="font-size: 12px; color: var(--el-text-color-secondary); cursor: help;">驳回理由</span>
                </el-tooltip>
              </template>
              <template v-if="row.status === 'pending' && userStore.isAdmin">
                <el-button size="small" link type="success" @click="handleApproveExport(row)">
                  通过
                </el-button>
                <el-button size="small" link type="danger" @click="handleRejectExport(row)">
                  驳回
                </el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!exportLoading && !exportList.length" description="暂无导出申请" style="margin-top: 20px;" />
      </el-tab-pane>

      <!-- ============ 意见反馈 ============ -->
      <el-tab-pane name="feedback">
        <template #label>意见反馈<span v-if="tabBadge('feedback')" class="tab-badge">{{ tabBadge('feedback') }}</span></template>
        <div class="tab-toolbar">
          <ReviewSearch
            v-model:keyword="feedbackKeyword"
            v-model:range="feedbackRange"
            @search="fetchFeedbackList"
          />
          <el-radio-group v-model="feedbackStatus" size="small" @change="fetchFeedbackList">
            <el-radio-button value="unread">未读</el-radio-button>
            <el-radio-button value="read">已读</el-radio-button>
            <el-radio-button value="replied">已回复</el-radio-button>
            <el-radio-button value="">全部</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="feedbackList" stripe border style="width: 100%; margin-top: 12px;">
          <el-table-column label="提交人" width="140" align="center">
            <template #default="{ row }">
              {{ row.student_name }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.student_no }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip align="left" />
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'unread'" type="info" size="small">未读</el-tag>
              <el-tag v-else-if="row.status === 'read'" type="warning" size="small">已读</el-tag>
              <el-tag v-else-if="row.status === 'replied'" type="success" size="small">已回复</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="提交时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="180" align="center">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="viewFeedback(row)">
                查看
              </el-button>
              <el-button
                v-if="row.status === 'unread'"
                size="small"
                link
                type="warning"
                @click="handleMarkRead(row)"
              >
                标为已读
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !feedbackList.length" description="暂无反馈" style="margin-top: 20px;" />
      </el-tab-pane>
    </el-tabs>

    <!-- 反馈详情弹窗 -->
    <el-dialog append-to-body v-model="feedbackDetailVisible" title="反馈详情" width="600px">
      <div v-if="currentFeedback" class="detail-content">
        <div class="detail-header">
          <h4>{{ currentFeedback.title }}</h4>
          <div class="detail-meta">
            <span>{{ currentFeedback.student_name }}（{{ currentFeedback.student_no }}）</span>
            <span class="detail-time">{{ formatDateTime(currentFeedback.created_at) }}</span>
          </div>
        </div>
        <div class="detail-body">{{ currentFeedback.content }}</div>

        <div v-if="currentFeedback.attachments?.length" class="attachment-block">
          <div class="attachment-title">附件</div>
          <div v-for="item in currentFeedback.attachments" :key="item.index" class="attachment-item">
            <el-icon><Paperclip /></el-icon>
            <span class="attachment-name" @click="downloadAttachment(currentFeedback.id, item)">
              {{ item.name }}
            </span>
            <span class="attachment-size">
              {{ isDownloading(`feedback-${currentFeedback.id}-${item.index}`) && downloadPercent
                ? `${downloadPercent}%` : formatFileSize(item.size) }}
            </span>
          </div>
        </div>

        <!-- 回复区 -->
        <div v-if="currentFeedback.status === 'replied'" class="reply-block">
          <div class="reply-title">
            <el-icon><ChatDotRound /></el-icon>
            <span>已回复</span>
          </div>
          <div class="reply-meta">
            {{ currentFeedback.reply_name }}（{{ currentFeedback.reply_no }}） ·
            {{ formatDateTime(currentFeedback.reply_at) }}
          </div>
          <div class="reply-content">{{ currentFeedback.reply_content }}</div>
        </div>

        <div v-if="currentFeedback.status !== 'replied'" class="reply-form">
          <el-divider>回复</el-divider>
          <el-input
            v-model="replyContent"
            type="textarea"
            :rows="4"
            placeholder="请输入回复内容"
            maxlength="2000"
            show-word-limit
          />
          <div style="margin-top: 12px; text-align: right;">
            <el-button type="primary" :loading="replying" @click="handleReply">
              提交回复
            </el-button>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 信息修改申请里的证件照：点缩略图放大看原图 / 新图 -->
    <FileViewer
      v-model="changePhotoViewerVisible"
      :file-url="changePhotoUrl"
      :file-name="changePhotoFileName"
      :download-name="changePhotoDownloadName"
      :title="changePhotoTitle"
    />

    <!-- 请假证明材料预览弹框 -->
    <FileViewer
      v-model="proofViewerVisible"
      :file-url="proofFileUrl"
      :file-name="proofFileName"
      :download-name="proofDownloadName"
      title="请假证明材料"
    />

    <!-- 电动车行驶证预览弹框 -->
    <FileViewer
      v-model="evLicenseViewerVisible"
      :file-url="evLicenseFileUrl"
      :file-name="evLicenseFileName"
      :download-name="evLicenseDownloadName"
      title="电动车行驶证"
    />

    <!-- 证明申请附件预览弹框 -->
    <FileViewer
      v-model="certAttachViewerVisible"
      :file-url="certAttachFileUrl"
      :file-name="certAttachFileName"
      :download-name="certAttachDownloadName"
      title="申请依据附件"
    />

    <!-- 签字图预览弹框（管理员在审批页直接看，不需申请） -->
    <FileViewer
      v-model="signViewerVisible"
      :file-url="signFileUrl"
      :file-name="signFileName"
      :download-name="signFileName"
      title="学生签字"
    />

    <!-- 批准 / 补签字弹框：同一套表单，两个入口
         「通过」走 approve（顺带填意见、选签字），「补签字」走 advisor-sign（只补这两样） -->
    <el-dialog append-to-body v-model="leaveDialogVisible" :title="leaveDialogTitle" width="560px">
      <div v-if="leaveDialogRow" style="margin-bottom: 12px;">
        <strong>{{ leaveDialogRow.student_name }}</strong>
        <span style="color: var(--el-text-color-regular);">
          （{{ leaveDialogRow.leave_type }}，{{ formatDateTime(leaveDialogRow.start_at) }}
          至 {{ formatDateTime(leaveDialogRow.end_at) }}）
        </span>
      </div>
      <el-form label-width="92px">
        <el-form-item label="班导师意见">
          <el-input
            v-model="leaveDialogForm.advisor_opinion"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
            placeholder="选填"
          />
        </el-form-item>
        <el-form-item label="班导师签字">
          <el-select v-model="leaveDialogForm.advisor_sign_no" style="width: 100%;">
            <el-option label="暂不签字" value="" />
            <el-option
              v-for="s in advisorSigners"
              :key="s.student_no"
              :label="s.is_external ? `${s.name}（域外账号）` : s.name"
              :value="s.student_no"
            />
          </el-select>
          <div style="font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5;">
            签的是批准当时这张图，之后换图也不会改动已生成的表。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="leaveDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="leaveDialogSubmitting" @click="doLeaveDialog">
          {{ leaveDialogMode === 'sign' ? '补签字' : '通过' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 电动车：批准 / 补签字弹框。和请假那套同一个套路，只是少一个意见输入框
         —— 这份表上没有意见栏，落款处只有一行「经办班委：签字」 -->
    <el-dialog append-to-body v-model="evPassDialogVisible" :title="evPassDialogTitle" width="520px">
      <div v-if="evPassDialogRow" style="margin-bottom: 12px;">
        <strong>{{ evPassDialogRow.student_name }}</strong>
        <span style="color: var(--el-text-color-regular);">
          （{{ evPassDialogRow.brand }}，{{ evPassDialogRow.plate_number }}）
        </span>
      </div>
      <el-form label-width="110px">
        <el-form-item label="经办班委签字">
          <el-select v-model="evPassDialogForm.sign_no" style="width: 100%;">
            <el-option label="暂不签署" value="" />
            <el-option
              v-for="s in evPassSigners"
              :key="s.student_no"
              :label="s.is_external ? `${s.name}（域外账号）` : s.name"
              :value="s.student_no"
            />
          </el-select>
          <div style="font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5;">
            签的是批准当时这张图，之后换图也不会改动已生成的表。
            选「暂不签署」的话，申请表落款处不会出现「经办班委」这一行。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="evPassDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="evPassDialogSubmitting" @click="doEvPassDialog">
          {{ evPassDialogMode === 'sign' ? '补签字' : '通过' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 上传成品 PDF 弹框 -->
    <el-dialog append-to-body v-model="certResultUploadVisible" title="上传成品证明 PDF" width="520px">
      <div v-if="certResultUploadRow">
        <div style="margin-bottom: 8px;">
          <strong>{{ certResultUploadRow.student_name }}</strong>（{{ certResultUploadRow.student_no }}）
        </div>
        <div style="margin-bottom: 16px; color: var(--el-text-color-regular);">
          证明标题：{{ certResultUploadRow.title }}
        </div>
        <el-upload
          :auto-upload="false"
          :limit="1"
          :on-change="handleCertResultFileChange"
          :on-exceed="handleCertResultExceed"
          accept=".pdf"
          drag
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">将 PDF 文件拖到此处，或<em>点击选择</em></div>
          <template #tip>
            <div class="el-upload__tip">仅支持 PDF 格式，大小不超过 20MB</div>
          </template>
        </el-upload>
      </div>
      <template #footer>
        <el-button @click="certResultUploadVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="certResultUploading"
          :disabled="!certResultFile"
          @click="doUploadCertResult"
        >
          上传{{ certResultUploading && certResultUploadProgress ? ` ${certResultUploadProgress}%` : '' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { blobErrorDetail } from '@/utils/download'
import { Right, ChatDotRound, Paperclip, UploadFilled } from '@element-plus/icons-vue'
import {
  getChangeRequests,
  approveChangeRequest,
  rejectChangeRequest
} from '@/api/changeRequest'
import {
  getAdvisorSigners,
  getLeaveList,
  acceptLeave,
  unacceptLeave,
  correctLeave,
  approveLeave,
  advisorSign,
  rejectLeave,
  revokeLeave,
  downloadLeaveProof,
  downloadLeavePdf as apiDownloadLeavePdf
} from '@/api/leave'
import {
  getFeedbackList,
  getFeedbackDetail,
  markFeedbackRead,
  replyFeedback,
  downloadFeedbackAttachment
} from '@/api/feedback'
import {
  getEvPassList,
  acceptEvPass,
  unacceptEvPass,
  correctEvPass,
  approveEvPass,
  signEvPass,
  getEvPassSigners,
  rejectEvPass,
  revokeEvPass,
  downloadEvPassPdf,
  downloadEvPromisePdf
} from '@/api/evPass'
import { FIELD_LABELS, PHOTO_FIELD, STATUS_LABELS, STATUS_TYPES } from '@/utils/changeFields'
import { formatDate, formatDateTime, formatFileSize } from '@/utils/format'
import Watermark from '@/components/Watermark.vue'
import FileViewer from '@/components/FileViewer.vue'
import ReviewSearch from '@/components/ReviewSearch.vue'
import { useWatermark } from '@/composables/useWatermark'
import { useDownloadProgress } from '@/composables/useDownloadProgress'
import { useUserStore } from '@/store/user'
import { useBadgeStore } from '@/store/badge'
import {
  getExportRequests,
  approveExportRequest,
  rejectExportRequest,
  downloadExportFile
} from '@/api/export'
import {
  getCertificateList,
  revokeCertificate,
  acceptCertificate,
  unacceptCertificate,
  correctCertificate,
  approveCertificate,
  rejectCertificate,
  uploadCertificateResult,
  downloadCertificateResult
} from '@/api/certificate'
import {
  getSignRequests,
  getSignStatus,
  signImageUrl,
  approveSignRequest,
  rejectSignRequest
} from '@/api/signPhoto'

const userStore = useUserStore()
  userStore.info = { student_no: '2024000001', name: '甲', role: 'admin', is_external: false }
// 办件里各下载入口的进度：key 里带材料类型和行 id，同一时间只跑一个
const { percent: downloadPercent, isDownloading, run: runDownload } = useDownloadProgress()
const badgeStore = useBadgeStore()
const watermarkText = useWatermark()

const route = useRoute()

const loading = ref(false)
// 从推送点进来时带着 ?tab=leave 之类的参数，直接落到对应分类；
// 不带参数（正常从菜单进）就还是老样子，停在信息修改申请
const TABS = ['change', 'leave', 'evpass', 'certificate', 'signphoto', 'export', 'feedback']
const activeTab = ref('leave')

/**
 * tab 上的待办红点数字，0 返回空串（不渲染红点）
 *
 * 数量取自 /api/badges 的 review_tabs，和侧边菜单的红点同一个接口、同一个口径。
 * 超过 99 收成 99+，同 App.vue 侧边菜单的做法。
 */
function tabBadge(tab) {
  const count = badgeStore.counts.review_tabs?.[tab] || 0
  if (!count) return ''
  return count > 99 ? '99+' : String(count)
}

/**
 * 审核列表的公共查询参数：状态 + 提交人（姓名/学号）+ 提交日期
 *
 * 空值一律不传，后端把「没传」理解为不过滤。日期是 YYYY-MM-DD，后端按自然日算。
 */
function reviewParams(status, keyword, range) {
  const params = {}
  if (status) params.status = status
  const kw = (keyword || '').trim()
  if (kw) params.keyword = kw
  if (range?.length === 2) {
    params.start = range[0]
    params.end = range[1]
  }
  return params
}

// —— 信息修改申请 ——
const changeList = ref([])
const changeStatus = ref('pending')
const changeKeyword = ref('')
const changeRange = ref(null)

/**
 * 待审照片的对照图。old = 学生现在档案里那张，new = 这条申请里传的那张。
 *
 * 走专门的接口而不是 GET /api/students/{id}/photo：新照片在通过之前还没写进学生表，
 * 那条路两个方向都只会取到旧图。
 */
function reviewPhotoUrl(id, side) {
  return `/api/change-requests/${id}/photo?side=${side}`
}

// 证件照预览：缩略图太小看不清脸，点开走通用预览框，能缩放、旋转
const changePhotoViewerVisible = ref(false)
const changePhotoUrl = ref('')
const changePhotoFileName = ref('')
const changePhotoTitle = ref('')
const changePhotoDownloadName = ref('')

/**
 * 打开待审申请里的证件照。old = 学生档案里现在那张，new = 申请里新传的自备证件照
 *
 * 文件名要从 current / changes 里取：取图地址上只有 side 参数、没有后缀，
 * 而 FileViewer 靠文件名后缀判断该按图片还是 PDF 渲染。
 * 下载名换成「姓名_自备证件照_原/新照片.ext」，免得班委存下一个 uuid 名。
 */
function openChangePhoto(row, side) {
  const stored = side === 'old' ? row.current?.id_photo : row.changes?.id_photo
  const ext = (stored || '').match(/\.[^.]+$/)?.[0] || '.jpg'
  const sideLabel = side === 'old' ? '原照片' : '新照片'
  changePhotoUrl.value = reviewPhotoUrl(row.id, side)
  changePhotoFileName.value = stored || `id-photo${ext}`
  changePhotoTitle.value = `${row.student_name} 的自备证件照（${sideLabel}）`
  changePhotoDownloadName.value = `${row.student_name}_自备证件照_${sideLabel}${ext}`
  changePhotoViewerVisible.value = true
}

/** 图挂了就藏起来：历史申请的照片文件可能已经被清掉，别给班委一个碎图图标 */
function onImgError(e) {
  e.target.style.display = 'none'
}

async function fetchChangeList() {
  loading.value = true
  try {
    changeList.value = await getChangeRequests(
      reviewParams(changeStatus.value, changeKeyword.value, changeRange.value)
    )
  } catch (e) {
    ElMessage.error('申请列表加载失败')
  } finally {
    loading.value = false
    badgeStore.refresh()
  }
}

async function handleApproveChange(row) {
  try {
    await ElMessageBox.confirm(
      `确定通过「${row.student_name}」的修改申请吗？通过后立即写入其学生信息。`,
      '审核确认',
      { type: 'warning', confirmButtonText: '通过', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 取消
  }
  try {
    await approveChangeRequest(row.id)
    ElMessage.success('已通过，修改已生效')
    fetchChangeList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleRejectChange(row) {
  let reason
  try {
    const res = await ElMessageBox.prompt('请填写驳回理由，会展示给申请人', '驳回申请', {
      inputPlaceholder: '如：请填写真实邮箱',
      inputValidator: (v) => (v && v.trim() ? true : '请填写驳回理由'),
      confirmButtonText: '驳回',
      cancelButtonText: '取消'
    })
    reason = res.value.trim()
  } catch (e) {
    return // 取消
  }
  try {
    await rejectChangeRequest(row.id, reason)
    ElMessage.success('已驳回')
    fetchChangeList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

// 受理三件套。三个办件的动作逐字一样（受理、撤回受理、退回补正），
// 差别只在「调哪个接口」「刷新哪个列表」，所以收成一份，免得三处各写一遍再各自漂移
function makeReviewActions({ accept, unaccept, correct, reload }) {
  const run = async (fn, okText) => {
    try {
      await fn()
      ElMessage.success(okText)
      reload()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }
  return {
    accept: (row) => run(() => accept(row.id), '已受理'),
    unaccept: (row) => ElMessageBox.confirm(
      '撤回后回到「待受理」。已经发出的审批结果不受影响。',
      '撤回受理',
      { confirmButtonText: '撤回受理', cancelButtonText: '取消', type: 'warning' }
    ).then(() => run(() => unaccept(row.id), '已撤回受理')).catch(() => {}),
    // 理由必填（会通知申请人），跟驳回同一个写法
    correct: (row) => ElMessageBox.prompt('请写清楚要补什么，会通知申请人', '退回补正', {
      inputPlaceholder: '如：证明材料上的日期看不清，麻烦重传一张',
      inputValidator: (v) => (v && v.trim() ? true : '请写清楚要补什么'),
      confirmButtonText: '退回补正',
      cancelButtonText: '取消'
    }).then(({ value }) => run(() => correct(row.id, value.trim()), '已退回补正')).catch(() => {})
  }
}

// —— 请假申请 ——
const leaveList = ref([{"id":1,"student_name":"丙","student_no":"2024000003","leave_type":"事假","start_at":"2026-10-15 08:00","end_at":"2026-10-17 18:00","reason":"家里有事","status":"pending","has_advisor_sign":false,"advisor_sign_name":"","advisor_opinion":"","correction_reason":"","created_at":"2026-10-12 09:00"}])
// 默认「全部」（空串）：进来先看见所有的。上面那排按钮的四档见模板里的注释
const leaveStatus = ref('')
const leaveKeyword = ref('')
const leaveRange = ref(null)

async function fetchLeaveList() {
  loading.value = true
  try {
    leaveList.value = await getLeaveList(
      reviewParams(leaveStatus.value, leaveKeyword.value, leaveRange.value)
    )
  } catch (e) {
    ElMessage.error('请假列表加载失败')
  } finally {
    loading.value = false
    badgeStore.refresh()
  }
}

const {
  accept: handleAcceptLeave,
  unaccept: handleUnacceptLeave,
  correct: handleCorrectLeave
} = makeReviewActions({
  accept: acceptLeave, unaccept: unacceptLeave, correct: correctLeave, reload: fetchLeaveList
})

/**
 * 管理员撤销已通过的单子。三个办件的后果一样：变成「已撤销」终态、不再提供下载、
 * 不能再编辑也不能恢复，只有「不能再下载什么」这句文案不同
 */
function handleRevoke(row, label, revoke, reload) {
  ElMessageBox.confirm(
    `撤销后这条申请会变成「已撤销」，${label}不再提供下载，也不能再编辑。撤销后不能恢复，确定撤销吗？`,
    '撤销申请',
    { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' }
  ).then(async () => {
    try {
      await revoke(row.id)
      ElMessage.success('已撤销')
      reload()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

function handleRevokeLeave(row) {
  handleRevoke(row, '请假审批表', revokeLeave, fetchLeaveList)
}

// 请假证明预览
const proofViewerVisible = ref(false)
const proofFileUrl = ref('')
const proofFileName = ref('')
const proofDownloadName = ref('')

function viewLeaveProof(row) {
  // 打开材料即受理。不 await：别让网络拖慢预览；出错也静默，管理员只是想看眼材料，
  // 不该因为已被别人审掉之类的缘故弹红条（显式的「受理」按钮是兜底）
  if (userStore.isAdmin) acceptLeave(row.id).then(fetchLeaveList).catch(() => {})
  // 预览用的文件路径（后端接口）
  proofFileUrl.value = `/api/leaves/${row.id}/proof/admin`
  proofFileName.value = row.proof_original_name || '证明材料'
  // 下载命名规则：姓名_请假证明_开始日期YYYYMMDD.扩展名
  // 沿用请假审批表的命名模式，保持一致
  const ext = (row.proof_original_name || '').match(/\.[^.]+$/)?.[0] || ''
  const dateStr = formatDate(row.start_at).replace(/-/g, '')
  proofDownloadName.value = `${row.student_name}_请假证明_${dateStr}${ext}`
  proofViewerVisible.value = true
}

// 批准 / 补签字共用一套弹窗：'approve' 走通过接口，'sign' 走补签字接口
const leaveDialogVisible = ref(false)
const leaveDialogMode = ref('approve')
const leaveDialogRow = ref(null)
const leaveDialogSubmitting = ref(false)
const leaveDialogForm = ref({ advisor_opinion: '', advisor_sign_no: '' })
// 能当签字人的管理员列表，第一次打开弹窗时拉一次就够了
const advisorSigners = ref([])

const leaveDialogTitle = computed(
  () => (leaveDialogMode.value === 'sign' ? '补班导师签字' : '通过请假申请')
)

async function openLeaveDialog(mode, row) {
  leaveDialogMode.value = mode
  leaveDialogRow.value = row
  // 补签字时把当初填过的意见带出来，方便接着改；批准时是空白
  leaveDialogForm.value = {
    advisor_opinion: (mode === 'sign' && row.advisor_opinion) || '',
    advisor_sign_no: ''
  }
  leaveDialogVisible.value = true
  if (!advisorSigners.value.length) {
    try {
      advisorSigners.value = await getAdvisorSigners()
    } catch (e) {
      ElMessage.error('签字人列表加载失败')
    }
  }
}

async function doLeaveDialog() {
  const row = leaveDialogRow.value
  if (!row) return
  leaveDialogSubmitting.value = true
  try {
    const payload = {
      advisor_opinion: leaveDialogForm.value.advisor_opinion,
      advisor_sign_no: leaveDialogForm.value.advisor_sign_no
    }
    if (leaveDialogMode.value === 'sign') {
      await advisorSign(row.id, payload)
      ElMessage.success('已补签字')
    } else {
      await approveLeave(row.id, payload)
      ElMessage.success('已通过')
    }
    leaveDialogVisible.value = false
    fetchLeaveList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    leaveDialogSubmitting.value = false
  }
}

function handleRejectLeave(row) {
  ElMessageBox.prompt('请填写驳回理由，会展示给申请人', '驳回申请', {
    inputPlaceholder: '如：证明材料不完整',
    inputValidator: (v) => (v && v.trim() ? true : '请填写驳回理由'),
    confirmButtonText: '驳回',
    cancelButtonText: '取消'
  }).then(async ({ value }) => {
    try {
      await rejectLeave(row.id, value.trim())
      ElMessage.success('已驳回')
      fetchLeaveList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

async function handleDownloadLeavePdf(row) {
  try {
    await runDownload(`leave-${row.id}`, async (onProgress) => {
      const blob = await apiDownloadLeavePdf(row.id, onProgress)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${row.student_name}_请假审批表_${formatDate(row.start_at).replace(/-/g, '')}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    })
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e, '下载失败，请稍后重试'))
  }
}

// —— 电动车通行证 ——
// 班委能看列表、看行驶证、下载已通过的申请表和承诺书（留档用），
// 但通过/驳回只有管理员能点 —— 和后端 ev_passes.py 里
// committee_required / admin_required / _pdf_target 的划分一致
const evPassList = ref([])
const evPassStatus = ref('')
const evPassKeyword = ref('')
const evPassRange = ref(null)

async function fetchEvPassList() {
  loading.value = true
  try {
    evPassList.value = await getEvPassList(
      reviewParams(evPassStatus.value, evPassKeyword.value, evPassRange.value)
    )
  } catch (e) {
    ElMessage.error('通行证申请列表加载失败')
  } finally {
    loading.value = false
    badgeStore.refresh()
  }
}

const {
  accept: handleAcceptEvPass,
  unaccept: handleUnacceptEvPass,
  correct: handleCorrectEvPass
} = makeReviewActions({
  accept: acceptEvPass, unaccept: unacceptEvPass, correct: correctEvPass, reload: fetchEvPassList
})

// 行驶证预览（班委和管理员走 /license/admin 这个口）
const evLicenseViewerVisible = ref(false)
const evLicenseFileUrl = ref('')
const evLicenseFileName = ref('')
const evLicenseDownloadName = ref('')

function viewEvLicense(row) {
  // 打开行驶证即受理（不 await、出错静默，理由同请假那边）
  if (userStore.isAdmin) acceptEvPass(row.id).then(fetchEvPassList).catch(() => {})
  evLicenseFileUrl.value = `/api/ev-passes/${row.id}/license/admin`
  evLicenseFileName.value = row.license_original_name || '行驶证'
  // 下载命名沿用请假证明的模式：姓名_材料名_日期
  const ext = (row.license_original_name || '').match(/\.[^.]+$/)?.[0] || ''
  const dateStr = formatDate(row.created_at).replace(/-/g, '')
  evLicenseDownloadName.value = `${row.student_name}_电动车行驶证_${dateStr}${ext}`
  evLicenseViewerVisible.value = true
}

// 申请表 / 承诺书：班委和管理员都要留档，两种文档的处理完全一样，只是地址和名字不同
async function downloadEvPassDoc(row, kind) {
  const [fetchBlob, label, key] = kind === 'promise'
    ? [downloadEvPromisePdf, '电动车承诺书', `evpass-promise-${row.id}`]
    : [downloadEvPassPdf, '电动车通行证申请表', `evpass-pass-${row.id}`]
  try {
    await runDownload(key, async (onProgress) => {
      const blob = await fetchBlob(row.id, onProgress)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${row.student_name}_${label}_${formatDate(row.created_at).replace(/-/g, '')}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    })
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e, '下载失败'))
  }
}

// 批准 / 补签字共用一套弹窗：'approve' 走通过接口，'sign' 走补签字接口
const evPassDialogVisible = ref(false)
const evPassDialogMode = ref('approve')
const evPassDialogRow = ref(null)
const evPassDialogSubmitting = ref(false)
const evPassDialogForm = ref({ sign_no: '' })
// 能当经办班委签字人的管理员列表，第一次打开弹窗时拉一次就够了
const evPassSigners = ref([])

const evPassDialogTitle = computed(
  () => (evPassDialogMode.value === 'sign' ? '补经办班委签字' : '通过电动车通行证申请')
)

async function openEvPassDialog(mode, row) {
  evPassDialogMode.value = mode
  evPassDialogRow.value = row
  evPassDialogForm.value = { sign_no: '' }
  evPassDialogVisible.value = true
  if (!evPassSigners.value.length) {
    try {
      evPassSigners.value = await getEvPassSigners()
    } catch (e) {
      ElMessage.error('签字人列表加载失败')
    }
  }
}

async function doEvPassDialog() {
  const row = evPassDialogRow.value
  if (!row) return
  const payload = { sign_no: evPassDialogForm.value.sign_no }
  // 补签字就是要补一个签字，选「暂不签署」等于什么都没做 —— 后端也会 400，
  // 在前端拦一下，省一次「点了没反应」的往返
  if (evPassDialogMode.value === 'sign' && !payload.sign_no) {
    ElMessage.warning('请选择签字人')
    return
  }
  evPassDialogSubmitting.value = true
  try {
    if (evPassDialogMode.value === 'sign') {
      await signEvPass(row.id, payload)
      ElMessage.success('已补签字')
    } else {
      await approveEvPass(row.id, payload)
      ElMessage.success('已通过，申请人现在可以下载申请表和承诺书')
    }
    evPassDialogVisible.value = false
    fetchEvPassList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    evPassDialogSubmitting.value = false
  }
}

function handleRejectEvPass(row) {
  ElMessageBox.prompt('请填写驳回理由，会展示给申请人', '驳回申请', {
    inputPlaceholder: '如：行驶证照片不清晰',
    inputValidator: (v) => (v && v.trim() ? true : '请填写驳回理由'),
    confirmButtonText: '驳回',
    cancelButtonText: '取消'
  }).then(async ({ value }) => {
    try {
      await rejectEvPass(row.id, value.trim())
      ElMessage.success('已驳回')
      fetchEvPassList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

function handleRevokeEvPass(row) {
  handleRevoke(row, '申请表和承诺书', revokeEvPass, fetchEvPassList)
}

// —— 证明开具 ——
// 班委能看列表、看附件，但不能下载成品 PDF、不能审批
const certificateList = ref([])
const certificateStatus = ref('')
const certificateKeyword = ref('')
const certificateRange = ref(null)

async function fetchCertificateList() {
  loading.value = true
  try {
    certificateList.value = await getCertificateList(
      reviewParams(certificateStatus.value, certificateKeyword.value, certificateRange.value)
    )
  } catch (e) {
    ElMessage.error('证明申请列表加载失败')
  } finally {
    loading.value = false
    badgeStore.refresh()
  }
}

const {
  accept: handleAcceptCertificate,
  unaccept: handleUnacceptCertificate,
  correct: handleCorrectCertificate
} = makeReviewActions({
  accept: acceptCertificate,
  unaccept: unacceptCertificate,
  correct: correctCertificate,
  reload: fetchCertificateList
})

// 证明附件预览
const certAttachViewerVisible = ref(false)
const certAttachFileUrl = ref('')
const certAttachFileName = ref('')
const certAttachDownloadName = ref('')

function viewCertAttachment(row) {
  if (!row.attachments?.length) return
  // 打开附件即受理（不 await、出错静默，理由同请假那边）
  if (userStore.isAdmin) acceptCertificate(row.id).then(fetchCertificateList).catch(() => {})
  const item = row.attachments[0]
  // 班委及以上走 admin 路径
  certAttachFileUrl.value = `/api/certificates/${row.id}/attachment/0/admin`
  certAttachFileName.value = item.name
  const ext = (item.name || '').match(/\.[^.]+$/)?.[0] || ''
  const dateStr = formatDate(row.created_at).replace(/-/g, '')
  certAttachDownloadName.value = `${row.student_name}_证明依据_${dateStr}${ext}`
  certAttachViewerVisible.value = true
}

// 下载成品 PDF（管理员用）
async function downloadCertResult(row) {
  try {
    await runDownload(`cert-${row.id}`, async (onProgress) => {
      const blob = await downloadCertificateResult(row.id, true, onProgress)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = row.result_original_name || `${row.student_name}_证明.pdf`
      a.click()
      URL.revokeObjectURL(url)
    })
  } catch (e) {
    ElMessage.error(await blobErrorDetail(e, '下载失败'))
  }
}

function handleApproveCertificate(row) {
  ElMessageBox.confirm(
    `确定通过「${row.student_name}」的证明开具申请吗？\n` +
    `标题：${row.title}\n收文单位：${row.recipient}`,
    '审批确认',
    { type: 'warning', confirmButtonText: '通过', cancelButtonText: '取消' }
  ).then(async () => {
    try {
      await approveCertificate(row.id)
      ElMessage.success('已通过，请上传成品 PDF')
      fetchCertificateList()
      // 通过后直接弹上传成品的对话框
      certResultUploadRow.value = row
      certResultFile.value = null
      certResultUploadVisible.value = true
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

function handleRejectCertificate(row) {
  ElMessageBox.prompt('请填写驳回理由，会展示给申请人', '驳回申请', {
    inputPlaceholder: '如：材料不完整',
    inputValidator: (v) => (v && v.trim() ? true : '请填写驳回理由'),
    confirmButtonText: '驳回',
    cancelButtonText: '取消'
  }).then(async ({ value }) => {
    try {
      await rejectCertificate(row.id, value.trim())
      ElMessage.success('已驳回')
      fetchCertificateList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

function handleRevokeCertificate(row) {
  handleRevoke(row, '成品证明', revokeCertificate, fetchCertificateList)
}

// —— 签字查看申请（仅管理员审批）——
const signList = ref([])
const signStatus = ref('pending')
const signKeyword = ref('')
const signRange = ref(null)
const signViewerVisible = ref(false)
const signFileUrl = ref('')
const signFileName = ref('')

async function fetchSignList() {
  loading.value = true
  try {
    const res = await getSignRequests(
      reviewParams(signStatus.value, signKeyword.value, signRange.value)
    )
    signList.value = res.items || []
  } catch (e) {
    ElMessage.error('签字申请列表加载失败')
  } finally {
    loading.value = false
    badgeStore.refresh()
  }
}

/** 管理员看一眼这条申请要看的那张签字图。取图不受审批限制，但**文件名得现问** ——
 *  列表里只有学号姓名，而预览组件靠文件名后缀判类型，库里那个 uuid 名不能给前端 */
async function viewSignImage(row) {
  try {
    const s = await getSignStatus(row.student_id)
    if (!s.download_name) {
      ElMessage.warning('该学生现在没有签字图片')
      return
    }
    signFileUrl.value = signImageUrl(row.student_id, s.download_name)
    signFileName.value = s.download_name
    signViewerVisible.value = true
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  }
}

function handleApproveSign(row) {
  ElMessageBox.confirm(
    `确定通过「${row.applicant_name}」查看「${row.student_name}」签字的申请吗？\n` +
    '通过后他可以在 1 小时内查看，过期要重新申请。',
    '审批确认',
    { type: 'warning', confirmButtonText: '通过', cancelButtonText: '取消' }
  ).then(async () => {
    try {
      await approveSignRequest(row.id)
      ElMessage.success('已通过')
      fetchSignList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

function handleRejectSign(row) {
  ElMessageBox.prompt('请填写驳回理由，会展示给申请人', '驳回申请', {
    inputPlaceholder: '如：用途不明确',
    inputValidator: (v) => (v && v.trim() ? true : '请填写驳回理由'),
    confirmButtonText: '驳回',
    cancelButtonText: '取消'
  }).then(async ({ value }) => {
    try {
      await rejectSignRequest(row.id, value.trim())
      ElMessage.success('已驳回')
      fetchSignList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

// 上传成品 PDF
const certResultUploadVisible = ref(false)
const certResultUploadRow = ref(null)
const certResultFile = ref(null)
const certResultUploading = ref(false)
const certResultUploadProgress = ref(0)

function handleCertResultFileChange(file) {
  const raw = file.raw
  if (!raw) return
  if (raw.size > 20 * 1024 * 1024) {
    ElMessage.error('文件不能超过 20MB')
    return
  }
  certResultFile.value = raw
}

function handleCertResultExceed() {
  ElMessage.warning('只能上传一个 PDF 文件')
}

async function doUploadCertResult() {
  if (!certResultFile.value || !certResultUploadRow.value) return
  certResultUploading.value = true
  certResultUploadProgress.value = 0
  try {
    await uploadCertificateResult(
      certResultUploadRow.value.id,
      certResultFile.value,
      (loaded, total) => {
        certResultUploadProgress.value = total ? Math.round((loaded / total) * 100) : 0
      }
    )
    ElMessage.success('成品上传成功')
    certResultUploadVisible.value = false
    fetchCertificateList()
  } catch (e) {
    ElMessage.error('上传失败：' + (e.response?.data?.detail || e.message))
  } finally {
    certResultUploading.value = false
  }
}

// —— 导出申请 ——
const exportList = ref([])
const exportStatus = ref('pending')
const exportKeyword = ref('')
const exportRange = ref(null)
const exportLoading = ref(false)
// 正在下载的那条申请：按钮转圈 + 显示百分比
const exportDownloadingId = ref(null)
const exportDownloadPercent = ref(0)

async function fetchExportList() {
  exportLoading.value = true
  try {
    const res = await getExportRequests({
      ...reviewParams(exportStatus.value, exportKeyword.value, exportRange.value),
      page: 1,
      page_size: 100
    })
    exportList.value = res.items || []
  } catch (e) {
    ElMessage.error('加载导出申请列表失败')
    console.error(e)
  } finally {
    exportLoading.value = false
    // 顺手刷一下红点，原因同 fetchFeedbackList 里的说明
    badgeStore.refresh()
  }
}

function scopeLabel(type) {
  return {
    all: '全部学生',
    filtered: '筛选结果',
    selected: '手动勾选',
    id_range: '学号范围'
  }[type] || type
}

function exportStatusTag(status) {
  return {
    pending: 'warning',
    approved: 'success',
    generated: 'success',
    rejected: 'danger',
    failed: 'info'
  }[status] || 'info'
}

function exportStatusLabel(status) {
  return {
    pending: '待审核',
    approved: '已通过',
    generated: '已生成',
    rejected: '已驳回',
    failed: '生成失败'
  }[status] || status
}

async function handleApproveExport(row) {
  ElMessageBox.confirm(
    `确定通过 ${row.student_name} 的导出申请？\n通过后会自动生成文件。`,
    '通过申请',
    { type: 'success', confirmButtonText: '通过', cancelButtonText: '取消' }
  ).then(async () => {
    try {
      await approveExportRequest(row.id)
      ElMessage.success('已通过，文件生成中…')
      fetchExportList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

async function handleRejectExport(row) {
  ElMessageBox.prompt('请输入驳回理由', '驳回申请', {
    confirmButtonText: '驳回',
    cancelButtonText: '取消',
    type: 'warning',
    inputPattern: /.+/,
    inputErrorMessage: '请填写驳回理由'
  }).then(async ({ value }) => {
    try {
      await rejectExportRequest(row.id, value)
      ElMessage.success('已驳回')
      fetchExportList()
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }).catch(() => {})
}

async function handleDownloadExport(row) {
  // 导出的 zip 可能几十 MB，按钮上显示百分比（同「资料下载」的做法）
  exportDownloadingId.value = row.id
  exportDownloadPercent.value = 0
  try {
    const blob = await downloadExportFile(row.id, (loaded, total) => {
      exportDownloadPercent.value = total ? Math.round((loaded / total) * 100) : 0
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.file_original_name || '学生信息导出'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    ElMessage.success('下载完成')
  } catch (e) {
    // 响应是 blob，后端的 detail 也被包成了 Blob，得专门解一下
    ElMessage.error(await blobErrorDetail(e, '下载失败'))
  } finally {
    exportDownloadingId.value = null
  }
}

// —— 意见反馈 ——
const feedbackList = ref([])
const feedbackStatus = ref('unread')
const feedbackKeyword = ref('')
const feedbackRange = ref(null)
const feedbackDetailVisible = ref(false)
const currentFeedback = ref(null)
const replyContent = ref('')
const replying = ref(false)

async function fetchFeedbackList() {
  loading.value = true
  try {
    feedbackList.value = await getFeedbackList(
      reviewParams(feedbackStatus.value, feedbackKeyword.value, feedbackRange.value)
    )
  } catch (e) {
    ElMessage.error('反馈列表加载失败')
  } finally {
    loading.value = false
    // 红点刷新统一挂在各列表的 finally 里：每个审核操作成功之后本来就都会重拉列表，
    // 这样将来新增操作时漏掉刷新的概率是零（红点里的数字会跟着立刻减下去）。
    // 代价是切 tab 会多发一次请求，可以接受
    badgeStore.refresh()
  }
}

async function viewFeedback(row) {
  try {
    currentFeedback.value = await getFeedbackDetail(row.id)
    replyContent.value = currentFeedback.value.reply_content || ''
    feedbackDetailVisible.value = true
    // 查看后刷新列表（状态可能从 unread 变 read）
    fetchFeedbackList()
  } catch (e) {
    ElMessage.error('加载失败')
  }
}

/** index 用后端给的，不靠数组下标猜（班委和学生看到的是同一份下标） */
async function downloadAttachment(feedbackId, item) {
  try {
    await runDownload(`feedback-${feedbackId}-${item.index}`, async (onProgress) => {
      const blob = await downloadFeedbackAttachment(feedbackId, item.index, onProgress)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      // blob: URL 上没有后端的 Content-Disposition，文件名只能自己给
      a.download = item.name
      a.click()
      URL.revokeObjectURL(url)
    })
  } catch (e) {
    ElMessage.error('附件下载失败')
  }
}

async function handleMarkRead(row) {
  try {
    await markFeedbackRead(row.id)
    ElMessage.success('已标记为已读')
    fetchFeedbackList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleReply() {
  if (!replyContent.value.trim()) return ElMessage.warning('请输入回复内容')
  if (!currentFeedback.value) return
  replying.value = true
  try {
    const updated = await replyFeedback(currentFeedback.value.id, replyContent.value.trim())
    currentFeedback.value = updated
    ElMessage.success('回复已发送')
    fetchFeedbackList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '回复失败')
  } finally {
    replying.value = false
  }
}

function handleTabChange() {
  if (activeTab.value === 'change') {
    fetchChangeList()
  } else if (activeTab.value === 'leave') {
    fetchLeaveList()
  } else if (activeTab.value === 'evpass') {
    fetchEvPassList()
  } else if (activeTab.value === 'certificate') {
    fetchCertificateList()
  } else if (activeTab.value === 'signphoto' && userStore.isAdmin) {
    // 带上 isAdmin：通知里的 ?tab=signphoto 谁都可能点进来，班委拉这个列表是 403
    fetchSignList()
  } else if (activeTab.value === 'export') {
    fetchExportList()
  } else if (activeTab.value === 'feedback') {
    fetchFeedbackList()
  }
}

// 按当前 tab 拉数据（而不是固定拉修改申请），这样 ?tab=leave 进来才是对的
onMounted(handleTabChange)
</script>

<style scoped>
.page-card {
  /* 水印的定位基准 */
  position: relative;
}

/* tab 标签上的待办红点。手写一个 span 而不用 el-badge：
   el-badge 会多套一层绝对定位的节点，位置不好控（同 App.vue 侧边菜单的做法） */
.tab-badge {
  display: inline-block;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  margin-left: 5px;
  box-sizing: border-box;
  border-radius: 8px;
  background: #f56c6c;
  color: #fff;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
  /* 红点比标签文字矮一点，抬 1px 让它跟文字的中线对齐 */
  vertical-align: 1px;
}

/* 左边是搜索（提交人 / 提交日期），右边是状态筛选；窄屏时换行而不是挤在一起 */
.tab-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 8px;
}

/* 起止时间竖排两行 */
.time-sep {
  font-size: 12px;
  color: var(--el-text-color-disabled);
  line-height: 1.4;
}

.diff-line {
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.9;
  font-size: 13px;
}

.diff-label {
  width: 84px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.diff-old {
  color: var(--el-text-color-secondary);
  text-decoration: line-through;
}

.diff-arrow {
  color: var(--el-text-color-disabled);
}

.diff-new {
  color: var(--el-text-color-primary);
  font-weight: 500;
}

/* 待审照片的缩略图：按证件照的竖版比例，别把表格行撑得太高 */
.diff-photo {
  width: 42px;
  height: 56px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--el-border-color-lighter);
  vertical-align: middle;
}

/* 缩略图能点开预览：手型光标 + 悬停描边，让人看得出这不是一张死图 */
.diff-photo-click {
  cursor: zoom-in;
  transition: border-color 0.2s;
}

.diff-photo-click:hover {
  border-color: var(--el-color-primary);
}

/* 手机上「原值 → 新值」一条可能折行，改成上下排列不容易串行 */
@media (max-width: 768px) {
  .diff-line {
    display: block;
    line-height: 1.7;
    margin-bottom: 4px;
  }

  .diff-label {
    width: auto;
    margin-right: 6px;
  }

  .diff-arrow {
    display: none;
  }

  .diff-new::before {
    content: '→ ';
    color: var(--el-text-color-disabled);
  }
}

/* 反馈详情弹窗里的样式 */
.detail-header {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 16px;
}

.detail-header h4 {
  margin: 0 0 8px 0;
  font-size: 16px;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.detail-time {
  margin-left: auto;
}

.detail-body {
  line-height: 1.8;
  color: var(--el-text-color-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.attachment-block {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.attachment-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  margin-bottom: 8px;
}

.attachment-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  padding: 4px 0;
}

/* 长文件名要能断行，否则会把大小挤出去、撑破弹窗 */
.attachment-name {
  color: #409eff;
  cursor: pointer;
  word-break: break-all;
}

.attachment-name:hover {
  text-decoration: underline;
}

.attachment-size {
  margin-left: auto;
  flex-shrink: 0;
}

.reply-block {
  margin-top: 20px;
  padding: 16px;
  background: var(--el-color-success-light-9);
  border-radius: 8px;
  border-left: 4px solid #67c23a;
}

.reply-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #67c23a;
  margin-bottom: 8px;
}

.reply-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 10px;
}

.reply-content {
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}

.reply-form {
  margin-top: 16px;
}
</style>
