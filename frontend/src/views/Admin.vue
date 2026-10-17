<template>
  <div class="page-card">
    <h3 class="page-title">系统管理</h3>

    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <!-- ============ 账号管理 ============ -->
      <el-tab-pane label="账号管理" name="users">
        <el-form :inline="true">
          <el-form-item label="搜索">
            <el-input
              v-model="userKeyword"
              placeholder="姓名或学号"
              clearable
              style="width: 200px"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="openCreateExternal">
              <el-icon><Plus /></el-icon>新建域外账号
            </el-button>
          </el-form-item>
        </el-form>

        <el-table :data="filteredUsers" v-loading="loadingUsers" stripe border style="width: 100%;">
          <el-table-column prop="student_no" label="学号" width="130" align="center" />
          <el-table-column prop="name" label="姓名" width="130" align="center">
            <template #default="{ row }">
              {{ row.name }}
              <!-- 冻结是能拦住登录的状态，必须一眼看得见，不能只藏在操作按钮的文字里 -->
              <el-tag v-if="row.is_frozen" type="danger" size="small">已冻结</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_external" type="warning" size="small">域外</el-tag>
              <el-tag v-else type="info" size="small">学生</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="160" align="center">
            <template #default="{ row }">
              <el-select
                :model-value="row.role"
                size="small"
                style="width: 130px"
                @change="(val) => handleRoleChange(row, val)"
              >
                <el-option
                  v-for="(label, value) in ROLE_LABELS"
                  :key="value"
                  :label="label"
                  :value="value"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="密码状态" width="150" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.must_change_password" type="warning" size="small">待改密</el-tag>
              <el-tag v-else type="success" size="small">已设置</el-tag>
            </template>
          </el-table-column>
          <!-- 每次登录成功都会刷新，点表头可排序，方便看出谁最近还没登过 -->
          <el-table-column prop="last_login_at" label="最近登录时间" width="170" align="center" sortable>
            <template #default="{ row }">
              <span v-if="row.last_login_at">{{ formatDateTime(row.last_login_at) }}</span>
              <span v-else style="color: var(--el-text-color-disabled);">从未登录</span>
            </template>
          </el-table-column>
          <el-table-column prop="last_login_ip" label="最近登录IP" width="150" align="center">
            <template #default="{ row }">
              <span v-if="row.last_login_ip" style="font-family: monospace; font-size: 12px;">
                {{ row.last_login_ip }}
              </span>
              <span v-else style="color: var(--el-text-color-disabled);">-</span>
            </template>
          </el-table-column>
          <el-table-column label="身份证号" width="100" align="center">
            <template #default="{ row }">
              <!-- 域外账号没有身份证号这一说 -->
              <span v-if="row.is_external" style="color: var(--el-text-color-disabled);">-</span>
              <el-tag v-else-if="row.has_id_card" type="info" size="small">已录入</el-tag>
              <el-tag v-else type="danger" size="small">缺失</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isMobile ? 175 : 265" align="center">
            <template #default="{ row }">
              <!-- 手机上 5 个按钮排不下（会把这列顶得比整屏还宽），
                   所以只直显 MOBILE_PRIMARY，其余收进「更多」下拉 -->
              <template v-if="isMobile">
                <el-button link type="primary" size="small" @click="primaryAction(row).run()">
                  {{ MOBILE_PRIMARY }}
                </el-button>
                <el-dropdown trigger="click" @command="(action) => action.run()">
                  <el-button link type="primary" size="small">
                    更多<el-icon><ArrowDown /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <!-- command 绑的是 action 对象本身，不是下标：过滤之后
                           下标和原数组对不上，会点「日志」执行「删除」 -->
                      <el-dropdown-item
                        v-for="action in restActions(row)"
                        :key="action.label"
                        :command="action"
                      >
                        {{ action.label }}
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </template>
              <template v-else>
                <el-button
                  v-for="action in rowActions(row)"
                  :key="action.label"
                  link
                  :type="action.type"
                  size="small"
                  @click="action.run()"
                >
                  {{ action.label }}
                </el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
        <div class="tip">
          共 {{ filteredUsers.length }} 个账号。域外账号不出现在学生名单、点名和各类统计里。
        </div>
      </el-tab-pane>

      <!-- ============ 操作日志 ============ -->
      <el-tab-pane label="操作日志" name="logs">
        <el-form :inline="true">
          <el-form-item label="操作人">
            <el-input v-model="logFilter.operator" placeholder="姓名或学号" clearable style="width: 160px" />
          </el-form-item>
          <el-form-item label="动作">
            <el-input v-model="logFilter.action" placeholder="如：发布通知" clearable style="width: 160px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="handleLogSearch">查询</el-button>
            <el-button @click="handleLogReset">重置</el-button>
            <el-button type="danger" plain :loading="clearingLogs" @click="handleClearLogs">
              清空日志
            </el-button>
          </el-form-item>
        </el-form>

        <el-table :data="logs" v-loading="loadingLogs" stripe border style="width: 100%;">
          <el-table-column label="时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作人" width="140" align="center">
            <template #default="{ row }">
              {{ row.operator_name || '-' }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.operator_no }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="action" label="动作" width="130" align="center" />
          <el-table-column prop="ip" label="操作IP" width="140" align="center">
            <template #default="{ row }">
              <span v-if="row.ip" style="font-family: monospace; font-size: 12px;">{{ row.ip }}</span>
              <span v-else style="color: var(--el-text-color-disabled);">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="target" label="对象" min-width="180" show-overflow-tooltip />
          <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip />
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="logPage"
            v-model:page-size="logPageSize"
            :page-sizes="[20, 50, 100, 200]"
            :total="logTotal"
            layout="total, sizes, prev, pager, next"
            background
            @size-change="fetchLogs"
            @current-change="fetchLogs"
          />
        </div>
      </el-tab-pane>

      <!-- ============ 文件访问日志 ============ -->
      <el-tab-pane label="文件访问日志" name="file-access">
        <el-form :inline="true">
          <el-form-item label="访问人">
            <el-input v-model="fileAccessFilter.user" placeholder="姓名或学号" clearable style="width: 160px" />
          </el-form-item>
          <el-form-item label="文件">
            <el-input v-model="fileAccessFilter.file" placeholder="按标题搜索" clearable style="width: 180px" />
          </el-form-item>
          <el-form-item label="动作">
            <el-select v-model="fileAccessFilter.action" placeholder="全部" clearable style="width: 120px">
              <el-option label="查看" value="view" />
              <el-option label="下载" value="download" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="handleFileAccessSearch">查询</el-button>
            <el-button @click="handleFileAccessReset">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 水印提取工具 -->
        <div class="watermark-extract-box">
          <span class="extract-label">水印溯源：</span>
          <input
            ref="watermarkFileInput"
            type="file"
            accept=".pdf,application/pdf"
            class="extract-file-input"
            @change="handleWatermarkExtract"
          />
          <!-- 要溯源的 PDF 可能几十 MB，慢网络下传好几分钟：
               没有进度的话，管理员只会以为点了没反应，然后重复上传 -->
          <span v-if="extractingWatermark" class="extract-progress">
            <el-icon class="is-loading"><Loading /></el-icon>
            正在上传 {{ extractLabel }}
          </span>
          <div v-if="watermarkResult" class="extract-result" :class="watermarkResult.found ? 'found' : 'not-found'">
            <template v-if="watermarkResult.found">
              <!-- 导出文件走另一套说法：它不是公告、没进文件访问日志，
                   水印里只有「这份文件是谁申请的、什么时候生成的」 -->
              <template v-if="watermarkResult.source_type === 'export'">
                <el-icon><CircleCheck /></el-icon>
                检测到水印：导出文件「{{ watermarkResult.file_title }}」
                <el-tag size="small" type="primary">{{ exportTypeText(watermarkResult.export_type) }}</el-tag>
                <el-tag size="small" type="info">{{ exportStatusText(watermarkResult.export_status) }}</el-tag>
                <div class="extract-hint">
                  申请人 <strong>{{ watermarkResult.user_name || watermarkResult.user_no }}</strong>
                  于 <strong>{{ formatDateTime(watermarkResult.accessed_at) }}</strong> 生成
                  <template v-if="watermarkResult.export_reviewer">
                    （{{ watermarkResult.export_reviewer }} 审核通过）
                  </template>
                  <template v-if="watermarkResult.export_scope">
                    ，导出范围：{{ watermarkResult.export_scope }}
                  </template>
                </div>
                <div class="extract-hint">
                  导出文件不进文件访问日志，只能确定「谁申请的、何时生成的」，
                  不能确定是谁下载走的
                </div>
              </template>

              <!-- 请假审批表也不进文件访问日志，但它的时间戳是**真的下载时间**
                   （令牌是下载那一刻现打的），所以这里能直接说「谁于何时下载的」 -->
              <template v-else-if="watermarkResult.source_type === 'leave'">
                <el-icon><CircleCheck /></el-icon>
                检测到水印：请假审批表「{{ watermarkResult.file_title }}」
                <div class="extract-hint">
                  <strong>{{ watermarkResult.user_name || watermarkResult.user_no }}</strong>
                  于 <strong>{{ formatDateTime(watermarkResult.accessed_at) }}</strong> 下载
                </div>
                <div class="extract-hint">
                  请假审批表不写文件访问日志（申请人本人和管理员下到的是同一份文件），
                  凭水印即可确定是谁下载的
                </div>
              </template>

              <!-- 电动车的申请表与承诺书和请假表一个待遇：不写访问日志，
                   时间戳也是**真的下载时间**。source_type 是 "evpass"，
                   到底是哪一份看 file_title（后端已经写成「某某的电动车通行证申请表（日期）」） -->
              <template v-else-if="watermarkResult.source_type === 'evpass'">
                <el-icon><CircleCheck /></el-icon>
                检测到水印：{{ watermarkResult.file_title }}
                <div class="extract-hint">
                  <strong>{{ watermarkResult.user_name || watermarkResult.user_no }}</strong>
                  于 <strong>{{ formatDateTime(watermarkResult.accessed_at) }}</strong> 下载
                </div>
                <div class="extract-hint">
                  电动车申请表与承诺书不写文件访问日志（申请人本人和班委下到的是同一份文件），
                  凭水印即可确定是谁下载的
                </div>
              </template>

              <template v-else>
                <el-icon><CircleCheck /></el-icon>
                检测到水印：
                <strong>{{ watermarkResult.user_name || watermarkResult.user_no }}</strong>
                于 <strong>{{ formatDateTime(watermarkResult.accessed_at) }}</strong>
                <!-- 动作从日志里核对，不能写死「下载」：一律打水印之后，
                     学生在线查看拿到的副本也带水印，一份流出的 PDF 未必是下载的 -->
                <template v-if="watermarkResult.log_matched">
                  <el-tag :type="watermarkResult.action === 'download' ? 'danger' : 'primary'" size="small">
                    {{ watermarkResult.action === 'download' ? '下载' : '在线查看' }}
                  </el-tag>
                </template>
                <template v-else>
                  <el-tag type="info" size="small">动作未知</el-tag>
                </template>
                <!-- 文件已从「文件公开」里删掉：公告表查不到那一行，令牌里的
                     「谁、何时、取了哪一号文件」还说得清，但标题没处取，也不能
                     再拿「文件#5」搪塞 —— 那个编号此刻已经指不回任何东西了 -->
                <template v-if="watermarkResult.file_deleted">
                  取过一份已删除的公开文件
                  <div class="extract-hint">
                    这份文件（编号 {{ watermarkResult.file_id }}）已从「文件公开」里删除，
                    它的查看/下载记录也一并清理了，所以不能确定是查看还是下载
                  </div>
                </template>
                <template v-else>
                  「{{ watermarkResult.file_title || '文件#' + watermarkResult.file_id }}」
                  <span v-if="watermarkResult.ip" class="extract-ip">IP {{ watermarkResult.ip }}</span>
                  <!-- 核不到就直说核不到，别让人以为是「查无此人」 -->
                  <div v-if="!watermarkResult.log_matched" class="extract-hint">
                    访问日志里没找到对应的记录（记录只保留最近一个月，更早的已清理；
                    也可能是本功能上线前取的文件），只能确定「谁、何时、取了哪个文件」，
                    不能确定是查看还是下载
                  </div>
                </template>
              </template>
            </template>
            <template v-else>
              <el-icon><Warning /></el-icon>
              {{ watermarkResult.message || '未检测到水印' }}
            </template>
          </div>
        </div>

        <el-table :data="fileAccessLogs" v-loading="loadingFileAccess" stripe border style="width: 100%;">
          <el-table-column label="时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="访问人" width="140" align="center">
            <template #default="{ row }">
              {{ row.user_name || '-' }}
              <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.user_no }}</div>
            </template>
          </el-table-column>
          <el-table-column label="动作" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.action === 'download'" type="danger" size="small">下载</el-tag>
              <el-tag v-else-if="row.action === 'view'" type="primary" size="small">查看</el-tag>
              <span v-else style="color: var(--el-text-color-disabled);">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="file_title" label="文件" min-width="200" show-overflow-tooltip />
          <el-table-column prop="ip" label="IP" width="140" align="center">
            <template #default="{ row }">
              <span v-if="row.ip" style="font-family: monospace; font-size: 12px;">{{ row.ip }}</span>
              <span v-else style="color: var(--el-text-color-disabled);">-</span>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="fileAccessPage"
            v-model:page-size="fileAccessPageSize"
            :page-sizes="[20, 50, 100, 200]"
            :total="fileAccessTotal"
            layout="total, sizes, prev, pager, next"
            background
            @size-change="fetchFileAccessLogs"
            @current-change="fetchFileAccessLogs"
          />
        </div>
      </el-tab-pane>

      <!-- ============ IP 封禁 ============ -->
      <el-tab-pane label="IP 封禁" name="bans">
        <!-- 手机上和账号管理那边的做法一致：竖排、每个控件占满一行 -->
        <el-form :inline="!isMobile" :label-width="isMobile ? 'auto' : undefined">
          <el-form-item label="目标">
            <el-input
              v-model="banForm.target"
              placeholder="IP 或网段，如 203.0.113.9 或 203.0.113.0/24"
              clearable
              :style="isMobile ? 'width: 100%' : 'width: 260px'"
            />
          </el-form-item>
          <el-form-item label="时长">
            <el-select v-model="banForm.minutes" :style="isMobile ? 'width: 100%' : 'width: 130px'">
              <el-option
                v-for="opt in BAN_DURATIONS"
                :key="String(opt.value)"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="原因">
            <el-input
              v-model="banForm.reason"
              placeholder="可留空，如：恶意爆破登录"
              clearable
              maxlength="200"
              :style="isMobile ? 'width: 100%' : 'width: 200px'"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="danger" :loading="creatingBan" @click="handleCreateBan">
              <el-icon><Lock /></el-icon>封禁
            </el-button>
            <el-button @click="fetchIpBans">刷新</el-button>
          </el-form-item>
        </el-form>

        <div class="tip ban-self-tip">
          你当前的 IP：<span class="mono">{{ selfIp || '未知' }}</span>
          （不能封禁自己所在的 IP 或网段）。
        </div>

        <el-table :data="ipBans" v-loading="loadingBans" stripe border style="width: 100%;">
          <el-table-column label="目标" width="190" align="center">
            <template #default="{ row }">
              <span class="mono">{{ row.target }}</span>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="90" align="center">
            <template #default="{ row }">
              <!-- 自动 = 登录失败攒够阈值触发的；手动 = 管理员封的（含被管理员延长过的） -->
              <el-tag v-if="row.is_manual" type="danger" size="small">手动</el-tag>
              <el-tag v-else type="warning" size="small">自动</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="原因" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.reason">{{ row.reason }}</span>
              <span v-else style="color: var(--el-text-color-disabled);">-</span>
            </template>
          </el-table-column>
          <el-table-column label="封禁时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="解封时间" width="160" align="center">
            <template #default="{ row }">
              <span v-if="!row.expires_at" style="color: #f56c6c; font-weight: 600;">永久</span>
              <span v-else>{{ formatDateTime(row.expires_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作人" width="140" align="center">
            <template #default="{ row }">
              <template v-if="row.operator_no">
                {{ row.operator_name || '-' }}
                <div style="font-size: 12px; color: var(--el-text-color-secondary);">{{ row.operator_no }}</div>
              </template>
              <span v-else style="color: var(--el-text-color-secondary);">系统（自动）</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="handleUnban(row)">解封</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loadingBans && !ipBans.length" description="当前没有封禁中的 IP" :image-size="60" />

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="banPage"
            v-model:page-size="banPageSize"
            :page-sizes="[20, 50, 100, 200]"
            :total="banTotal"
            layout="total, sizes, prev, pager, next"
            background
            @size-change="fetchIpBans"
            @current-change="fetchIpBans"
          />
        </div>

        <div class="tip">
          列表只显示生效中的封禁，过期的会自动消失。操作人标着「系统（自动）」的，
          是登录失败次数过多触发的。
        </div>
      </el-tab-pane>

      <!-- ============ 资料下载管理 ============ -->
      <el-tab-pane label="资料下载管理" name="resources">
        <div class="resource-toolbar">
          <el-button type="primary" :loading="uploading" @click="handleUploadClick">
            <el-icon v-if="!uploading"><Upload /></el-icon>
            <!-- 资料里有几十 MB 的压缩包，慢网络下把百分比显示出来 -->
            上传新资料{{ uploading && uploadProgress ? ` ${uploadProgress}%` : '' }}
          </el-button>
          <input
            ref="fileInputRef"
            type="file"
            style="display: none"
            @change="handleFileSelected"
          />
          <span class="tip">管理「资料下载」页面显示的条目；分类旁的箭头调整分类之间的顺序。</span>
        </div>

        <div v-for="(group, gi) in resourceGroups" :key="group.category" class="resource-group">
          <div class="resource-group-title">
            <el-icon><FolderOpened /></el-icon>
            {{ group.category }}
            <span class="group-count">{{ group.items.length }} 份</span>
            <!-- 分类之间的顺序：一个分类整体上移/下移，不动分类里的资料 -->
            <span class="category-order">
              <el-button size="small" :disabled="gi === 0" @click="moveResourceCategory(gi, -1)">
                <el-icon><Top /></el-icon>
              </el-button>
              <el-button
                size="small"
                :disabled="gi === resourceGroups.length - 1"
                @click="moveResourceCategory(gi, 1)"
              >
                <el-icon><Bottom /></el-icon>
              </el-button>
            </span>
          </div>

          <el-table :data="group.items" v-loading="loadingResources" stripe border style="width: 100%;">
            <el-table-column label="序号" width="60" align="center">
              <template #default="{ $index }">{{ $index + 1 }}</template>
            </el-table-column>
            <el-table-column prop="name" label="名称" min-width="200" show-overflow-tooltip />
            <el-table-column prop="original_name" label="原始文件名" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span style="font-family: monospace; font-size: 12px;">{{ row.original_name || row.file_name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="download_count" label="下载次数" width="100" align="center" />
            <el-table-column label="排序" width="140" align="center">
              <template #default="{ row, $index }">
                <el-button size="small" :disabled="$index === 0" @click="moveResource(row, -1)">
                  <el-icon><Top /></el-icon>
                </el-button>
                <el-button size="small" :disabled="$index === group.items.length - 1" @click="moveResource(row, 1)">
                  <el-icon><Bottom /></el-icon>
                </el-button>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" align="center">
              <template #default="{ row }">
                <el-button size="small" @click="handleEditResource(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="handleDeleteResource(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ============ 生日关怀 ============ -->
      <el-tab-pane label="生日关怀" name="birthday">
        <div v-loading="loadingBirthday" class="birthday-form">
          <!-- 1. 首页条幅 -->
          <div class="birthday-block">
            <div class="birthday-block-head">
              <el-switch v-model="birthdayForm.banner_enabled" />
              <span class="birthday-block-title">首页显示生日条幅</span>
            </div>
            <div class="birthday-block-body">
              <el-switch
                v-model="birthdayForm.banner_show_names"
                :disabled="!birthdayForm.banner_enabled"
              />
              <span>显示寿星姓名</span>
              <span class="tip birthday-inline-tip">
                关掉只显示「今天有 N 位同志生日啦」。匿名访客无论开关如何都只看得到人数。
              </span>
            </div>
          </div>

          <!-- 2. 给寿星本人推祝福 -->
          <div class="birthday-block">
            <div class="birthday-block-head">
              <el-switch v-model="birthdayForm.greet_enabled" />
              <span class="birthday-block-title">给寿星本人推送祝福语</span>
            </div>
            <div class="birthday-block-body column">
              <el-input
                v-model="birthdayForm.greet_template"
                type="textarea"
                :rows="3"
                :disabled="!birthdayForm.greet_enabled"
                :placeholder="birthdayDefaults.template"
              />
              <div class="tip birthday-inline-tip" v-pre>
                可用占位符：{{name}}（姓名）、{{age}}（今天要过的岁数）、{{class}}（班级）。
                留空则用灰字里那份默认文案。本站没有站内收件箱，寿星自己没开启任何通知渠道时收不到。
              </div>
            </div>
          </div>

          <!-- 3. 生日当天连带通知指定账号 -->
          <div class="birthday-block">
            <div class="birthday-block-head">
              <el-switch v-model="birthdayForm.notify_enabled" />
              <span class="birthday-block-title">生日当天通知指定账号</span>
            </div>
            <div class="birthday-block-body column">
              <el-select
                v-model="birthdayForm.notify_student_nos"
                multiple
                filterable
                clearable
                :disabled="!birthdayForm.notify_enabled"
                placeholder="选择要通知的账号"
                class="birthday-select"
              >
                <el-option
                  v-for="u in users"
                  :key="u.student_no"
                  :label="u.name + '（' + u.student_no + '）'"
                  :value="u.student_no"
                />
              </el-select>
              <div class="tip birthday-inline-tip">
                通知内容含几人生日、几岁生日、是谁。每天 08:00 后由服务端自动发送，
                未勾选任何账号时不会发出。测试只发给你自己，不会打扰上面这些人。
              </div>
            </div>
          </div>

          <div class="birthday-actions">
            <el-button type="primary" :loading="savingBirthday" @click="handleSaveBirthday">
              保存
            </el-button>
            <el-button :loading="testingBirthday" @click="handleTestBirthday">发送测试</el-button>
          </div>
          <!-- 运行状态：定时任务在不在跑、上次跑出什么结果、下次什么时候跑 -->
          <div v-if="birthdayLoaded" class="birthday-status">{{ birthdayStatusText }}</div>
        </div>
      </el-tab-pane>

      <!--
        只有班委及以上能分配日程，但这一页是给管理员收拾烂摊子用的，所以按管理员
        收口（本页面在系统管理里，路由 meta.role 已经是 admin）。后端接口权限照旧
        （committee_required + 只能看自己建的），这里不做二次过滤 —— 后果是这个
        tab 只列当前登录管理员自己建的批次，不是全站批次
      -->
      <el-tab-pane label="日程批次" name="schedule-batches">
        <ScheduleBatchPanel />
      </el-tab-pane>

      <el-tab-pane label="数据体检" name="health">
        <div v-loading="loadingHealth" class="health-wrap">
          <div class="health-head">
            <span v-if="healthLoaded" class="health-summary">
              全班 {{ health.total_students }} 名学生，查出 {{ healthCount }} 处待确认
            </span>
            <span v-else class="health-summary">检查身份证、联系方式、必填字段、照片四类</span>
            <el-button :loading="loadingHealth" @click="fetchHealth">重新检查</el-button>
          </div>

          <el-alert
            v-if="healthLoaded && !health.groups.length"
            type="success"
            :closable="false"
            show-icon
            title="没查出问题"
            description="四类检查都过了。这也包括「照片文件在磁盘上找得到」这种只有从数据库以外才看得出来的问题。"
          />

          <!-- 一项问题都没有的那类不会出现在结果里（后端就不返回），所以这里直接顺序渲染 -->
          <div v-for="group in health.groups" :key="group.key" class="health-card">
            <div class="health-card-head">
              <el-tag :type="group.level === 'error' ? 'danger' : 'warning'" size="small">
                {{ group.label }}
              </el-tag>
              <!-- 一个人可能在同一类里占两条（比如身份证号和生日都对不上），所以数的是「条」不是「人」 -->
              <span class="health-count">{{ group.items.length }} 条</span>
            </div>
            <el-table :data="group.items" size="small" border>
              <el-table-column prop="student_no" label="学号" width="130" />
              <el-table-column prop="name" label="姓名" width="110" />
              <el-table-column prop="reason" label="问题" min-width="260" />
              <el-table-column label="操作" width="90" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="openStudent(row.id)">
                    查看
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ============ 新建 / 编辑域外账号 ============ -->
    <el-dialog
      v-model="extDialogVisible"
      :title="extForm.editing ? '编辑域外账号' : '新建域外账号'"
      width="520px"
    >
      <el-form :model="extForm" label-width="110px">
        <el-form-item label="登录名" required>
          <!-- 登录名是账号的主键，建好之后不能改（改了等于换一个账号） -->
          <el-input
            v-model="extForm.login_name"
            :disabled="extForm.editing"
            maxlength="20"
            placeholder="登录时填在「学号」那一栏，如 teacher"
          />
        </el-form-item>
        <el-form-item label="展示用户名" required>
          <el-input
            v-model="extForm.display_name"
            maxlength="50"
            placeholder="姓名、水印都用它，如 李俊刚"
          />
        </el-form-item>
        <el-form-item label="等效权限" required>
          <el-select v-model="extForm.role" style="width: 100%">
            <el-option
              v-for="(label, value) in ROLE_LABELS"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!extForm.editing" label="初始密码" required>
          <el-input v-model="extForm.password" placeholder="6-32 位，需同时含字母和数字" />
        </el-form-item>
        <el-form-item label="头像">
          <input
            ref="extAvatarInput"
            type="file"
            accept="image/*"
            style="display: none"
            @change="handleExtAvatarPicked"
          />
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <el-button @click="extAvatarInput?.click()">选择图片</el-button>
            <span class="tip" style="margin: 0;">
              {{ extAvatarText }}
            </span>
            <el-button
              v-if="extForm.avatarFile || (extForm.hasAvatar && !extForm.removeAvatar)"
              link
              type="danger"
              @click="handleExtAvatarClear"
            >
              清除头像
            </el-button>
          </div>
        </el-form-item>
        <!-- 签字图：域外账号可能是办件的审批者，落款要用它。
             这块**只显示状态文字、不渲染预览**（与头像一致）——
             签字是敏感物，管理界面里没必要把图摊在屏幕上 -->
        <el-form-item label="签字图">
          <input
            ref="extSignInput"
            type="file"
            accept="image/*"
            style="display: none"
            @change="handleExtSignPicked"
          />
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <el-button @click="extSignInput?.click()">选择图片</el-button>
            <span class="tip" style="margin: 0;">
              {{ extSignText }}
            </span>
            <el-button
              v-if="extForm.signPhotoFile || (extForm.hasSignPhoto && !extForm.removeSignPhoto)"
              link
              type="danger"
              @click="handleExtSignClear"
            >
              清除签字图
            </el-button>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="extDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="extSaving" @click="handleExtSave">
          {{ extForm.editing ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ============ 某个账号的日志 ============ -->
    <el-dialog v-model="logVisible" :title="logTitle" width="720px">
      <div v-loading="loadingUserLogs">
        <div class="log-section-title">操作日志</div>
        <el-table :data="userLogs.operations.items" stripe border style="width: 100%;">
          <el-table-column label="时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="action" label="动作" width="120" align="center" />
          <el-table-column prop="target" label="对象" min-width="150" show-overflow-tooltip />
          <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
        </el-table>
        <el-empty
          v-if="!loadingUserLogs && !userLogs.operations.total"
          description="这个账号还没有操作记录"
          :image-size="60"
        />
        <div v-if="userLogs.operations.total" class="pagination-wrap">
          <el-pagination
            v-model:current-page="userLogPage"
            v-model:page-size="userLogPageSize"
            :page-sizes="[20, 50, 100, 200]"
            :total="userLogs.operations.total"
            layout="total, sizes, prev, pager, next"
            background
            @size-change="fetchUserLogs"
            @current-change="fetchUserLogs"
          />
        </div>

        <div class="log-section-title">
          被操作记录
          <!-- 本人对自己的操作（提交请假、提交修改申请）也算在内，所以措辞是
               「以这个账号为对象」而不是「别人对它做的」 -->
          <span class="log-section-hint">以这个账号为对象的操作（含本人提交的申请）</span>
        </div>
        <!-- 列和上面那块刻意不同：对象恒是本人，所以不列「对象」，改列「操作人」 -->
        <el-table :data="userLogs.targeted.items" stripe border style="width: 100%;">
          <el-table-column label="时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作人" width="120" align="center" show-overflow-tooltip>
            <template #default="{ row }">{{ row.operator_name || row.operator_no || '-' }}</template>
          </el-table-column>
          <el-table-column prop="action" label="动作" width="120" align="center" />
          <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
        </el-table>
        <el-empty
          v-if="!loadingUserLogs && !userLogs.targeted.total"
          description="还没有针对这个账号的操作记录"
          :image-size="60"
        />
        <div v-if="userLogs.targeted.total" class="pagination-wrap">
          <el-pagination
            v-model:current-page="targetedPage"
            v-model:page-size="targetedPageSize"
            :page-sizes="[20, 50, 100, 200]"
            :total="userLogs.targeted.total"
            layout="total, sizes, prev, pager, next"
            background
            @size-change="fetchUserLogs"
            @current-change="fetchUserLogs"
          />
        </div>

        <div class="log-section-title">
          登录与账号操作
          <!-- 把 7 天这个边界显示出来，不然只会让人猜为什么只有这几条 -->
          <span class="log-section-hint">
            仅最近 7 天（{{ formatDateTime(userLogs.events_since) }} 起）
          </span>
        </div>
        <el-table :data="userLogs.events" stripe border style="width: 100%;">
          <el-table-column label="时间" width="160" align="center">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="事件" width="120" align="center">
            <template #default="{ row }">
              <AccountEventTag :event="row.event" />
            </template>
          </el-table-column>
          <el-table-column label="IP" min-width="150" align="center">
            <template #default="{ row }">
              <span v-if="row.ip" style="font-family: monospace; font-size: 12px;">{{ row.ip }}</span>
              <span v-else style="color: var(--el-text-color-disabled);">-</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="userLogs.events_total > userLogs.events.length" class="tip">
          7 天内共 {{ userLogs.events_total }} 条，这里只列出最近 {{ userLogs.events.length }} 条。
        </div>
        <el-empty
          v-else-if="!loadingUserLogs && !userLogs.events_total"
          description="最近 7 天没有登录或账号操作记录"
          :image-size="60"
        />
        <!-- 这个功能上线之前的登录/改密压根没入库，历史补不回来，说清楚免得以为漏查 -->
        <div class="tip">登录与账号操作记录自本功能上线起才开始保存，更早的记录查不到。</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Lock } from '@element-plus/icons-vue'
import {
  getUsers,
  setUserRole,
  resetUserPassword,
  freezeUser,
  unfreezeUser,
  clearUserPasskeys,
  clearUserTwoFactor,
  revokeUserSessions,
  getUserLogs,
  createExternalUser,
  updateExternalUser,
  deleteExternalUser,
  getLogs,
  clearLogs,
  getIpBans,
  createIpBan,
  deleteIpBan,
  listResources,
  uploadResource,
  updateResource,
  reorderResourceCategories,
  reorderResources,
  deleteResource,
  getFileAccessLogs,
  extractWatermark,
  getDataHealth
} from '@/api/admin'
import {
  getBirthdaySettings,
  saveBirthdaySettings,
  testBirthdayNotify
} from '@/api/birthday'
import { useRouter } from 'vue-router'
import { ROLE_LABELS } from '@/utils/roles'
import { formatDateTime } from '@/utils/format'
import { useIsMobile } from '@/composables/useIsMobile'
import ScheduleBatchPanel from '@/components/ScheduleBatchPanel.vue'
import AccountEventTag from '@/components/AccountEventTag.vue'

// 手机上操作列只直显这一个按钮，其余收进「更多」下拉。想换直显项改这里一个词
const MOBILE_PRIMARY = '重置密码'

const activeTab = ref('users')
const isMobile = useIsMobile()
const router = useRouter()

// ---------- 账号管理 ----------
const users = ref([])
const loadingUsers = ref(false)
const userKeyword = ref('')

const filteredUsers = computed(() => {
  const kw = userKeyword.value.trim()
  if (!kw) return users.value
  return users.value.filter((u) => u.name.includes(kw) || u.student_no.includes(kw))
})

async function fetchUsers() {
  loadingUsers.value = true
  try {
    users.value = await getUsers()
  } catch (e) {
    ElMessage.error('账号列表加载失败')
  } finally {
    loadingUsers.value = false
  }
}

async function handleRoleChange(row, role) {
  if (role === row.role) return
  try {
    await ElMessageBox.confirm(
      `确定把「${row.name}」的角色改为「${ROLE_LABELS[role]}」吗？`,
      '修改角色',
      { type: 'warning' }
    )
  } catch (e) {
    return // 取消，下拉框绑的是 model-value，不刷新也不会串值
  }
  try {
    await setUserRole(row.student_no, role)
    ElMessage.success('角色已更新')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  }
}

// ---------- 行内操作 ----------
// 一行有哪些按钮只在这里定义一次：桌面端平铺、手机端取其中一项直显，两边共用，
// 不把按钮列表在模板里抄两遍（抄两遍之后加个按钮必然会漏一边）
function rowActions(row) {
  const frozen = row.is_frozen
  return [
    ...(row.is_external
      ? [{ label: '编辑', type: 'primary', run: () => openEditExternal(row) }]
      : []),
    {
      label: '重置密码',
      type: 'primary',
      // 两种账号的重置方式不同（学生重置回原始密码，域外账号由管理员指定新密码）
      run: () => (row.is_external ? handleExtResetPassword(row) : handleStudentReset(row))
    },
    { label: '日志', type: 'primary', run: () => openUserLogs(row) },
    { label: '清除通行密钥', type: 'warning', run: () => handleClearPasskeys(row) },
    // 只在真的开着时才出现：没开的人点进去只会看到「本来就没开」
    ...(row.two_factor_method
      ? [{ label: '清除二次验证', type: 'warning', run: () => handleClearTwoFactor(row) }]
      : []),
    { label: '吊销会话', type: 'warning', run: () => handleRevokeSessions(row) },
    {
      label: frozen ? '解冻' : '冻结',
      type: frozen ? 'success' : 'warning',
      run: () => handleToggleFreeze(row)
    },
    ...(row.is_external
      ? [{ label: '删除', type: 'danger', run: () => handleExtDelete(row) }]
      : [])
  ]
}

/** 手机端直显的那个。一定存在，不用可选链 */
function primaryAction(row) {
  return rowActions(row).find((a) => a.label === MOBILE_PRIMARY)
}

/** 手机端下拉里的其余项 */
function restActions(row) {
  return rowActions(row).filter((a) => a.label !== MOBILE_PRIMARY)
}

// ---------- 重置密码 ----------
async function handleStudentReset(row) {
  try {
    await ElMessageBox.confirm(
      `确定把「${row.name}」的密码重置为原始密码吗？`,
      '重置密码',
      { type: 'warning', confirmButtonText: '重置' }
    )
  } catch (e) {
    return // 取消
  }

  try {
    const res = await resetUserPassword(row.student_no)
    if (res.password) {
      // 没有身份证号时密码退化成学号后 6 位，后端把明文回带，好让管理员转告学生
      ElMessageBox.alert(`该生没有身份证号，密码已重置为：${res.password}`, '重置成功', {
        confirmButtonText: '知道了'
      })
    } else {
      ElMessage.success('已重置为身份证号后 6 位')
    }
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '重置失败')
  }
}

// ---------- 冻结 / 解冻 ----------
async function handleToggleFreeze(row) {
  const freezing = !row.is_frozen
  try {
    await ElMessageBox.confirm(
      freezing
        ? `确定冻结「${row.name}」吗？冻结后该账号无法登录，已登录的设备会被踢下线。`
        : `确定解冻「${row.name}」吗？解冻后可以重新登录。`,
      freezing ? '冻结账号' : '解冻账号',
      { type: 'warning', confirmButtonText: freezing ? '冻结' : '解冻' }
    )
  } catch (e) {
    return // 取消
  }

  try {
    await (freezing ? freezeUser(row.student_no) : unfreezeUser(row.student_no))
    ElMessage.success(freezing ? '已冻结' : '已解冻')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || (freezing ? '冻结失败' : '解冻失败'))
  }
}

// 清除通行密钥：学生换了手机、旧钥匙丢了，或怀疑账号被冒用时用。
// 密码不受影响，清完照样能用密码登录，所以确认框里要说清楚
async function handleClearPasskeys(row) {
  try {
    await ElMessageBox.confirm(
      `确定清除「${row.name}」名下的全部通行密钥吗？清除后那些设备不能再免密登录，密码登录不受影响。`,
      '清除通行密钥',
      { type: 'warning', confirmButtonText: '清除' }
    )
  } catch (e) {
    return // 取消
  }

  try {
    const res = await clearUserPasskeys(row.student_no)
    ElMessage.success(res.message || '已清除')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '清除失败')
  }
}

// 清除二次验证：手机丢了、验证器没备份恢复码时，管理员帮他把这道门临时拆掉。
// 密码和通行密钥都不受影响，清完照样能登录
async function handleClearTwoFactor(row) {
  const label = row.two_factor_method === 'email' ? '电子邮件验证码' : '身份验证器'
  try {
    await ElMessageBox.confirm(
      `确定清除「${row.name}」的二次验证吗？当前方式：${label}。清除后只需密码即可登录，恢复码一并作废。`,
      '清除二次验证',
      { type: 'warning', confirmButtonText: '清除' }
    )
  } catch (e) {
    return // 取消
  }

  try {
    const res = await clearUserTwoFactor(row.student_no)
    ElMessage.success(res.message || '已清除')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '清除失败')
  }
}

// 吊销会话：把人踢下线，但不禁用账号，和「冻结」是两回事，确认框里要点明区别，
// 否则管理员容易以为点了它就等于停用了这个号
async function handleRevokeSessions(row) {
  try {
    await ElMessageBox.confirm(
      `确定吊销「${row.name}」的全部会话吗？该账号将在所有设备上退出登录，重新登录后可继续使用。`,
      '吊销所有会话',
      { type: 'warning', confirmButtonText: '吊销' }
    )
  } catch (e) {
    return // 取消
  }

  try {
    await revokeUserSessions(row.student_no)
    ElMessage.success('已吊销该账号的全部会话')
    // 吊销的要是自己，这次刷新就会吃到一个 401，由拦截器接管跳登录页
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '吊销失败')
  }
}

// ---------- 某个账号的日志 ----------
const logVisible = ref(false)
const loadingUserLogs = ref(false)
const logTarget = ref({})
const userLogPage = ref(1)
const userLogPageSize = ref(20)
// 被操作记录单独一套分页：两块表各翻各的，翻上面那块不该把下面顶回第一页
const targetedPage = ref(1)
const targetedPageSize = ref(20)
// 先给个空壳，模板里就不用到处判空了（events_since 为空时 formatDateTime 显示 '-'）
const userLogs = ref({
  operations: { total: 0, items: [] },
  targeted: { total: 0, items: [] },
  events: [],
  events_total: 0,
  events_since: null
})

const logTitle = computed(
  () => `${logTarget.value.name || ''}（${logTarget.value.student_no || ''}）的日志`
)

async function openUserLogs(row) {
  logTarget.value = row
  userLogPage.value = 1
  userLogPageSize.value = 20
  targetedPage.value = 1
  targetedPageSize.value = 20
  logVisible.value = true
  // 打开才请求：账号列表可能有几十上百行，进页面时为每行都拉一次日志没意义
  await fetchUserLogs()
}

async function fetchUserLogs() {
  if (!logTarget.value.student_no) return
  loadingUserLogs.value = true
  try {
    userLogs.value = await getUserLogs(logTarget.value.student_no, {
      page: userLogPage.value,
      page_size: userLogPageSize.value,
      target_page: targetedPage.value,
      target_page_size: targetedPageSize.value
    })
  } catch (e) {
    ElMessage.error('日志加载失败')
  } finally {
    loadingUserLogs.value = false
  }
}

// ---------- 域外账号（不与学生关联的账号：老师、协助人员等）----------
// 新建和编辑共用一个对话框，靠 extForm.editing 区分。
// 登录名是账号主键，建好之后不让改（要换登录名等于换个账号，重新建即可）
const extDialogVisible = ref(false)
const extSaving = ref(false)
const extAvatarInput = ref(null)
const extSignInput = ref(null)
const extForm = reactive({
  editing: false,
  login_name: '',
  display_name: '',
  role: 'student',
  password: '',
  avatarFile: null,   // 本次选中的新图片
  hasAvatar: false,   // 服务端已有的头像
  removeAvatar: false, // 编辑时勾了「清除头像」
  signPhotoFile: null, // 本次选中的新签字图
  hasSignPhoto: false, // 服务端已有的签字图
  removeSignPhoto: false // 编辑时勾了「清除签字图」
})

const extAvatarText = computed(() => {
  if (extForm.avatarFile) return `已选择：${extForm.avatarFile.name}`
  if (extForm.hasAvatar && !extForm.removeAvatar) return '已有头像，重新选择可替换'
  if (extForm.removeAvatar) return '保存后清除头像'
  return '不传则用姓名首字占位，单张不超过 2MB'
})

const extSignText = computed(() => {
  if (extForm.signPhotoFile) return `已选择：${extForm.signPhotoFile.name}`
  if (extForm.hasSignPhoto && !extForm.removeSignPhoto) return '已有签字图，重新选择可替换'
  if (extForm.removeSignPhoto) return '保存后清除签字图'
  return '不传则留空，单张不超过 10MB'
})

function resetExtForm() {
  extForm.editing = false
  extForm.login_name = ''
  extForm.display_name = ''
  extForm.role = 'student'
  extForm.password = ''
  extForm.avatarFile = null
  extForm.hasAvatar = false
  extForm.removeAvatar = false
  extForm.signPhotoFile = null
  extForm.hasSignPhoto = false
  extForm.removeSignPhoto = false
  // 清掉原生 input 里的选择，否则再打开还是上次那个文件
  if (extAvatarInput.value) extAvatarInput.value.value = ''
  if (extSignInput.value) extSignInput.value.value = ''
}

function openCreateExternal() {
  resetExtForm()
  extDialogVisible.value = true
}

function openEditExternal(row) {
  resetExtForm()
  extForm.editing = true
  extForm.login_name = row.student_no
  extForm.display_name = row.name
  extForm.role = row.role || 'student'
  extForm.hasAvatar = !!row.has_avatar
  extForm.hasSignPhoto = !!row.has_sign_photo
  extDialogVisible.value = true
}

function handleExtAvatarPicked(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning('头像不能超过 2MB')
    e.target.value = ''
    return
  }
  extForm.avatarFile = file
  extForm.removeAvatar = false
}

function handleExtAvatarClear() {
  extForm.avatarFile = null
  extForm.removeAvatar = true
  if (extAvatarInput.value) extAvatarInput.value.value = ''
}

function handleExtSignPicked(e) {
  const file = e.target.files?.[0]
  if (!file) return
  // 上限与后端 save_photo 的 MAX_PHOTO_SIZE 一致（签字走的是照片那套校验），
  // 不是头像那个 2MB
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('签字图不能超过 10MB')
    e.target.value = ''
    return
  }
  extForm.signPhotoFile = file
  extForm.removeSignPhoto = false
}

function handleExtSignClear() {
  extForm.signPhotoFile = null
  extForm.removeSignPhoto = true
  if (extSignInput.value) extSignInput.value.value = ''
}

async function handleExtSave() {
  if (!extForm.editing) {
    if (!extForm.login_name.trim()) return ElMessage.warning('请填写登录名')
  }
  if (!extForm.display_name.trim()) return ElMessage.warning('请填写展示用户名')
  if (!extForm.editing) {
    // 规则与后端 _clean_login_name 一致：非空、不超过 20 位、不能有空格
    // （不限定字母数字，老师也可能想用姓名当登录名）
    const name = extForm.login_name.trim()
    if (name.length > 20) return ElMessage.warning('登录名不能超过 20 位')
    if (/\s/.test(name)) return ElMessage.warning('登录名不能包含空格')
    if (extForm.password.length < 6 || extForm.password.length > 32) {
      return ElMessage.warning('初始密码长度需为 6-32 位')
    }
    if (!/[A-Za-z]/.test(extForm.password) || !/\d/.test(extForm.password)) {
      return ElMessage.warning('初始密码必须同时包含字母和数字')
    }
  }

  const fd = new FormData()
  fd.append('display_name', extForm.display_name.trim())
  fd.append('role', extForm.role)
  if (extForm.editing) {
    // 用 remove_avatar 明确告诉后端「是清了还是没动」——
    // 不传 avatar 字段时后端无法区分这两种情况
    fd.append('remove_avatar', extForm.removeAvatar ? 'true' : 'false')
    // 同样要明确告诉后端「签字图是清了还是没动」——不传 sign_photo 时后端分不清
    fd.append('remove_sign_photo', extForm.removeSignPhoto ? 'true' : 'false')
  } else {
    fd.append('login_name', extForm.login_name.trim())
    fd.append('password', extForm.password)
  }
  if (extForm.avatarFile) fd.append('avatar', extForm.avatarFile)
  if (extForm.signPhotoFile) fd.append('sign_photo', extForm.signPhotoFile)

  extSaving.value = true
  try {
    if (extForm.editing) {
      await updateExternalUser(extForm.login_name, fd)
      ElMessage.success('已保存')
    } else {
      await createExternalUser(fd)
      ElMessage.success('域外账号已创建')
    }
    extDialogVisible.value = false
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    extSaving.value = false
  }
}

async function handleExtResetPassword(row) {
  let value
  try {
    const res = await ElMessageBox.prompt(
      `给「${row.name}」设置一个新密码（6-32 位，需同时含字母和数字）。设置后立即生效，不会要求他再改一次。`,
      '重置密码',
      {
        confirmButtonText: '确定',
        inputPlaceholder: '新密码',
        inputValidator: (v) => {
          if (!v || v.length < 6 || v.length > 32) return '长度需为 6-32 位'
          if (!/[A-Za-z]/.test(v) || !/\d/.test(v)) return '必须同时包含字母和数字'
          return true
        }
      }
    )
    value = res.value
  } catch (e) {
    return // 取消
  }

  try {
    await resetUserPassword(row.student_no, value)
    ElMessage.success('密码已重置')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '重置失败')
  }
}

async function handleExtDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除域外账号「${row.name}」（${row.student_no}）吗？删除后无法恢复。`,
      '删除账号',
      { type: 'warning', confirmButtonText: '删除' }
    )
  } catch (e) {
    return // 取消
  }
  try {
    await deleteExternalUser(row.student_no)
    ElMessage.success('已删除')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// ---------- 操作日志 ----------
const logs = ref([])
const loadingLogs = ref(false)
const logTotal = ref(0)
const logPage = ref(1)
const logPageSize = ref(50)
const logFilter = reactive({ operator: '', action: '' })

async function fetchLogs() {
  loadingLogs.value = true
  try {
    const res = await getLogs({
      operator: logFilter.operator || undefined,
      action: logFilter.action || undefined,
      page: logPage.value,
      page_size: logPageSize.value
    })
    logs.value = res.items
    logTotal.value = res.total
  } catch (e) {
    ElMessage.error('操作日志加载失败')
  } finally {
    loadingLogs.value = false
  }
}

function handleLogSearch() {
  logPage.value = 1
  fetchLogs()
}

function handleLogReset() {
  logFilter.operator = ''
  logFilter.action = ''
  handleLogSearch()
}

// 清空是「全清」，不是只清当前筛选出来的那些，所以确认文案里要写明白
const clearingLogs = ref(false)

async function handleClearLogs() {
  try {
    await ElMessageBox.confirm(
      `确定清空全部操作日志吗？共 ${logTotal.value} 条，清空后无法恢复。`,
      '清空日志',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 取消
  }

  clearingLogs.value = true
  try {
    const res = await clearLogs()
    ElMessage.success(`已清空 ${res.deleted} 条日志`)
    logPage.value = 1
    fetchLogs()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '清空失败')
  } finally {
    clearingLogs.value = false
  }
}

// ---------- 文件访问日志 ----------
const fileAccessLogs = ref([])
const loadingFileAccess = ref(false)
const fileAccessTotal = ref(0)
const fileAccessPage = ref(1)
const fileAccessPageSize = ref(50)
const fileAccessFilter = reactive({ user: '', file: '', action: '' })
// 水印提取结果
const watermarkResult = ref(null)
const watermarkFileInput = ref(null)
const extractingWatermark = ref(false)
// 上传进度百分比（浏览器算不出总大小时为 0，此时只显示「正在上传」不显示数字）
const extractProgress = ref(0)

async function fetchFileAccessLogs() {
  loadingFileAccess.value = true
  try {
    const res = await getFileAccessLogs({
      user: fileAccessFilter.user || undefined,
      file: fileAccessFilter.file || undefined,
      action: fileAccessFilter.action || undefined,
      page: fileAccessPage.value,
      page_size: fileAccessPageSize.value
    })
    fileAccessLogs.value = res.items
    fileAccessTotal.value = res.total
  } catch (e) {
    ElMessage.error('文件访问日志加载失败')
  } finally {
    loadingFileAccess.value = false
  }
}

function handleFileAccessSearch() {
  fileAccessPage.value = 1
  fetchFileAccessLogs()
}

function handleFileAccessReset() {
  fileAccessFilter.user = ''
  fileAccessFilter.file = ''
  fileAccessFilter.action = ''
  handleFileAccessSearch()
}

/** 上传阶段显示的文字：有总大小就写百分比，没有就只说在传 */
const extractLabel = computed(() =>
  extractProgress.value ? `${extractProgress.value}%` : '…'
)

async function handleWatermarkExtract(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    ElMessage.warning('只支持 PDF 文件')
    e.target.value = ''
    return
  }
  extractingWatermark.value = true
  extractProgress.value = 0
  watermarkResult.value = null
  try {
    // 传进度：要溯源的 PDF 可能是刚下发出去的几十 MB 的公告，
    // 慢网络下光上传就要几分钟，不给进度会被当成「点了没反应」
    const res = await extractWatermark(file, (loaded, total) => {
      extractProgress.value = total ? Math.round((loaded / total) * 100) : 0
    })
    watermarkResult.value = res
  } catch (e) {
    ElMessage.error('提取失败：' + (e.response?.data?.detail || e.message))
  } finally {
    extractingWatermark.value = false
    // 重置 input，方便下次选同一个文件也能触发 change
    e.target.value = ''
  }
}

/** 导出文件溯源用到的两个中文名。溯源接口返回的是内部代号，
 *  页面上照搬会写成「pdf_individual 已生成」，看不懂 */
function exportTypeText(type) {
  return { excel_list: '名单 Excel', pdf_individual: '个人信息表 PDF' }[type] || '导出文件'
}

function exportStatusText(status) {
  return {
    pending: '待审核', approved: '已通过', generated: '文件已生成',
    rejected: '已驳回', failed: '生成失败'
  }[status] || status || ''
}

// ---------- IP 封禁 ----------
// 时长走预设：手填分钟数既容易填错，也不好判断「到底封了多久」
// 「永久」用 0 当哨兵值，**不能写 null** —— el-select 把 null 当成「没选」，
// 选中后框里还是显示 placeholder「请选择」，看着像点不动。提交时 0 再转回 null，
// 后端 minutes=null 才是永久。后端校验是 ge=1，0 不是合法时长，不会歧义。
const BAN_DURATIONS = [
  { label: '1 小时', value: 60 },
  { label: '1 天', value: 1440 },
  { label: '7 天', value: 10080 },
  { label: '30 天', value: 43200 },
  { label: '永久', value: 0 }
]

const ipBans = ref([])
const loadingBans = ref(false)
const creatingBan = ref(false)
const banTotal = ref(0)
const banPage = ref(1)
const banPageSize = ref(50)
// 后端带回的「我自己的 IP」，显示在表格上方
const selfIp = ref('')
const banForm = reactive({ target: '', minutes: 60, reason: '' })

// 懒加载：进页面时有账号 / 日志 / 资料三个请求，不为一个默认看不见的 tab 再多发一个
const bansLoaded = ref(false)

async function fetchIpBans() {
  loadingBans.value = true
  try {
    const res = await getIpBans({
      page: banPage.value,
      page_size: banPageSize.value
    })
    ipBans.value = res.items
    banTotal.value = res.total
    selfIp.value = res.self_ip || ''
    bansLoaded.value = true
  } catch (e) {
    ElMessage.error('封禁列表加载失败')
  } finally {
    loadingBans.value = false
  }
}

let fileAccessLoaded = false
function handleTabChange(name) {
  if (name === 'bans' && !bansLoaded.value) fetchIpBans()
  if (name === 'file-access' && !fileAccessLoaded) {
    fileAccessLoaded = true
    fetchFileAccessLogs()
  }
  if (name === 'birthday' && !birthdayLoaded.value) fetchBirthdaySettings()
  // 体检每次都重查：脏数据是改完才没的，缓存住上次的结果反而误导人
  if (name === 'health') fetchHealth()
}

async function handleCreateBan() {
  const target = banForm.target.trim()
  if (!target) return ElMessage.warning('请输入要封禁的 IP 或网段')

  const isNetwork = target.includes('/')
  const isForever = banForm.minutes === 0

  // 确认框分两档：封网段和封永久都是「一按下去影响一片」的操作，
  // 后果必须在按下去之前说清楚，而不是事后来解封
  let tip = `确定封禁 ${target} 吗？该地址将无法登录本系统。`
  if (isNetwork) {
    tip = `确定封禁网段 ${target} 吗？该网段内的所有地址都将无法登录本系统。`
  }
  if (isForever) {
    tip += isNetwork
      ? '这是永久封禁，不会自动解除，只能由管理员手动解封。'
      : '这是永久封禁，不会自动解除。'
  }
  try {
    await ElMessageBox.confirm(tip, isForever ? '永久封禁' : '封禁 IP', {
      type: 'warning',
      confirmButtonText: '封禁',
      cancelButtonText: '取消',
      dangerouslyUseHTMLString: false
    })
  } catch (e) {
    return // 取消
  }

  creatingBan.value = true
  try {
    const res = await createIpBan({
      target,
      // 0 是界面上的哨兵，后端认的是 null（永久）
      minutes: isForever ? null : banForm.minutes,
      reason: banForm.reason.trim()
    })
    ElMessage.success(res?.message || '已封禁')
    banForm.target = ''
    banForm.reason = ''
    banPage.value = 1
    fetchIpBans()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '封禁失败')
  } finally {
    creatingBan.value = false
  }
}

async function handleUnban(row) {
  try {
    await ElMessageBox.confirm(
      `确定解除对 ${row.target} 的封禁吗？解除后该地址立即可以登录，登录失败计数也会清零。`,
      '解除封禁',
      { type: 'warning', confirmButtonText: '解封' }
    )
  } catch (e) {
    return // 取消
  }
  try {
    await deleteIpBan(row.id)
    ElMessage.success('已解除封禁')
    fetchIpBans()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '解封失败')
  }
}

// ---------- 资料下载管理 ----------
const resources = ref([])
const loadingResources = ref(false)
const uploading = ref(false)
// 上传进度百分比（算不出总大小时为 0，就不显示数字）
const uploadProgress = ref(0)
const fileInputRef = ref(null)

// 按分类分组给展示
const resourceGroups = computed(() => {
  const groups = {}
  const order = []
  for (const r of resources.value) {
    if (!groups[r.category]) {
      groups[r.category] = []
      order.push(r.category)
    }
    groups[r.category].push(r)
  }
  return order.map((cat) => ({
    category: cat,
    items: groups[cat].sort((a, b) => a.sort_order - b.sort_order)
  }))
})

async function fetchResources() {
  loadingResources.value = true
  try {
    resources.value = await listResources()
  } catch (e) {
    ElMessage.error('资料列表加载失败')
  } finally {
    loadingResources.value = false
  }
}

function handleUploadClick() {
  fileInputRef.value?.click()
}

async function handleFileSelected(e) {
  const file = e.target.files?.[0]
  if (!file) return

  try {
    // 弹框填名称和分类
    const { value: name, } = await ElMessageBox.prompt('请输入资料名称', '上传资料', {
      confirmButtonText: '下一步',
      cancelButtonText: '取消',
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空'
    })
    const { value: category } = await ElMessageBox.prompt('请输入分类（如：徽章标志、常用表格）', '选择分类', {
      confirmButtonText: '上传',
      cancelButtonText: '取消',
      inputValue: resourceGroups.value[0]?.category || '',
      inputPattern: /\S+/,
      inputErrorMessage: '分类不能为空'
    })

    const formData = new FormData()
    formData.append('name', name)
    formData.append('category', category)
    formData.append('file', file)

    uploading.value = true
    uploadProgress.value = 0
    try {
      await uploadResource(formData, (loaded, total) => {
        uploadProgress.value = total ? Math.round((loaded / total) * 100) : 0
      })
      ElMessage.success('上传成功')
      fetchResources()
    } catch (err) {
      ElMessage.error(err?.response?.data?.detail || '上传失败')
    } finally {
      uploading.value = false
    }
  } catch (e) {
    // 用户取消了 prompt
  } finally {
    // 重置 input，否则同一个文件下次还能触发 change
    e.target.value = ''
  }
}

async function handleEditResource(row) {
  try {
    const { value: name } = await ElMessageBox.prompt('修改资料名称', '编辑资料', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: row.name,
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空'
    })
    const { value: category } = await ElMessageBox.prompt('修改分类', '编辑资料', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: row.category,
      inputPattern: /\S+/,
      inputErrorMessage: '分类不能为空'
    })

    const formData = new FormData()
    formData.append('name', name)
    formData.append('category', category)
    await updateResource(row.id, formData)
    ElMessage.success('已更新')
    fetchResources()
  } catch (e) {
    if (e !== 'cancel') return // 用户取消
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  }
}

async function handleDeleteResource(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.name}」吗？文件也会一并删除，无法恢复。`,
      '删除资料',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch (e) {
    return
  }
  try {
    await deleteResource(row.id)
    ElMessage.success('已删除')
    fetchResources()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

async function moveResource(row, direction) {
  // direction: -1=上移, 1=下移
  const group = resourceGroups.value.find((g) => g.category === row.category)
  if (!group) return
  const idx = group.items.findIndex((r) => r.id === row.id)
  if (idx < 0) return
  const newIdx = idx + direction
  if (newIdx < 0 || newIdx >= group.items.length) return

  // 本地交换，发请求
  const newItems = [...group.items]
  ;[newItems[idx], newItems[newIdx]] = [newItems[newIdx], newItems[idx]]
  const order = newItems.map((r) => r.id)

  try {
    await reorderResources(row.category, order)
    fetchResources()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '排序失败')
  }
}

async function moveResourceCategory(index, direction) {
  // direction: -1=上移, 1=下移。整组交换，不动组内资料
  const target = index + direction
  if (target < 0 || target >= resourceGroups.value.length) return

  const order = resourceGroups.value.map((g) => g.category)
  ;[order[index], order[target]] = [order[target], order[index]]

  try {
    await reorderResourceCategories(order)
    fetchResources()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '调整分类顺序失败')
  }
}

// ---------- 生日关怀 ----------
const birthdayLoaded = ref(false)
const loadingBirthday = ref(false)
const savingBirthday = ref(false)
const testingBirthday = ref(false)
// 后端回给前端的默认祝福语文案，用作输入框的灰字 placeholder
const birthdayDefaults = reactive({ template: '' })
const birthdayForm = reactive({
  banner_enabled: false,
  banner_show_names: false,
  greet_enabled: false,
  greet_template: '',
  notify_enabled: false,
  notify_student_nos: [],
  // 下面这些是只读的运行状态，不参与提交（见 birthdayPayload）
  last_run_date: null,
  last_run_at: null,
  last_run_birthdays: null,
  last_run_notices: null,
  scheduler_state: '',
  next_run_at: null
})

async function fetchBirthdaySettings() {
  loadingBirthday.value = true
  try {
    const data = await getBirthdaySettings()
    Object.assign(birthdayForm, {
      banner_enabled: !!data.banner_enabled,
      banner_show_names: !!data.banner_show_names,
      greet_enabled: !!data.greet_enabled,
      greet_template: data.greet_template || '',
      notify_enabled: !!data.notify_enabled,
      notify_student_nos: data.notify_student_nos || [],
      // 运行状态（后端只读字段）
      last_run_date: data.last_run_date || null,
      last_run_at: data.last_run_at || null,
      last_run_birthdays: data.last_run_birthdays,
      last_run_notices: data.last_run_notices,
      scheduler_state: data.scheduler_state || '',
      next_run_at: data.next_run_at || null
    })
    birthdayDefaults.template = data.default_greet_template || ''
    birthdayLoaded.value = true
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '生日关怀设置加载失败')
  } finally {
    loadingBirthday.value = false
  }
}

/** 把后端的 ISO 时间显示成「MM-DD HH:MM」
 *
 * **只切字符串、不经过 new Date()**：后端给的是不带时区的本地时间串
 * （容器 TZ=Asia/Shanghai），交给 Date 去解析会被按**浏览器所在时区**重新解释，
 * 换个时区打开页面就显示成另一个时间了。截字符串永远不会错。
 */
function fmtRunTime(iso) {
  if (!iso) return ''
  const [day, clock] = String(iso).split('T')
  const [, mm, dd] = (day || '').split('-')
  return `${mm}-${dd} ${(clock || '').slice(0, 5)}`
}

/** 底部那行运行状态。三段用「；」连起来 */
const birthdayStatusText = computed(() => {
  const parts = []
  const state = birthdayForm.scheduler_state
  if (state === 'running') {
    parts.push('检查正常运行中')
  } else if (state === 'off') {
    parts.push('定时检查已关闭（BIRTHDAY_SCHEDULER=0），不会自动发送')
  } else {
    parts.push('定时检查未在运行，请查看后端日志')
  }

  if (birthdayForm.last_run_at) {
    parts.push(
      `上次检查于 ${fmtRunTime(birthdayForm.last_run_at)}，` +
        `${birthdayForm.last_run_birthdays ?? 0} 人生日，` +
        `通知 ${birthdayForm.last_run_notices ?? 0} 条`
    )
  } else {
    parts.push('还没有执行过检查')
  }

  // 只有确实在跑才谈得上「下次」：off / dead 时后端返回的 next_run_at 是 null，
  // 再说一句「预计很快执行」就是谎话了
  if (state === 'running') {
    parts.push(
      birthdayForm.next_run_at
        ? `预计下次于 ${fmtRunTime(birthdayForm.next_run_at)} 执行检查`
        : '预计很快会执行下一次检查'
    )
  }
  return parts.join('；')
})

/** 提交时只送后端认的六个字段：last_run_date 是只读的 */
function birthdayPayload() {
  return {
    banner_enabled: birthdayForm.banner_enabled,
    banner_show_names: birthdayForm.banner_show_names,
    greet_enabled: birthdayForm.greet_enabled,
    greet_template: birthdayForm.greet_template,
    notify_enabled: birthdayForm.notify_enabled,
    notify_student_nos: birthdayForm.notify_student_nos
  }
}

async function handleSaveBirthday() {
  savingBirthday.value = true
  try {
    const res = await saveBirthdaySettings(birthdayPayload())
    birthdayForm.last_run_date = res.last_run_date || birthdayForm.last_run_date
    ElMessage.success(res.message || '已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    savingBirthday.value = false
  }
}

async function handleTestBirthday() {
  testingBirthday.value = true
  try {
    // 测试只发给当前管理员自己，和上面三个开关无关，所以不用「先保存再测」
    const res = await testBirthdayNotify()
    ElMessage.success(res.message || '已发送')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发送失败')
  } finally {
    testingBirthday.value = false
  }
}

// ---------- 数据体检 ----------

const healthLoaded = ref(false)
const loadingHealth = ref(false)
// 一份报告的形状：{total_students, checked_at, groups: [{key, label, level, items}]}
const health = reactive({ total_students: 0, checked_at: null, groups: [] })

/** 所有卡片加起来多少条。卡片标题里的数字是各类分开算的，这个用于顶部汇总 */
const healthCount = computed(() =>
  health.groups.reduce((sum, group) => sum + group.items.length, 0)
)

async function fetchHealth() {
  loadingHealth.value = true
  try {
    const data = await getDataHealth()
    health.total_students = data.total_students || 0
    health.checked_at = data.checked_at || null
    health.groups = data.groups || []
    healthLoaded.value = true
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '数据体检失败')
  } finally {
    loadingHealth.value = false
  }
}

/** 跳到学生名单并直接弹开这个学生的详情（学生名单页认 ?open=<id>） */
function openStudent(id) {
  router.push({ path: '/students', query: { open: String(id) } })
}

onMounted(() => {
  fetchUsers()
  fetchLogs()
  fetchResources()
})
</script>

<style scoped>
.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.tip {
  margin-top: 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

/* ---------- 账号日志对话框 ---------- */
.log-section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 0 0 10px;
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

/* 第二个小标题跟上面的表格拉开距离，第一个不用（它就在弹窗顶部） */
.log-section-title:not(:first-child) {
  margin-top: 24px;
}

.log-section-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: normal;
}

/* ---------- 生日关怀 ---------- */
/* 一组开关，块之间留同样的间距；每块的标题行左对齐开关、右跟说明 */
.birthday-block:not(:first-child) {
  margin-top: 28px;
}

.birthday-block-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.birthday-block-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.birthday-block-body {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
  padding-left: 50px; /* 和上面的开关对齐，让从属关系看得出来 */
}

/* 输入框 / 下拉这类需要占满宽度的，换行竖排 */
.birthday-block-body.column {
  flex-direction: column;
  align-items: stretch;
  max-width: 560px;
}

.birthday-select {
  width: 100%;
}

.birthday-inline-tip {
  margin-top: 0;
}

.birthday-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 28px;
}

/* 运行状态行。是一整句长文案，行高放松一点才好读（.tip 是给短语用的） */
.birthday-status {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .birthday-block-body {
    padding-left: 0;
  }
}

/* ---------- 数据体检 ---------- */
.health-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.health-summary {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.health-card {
  margin-bottom: 20px;
}

.health-card:last-child {
  margin-bottom: 0;
}

.health-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.health-count {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

/* ---------- IP 封禁 ---------- */
.mono {
  font-family: monospace;
  font-size: 12px;
}

.ban-self-tip {
  margin-bottom: 12px;
}

/* ---------- 文件访问日志 ---------- */
.watermark-extract-box {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: 12px;
  background: var(--el-color-success-light-9);
  border: 1px solid var(--el-color-success-light-8);
  border-radius: 6px;
  flex-wrap: wrap;
}

.extract-label {
  font-size: 13px;
  font-weight: 600;
  color: #67c23a;
  flex-shrink: 0;
}

/* 上传中的提示：和 .extract-result 一样是这条绿色横条里的一格 */
.extract-progress {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.extract-file-input {
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.extract-file-input::file-selector-button {
  padding: 4px 12px;
  margin-right: 8px;
  border: 1px solid #67c23a;
  border-radius: 4px;
  background: var(--el-bg-color);
  color: #67c23a;
  cursor: pointer;
  font-size: 12px;
}

.extract-file-input::file-selector-button:hover {
  background: #67c23a;
  color: #fff;
}

.extract-result {
  font-size: 13px;
  display: flex;
  align-items: center;
  /* 允许换行：核不到日志时下面那行说明要独占一行 */
  flex-wrap: wrap;
  gap: 6px;
}

.extract-ip {
  color: var(--el-text-color-secondary);
  font-family: monospace;
  font-size: 12px;
}

/* 独占一行（父级是 flex 且已 flex-wrap） */
.extract-hint {
  width: 100%;
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}

.extract-result.found {
  color: #67c23a;
}

.extract-result.not-found {
  color: #e6a23c;
}

.extract-result strong {
  color: var(--el-text-color-primary);
  margin: 0 2px;
}

/* ---------- 资料下载管理 ---------- */
.resource-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.resource-toolbar .tip {
  margin: 0;
}

.resource-group {
  margin-bottom: 24px;
}

.resource-group:last-child {
  margin-bottom: 0;
}

.resource-group-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.group-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: normal;
  margin-left: 4px;
}

/* 分类的上移/下移按钮，推到标题行最右边，不跟分类名挤在一起 */
.category-order {
  margin-left: auto;
  display: inline-flex;
  gap: 6px;
}
</style>
