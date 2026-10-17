<template>
  <div v-loading="loading">
    <!-- 和其他页面一样：page-card 套 page-title，tab 在卡片里 -->
    <div class="page-card">
      <h3 class="page-title">我的信息</h3>

      <!-- 顶部 Tab：学生账号能看到「基本信息」，域外账号只有「账户设置」 -->
      <el-tabs v-model="activeTab">
        <!-- 基本信息：只有学生账号才有 -->
        <el-tab-pane v-if="!userStore.isExternal" label="基本信息" name="info">
          <!-- 和「账户设置」「办件空间」一样在内部再分子 tab：
               档案 / 申请 / 记录本来是各不相干的三件事，只是原先挤在一页里往下排 -->
          <el-tabs v-model="infoTab">
            <!-- ==================== 我的档案 ==================== -->
            <el-tab-pane label="我的档案" name="profile">
              <div class="tab-section">
                <template v-if="me">
                  <!-- 三张照片：高考照片 + 实地采集 + 自备证件照，点一下放大 -->
                  <div class="photos-row">
                    <div
                      v-for="item in PHOTOS"
                      :key="item.type"
                      class="photo-item"
                      :class="{ 'photo-empty-box': !hasPhoto(item.type) }"
                      @click="openPhotos(item.type)"
                    >
                      <img
                        v-if="hasPhoto(item.type)"
                        :src="photoUrl(item.type)"
                        class="photo-img"
                        :alt="item.label"
                        @error="onImgError"
                      />
                      <div v-else class="photo-placeholder">
                        <el-icon style="font-size: 34px;"><Avatar /></el-icon>
                        <span>暂无照片</span>
                      </div>
                      <div class="photo-label">{{ item.label }}</div>
                    </div>
                  </div>
                  <p class="photos-tip">点击照片可放大查看</p>

                  <el-descriptions :column="detailColumns" border style="margin-top: 16px;">
                    <el-descriptions-item label="学号">{{ me.student_no || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="姓名">{{ me.name || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="性别">{{ me.gender || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="出生日期">{{ me.birth_date || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="民族">{{ me.ethnicity || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="政治面貌">{{ me.political_status || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="学院/班级">{{ me.class_name || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="专业">{{ me.major || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="宿舍">{{ me.dormitory || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="床位号">{{ me.bed || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="本人电话">{{ me.phone || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="高考总分">{{ me.gaokao_score ?? '-' }}</el-descriptions-item>
                    <!-- 备注是班委内部记录，普通学生拿到的一律是 null，只有班委/管理员能看到自己的 -->
                    <el-descriptions-item v-if="me.remark" label="备注" :span="detailColumns">
                      {{ me.remark }}
                    </el-descriptions-item>
                  </el-descriptions>
                </template>
                <el-empty v-else-if="!loading" description="未获取到个人信息" />
              </div>
            </el-tab-pane>

            <!-- ==================== 申请修改 ==================== -->
            <el-tab-pane label="申请修改" name="apply">
              <div class="tab-section">
                <!-- 已经有一条排队等审：只解释原因，不给表单 -->
                <el-alert v-if="pending" type="warning" :closable="false" show-icon>
                  <template #title>
                    你有一条待审核的申请（{{ formatDateTime(pending.created_at) }} 提交），班委处理后才能再次提交。
                  </template>
                  <div style="margin-top: 4px;">{{ describeChanges(pending.changes) }}</div>
                </el-alert>

                <template v-else>
                  <p class="section-sub">改动提交后需班委审核，审核通过才会真正生效</p>
                  <el-form :model="form" label-width="100px" style="max-width: 640px; margin-top: 12px;">
                    <el-form-item v-for="f in CHANGE_FIELDS" :key="f.prop" :label="f.label">
                      <el-input
                        v-model="form[f.prop]"
                        :type="f.prop === 'family_address' ? 'textarea' : 'text'"
                        :rows="2"
                        :placeholder="f.placeholder"
                        :maxlength="f.maxLength"
                      />
                    </el-form-item>
                    <!-- 自备证件照单独一项：交的是文件，不是填字。
                         只换照片也算一次有效申请，所以不选就是不改，不强制 -->
                    <el-form-item label="自备证件照">
                      <div class="photo-pick">
                        <img
                          v-if="photoPreview"
                          :src="photoPreview"
                          class="photo-pick-img"
                          alt="新证件照预览"
                        />
                        <div>
                          <el-upload
                            :auto-upload="false"
                            :show-file-list="false"
                            accept=".jpg,.jpeg,.png,.gif,.bmp,.webp"
                            :on-change="handlePhotoChange"
                          >
                            <el-button>{{ photoFile ? '重新选择' : '选择照片' }}</el-button>
                          </el-upload>
                          <div class="photo-pick-tip">
                            支持 JPG / PNG 等图片，最大 10MB；不选就是不改。
                            <el-button v-if="photoFile" link type="danger" @click="clearPhoto">
                              取消
                            </el-button>
                          </div>
                        </div>
                      </div>
                    </el-form-item>

                    <el-form-item>
                      <el-button type="primary" :loading="submitting" @click="handleSubmit">提交申请</el-button>
                    </el-form-item>
                  </el-form>
                </template>
              </div>
            </el-tab-pane>

            <!-- ==================== 申请记录 ==================== -->
            <el-tab-pane label="申请记录" name="records">
              <div class="tab-section">
                <el-table :data="records" stripe border style="width: 100%;">
                  <el-table-column label="申请时间" width="160" align="center">
                    <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
                  </el-table-column>
                  <el-table-column label="申请修改的内容" min-width="260">
                    <template #default="{ row }">{{ describeChanges(row.changes) }}</template>
                  </el-table-column>
                  <el-table-column label="状态" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag :type="STATUS_TYPES[row.status]" size="small">
                        {{ STATUS_LABELS[row.status] || row.status }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="审核人" width="100" align="center">
                    <template #default="{ row }">{{ row.reviewer_name || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="审核时间" width="160" align="center">
                    <template #default="{ row }">{{ formatDateTime(row.reviewed_at) }}</template>
                  </el-table-column>
                  <el-table-column label="驳回理由" min-width="160">
                    <template #default="{ row }">
                      <span :style="{ color: row.reason ? '#f56c6c' : '#c0c4cc' }">{{ row.reason || '-' }}</span>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-if="!records.length" description="还没有提交过申请" style="margin-top: 20px;" />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <!-- 我的成绩：只有学生账号才有。**必须是顶层 tab** ——
             「办件空间」那一层的二级 tab 被 ?sub= 占着，塞进去就没法从站内信直接跳过来 -->
        <el-tab-pane v-if="!userStore.isExternal" label="我的成绩" name="grades">
          <div v-loading="gradesLoading" class="workspace-list">
            <div v-if="gradesList.length" class="case-list">
              <div v-for="item in gradesList" :key="item.test_id" class="case-item">
                <div class="case-header">
                  <el-tag size="small" type="primary" effect="plain">{{ formatDate(item.tested_at) }}</el-tag>
                </div>
                <div class="case-title">{{ item.name }}</div>
                <el-table :data="item.scores" size="small" class="grade-table">
                  <el-table-column prop="subject" label="科目" min-width="120" />
                  <el-table-column label="成绩" width="200">
                    <template #default="{ row }">
                      <!-- 通过制：通过 / 不通过本身就是成绩，用绿红两色，
                           跟缺考那种橙色标记区分开 -->
                      <div v-if="row.mode === 'pass_fail' && PASS_VALUES.includes(row.value)"
                           :class="row.value === '通过' ? 'grade-pass' : 'grade-fail'">
                        {{ row.value }}
                      </div>
                      <template v-else-if="row.value">
                        <div :class="{ 'grade-mark': !isScore(row.value) }">{{ row.value }}</div>
                        <!-- 位次只给自己的。平均分、最高最低、分数段、及格率
                             都是班级层面的统计，一律班委及以上才看得到 -->
                        <div v-if="row.rank_percent != null" class="grade-rank">
                          排在前 {{ row.rank_percent }}%
                        </div>
                      </template>
                      <div v-else class="grade-none">未录入</div>
                    </template>
                  </el-table-column>
                </el-table>
                <div v-if="item.remark" class="case-meta">备注：{{ item.remark }}</div>
              </div>
            </div>
            <el-empty
              v-if="!gradesLoading && !gradesList.length"
              description="还没有成绩记录"
              style="margin-top: 20px;"
            />
          </div>
        </el-tab-pane>

        <!-- 账户设置：改密码 + 通知设置，所有登录用户都能看到 -->
        <el-tab-pane label="账户设置" name="account">
          <!-- 账户设置内部再分三个子 tab。原来是一长条滚动页，加了 webhook 和邮件
               两个渠道之后太长，而且「改密 / 通知 / 日志」本来也是各不相干的三件事 -->
          <el-tabs v-model="accountTab">
            <!-- ==================== 账号安全 ==================== -->
            <el-tab-pane label="账号安全" name="security">
              <!-- 修改密码 -->
              <div class="tab-section">
                <h3 class="page-title">修改密码</h3>
                <el-form :model="pwdForm" label-width="100px" style="max-width: 480px; margin-top: 12px;">
                  <el-form-item label="原密码">
                    <el-input v-model="pwdForm.old_password" type="password" show-password />
                  </el-form-item>
                  <el-form-item label="新密码">
                    <el-input
                      v-model="pwdForm.new_password"
                      type="password"
                      show-password
                      placeholder="6-32 位，需同时包含字母和数字"
                    />
                  </el-form-item>
                  <el-form-item label="确认密码">
                    <el-input
                      v-model="pwdForm.confirm"
                      type="password"
                      show-password
                      @keyup.enter="handleChangePassword"
                    />
                  </el-form-item>
                  <el-form-item>
                    <el-button type="primary" :loading="pwdLoading" @click="handleChangePassword">
                      确认修改
                    </el-button>
                  </el-form-item>
                </el-form>
              </div>

              <!-- 访问令牌：同样是「账号安全」范畴（拿到令牌等于拿到你的账号），
                   所以和修改密码放同一个 tab。组件自己是折叠的，平时不占地方 -->
              <el-divider />
              <AccessTokenSetting />

              <!-- 通行密钥：同样是账号安全的范畴，和访问令牌并列 -->
              <el-divider />
              <PasskeySetting />

              <!-- 二次验证：密码之外再加一道，和通行密钥一样属于登录方式 -->
              <el-divider />
              <TwoFactorSetting />
            </el-tab-pane>

            <!-- ==================== 通知设置 ==================== -->
            <el-tab-pane label="通知设置" name="notify">
              <div class="tab-section">
                <p class="section-sub" style="margin-bottom: 12px;">
                  有审核结果、新通知等情况时，通过以下方式推送给你
                </p>

                <!-- 安装到桌面：Chrome/Edge/Android 能触发原生安装横幅，iOS 没有 -->
                <el-alert
                  v-if="!standalone && canInstall"
                  type="success"
                  :closable="false"
                  show-icon
                  style="margin-bottom: 16px;"
                >
                  <template #title>把这个应用装到桌面</template>
                  <div class="install-row">
                    <span>装进桌面后像原生应用一样打开，全屏显示，没有地址栏。</span>
                    <el-button type="primary" size="small" :loading="installing" @click="handleInstall">
                      安装应用
                    </el-button>
                  </div>
                </el-alert>

                <!-- ==================== 浏览器通知 ==================== -->
                <div class="section-title">浏览器通知</div>
                <div class="section-sub">用本机浏览器直接收，不用装任何东西</div>

                <!-- 不支持 / 环境限制 -->
                <el-alert v-if="webState === 'blocked'" type="warning" :closable="false" show-icon>
                  <template #title>当前环境用不了浏览器通知</template>
                  {{ webNote }}
                </el-alert>

                <!-- iPhone：普通标签页里连权限弹窗都弹不出来，必须先添加到主屏 -->
                <el-alert v-else-if="webState === 'ios-tab'" type="info" :closable="false" show-icon>
                  <template #title>iPhone 上需要先「添加到主屏」</template>
                  在 Safari 里点底部的分享按钮 →「添加到主屏」，然后<b>从主屏图标打开</b>本应用，
                  再回到这里开启通知。普通标签页里收不到网页通知，这是 iOS 的限制。
                </el-alert>

                <!-- 浏览器记住了「不允许」 -->
                <el-alert v-else-if="webState === 'denied'" type="warning" :closable="false" show-icon>
                  <template #title>本站的通知被浏览器拒绝了</template>
                  点地址栏左侧的站点设置，把「通知」改回「允许」，然后重新开启。
                </el-alert>

                <template v-else>
                  <div class="status-row">
                    <el-tag v-if="webState === 'on'" type="success" size="small">已开启</el-tag>
                    <el-tag v-else type="info" size="small">未开启</el-tag>
                    <span class="desc">
                      {{ webState === 'on' ? '本机浏览器已订阅' : '开启后本机能收到站内通知' }}
                    </span>
                  </div>

                  <div v-if="webCount > 0" class="desc count">
                    本账号共有 {{ webCount }} 台设备已开启浏览器通知
                  </div>

                  <div class="actions">
                    <el-button
                      v-if="webState === 'off'"
                      type="primary"
                      size="small"
                      :loading="webBusy"
                      @click="handleWebEnable"
                    >
                      开启通知
                    </el-button>
                    <template v-else>
                      <el-button size="small" :loading="webTesting" @click="handleWebTest">
                        发送测试
                      </el-button>
                      <el-button size="small" :loading="webBusy" @click="handleWebDisable">
                        关闭通知
                      </el-button>
                    </template>
                  </div>
                </template>

                <el-divider />

                <!-- ==================== Bark 推送 ==================== -->
                <div class="section-title">Bark 推送</div>
                <div class="section-sub">手机上装 Bark App，填一个设备 ID 就能收</div>

                <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px;">
                  <template #title>怎么拿到设备 ID</template>
                  在手机上装好 Bark App，打开后首页显示的那串字符就是设备 ID。
                  复制粘贴到下面即可（粘整条链接也行，会自动识别）。
                </el-alert>

                <el-form :model="barkForm" label-width="100px">
                  <el-form-item label="设备 ID">
                    <el-input
                      v-model="barkForm.bark_key"
                      placeholder="留空并保存 = 关闭推送"
                      clearable
                      @keyup.enter="handleBarkSave"
                    />
                  </el-form-item>
                </el-form>

                <div class="actions">
                  <el-button size="small" :loading="barkTesting" @click="handleBarkTest">发送测试推送</el-button>
                  <el-button type="primary" size="small" :loading="barkSaving" @click="handleBarkSave">保存</el-button>
                  <el-button v-if="savedBarkKey" link type="danger" size="small" @click="handleBarkUnbind">
                    解除绑定
                  </el-button>
                </div>

                <!-- ==================== 两个后加的渠道 ====================
                     整块藏在 newChannelsAvailable 后面：新前端配旧后端时这几个接口是 404，
                     与其给用户看半截能用、点一下报错的界面，不如不显示（见 fetchAccountData） -->
                <template v-if="newChannelsAvailable">
                  <el-divider />

                  <WebhookSetting />

                  <el-divider />

                  <EmailNotifySetting />
                </template>
              </div>
            </el-tab-pane>

            <!-- ==================== 我的日志 ==================== -->
            <el-tab-pane label="我的日志" name="logs">
              <div class="tab-section">
                <div class="section-title">操作日志</div>
                <div class="section-sub">我自己做过的事（发布通知、审核办件、点名等）</div>
                <el-table
                  v-loading="logsLoading"
                  :data="myLogs.operations.items"
                  stripe
                  border
                  style="width: 100%;"
                >
                  <el-table-column label="时间" width="160" align="center">
                    <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
                  </el-table-column>
                  <el-table-column prop="action" label="动作" width="120" align="center" />
                  <el-table-column prop="target" label="对象" min-width="150" show-overflow-tooltip />
                  <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
                </el-table>
                <el-empty
                  v-if="!logsLoading && !myLogs.operations.total"
                  description="还没有操作记录"
                  :image-size="60"
                />
                <div v-if="myLogs.operations.total" class="pagination-wrap">
                  <el-pagination
                    v-model:current-page="logPage"
                    v-model:page-size="logPageSize"
                    :page-sizes="[20, 50, 100, 200]"
                    :total="myLogs.operations.total"
                    layout="total, sizes, prev, pager, next"
                    background
                    @size-change="fetchMyLogs"
                    @current-change="fetchMyLogs"
                  />
                </div>

                <div class="section-title" style="margin-top: 20px;">
                  登录与账号操作
                  <!-- 把 7 天这个边界显示出来，不然只会让人猜为什么只有这几条 -->
                  <span class="section-sub" style="margin-left: 8px;">
                    仅最近 7 天（{{ formatDateTime(myLogs.events_since) }} 起）
                  </span>
                </div>
                <el-table v-loading="logsLoading" :data="myLogs.events" stripe border style="width: 100%;">
                  <el-table-column label="时间" width="160" align="center">
                    <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
                  </el-table-column>
                  <el-table-column label="事件" width="120" align="center">
                    <template #default="{ row }">
                      <el-tag v-if="row.event === 'login'" type="info" size="small">登录</el-tag>
                      <el-tag v-else-if="row.event === 'change_password'" type="warning" size="small">
                        修改密码
                      </el-tag>
                      <el-tag v-else-if="row.event === 'token_create'" type="success" size="small">
                        创建令牌
                      </el-tag>
                      <el-tag v-else-if="row.event === 'token_revoke'" type="danger" size="small">
                        吊销令牌
                      </el-tag>
                      <!-- 兜底显示原始事件名：后端将来加新事件类型时，这里不会变成一片空白 -->
                      <span v-else>{{ row.event }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="IP" min-width="150" align="center">
                    <template #default="{ row }">
                      <span v-if="row.ip" style="font-family: monospace; font-size: 12px;">{{ row.ip }}</span>
                      <span v-else style="color: var(--el-text-color-disabled);">-</span>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty
                  v-if="!logsLoading && !myLogs.events_total"
                  description="最近 7 天没有登录或账号操作记录"
                  :image-size="60"
                />
                <div v-if="myLogs.events_total" class="pagination-wrap">
                  <el-pagination
                    v-model:current-page="logEventPage"
                    v-model:page-size="logEventPageSize"
                    :page-sizes="[20, 50, 100, 200]"
                    :total="myLogs.events_total"
                    layout="total, sizes, prev, pager, next"
                    background
                    @size-change="fetchMyLogs"
                    @current-change="fetchMyLogs"
                  />
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <!-- 办件空间：我申请的 / 我审批的 -->
        <el-tab-pane label="办件空间" name="workspace">
          <el-tabs v-model="workspaceTab">
            <!-- 我申请的 -->
            <el-tab-pane label="我申请的" name="submitted">
              <div v-loading="submittedLoading" class="workspace-list">
                <div v-if="submittedList.length" class="case-list">
                  <div
                    v-for="item in submittedList"
                    :key="`${item.type}-${item.id}`"
                    class="case-item"
                    @click="goToDetail(item)"
                  >
                    <div class="case-header">
                      <el-tag size="small" type="info" effect="plain">{{ item.type_name }}</el-tag>
                      <el-tag :type="item.status_type" size="small">{{ item.status_label }}</el-tag>
                    </div>
                    <div class="case-title">{{ item.title }}</div>
                    <div class="case-meta">
                      <span>提交时间：{{ formatDateTime(item.created_at) }}</span>
                      <span v-if="item.updated_at && item.updated_at !== item.created_at">
                        处理时间：{{ formatDateTime(item.updated_at) }}
                      </span>
                    </div>
                    <div v-if="item.reviewer_name" class="case-meta">
                      处理人：{{ item.reviewer_name }}
                    </div>
                    <div v-if="item.reason" class="case-reason">
                      驳回理由：{{ item.reason }}
                    </div>
                    <div class="case-actions" @click.stop>
                      <el-button size="small" type="primary" link @click="goToDetail(item)">
                        查看详情
                      </el-button>
                    </div>
                  </div>
                </div>
                <el-empty
                  v-if="!submittedLoading && !submittedList.length"
                  description="暂无申请记录"
                  style="margin-top: 20px;"
                />
              </div>
            </el-tab-pane>

            <!-- 我审批的 -->
            <el-tab-pane v-if="canReview" label="我审批的" name="involved">
              <div v-loading="involvedLoading" class="workspace-list">
                <div v-if="involvedList.length" class="case-list">
                  <div
                    v-for="item in involvedList"
                    :key="`${item.type}-${item.id}`"
                    class="case-item"
                    @click="goToDetail(item)"
                  >
                    <div class="case-header">
                      <el-tag size="small" type="info" effect="plain">{{ item.type_name }}</el-tag>
                      <el-tag :type="item.status_type" size="small">{{ item.status_label }}</el-tag>
                    </div>
                    <div class="case-title">{{ item.title }}</div>
                    <div class="case-meta">
                      <span>申请人：{{ item.applicant_name || '-' }}
                        <span v-if="item.applicant_no" style="color:#909399;">({{ item.applicant_no }})</span>
                      </span>
                    </div>
                    <div class="case-meta">
                      <span>申请时间：{{ formatDateTime(item.created_at) }}</span>
                      <span v-if="item.updated_at">处理时间：{{ formatDateTime(item.updated_at) }}</span>
                    </div>
                    <div v-if="item.reason" class="case-reason">
                      驳回理由：{{ item.reason }}
                    </div>
                    <div class="case-actions" @click.stop>
                      <el-button size="small" type="primary" link @click="goToDetail(item)">
                        查看详情
                      </el-button>
                    </div>
                  </div>
                </div>
                <el-empty
                  v-if="!involvedLoading && !involvedList.length"
                  description="暂无处理记录"
                  style="margin-top: 20px;"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 照片查看器 -->
    <el-image-viewer
      v-if="viewerVisible"
      :url-list="viewerList"
      :initial-index="viewerIndex"
      @close="viewerVisible = false"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMyInfo } from '@/api/student'
import { changePassword, getMyLogs } from '@/api/auth'
import { submitChangeRequest, getMyChangeRequests } from '@/api/changeRequest'
import {
  getBarkSetting,
  saveBarkSetting,
  testBarkPush
} from '@/api/bark'
import {
  getWebpushState,
  saveWebpushSubscription,
  removeWebpushSubscription,
  testWebpush
} from '@/api/webpush'
import {
  CHANGE_FIELDS,
  FIELD_LABELS,
  PHOTO_FIELD,
  STATUS_LABELS,
  STATUS_TYPES
} from '@/utils/changeFields'
import { formatDate, formatDateTime } from '@/utils/format'
import { useIsMobile } from '@/composables/useIsMobile'
import { useUserStore } from '@/store/user'
import { rankOf } from '@/utils/roles'
import { getMySubmitted, getMyInvolved } from '@/api/workspace'
import { getMyGrades } from '@/api/grade'
import { getWebhookSetting } from '@/api/notifyChannels'
import WebhookSetting from '@/components/WebhookSetting.vue'
import AccessTokenSetting from '@/components/AccessTokenSetting.vue'
import PasskeySetting from '@/components/PasskeySetting.vue'
import TwoFactorSetting from '@/components/TwoFactorSetting.vue'
import EmailNotifySetting from '@/components/EmailNotifySetting.vue'
import {
  isSupported,
  isIos,
  isStandalone as checkIsStandalone,
  canInstall as checkCanInstall,
  triggerInstallPrompt,
  currentSubscription,
  subscribe,
  unsubscribe
} from '@/utils/webpush'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 手机上 3 列会把标签挤成竖排（「政 治 面 貌」），收成 1 列
const isMobile = useIsMobile()
const detailColumns = computed(() => (isMobile.value ? 1 : 3))

// 当前激活的 tab：从 URL query 读，域外账号默认是账户设置
const activeTab = ref('info')

// 同步 URL 的 tab 参数（支持分享链接直接定位到某个 tab）
// 注意：这里必须认识全部 tab。漏掉一个的话，点它就会立刻被这个 watcher
// 拽回默认 tab（切 tab 时同 URL 会被反写一次），表现成「点了没反应」
watch(
  () => route.query.tab,
  (val) => {
    // 域外账号没有「基本信息」和「我的成绩」——这两块都挂在学生身份上，
    // 带 ?tab=grades 进来若放行，pane 是 v-if 掉的、内容区空白，还会白拉一次接口吃 403
    const known = ['info', 'grades', 'account', 'workspace']
    const hidden = (val === 'info' || val === 'grades') && userStore.isExternal
    if (known.includes(val) && !hidden) {
      activeTab.value = val
    } else {
      // 默认 tab：学生 → info，域外 → account
      activeTab.value = userStore.isExternal ? 'account' : 'info'
    }
  },
  { immediate: true }
)

// 切换 tab 时更新 URL，方便刷新后还在同一个 tab
watch(activeTab, (val) => {
  if (route.query.tab !== val) {
    router.replace({ query: { ...route.query, tab: val } })
  }
})

// 三个照片位，字段名与后端 students 表一致。前两张是考试院/学校采集的，
// 只有自备证件照是学生自己交的 —— 所以也只有它能在「申请修改」里换（见 photoFile）
const PHOTOS = [
  { type: 'gaokao', field: 'gaokao_photo', label: '高考照片' },
  { type: 'on_site', field: 'on_site_photo', label: '实地采集' },
  { type: 'id', field: 'id_photo', label: '自备证件照' }
]

const loading = ref(false)
const me = ref(null)
const records = ref([])

const submitting = ref(false)

// 表单先摆全部字段，拿到自己的信息后再回填
const form = reactive(Object.fromEntries(CHANGE_FIELDS.map((f) => [f.prop, ''])))

// 申请修改里选中的新证件照。文件不进 form（form 里全是字符串），单独放这里：
// 提交时作为 multipart 的 photo 一并发出，后端落盘后自己填 id_photo
const photoFile = ref(null)
// 本地预览地址。提交前就能看到选的这张，不用先传后端
const photoPreview = ref('')

/** 已经有一条排队等着审，就锁住表单（后端也会拒，前端锁住体验更好） */
const pending = computed(() => records.value.find((r) => r.status === 'pending'))

// 照片查看器
const viewerVisible = ref(false)
const viewerList = ref([])
const viewerIndex = ref(0)

// ---------- 修改密码 ----------
const pwdLoading = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

// ---------- 通知设置 ----------
const installing = ref(false)
const standalone = ref(false)
const canInstall = ref(false)

// 浏览器通知
const webState = ref('off')
const webNote = ref('')
const webBusy = ref(false)
const webTesting = ref(false)
const webCount = ref(0)
const vapidKey = ref('')

// Bark
const barkSaving = ref(false)
const barkTesting = ref(false)
const savedBarkKey = ref('')
const barkForm = reactive({ bark_key: '' })

// 后端有没有自定义 webhook / 邮件这两个渠道的接口。探测失败（旧后端 404）就整块不显示
const newChannelsAvailable = ref(false)

const KEY_PATTERN = /^[A-Za-z0-9_-]{5,128}$/

// 账户设置内部的子 tab：账号安全 / 通知设置 / 我的日志
// 基本信息的三个子 tab：档案 / 申请修改 / 申请记录
const infoTab = ref('profile')
const accountTab = ref('security')

// ---------- 我的日志 ----------
// 形状与后端 /auth/my-logs 一致：操作日志、登录/改密各自分页
const myLogs = ref({
  operations: { total: 0, items: [] },
  events: [],
  events_total: 0,
  events_since: null
})
const logsLoading = ref(false)
const logPage = ref(1)
const logPageSize = ref(20)
// 登录与改密那一块自己的页码：它和操作日志是两个独立的列表
// （一个是全量历史、一个是 7 天窗口），共用一个页码会互相打架
const logEventPage = ref(1)
const logEventPageSize = ref(20)

async function fetchMyLogs() {
  logsLoading.value = true
  try {
    myLogs.value = await getMyLogs({
      page: logPage.value,
      page_size: logPageSize.value,
      events_page: logEventPage.value,
      events_page_size: logEventPageSize.value
    })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '日志加载失败')
  } finally {
    logsLoading.value = false
  }
}

// ---------- 办件空间 ----------
const workspaceTab = ref('submitted')
const submittedList = ref([])
const submittedLoading = ref(false)
const involvedList = ref([])
const involvedLoading = ref(false)

// 能不能看到「我审批的」tab：班委及以上
const canReview = computed(() => rankOf(userStore.info?.role) >= rankOf('committee'))

// 同步 URL 的 sub 参数（办件空间内的子 tab）。
// immediate 是为了让通知里的 ...&sub=involved 直接落到「我审批的」
watch(
  () => route.query.sub,
  (val) => {
    if (val === 'involved' && canReview.value) {
      workspaceTab.value = 'involved'
    } else {
      workspaceTab.value = 'submitted'
    }
  },
  { immediate: true }
)

watch(workspaceTab, (val) => {
  if (activeTab.value !== 'workspace') return
  if (route.query.sub !== val) {
    router.replace({ query: { ...route.query, sub: val } })
  }
})

// ---------- 我的成绩 ----------

const gradesList = ref([])
const gradesLoading = ref(false)

/** 这格是分数还是标记词（缺考/免修…）。空串永远不会走到这里，调用处已经挡了 */
function isScore(value) {
  return value !== '' && !Number.isNaN(Number(value))
}

/** 通过制科目能填的两个值。与后端 models/grade.py 的 PASS_VALUES 一致 ——
 *  改那边要一起改这边。别的词（缺考等）在通过制科目里也是标记词，照旧橙色 */
const PASS_VALUES = ['通过', '不通过']

async function fetchMyGrades() {
  gradesLoading.value = true
  try {
    // 同下面几个：接口返回 null 时退化成空数组，否则模板里的 .length 会白屏
    gradesList.value = (await getMyGrades()) || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    gradesLoading.value = false
  }
}

async function fetchSubmitted() {
  submittedLoading.value = true
  try {
    // 兜一层：接口若返回 null/undefined（旧后端、代理异常），列表 ref 会变成
    // undefined，模板里的 .length 立刻抛错、整个 tab 白屏 —— 连「暂无申请记录」
    // 都显示不出来。退化成空数组至少还能正常显示空状态。
    submittedList.value = (await getMySubmitted()) || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    submittedLoading.value = false
  }
}

async function fetchInvolved() {
  if (!canReview.value) return
  involvedLoading.value = true
  try {
    involvedList.value = (await getMyInvolved()) || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    involvedLoading.value = false
  }
}

// 切到办件空间 / 账户设置时才拉数据，避免白跑请求。
// immediate 是给「直接带着 ?tab=workspace 进来」用的（通知点击就是这条路径）：
// 顶上那个读 URL 的 watcher 在 setup 阶段就把 activeTab 定好了，
// 非 immediate 的 watcher 建的时候看到的就是终值，永远不会触发，页面就空着
watch(
  activeTab,
  (val) => {
    if (val === 'workspace') {
      fetchSubmitted()
      if (canReview.value && workspaceTab.value === 'involved') {
        fetchInvolved()
      }
    }
    if (val === 'account') fetchMyLogs()
    if (val === 'grades') fetchMyGrades()
  },
  { immediate: true }
)

watch(workspaceTab, (val) => {
  if (activeTab.value !== 'workspace') return
  if (val === 'submitted') fetchSubmitted()
  if (val === 'involved') fetchInvolved()
})

function goToDetail(item) {
  if (item.detail_url) {
    router.push(item.detail_url)
  }
}

/** 照片走带鉴权的接口，不直连静态目录（和「学生信息」页一个取法） */
function photoUrl(type) {
  return `/api/students/${me.value?.id}/photo?type=${type}`
}

function hasPhoto(type) {
  const field = PHOTOS.find((p) => p.type === type)?.field
  return !!me.value?.[field]
}

function onImgError(e) {
  e.target.style.display = 'none'
}

/** 打开查看器：只在已有的照片之间翻页 */
function openPhotos(activeType) {
  const photos = PHOTOS.filter((p) => hasPhoto(p.type))
  if (!photos.length) return
  viewerList.value = photos.map((p) => photoUrl(p.type))
  const index = photos.findIndex((p) => p.type === activeType)
  viewerIndex.value = index >= 0 ? index : 0
  viewerVisible.value = true
}

/** 把 {"qq":"123","email":null} 说成「QQ号码：123；电子邮箱：（清空）」 */
function describeChanges(changes) {
  const parts = Object.entries(changes || {}).map(([key, value]) => {
    // 照片那一项的值是服务端生成的文件名，甩给学生看没有任何意义
    if (key === PHOTO_FIELD.prop) return `${PHOTO_FIELD.label}：已上传新照片`
    return `${FIELD_LABELS[key] || key}：${value ? value : '（清空）'}`
  })
  return parts.length ? parts.join('；') : '-'
}

/** 选中一张新证件照：留文件、生成本地预览。不设 limit，再选一张就是替换 */
function handlePhotoChange(file) {
  // el-upload 的 raw 才是真实文件对象
  photoFile.value = file.raw || file
  if (photoPreview.value) URL.revokeObjectURL(photoPreview.value)
  photoPreview.value = URL.createObjectURL(photoFile.value)
}

function clearPhoto() {
  // 预览地址是 blob:，不主动回收会一直占着那张图的内存
  if (photoPreview.value) URL.revokeObjectURL(photoPreview.value)
  photoPreview.value = ''
  photoFile.value = null
}

/** 回填表单：显示当前值，学生在此基础上改 */
function resetForm() {
  for (const { prop } of CHANGE_FIELDS) {
    form[prop] = me.value?.[prop] ?? ''
  }
}

/** 只把改动过的字段提交上去，避免整表覆盖 */
function buildChanges() {
  const changes = {}
  for (const { prop } of CHANGE_FIELDS) {
    const next = (form[prop] ?? '').trim()
    const old = (me.value?.[prop] ?? '').trim()
    if (next !== old) changes[prop] = next
  }
  return changes
}

function validate() {
  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
    ElMessage.warning('电子邮箱格式不正确')
    return false
  }
  if (form.postal_code && !/^\d{6}$/.test(form.postal_code.trim())) {
    ElMessage.warning('邮政编码应为 6 位数字')
    return false
  }
  return true
}

// ---------- 修改密码 ----------
async function handleChangePassword() {
  if (!pwdForm.old_password) return ElMessage.warning('请输入原密码')
  if (pwdForm.new_password.length < 6 || pwdForm.new_password.length > 32) {
    return ElMessage.warning('新密码长度需为 6-32 位')
  }
  if (!/[A-Za-z]/.test(pwdForm.new_password) || !/\d/.test(pwdForm.new_password)) {
    return ElMessage.warning('新密码必须同时包含字母和数字')
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    return ElMessage.warning('两次输入的新密码不一致')
  }

  pwdLoading.value = true
  try {
    await changePassword({
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password
    })
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm = ''
    ElMessage.success('密码修改成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  } finally {
    pwdLoading.value = false
  }
}

// ---------- 通知设置：浏览器通知 ----------
function cleanKey(raw) {
  let text = (raw || '').trim()
  if (text.includes('://')) {
    text = text.split('://')[1]
    text = text.includes('/') ? text.split('/')[1] : ''
  }
  return text.split('/')[0].split('?')[0].trim()
}

async function refreshWebState() {
  if (!isSupported()) {
    webState.value = 'blocked'
    webNote.value =
      '这个浏览器没有提供网页通知能力，可以改用下面的 Bark 推送，或换 Chrome / Edge / Safari 打开本站。'
    return
  }
  if (isIos() && !checkIsStandalone()) {
    webState.value = 'ios-tab'
    return
  }
  if (Notification.permission === 'denied') {
    webState.value = 'denied'
    return
  }
  try {
    webState.value = (await currentSubscription()) ? 'on' : 'off'
  } catch (e) {
    webState.value = 'blocked'
    webNote.value = '浏览器通知要求以 HTTPS 打开本站，用 http 或局域网 IP 访问时用不了。'
  }
}

async function loadWebpushServerState() {
  const data = await getWebpushState()
  vapidKey.value = data.vapid_public_key || ''
  webCount.value = data.count || 0

  // 对账：本机明明有订阅，服务端却一条都没有 —— 顺手补登记一次
  const sub = await currentSubscription().catch(() => null)
  if (sub && webCount.value === 0) {
    await saveWebpushSubscription(sub.toJSON())
    webCount.value = 1
  }
}

async function handleWebEnable() {
  if (!vapidKey.value) return ElMessage.error('推送服务还没准备好，请稍后重试')

  webBusy.value = true
  try {
    const sub = await subscribe(vapidKey.value)
    await saveWebpushSubscription(sub.toJSON())
    await refreshWebState()
    await loadWebpushServerState()
    ElMessage.success('已开启，本机会收到浏览器通知')
  } catch (e) {
    await refreshWebState()
    ElMessage.error(e?.response?.data?.detail || e?.message || '开启失败')
  } finally {
    webBusy.value = false
  }
}

async function handleWebDisable() {
  webBusy.value = true
  try {
    const sub = await currentSubscription()
    if (sub) {
      await removeWebpushSubscription(sub.endpoint)
      await unsubscribe()
    }
    await refreshWebState()
    await loadWebpushServerState()
    ElMessage.success('已关闭浏览器通知')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '操作失败')
  } finally {
    webBusy.value = false
  }
}

async function handleWebTest() {
  webTesting.value = true
  try {
    const res = await testWebpush()
    ElMessage.success(res.message || '已发送，请查看本机通知')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发送失败')
  } finally {
    webTesting.value = false
  }
}

async function handleInstall() {
  installing.value = true
  try {
    const ok = await triggerInstallPrompt()
    if (ok) {
      ElMessage.success('已添加到桌面')
      canInstall.value = false
    }
  } catch (e) {
    ElMessage.error('安装失败')
  } finally {
    installing.value = false
  }
}

// ---------- 通知设置：Bark ----------
function checkedKey() {
  const raw = barkForm.bark_key.trim()
  const key = cleanKey(raw)
  if (raw && !key) {
    ElMessage.warning('没能从里面认出设备 ID，请从 Bark App 首页复制')
    return null
  }
  if (key && !KEY_PATTERN.test(key)) {
    ElMessage.warning('设备 ID 格式不对，请从 Bark App 首页完整复制')
    return null
  }
  return key
}

async function handleBarkSave() {
  const key = checkedKey()
  if (key === null) return
  barkSaving.value = true
  try {
    const res = await saveBarkSetting(key)
    savedBarkKey.value = key
    barkForm.bark_key = key
    ElMessage.success(res.message || '设置成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    barkSaving.value = false
  }
}

async function handleBarkTest() {
  const key = checkedKey()
  if (key === null) return
  if (!key) return ElMessage.warning('请先填入设备 ID')

  barkTesting.value = true
  try {
    await saveBarkSetting(key)
    savedBarkKey.value = key
    barkForm.bark_key = key
    const res = await testBarkPush()
    ElMessage.success(res.message || '已发送，请查看手机')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '推送失败')
  } finally {
    barkTesting.value = false
  }
}

async function handleBarkUnbind() {
  barkSaving.value = true
  try {
    const res = await saveBarkSetting('')
    savedBarkKey.value = ''
    barkForm.bark_key = ''
    ElMessage.success(res.message || '已解除绑定')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    barkSaving.value = false
  }
}

// ---------- 申请修改 ----------
async function handleSubmit() {
  if (pending.value) return ElMessage.warning('已有一条待审核的申请')
  if (!validate()) return
  const changes = buildChanges()
  // 只换一张照片也是一次有效申请，所以判据要带上传的文件
  if (!Object.keys(changes).length && !photoFile.value) {
    return ElMessage.warning('没有修改任何内容')
  }

  submitting.value = true
  try {
    // 选没选照片决定了这条路走 JSON 还是 multipart，判断在 api 层
    await submitChangeRequest(changes, photoFile.value)
    ElMessage.success('已提交，等待班委审核')
    clearPhoto()
    // 跳到「申请记录」：刚提交的那条就在最上面，能立刻看到它的待审核状态
    infoTab.value = 'records'
    await fetchStudentData()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

// 学生专属数据（基本信息 + 申请记录），域外账号不加载
async function fetchStudentData() {
  if (userStore.isExternal) return
  me.value = await getMyInfo()
  records.value = await getMyChangeRequests()
  resetForm()
}

// 账户设置数据（所有登录用户都加载）
async function fetchAccountData() {
  try {
    await refreshWebState()
    await loadWebpushServerState()
  } catch (e) {
    // 读不到状态不影响使用
  }

  try {
    const data = await getBarkSetting()
    savedBarkKey.value = data.bark_key || ''
    barkForm.bark_key = savedBarkKey.value
  } catch (e) {
    // 读不到 Bark 设置不影响改密码
  }

  // 探测后端有没有那两条新渠道的接口（webhook / 邮件），用来做灰度降级：
  // 新前端配旧后端时这里会 404，而 request.js 只特判 401，404 会一路 reject
  // 到用户脸上。与其让他看见「自定义 Webhook」展开后点什么都报错，不如整块不显示。
  // 探到就用同一个 getWebhookSetting —— 组件挂载后自己还会再拉一次，多这一个小 GET
  // 换「父组件不用替子组件保管数据」，值当。
  try {
    await getWebhookSetting()
    newChannelsAvailable.value = true
  } catch (e) {
    newChannelsAvailable.value = false
  }
}

async function fetchData() {
  loading.value = true
  try {
    // 两类数据并行拉
    await Promise.all([fetchStudentData().catch(() => {}), fetchAccountData().catch(() => {})])
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  // 确保登录状态已解析（路由守卫通常已经做了，但以防万一）
  if (!userStore.resolved) await userStore.fetchMe()

  // 安装 PWA 提示
  standalone.value = checkIsStandalone()
  canInstall.value = checkCanInstall()

  await fetchData()
})
</script>

<style scoped>
/* tab 内的分节：外层 page-card 已经给了白底和内边距，这里只要间距 */
.tab-section {
  margin-bottom: 28px;
}

.tab-section:last-child {
  margin-bottom: 0;
}

.page-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.photos-row {
  display: flex;
  gap: 20px;
  margin-top: 4px;
}

.photo-item {
  position: relative;
  width: 200px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  cursor: zoom-in;
}

.photo-empty-box {
  cursor: default;
}

.photo-img {
  width: 100%;
  height: 160px;
  object-fit: contain;
  display: block;
  background: var(--el-fill-color-light);
  padding: 8px;
  box-sizing: border-box;
}

.photo-placeholder {
  height: 160px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--el-text-color-disabled);
  background: var(--el-fill-color-light);
  font-size: 13px;
}

.photo-label {
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  text-align: center;
  padding: 6px 0;
  font-size: 13px;
}

/* 申请修改里选新证件照的那一行：左边预览、右边按钮 */
.photo-pick {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.photo-pick-img {
  width: 72px;
  height: 96px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--el-border-color);
}

.photo-pick-tip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.photos-tip {
  text-align: center;
  font-size: 12px;
  color: var(--el-text-color-disabled);
  margin: 8px 0 0 0;
  width: 100%;
  max-width: 420px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.section-sub {
  margin: 2px 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* 日志表格底部翻页（与系统管理页一致）。Admin.vue 里那份是 scoped 的，
   跨组件不生效，所以这边自己再来一份 */
.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.count {
  margin-bottom: 8px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0 0 0;
}

.install-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

/* ---------- 办件空间 ---------- */
.workspace-list {
  min-height: 200px;
}

.case-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 我的成绩：每次测试一张卡片，科目表紧跟在标题下面 */
.grade-table {
  margin-top: 8px;
}

/* 缺考 / 免修 / 缓考 / 违纪这些不是分数，换个颜色免得当成分数看 */
.grade-mark {
  color: var(--el-color-warning);
}

/* 通过制的两个取值。跟标记词的橙色分开：这是成绩本身，不是「没考」 */
.grade-pass {
  color: var(--el-color-success);
}

.grade-fail {
  color: var(--el-color-danger);
}

/* 位次小字：排在前 X% */
.grade-rank {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.grade-none {
  color: var(--el-text-color-placeholder);
}

.case-item {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px 16px;
  cursor: pointer;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.case-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}

.case-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.case-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  margin-bottom: 6px;
  line-height: 1.4;
}

.case-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  gap: 16px;
  line-height: 1.8;
  flex-wrap: wrap;
}

.case-reason {
  margin-top: 6px;
  font-size: 12px;
  color: #f56c6c;
}

.case-actions {
  margin-top: 8px;
  text-align: right;
}

/* 手机适配 */
@media (max-width: 768px) {
  .photos-row {
    flex-wrap: wrap;
  }
  .photo-item {
    width: calc(50% - 10px);
  }

  .case-item {
    padding: 12px;
  }

  .case-meta {
    gap: 12px;
  }
}
</style>
