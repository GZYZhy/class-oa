<template>
  <div class="student-list">
    <!-- 筛选区域 -->
    <div class="page-card filter-card">
      <el-form :inline="true" :model="filterForm" size="default">
        <el-form-item label="关键词">
          <el-input
            v-model="filterForm.keyword"
            placeholder="任意信息（姓名/学号/电话/备注等）"
            clearable
            style="width: 240px"
            @keyup.enter="handleSearch"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </el-form-item>

        <el-form-item label="性别">
          <el-select v-model="filterForm.gender" placeholder="全部" clearable style="width: 100px">
            <el-option label="男" value="男" />
            <el-option label="女" value="女" />
          </el-select>
        </el-form-item>

        <el-form-item label="民族">
          <el-select v-model="filterForm.ethnicity" placeholder="全部" clearable style="width: 120px">
            <el-option
              v-for="item in filterOptions?.ethnicities || []"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="政治面貌">
          <el-select v-model="filterForm.political_status" placeholder="全部" clearable style="width: 130px">
            <el-option
              v-for="item in filterOptions?.political_statuses || []"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="宿舍">
          <el-select v-model="filterForm.dormitory" placeholder="全部" clearable style="width: 110px">
            <el-option
              v-for="item in filterOptions?.dormitories || []"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="贫困生">
          <el-select v-model="filterForm.is_poor" placeholder="全部" clearable style="width: 100px">
            <el-option label="是" value="是" />
            <el-option label="否" value="否" />
          </el-select>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="handleSearch">
            <el-icon><Search /></el-icon>查询
          </el-button>
          <el-button @click="handleReset">
            <el-icon><Refresh /></el-icon>重置
          </el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 表格区域 -->
    <div class="page-card" style="margin-top: 16px;">
      <div class="table-header">
        <h3 class="page-title" style="margin-bottom: 0;">学生名单</h3>
        <div class="table-tools">
          <span class="tools-count">共 {{ total }} 人</span>
          <el-dropdown @command="handleSort">
            <el-button>
              <el-icon><Sort /></el-icon>
              排序
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="student_no_asc">按学号 ↑</el-dropdown-item>
                <el-dropdown-item command="student_no_desc">按学号 ↓</el-dropdown-item>
                <el-dropdown-item command="name_asc">按姓名 ↑</el-dropdown-item>
                <el-dropdown-item command="birth_date_desc">按年龄从大到小</el-dropdown-item>
                <el-dropdown-item command="birth_date_asc">按年龄从小到大</el-dropdown-item>
                <el-dropdown-item command="gaokao_score_desc">按高考分数 ↓</el-dropdown-item>
                <el-dropdown-item command="gaokao_score_asc">按高考分数 ↑</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <!-- 近期生日筛选：弹出输入天数 -->
          <el-popover :width="240" trigger="click" placement="bottom-end">
            <template #reference>
              <el-button :type="birthdayFilter ? 'warning' : ''">
                <!-- Element Plus 没有 Cake 这个图标，写了会渲染成未知元素、什么都不显示。
                     最贴近「生日」的是 Present（礼物盒） -->
                <el-icon><Present /></el-icon>
                近期生日
              </el-button>
            </template>
            <div class="birthday-pop">
              <p style="margin: 0 0 10px 0; font-size: 13px; color: var(--el-text-color-regular);">
                筛选未来 N 天内过生日的同学
              </p>
              <el-input-number v-model="birthdayDays" :min="1" :max="365" style="width: 100%;" />
              <div style="margin-top: 10px; text-align: right;">
                <el-button size="small" @click="clearBirthday">清除</el-button>
                <el-button size="small" type="primary" @click="applyBirthday">筛选</el-button>
              </div>
            </div>
          </el-popover>

          <!-- 点名：独立弹窗承载「选范围 → 逐个叫 → 汇总」三步 -->
          <el-button @click="rollCallRef?.open()">
            <el-icon><Pointer /></el-icon>
            点名
          </el-button>

          <!-- 抽签：独立弹窗，权限与页面一致（班委及以上） -->
          <el-button v-if="userStore.isCommittee" @click="drawRef?.open()">
            <el-icon><Aim /></el-icon>
            抽签
          </el-button>

          <!-- 导出：班委及以上可用，提交申请后管理员审批 -->
          <el-button
            v-if="userStore.isCommittee"
            type="success"
            @click="exportDialogVisible = true"
          >
            <el-icon><Download /></el-icon>
            导出
          </el-button>

          <!-- 管理员专属的三个低频操作收进「更多」：都摆出来窄屏就排不开了 -->
          <el-dropdown v-if="userStore.isAdmin" @command="handleMore">
            <el-button>
              <el-icon><MoreFilled /></el-icon>
              更多
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="import">
                  <el-icon><Upload /></el-icon>导入 Excel
                </el-dropdown-item>
                <el-dropdown-item command="photo-import">
                  <el-icon><Picture /></el-icon>批量导入照片
                </el-dropdown-item>
                <el-dropdown-item command="create">
                  <el-icon><Plus /></el-icon>添加学生
                </el-dropdown-item>
                <!-- 批量删除：勾了人才出现 -->
                <el-dropdown-item
                  v-if="selectedStudents.length"
                  command="batch-delete"
                  divided
                >
                  <el-icon><Delete /></el-icon>删除选中 {{ selectedStudents.length }} 人
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <!-- 生日筛选生效时显示的标签 -->
          <el-tag v-if="birthdayFilter" type="warning" closable @close="clearBirthday">
            未来 {{ birthdayDays }} 天生日 · {{ total }} 人
          </el-tag>

          <!-- 勾选跨页保留之后，当前页可能一个勾都没有，得让「手上还攥着人」可见 -->
          <el-tag v-if="selectedStudents.length" type="info" closable @close="clearSelection">
            已选 {{ selectedStudents.length }} 人
          </el-tag>
        </div>
      </div>

      <!-- row-key + reserve-selection 一起才有跨页保留勾选的效果（前者认人，后者记住） -->
      <el-table
        ref="tableRef"
        :data="tableData"
        row-key="id"
        v-loading="loading"
        stripe
        border
        style="width: 100%; margin-top: 16px;"
        @selection-change="handleSelectionChange"
        @row-click="handleView"
        :row-style="{ cursor: 'pointer' }"
      >
        <el-table-column
          v-if="userStore.isCommittee || userStore.isAdmin"
          type="selection"
          :reserve-selection="true"
          width="50"
          align="center"
        />
        <el-table-column type="index" label="序号" width="60" align="center" />
        <el-table-column label="照片" width="70" align="center">
          <template #default="{ row }">
            <div
              class="thumb-photo"
              @click.stop="row.gaokao_photo && openRowPhotos(row)"
            >
              <img
                v-if="row.gaokao_photo"
                :src="getPhotoUrl(row, 'gaokao')"
                class="thumb-img"
                loading="lazy"
                fetchpriority="low"
                @error="handleImgError($event)"
              />
              <div v-else class="thumb-placeholder">
                <el-icon style="font-size: 22px;"><Avatar /></el-icon>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="姓名" width="90" align="center" />
        <el-table-column prop="gender" label="性别" width="60" align="center">
          <template #default="{ row }">
            <el-tag :type="row.gender === '男' ? 'primary' : 'danger'" size="small">
              {{ row.gender }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="student_no" label="学号" width="130" align="center" />
        <el-table-column prop="ethnicity" label="民族" width="90" align="center" />
        <el-table-column prop="political_status" label="政治面貌" width="100" align="center" />
        <!-- 生源地不再平铺展示，让位给备注：备注是班委内部记录，需要一眼看到 -->
        <!-- 备注列：去掉 Markdown 语法符号后显示，避免表格里出现 # ** 等符号 -->
        <el-table-column prop="remark" label="备注" min-width="180" align="center" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.remark">{{ stripMarkdown(row.remark) }}</span>
            <span v-else style="color: var(--el-text-color-disabled);">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="dormitory" label="宿舍" width="90" align="center" />
        <el-table-column prop="gaokao_score" label="高考分数" width="90" align="center" sortable />
        <el-table-column prop="class_position" label="班委" width="120" align="center" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="row.class_position && row.class_position !== '无'" type="warning" size="small">
              {{ row.class_position }}
            </el-tag>
            <span v-else style="color: var(--el-text-color-disabled);">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right" align="center">
          <template #default="{ row }">
            <el-button type="primary" link @click.stop="handleView(row)">查看</el-button>
            <el-button type="warning" link @click.stop="handleEdit(row)">编辑</el-button>
            <el-button
              v-if="userStore.isAdmin"
              type="danger"
              link
              @click.stop="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 36, 50]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </div>

    <!-- 详情弹窗 -->
    <el-dialog
      v-model="detailVisible"
      title="学生详情"
      width="800px"
      :close-on-click-modal="false"
      class="detail-dialog"
    >
      <!-- 详情弹窗里是身份证号、家庭地址这类最敏感的信息，同样盖一层水印 -->
      <Watermark :text="watermarkText" />

      <template v-if="currentStudent">
        <div class="detail-header">
          <div class="detail-photo" @click="currentStudent.gaokao_photo && openStudentPhotos(currentStudent)">
            <img
              v-if="currentStudent.gaokao_photo"
              :src="getPhotoUrl(currentStudent, 'gaokao')"
              class="detail-photo-img"
              @error="handleImgError($event)"
            />
            <div v-else class="no-photo">
              <el-icon style="font-size: 48px;"><Avatar /></el-icon>
              <span>暂无照片</span>
            </div>
          </div>
          <div class="detail-info">
            <h2 style="margin: 0 0 8px 0; font-size: 22px;">{{ currentStudent.name }}</h2>
            <p style="margin: 4px 0; color: var(--el-text-color-regular);">
              学号：{{ currentStudent.student_no }}
              <el-button link type="primary" @click="copyText(currentStudent.student_no)">
                <el-icon><CopyDocument /></el-icon>
              </el-button>
            </p>
            <p style="margin: 4px 0; color: var(--el-text-color-regular);">
              {{ currentStudent.class_name }}班 · {{ currentStudent.major }}专业
            </p>
            <p style="margin: 4px 0; color: var(--el-text-color-regular);">
              <el-tag :type="currentStudent.gender === '男' ? 'primary' : 'danger'" size="small" style="margin-right: 8px;">
                {{ currentStudent.gender }}
              </el-tag>
              <el-tag type="info" size="small" style="margin-right: 8px;">
                {{ currentStudent.ethnicity }}
              </el-tag>
              <el-tag type="warning" size="small">
                {{ currentStudent.political_status }}
              </el-tag>
            </p>
          </div>
        </div>

        <el-descriptions :column="detailColumns" border size="default" style="margin-top: 16px;">
          <el-descriptions-item label="出生日期">{{ formatDate(currentStudent.birth_date) }}</el-descriptions-item>
          <el-descriptions-item label="在校状态">
            <el-tag :type="currentStudent.school_status === '正常' ? 'success' : 'warning'">
              {{ currentStudent.school_status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="生源地" :span="detailColumns">
            {{ currentStudent.hometown }}
            <el-button link type="primary" @click="copyText(currentStudent.hometown)">
              <el-icon><CopyDocument /></el-icon>复制
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="本人电话">
            {{ currentStudent.phone }}
            <el-button link type="primary" @click="copyText(currentStudent.phone)">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="家庭电话">
            {{ currentStudent.family_phone }}
            <el-button link type="primary" @click="copyText(currentStudent.family_phone)">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="电子邮箱">
            {{ currentStudent.email }}
            <el-button link type="primary" @click="copyText(currentStudent.email)">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="QQ号码">
            {{ currentStudent.qq }}
            <el-button link type="primary" @click="copyText(currentStudent.qq)">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="家庭地址" :span="detailColumns">
            {{ currentStudent.family_address }}
            <el-button link type="primary" @click="copyText(currentStudent.family_address)">
              <el-icon><CopyDocument /></el-icon>复制
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="邮政编码">{{ currentStudent.postal_code }}</el-descriptions-item>
          <el-descriptions-item label="宿舍/床位">{{ currentStudent.dormitory }} / {{ currentStudent.bed }}床</el-descriptions-item>
          <el-descriptions-item label="班委职务">{{ currentStudent.class_position || '无' }}</el-descriptions-item>
          <el-descriptions-item label="团学会职务">{{ currentStudent.league_position || '无' }}</el-descriptions-item>
          <el-descriptions-item label="考生号">{{ currentStudent.exam_no }}</el-descriptions-item>
          <el-descriptions-item label="身份证号">
            {{ currentStudent.id_card }}
            <el-button link type="primary" @click="copyText(currentStudent.id_card)">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="考生类别">{{ currentStudent.exam_category }}</el-descriptions-item>
          <el-descriptions-item label="科类">{{ currentStudent.subject_type }}</el-descriptions-item>
          <el-descriptions-item label="考试类型">{{ currentStudent.exam_type }}</el-descriptions-item>
          <el-descriptions-item label="录取批次">{{ currentStudent.admission_batch }}</el-descriptions-item>
          <el-descriptions-item label="高考总分" style="font-weight: bold; color: #409EFF;">
            {{ currentStudent.gaokao_score }}分
          </el-descriptions-item>
          <el-descriptions-item label="毕业中学">{{ currentStudent.high_school }}</el-descriptions-item>
          <el-descriptions-item label="报到状态">{{ currentStudent.registration_status }}</el-descriptions-item>
          <el-descriptions-item label="报到时间">{{ formatDateTime(currentStudent.registration_time) }}</el-descriptions-item>
          <el-descriptions-item label="是否贫困生">
            <el-tag :type="currentStudent.is_poor === '是' ? 'warning' : 'info'">
              {{ currentStudent.is_poor }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 备注：独立一块，和照片资料平级 -->
        <div class="remark-section">
          <h4 class="section-title">
            <el-icon><EditPen /></el-icon> 备注
          </h4>
          <div v-if="currentStudent.remark" class="markdown-body remark-detail-content" v-html="renderMarkdown(currentStudent.remark)"></div>
          <div v-else style="color: var(--el-text-color-disabled);">暂无备注</div>

          <!-- 备注附件列表 -->
          <div v-if="currentStudent.remark_attachments?.length" class="remark-attach-section">
            <div class="attach-title">
              <el-icon><Paperclip /></el-icon>
              附件（{{ currentStudent.remark_attachments.length }}）
            </div>
            <div class="attach-list">
              <div
                v-for="(att, idx) in currentStudent.remark_attachments"
                :key="idx"
                class="attach-item"
                @click="downloadRemarkAttachment(currentStudent.id, idx, att.name)"
              >
                <el-icon><Document /></el-icon>
                <span class="attach-name">{{ att.name }}</span>
                <span class="attach-size">{{ formatFileSize(att.size) }}</span>
                <el-icon class="attach-download"><Download /></el-icon>
              </div>
            </div>
          </div>
        </div>

        <!-- 照片展示区 -->
        <div class="photos-section" v-if="PHOTO_TYPES.some((p) => currentStudent[p.field])">
          <h4 class="section-title">
            <el-icon><Picture /></el-icon> 照片资料
          </h4>
          <div class="photos-row">
            <template v-for="p in PHOTO_TYPES" :key="p.type">
              <div
                class="photo-item"
                v-if="currentStudent[p.field]"
                @click="openStudentPhotos(currentStudent, p.type)"
              >
                <img :src="getPhotoUrl(currentStudent, p.type)" class="photo-item-img" @error="handleImgError($event)" />
                <span class="photo-label">{{ p.label }}</span>
              </div>
            </template>
          </div>
          <p class="photos-tip">点击照片可放大查看</p>
        </div>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="primary" @click="handleEdit(currentStudent)">编辑信息</el-button>
      </template>
    </el-dialog>

    <!-- 编辑 / 新增弹窗：同一个表单，靠 editForm.id 区分模式。
         新增时只有学号、姓名必填，其余留空后补 -->
    <el-dialog
      v-model="editVisible"
      :title="editForm.id ? '编辑学生信息' : '添加学生'"
      width="700px"
      :close-on-click-modal="false"
      @closed="resetEditForm"
    >
      <el-form :model="editForm" label-width="100px" v-if="editVisible">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="基本信息" name="basic">
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="学号" required>
                  <!-- 学号就是登录账号，建好之后不能改：改了这学生立刻登不上，
                       请假/反馈里存的学号也对不上号。要换号只能删除后重新新增 -->
                  <el-input
                    v-model="editForm.student_no"
                    :disabled="!!editForm.id"
                    placeholder="登录账号，建好后不可修改"
                  />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="姓名" required>
                  <el-input v-model="editForm.name" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="性别">
                  <el-select v-model="editForm.gender" style="width: 100%">
                    <el-option label="男" value="男" />
                    <el-option label="女" value="女" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="民族">
                  <el-input v-model="editForm.ethnicity" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="出生日期">
                  <el-date-picker v-model="editForm.birth_date" type="date" style="width: 100%" value-format="YYYY-MM-DD" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="政治面貌">
                  <el-input v-model="editForm.political_status" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="班级">
                  <el-input v-model="editForm.class_name" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="专业">
                  <el-input v-model="editForm.major" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="生源地">
                  <el-input v-model="editForm.hometown" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="身份证号">
                  <el-input v-model="editForm.id_card" />
                </el-form-item>
              </el-col>

              <el-col :span="24">
                <el-form-item label="照片">
                  <div v-if="!editForm.id" style="color: var(--el-text-color-secondary); font-size: 13px;">
                    先保存学生信息，之后就能在这里上传照片
                  </div>
                  <div v-else class="edit-photos">
                    <div v-for="p in PHOTO_TYPES" :key="p.type" class="edit-photo">
                      <div class="edit-photo-box" @click="editForm[p.field] && openPhotoViewer(editForm, p.type)">
                        <img
                          v-if="editForm[p.field]"
                          :src="getPhotoUrl(editForm, p.type)"
                          class="edit-photo-img"
                          @error="handleImgError($event)"
                        />
                        <div v-else class="edit-photo-empty">
                          <el-icon style="font-size: 24px;"><Avatar /></el-icon>
                        </div>
                      </div>
                      <div class="edit-photo-label">{{ p.label }}</div>
                      <div>
                        <el-button
                          size="small"
                          :loading="photoUploading === p.type"
                          @click="pickPhoto(p.type)"
                        >
                          <!-- 照片上限 10MB，慢网络下把上传进度显示出来 -->
                          {{ photoUploading === p.type && photoUploadProgress
                            ? `上传中 ${photoUploadProgress}%` : '选择图片' }}
                        </el-button>
                        <!-- 只有现场采集的那张需要开相机。必须是 link 样式：带边框的按钮
                             会把这一格撑得比另外两个照片框宽，三格就对不齐了。
                             上传中锁住 —— 开相机会把页面切到后台，可能挂起正在传的那张 -->
                        <el-button
                          v-if="p.camera"
                          size="small"
                          link
                          type="primary"
                          :disabled="!!photoUploading"
                          @click="pickPhoto(p.type, true)"
                        >
                          拍照
                        </el-button>
                        <el-button
                          v-if="editForm[p.field]"
                          size="small"
                          link
                          type="danger"
                          @click="handleDeletePhoto(p.type)"
                        >
                          删除
                        </el-button>
                      </div>
                    </div>
                  </div>
                  <!-- 隐藏的原生文件选择框：选完即传，不需要额外的「上传」按钮。
                       两个框共用 handlePhotoPicked —— 换哪一张由 pickPhoto 写进 photoPicking。
                       第二个框靠 capture 唤起系统相机（手机）；桌面浏览器忽略它，退化成选文件 -->
                  <input
                    ref="photoInput"
                    type="file"
                    accept="image/*"
                    style="display: none"
                    @change="handlePhotoPicked"
                  />
                  <input
                    ref="cameraInput"
                    type="file"
                    accept="image/*"
                    capture="environment"
                    style="display: none"
                    @change="handlePhotoPicked"
                  />
                </el-form-item>
              </el-col>
            </el-row>
          </el-tab-pane>

          <el-tab-pane label="联系方式" name="contact">
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="本人电话">
                  <el-input v-model="editForm.phone" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="家庭电话">
                  <el-input v-model="editForm.family_phone" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="电子邮箱">
                  <el-input v-model="editForm.email" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="QQ号码">
                  <el-input v-model="editForm.qq" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="家庭地址">
                  <el-input v-model="editForm.family_address" type="textarea" :rows="2" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="邮政编码">
                  <el-input v-model="editForm.postal_code" />
                </el-form-item>
              </el-col>
            </el-row>
          </el-tab-pane>

          <el-tab-pane label="入学信息" name="enrollment">
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="高考总分">
                  <el-input-number v-model="editForm.gaokao_score" :min="0" :max="750" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="毕业中学">
                  <el-input v-model="editForm.high_school" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="考生号">
                  <el-input v-model="editForm.exam_no" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="考生类别">
                  <el-input v-model="editForm.exam_category" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="科类">
                  <el-input v-model="editForm.subject_type" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="考试类型">
                  <el-input v-model="editForm.exam_type" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="录取批次">
                  <el-input v-model="editForm.admission_batch" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="报到状态">
                  <el-input v-model="editForm.registration_status" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="报到时间">
                  <el-date-picker
                    v-model="editForm.registration_time"
                    type="datetime"
                    style="width: 100%"
                    value-format="YYYY-MM-DD HH:mm:ss"
                    placeholder="选择报到时间"
                  />
                </el-form-item>
              </el-col>
            </el-row>
          </el-tab-pane>

          <el-tab-pane label="在校情况" name="school">
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="在校状态">
                  <el-input v-model="editForm.school_status" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="宿舍">
                  <el-input v-model="editForm.dormitory" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="床位">
                  <el-input v-model="editForm.bed" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="班委职务">
                  <el-input v-model="editForm.class_position" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="团学会职务">
                  <el-input v-model="editForm.league_position" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="是否贫困生">
                  <el-select v-model="editForm.is_poor" style="width: 100%">
                    <el-option label="是" value="是" />
                    <el-option label="否" value="否" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
          </el-tab-pane>

          <el-tab-pane label="备注" name="remark">
            <el-row :gutter="20">
              <el-col :span="24">
                <el-form-item label="备注内容">
                  <el-input
                    v-model="editForm.remark"
                    type="textarea"
                    :rows="10"
                    placeholder="支持 Markdown 格式：# 标题、**加粗**、- 列表 等；班委内部记录，普通学生看不到"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="附件">
                  <div class="upload-area">
                    <!-- 已有附件 -->
                    <div v-if="editAttachments.length" class="existing-attachments">
                      <div
                        v-for="(att, idx) in editAttachments"
                        :key="'edit-old-' + idx"
                        class="attach-row"
                      >
                        <el-icon><Document /></el-icon>
                        <span class="attach-name">{{ att.name }}</span>
                        <span class="attach-size">{{ formatFileSize(att.size) }}</span>
                        <el-button
                          type="danger"
                          link
                          size="small"
                          @click="removeEditAttachment(idx)"
                        >移除</el-button>
                      </div>
                    </div>
                    <!-- 新上传的文件 -->
                    <div v-if="editNewAttachments.length" class="existing-attachments">
                      <div
                        v-for="(file, idx) in editNewAttachments"
                        :key="'edit-new-' + idx"
                        class="attach-row"
                      >
                        <el-icon><Document /></el-icon>
                        <span class="attach-name">{{ file.name }}</span>
                        <span class="attach-size">{{ formatFileSize(file.size) }}</span>
                        <el-button
                          type="danger"
                          link
                          size="small"
                          @click="removeEditNewAttachment(idx)"
                        >移除</el-button>
                      </div>
                    </div>
                    <el-upload
                      class="remark-upload"
                      :auto-upload="false"
                      :show-file-list="false"
                      :on-change="handleEditAttachChange"
                      :accept="REMARK_ALLOWED_EXTS"
                      multiple
                    >
                      <el-button :disabled="editAttachments.length + editNewAttachments.length >= REMARK_MAX_TOTAL_ATTACHMENTS">
                        <el-icon><Upload /></el-icon>
                        上传附件
                      </el-button>
                    </el-upload>
                    <div class="upload-tip">
                      每次最多上传 {{ REMARK_MAX_NEW_ATTACHMENTS }} 个，每个 {{ REMARK_MAX_ATTACH_SIZE / 1024 / 1024 }}MB；
                      总共最多 {{ REMARK_MAX_TOTAL_ATTACHMENTS }} 个附件
                    </div>
                  </div>
                </el-form-item>
              </el-col>
            </el-row>
          </el-tab-pane>
        </el-tabs>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">
          {{ editForm.id ? '保存' : '添加' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 备注编辑弹窗：班委及以上都能改，是班委唯一可编辑的学生字段 -->
    <el-dialog
      v-model="remarkVisible"
      :title="`编辑备注 - ${remarkForm.name || ''}`"
      width="640px"
      :close-on-click-modal="false"
    >
      <el-form :model="remarkForm" label-width="70px">
        <el-form-item label="备注">
          <el-input
            v-model="remarkForm.remark"
            type="textarea"
            :rows="10"
            placeholder="支持 Markdown 格式：# 标题、**加粗**、- 列表 等；班委内部记录，普通学生看不到"
          />
        </el-form-item>
        <el-form-item label="附件">
          <div class="upload-area">
            <!-- 已有附件 -->
            <div v-if="remarkAttachments.length" class="existing-attachments">
              <div
                v-for="(att, idx) in remarkAttachments"
                :key="'old-' + idx"
                class="attach-row"
              >
                <el-icon><Document /></el-icon>
                <span class="attach-name">{{ att.name }}</span>
                <span class="attach-size">{{ formatFileSize(att.size) }}</span>
                <el-button
                  type="danger"
                  link
                  size="small"
                  @click="removeRemarkAttachment(idx)"
                >移除</el-button>
              </div>
            </div>
            <!-- 新上传的文件 -->
            <div v-if="remarkNewAttachments.length" class="existing-attachments">
              <div
                v-for="(file, idx) in remarkNewAttachments"
                :key="'new-' + idx"
                class="attach-row"
              >
                <el-icon><Document /></el-icon>
                <span class="attach-name">{{ file.name }}</span>
                <span class="attach-size">{{ formatFileSize(file.size) }}</span>
                <el-button
                  type="danger"
                  link
                  size="small"
                  @click="removeNewRemarkAttachment(idx)"
                >移除</el-button>
              </div>
            </div>
            <!-- 上传按钮 -->
            <el-upload
              class="remark-upload"
              :auto-upload="false"
              :show-file-list="false"
              :on-change="handleRemarkAttachChange"
              :accept="REMARK_ALLOWED_EXTS"
              multiple
            >
              <el-button :disabled="remarkAttachments.length + remarkNewAttachments.length >= REMARK_MAX_TOTAL_ATTACHMENTS">
                <el-icon><Upload /></el-icon>
                上传附件
              </el-button>
            </el-upload>
            <div class="upload-tip">
              每次最多上传 {{ REMARK_MAX_NEW_ATTACHMENTS }} 个，每个 {{ REMARK_MAX_ATTACH_SIZE / 1024 / 1024 }}MB；
              总共最多 {{ REMARK_MAX_TOTAL_ATTACHMENTS }} 个附件
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="remarkVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSaveRemark">保存</el-button>
      </template>
    </el-dialog>

    <!-- 照片查看器 -->
    <el-image-viewer
      v-if="viewerVisible"
      :url-list="viewerList"
      :initial-index="viewerIndex"
      @close="viewerVisible = false"
    />

    <!-- 导入 Excel 弹框（与初始化浮层共用同一个组件） -->
    <StudentImportDialog ref="importDialogRef" @done="fetchList" />

    <!-- 导出弹框 -->
    <el-dialog
      v-model="exportDialogVisible"
      title="导出学生信息"
      width="560px"
      @open="onExportDialogOpen"
    >
      <el-tabs v-model="exportTab" @tab-change="handleExportTabChange">
        <!-- 新建申请 -->
        <el-tab-pane label="新建申请" name="new">
          <el-form label-position="top">
            <el-form-item label="导出类型">
              <el-radio-group v-model="exportForm.export_type">
                <el-radio value="excel_list">名单 Excel</el-radio>
                <el-radio value="pdf_individual">个人信息表 PDF</el-radio>
              </el-radio-group>
              <div style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 10px;">
                <template v-if="exportForm.export_type === 'excel_list'">
                  一张 Excel 表，可选导出哪些列
                </template>
                <template v-else>
                  每人一份一页完整信息 PDF，打包成 zip 下载
                </template>
              </div>
            </el-form-item>

            <el-form-item label="学生范围">
              <el-radio-group v-model="exportForm.scope_type">
                <el-radio value="all">全部学生</el-radio>
                <el-radio value="filtered">当前筛选结果</el-radio>
                <el-radio value="selected">手动勾选</el-radio>
                <el-radio value="id_range">学号范围</el-radio>
              </el-radio-group>

              <div v-if="exportForm.scope_type === 'selected'" style="font-size: 13px; color: var(--el-text-color-regular); margin-top: 10px;">
                已选中 <b>{{ selectedStudents.length }}</b> 人
                <el-button size="small" link type="primary" @click="exportDialogVisible = false">
                  去表格里勾选
                </el-button>
              </div>

              <div v-if="exportForm.scope_type === 'id_range'" style="display: flex; gap: 8px; margin-top: 10px;">
                <el-input
                  v-model="exportForm.start_no"
                  placeholder="起始学号"
                  style="flex: 1;"
                />
                <span style="align-self: center; color: var(--el-text-color-secondary);">至</span>
                <el-input
                  v-model="exportForm.end_no"
                  placeholder="结束学号"
                  style="flex: 1;"
                />
              </div>
            </el-form-item>

            <!-- 仅 Excel 导出显示字段选择 -->
            <el-form-item v-if="exportForm.export_type === 'excel_list'" label="导出字段">
              <div class="export-field-groups">
                <div v-for="g in fieldGroups" :key="g.key" class="field-group">
                  <div class="field-group-title">{{ g.label }}</div>
                  <el-checkbox-group v-model="exportForm.fields">
                    <el-checkbox
                      v-for="f in g.fields"
                      :key="f.prop"
                      :value="f.prop"
                      :label="f.prop"
                    >
                      {{ f.label }}
                    </el-checkbox>
                  </el-checkbox-group>
                </div>
              </div>
              <div style="margin-top: 8px;">
                <el-button
                  size="small"
                  link
                  type="primary"
                  @click="exportForm.fields = defaultFields"
                >
                  恢复默认
                </el-button>
                <el-button
                  size="small"
                  link
                  type="primary"
                  @click="exportForm.fields = fieldGroups.flatMap(g => g.fields.map(f => f.prop))"
                >
                  全选
                </el-button>
                <el-button
                  size="small"
                  link
                  type="primary"
                  @click="exportForm.fields = []"
                >
                  清空
                </el-button>
              </div>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 我的申请 -->
        <el-tab-pane label="我的申请" name="history">
          <el-table :data="myRequests" v-loading="myRequestsLoading" stripe size="small">
            <el-table-column prop="created_at" label="申请时间" width="160">
              <template #default="{ row }">
                {{ new Date(row.created_at).toLocaleString() }}
              </template>
            </el-table-column>
            <el-table-column label="类型" width="130">
              <template #default="{ row }">{{ typeLabel(row.export_type) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button
                  v-if="row.status === 'generated' || row.status === 'approved'"
                  type="primary"
                  size="small"
                  link
                  :loading="downloadProgress?.reqId === row.id"
                  @click="handleDownload(row)"
                >
                  <!-- 导出的 zip 可能几十 MB，把进度写在按钮上：
                       网络差的时候看着数字涨，总比一个转圈转到人以为卡死了强 -->
                  {{ downloadProgress?.reqId === row.id && downloadPercent
                      ? downloadPercent + '%' : '下载' }}
                </el-button>
                <span v-else-if="row.status === 'rejected'" style="font-size: 12px; color: var(--el-text-color-secondary);">
                  {{ row.reject_reason }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="exportDialogVisible = false">取消</el-button>
        <el-button
          v-if="exportTab === 'new'"
          type="primary"
          :loading="submitting"
          @click="handleSubmitExport"
        >
          提交申请
        </el-button>
      </template>
    </el-dialog>

    <!-- 点名弹窗 -->
    <RollCallDialog ref="rollCallRef" />
    <PhotoImportDialog ref="photoImportRef" @done="fetchList" />

    <!-- 抽签弹窗。勾选要实时反映到「从表格里选（N）」上，所以走 prop 而不是 open 传参 -->
    <DrawDialog ref="drawRef" :selected="selectedStudents" />

    <!-- 整页水印：记录「谁在什么时候看的」，防止名单被截图外传 -->
    <Watermark :text="watermarkText" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getStudentList,
  getStudent,
  getFilterOptions,
  createStudent,
  updateStudent,
  deleteStudent,
  uploadStudentPhoto,
  deleteStudentPhoto,
  batchDeleteStudents
} from '@/api/student'
import {
  createExportRequest,
  getMyExportRequests,
  getExportFieldGroups,
  downloadExportFile
} from '@/api/export'
import { useUserStore } from '@/store/user'
import Watermark from '@/components/Watermark.vue'
import RollCallDialog from '@/components/RollCallDialog.vue'
import DrawDialog from '@/components/DrawDialog.vue'
import PhotoImportDialog from '@/components/PhotoImportDialog.vue'
import StudentImportDialog from '@/components/StudentImportDialog.vue'
import { useWatermark } from '@/composables/useWatermark'
import { useIsMobile } from '@/composables/useIsMobile'
import { copyText } from '@/utils/clipboard'
import { renderMarkdown, stripMarkdown, formatFileSize } from '@/utils/markdown'
import { downloadFile } from '@/utils/download'

// 备注附件限制（与后端对应）
const REMARK_MAX_NEW_ATTACHMENTS = 3
const REMARK_MAX_TOTAL_ATTACHMENTS = 15
const REMARK_MAX_ATTACH_SIZE = 20 * 1024 * 1024
const REMARK_ALLOWED_EXTS =
  '.jpg,.jpeg,.png,.gif,.bmp,.webp,.heic,.heif,.mp4,.mov,.m4v,.avi,.mkv,.webm,.mp3,.m4a,.wav,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.pdf,.txt,.md,.wps,.et,.dps,.zip,.rar,.7z'

const userStore = useUserStore()
// 读 ?open= 用（见 openFromQuery）
const route = useRoute()
const router = useRouter()

// 点名 / 抽签弹窗（独立组件，靠 ref 调它的 open()）
const rollCallRef = ref(null)
const drawRef = ref(null)
const photoImportRef = ref(null)
const importDialogRef = ref(null)

// 满页个人信息，盖一层「谁在看」的水印
const watermarkText = useWatermark()

// 详情弹窗在手机上只有 92% 宽，两列会把标签挤成竖排，收成一列
const isMobile = useIsMobile()
const detailColumns = computed(() => (isMobile.value ? 1 : 2))

const tableData = ref([])
const total = ref(0)
const loading = ref(false)
const currentPage = ref(1)
const pageSize = ref(20)
const filterOptions = ref(null)

const filterForm = reactive({
  keyword: '',
  gender: '',
  ethnicity: '',
  political_status: '',
  dormitory: '',
  is_poor: ''
})

const sortBy = ref('')
const sortOrder = ref('asc')

// 近期生日筛选
const birthdayDays = ref(7)
const birthdayFilter = ref(false)

const detailVisible = ref(false)
const currentStudent = ref(null)

const editVisible = ref(false)
const editForm = reactive({})
const saving = ref(false)
const activeTab = ref('basic')
// 管理员弹窗里的备注附件
const editAttachments = ref([])     // 保留的原附件
const editNewAttachments = ref([])  // 本次新上传的附件

// 弹窗里的三种照片。type 与后端 ?type= 的取值一致，field 是 students 表里对应的列
const PHOTO_TYPES = [
  { type: 'gaokao', field: 'gaokao_photo', label: '高考照片' },
  { type: 'on_site', field: 'on_site_photo', label: '实地采集', camera: true },
  { type: 'id', field: 'id_photo', label: '自备证件照' }
]
// type → 照片配置的查找表，替代各处 type === 'on_site' 的二元判断
const PHOTO_TYPE_MAP = Object.fromEntries(PHOTO_TYPES.map((p) => [p.type, p]))
const photoInput = ref(null)
// 第二个隐藏文件框：带 capture，手机上直接开相机（桌面浏览器忽略它，等同选文件）
const cameraInput = ref(null)
const photoUploading = ref('') // 正在上传的那张照片的 type，用来显示按钮 loading
// 照片上传进度百分比（算不出总大小时为 0，就不显示数字）
const photoUploadProgress = ref(0)
let photoPicking = '' // 这次点「选择图片」是想换哪一张

// 备注单独一个弹窗：班委只能改备注，没必要给他们开全字段的表单
const remarkVisible = ref(false)
const remarkForm = reactive({ id: null, name: '', remark: '' })
const remarkAttachments = ref([])     // 保留的原附件（按原下标，可能不连续）
const remarkNewAttachments = ref([])  // 本次新上传的附件文件

// 照片查看器
const viewerVisible = ref(false)
const viewerList = ref([])
const viewerIndex = ref(0)

/**
 * 照片地址：走带鉴权的接口，不再直连静态目录
 *
 * v 参数是照片文件名，后端不用它 —— 纯粹当版本号：换了照片文件名就变，
 * 地址跟着变，浏览器不会拿缓存里那张旧图接着显示
 * @param {object} student 学生对象（需要 id）
 * @param {string} type gaokao=高考照片，on_site=实地采集，id=自备证件照
 */
function getPhotoUrl(student, type) {
  if (!student?.id) return ''
  const fileName = student[PHOTO_TYPE_MAP[type]?.field]
  return `/api/students/${student.id}/photo?type=${type}&v=${encodeURIComponent(fileName || '')}`
}

/** 组装某学生可用的照片列表 [{ type, url }] */
function studentPhotos(student) {
  return PHOTO_TYPES
    .filter((p) => student?.[p.field])
    .map((p) => ({ type: p.type, url: getPhotoUrl(student, p.type) }))
}

function handleImgError(e) {
  // 图片加载失败时显示占位
  e.target.style.display = 'none'
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  return dateStr
}

function formatDateTime(dtStr) {
  if (!dtStr) return '-'
  return String(dtStr).replace('T', ' ').replace(/\.\d+$/, '')
}

/**
 * 打开照片查看器
 * @param {object} student 学生对象
 * @param {string} activeType 需要定位显示的照片类型
 */
function openPhotoViewer(student, activeType = 'gaokao') {
  const photos = studentPhotos(student)
  if (!photos.length) return
  viewerList.value = photos.map((p) => p.url)
  const index = photos.findIndex((p) => p.type === activeType)
  viewerIndex.value = index >= 0 ? index : 0
  viewerVisible.value = true
}

// 名单表格中点击某行的缩略图
function openRowPhotos(row) {
  openPhotoViewer(row, 'gaokao')
}

// 详情弹窗中点击照片
function openStudentPhotos(student, photoType = 'gaokao') {
  openPhotoViewer(student, photoType)
}

async function fetchData() {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize.value,
      keyword: filterForm.keyword || undefined,
      gender: filterForm.gender || undefined,
      ethnicity: filterForm.ethnicity || undefined,
      political_status: filterForm.political_status || undefined,
      dormitory: filterForm.dormitory || undefined,
      is_poor: filterForm.is_poor || undefined,
      sort_by: sortBy.value || undefined,
      sort_order: sortOrder.value,
      birthday_days: birthdayFilter.value ? birthdayDays.value : undefined
    }
    const res = await getStudentList(params)
    tableData.value = res.items
    total.value = res.total
  } catch (e) {
    ElMessage.error('获取数据失败')
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function fetchFilterOptions() {
  filterOptions.value = await getFilterOptions()
}

function handleSearch() {
  currentPage.value = 1
  fetchData()
}

function handleReset() {
  Object.keys(filterForm).forEach(key => { filterForm[key] = '' })
  birthdayFilter.value = false
  sortBy.value = ''
  sortOrder.value = 'asc'
  currentPage.value = 1
  fetchData()
}

function handleSort(command) {
  const parts = command.split('_')
  const order = parts.pop()
  const field = parts.join('_')
  sortBy.value = field
  sortOrder.value = order
  fetchData()
}

function applyBirthday() {
  birthdayFilter.value = true
  currentPage.value = 1
  fetchData()
}

function clearBirthday() {
  birthdayFilter.value = false
  currentPage.value = 1
  fetchData()
}

function handleSizeChange(size) {
  pageSize.value = size
  currentPage.value = 1
  fetchData()
}

function handleCurrentChange(page) {
  currentPage.value = page
  fetchData()
}

async function handleView(row) {
  // 列表数据本就是完整的学生信息，先用它打开弹窗，交互零等待；
  // 再后台请求详情接口静默刷新（差网络下也不阻塞弹窗操作）
  currentStudent.value = row
  detailVisible.value = true
  try {
    currentStudent.value = await getStudent(row.id)
  } catch (e) {
    // 弹窗已经打开，不必打断用户；详情与列表数据一致，失败也无实质影响
    console.error('详情刷新失败', e)
  }
}

/**
 * 清空编辑表单
 *
 * 不能用 `editForm = {}` —— `<script setup>` 里的绑定是只读的，
 * 那样写等于什么都没做（Vue 只会打一条警告），上一个学生的数据会漏进下一个表单。
 * 新增和编辑每次打开弹窗都先调一次。
 */
function resetEditForm() {
  Object.keys(editForm).forEach((key) => delete editForm[key])
  editAttachments.value = []
  editNewAttachments.value = []
}

/** 「更多」下拉：管理员那三个低频操作 */
function handleMore(command) {
  if (command === 'import') importDialogRef.value?.open()
  else if (command === 'photo-import') photoImportRef.value?.open()
  else if (command === 'create') handleCreate()
  else if (command === 'batch-delete') handleBatchDelete()
}

// 新增：空表单，只预填两个默认值（与后端 schema 的默认值一致）
function handleCreate() {
  resetEditForm()
  Object.assign(editForm, { school_status: '正常', is_poor: '否' })
  activeTab.value = 'basic'
  editVisible.value = true
}

// 编辑入口按角色分流：管理员开全字段弹窗，班委只开备注弹窗
function handleEdit(row) {
  detailVisible.value = false
  if (userStore.isAdmin) {
    resetEditForm()
    Object.assign(editForm, row)
    // 备注附件初始化
    editAttachments.value = (row.remark_attachments || []).map(a => ({ ...a }))
    editNewAttachments.value = []
    editVisible.value = true
    activeTab.value = 'basic'
  } else {
    remarkForm.id = row.id
    remarkForm.name = row.name
    remarkForm.remark = row.remark || ''
    // 原附件深拷贝一份（避免直接修改列表数据）
    remarkAttachments.value = (row.remark_attachments || []).map(a => ({ ...a }))
    remarkNewAttachments.value = []
    remarkVisible.value = true
  }
}

async function handleSave() {
  if (!editForm.name || !editForm.student_no) {
    ElMessage.warning('姓名和学号不能为空')
    return
  }
  saving.value = true
  try {
    if (editForm.id) {
      // 编辑：备注附件也一起提交
      const keepIndices = editAttachments.value.map(a => a.index)
      await updateStudent(
        editForm.id,
        editForm,
        {
          remarkNewAttachments: editNewAttachments.value,
          remarkKeepAttachments: keepIndices,
        }
      )
      ElMessage.success('保存成功')
    } else {
      // 新增：先创建学生（新增时不带附件，附件等编辑时再加）
      const res = await createStudent(editForm)
      showCreateResult(res)
    }
    editVisible.value = false
    fetchData()
    userStore.refreshTotal()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

// 管理员弹窗：移除已有附件
function removeEditAttachment(idx) {
  editAttachments.value.splice(idx, 1)
}

// 管理员弹窗：移除新上传的附件
function removeEditNewAttachment(idx) {
  editNewAttachments.value.splice(idx, 1)
}

// 管理员弹窗：上传文件变更
function handleEditAttachChange(file) {
  const total = editAttachments.value.length + editNewAttachments.value.length + 1
  if (total > REMARK_MAX_TOTAL_ATTACHMENTS) {
    ElMessage.warning(`备注附件总共最多 ${REMARK_MAX_TOTAL_ATTACHMENTS} 个`)
    return
  }
  if (editNewAttachments.value.length >= REMARK_MAX_NEW_ATTACHMENTS) {
    ElMessage.warning(`每次最多上传 ${REMARK_MAX_NEW_ATTACHMENTS} 个新附件`)
    return
  }
  if (file.size > REMARK_MAX_ATTACH_SIZE) {
    ElMessage.warning(`文件「${file.name}」超过 ${REMARK_MAX_ATTACH_SIZE / 1024 / 1024}MB`)
    return
  }
  editNewAttachments.value.push(file.raw)
}

/** 新增成功后交代初始密码：没有身份证号的那批要管理员单独去说一声 */
function showCreateResult(res) {
  if (!res.fallback) {
    // 有身份证号：密码是身份证后 6 位，属于隐私，不在界面上回显
    ElMessage.success(`${res.message}，初始密码为身份证号后 6 位`)
    return
  }
  ElMessageBox.alert(
    `${res.message}。该生还没有身份证号，初始密码为【学号后 6 位】：${res.password}。` +
      '学号本身不是秘密，请单独告知本人，并让他首次登录后立即改成自己的密码。',
    '新增成功，请转告初始密码',
    { confirmButtonText: '知道了' }
  )
}

// 删除学生：账号和照片一起清掉，历史请假/反馈记录保留
async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.name}（${row.student_no}）」吗？他的登录账号和照片文件会一并删除，` +
        '此操作不可恢复；已经审核过的请假、反馈记录会保留。',
      '删除学生',
      { type: 'warning', confirmButtonText: '删除' }
    )
  } catch (e) {
    return // 取消
  }
  try {
    await deleteStudent(row.id)
    ElMessage.success('已删除')
    fetchData()
    userStore.refreshTotal()
  } catch (e) {
    // 后端会挡住「删自己」和「还有待审核记录」两种情况，理由要原样告诉管理员
    ElMessageBox.alert(e?.response?.data?.detail || '删除失败', '无法删除', {
      type: 'warning',
      confirmButtonText: '知道了'
    })
  }
}

// 批量删除：能删则删，失败的单列理由
async function handleBatchDelete() {
  const n = selectedStudents.value.length
  if (!n) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${n} 名学生吗？账号和照片一并删除，不可恢复。`,
      '批量删除',
      { type: 'warning', confirmButtonText: '删除' }
    )
  } catch (e) {
    return // 取消
  }
  try {
    const ids = selectedStudents.value.map(s => s.id)
    const result = await batchDeleteStudents(ids)
    // 勾选是跨页保留的，不清掉的话删掉的人会留在选中集里，下次「删除 N 人」会带上幽灵行。
    // 部分失败时也清空：没删掉的人已经在结果弹窗里列出来了，重新勾比留着幽灵安全
    clearSelection()
    fetchData()
    userStore.refreshTotal()

    // 全部成功：一条提示即可；有失败的，弹窗列出每个人的原因
    if (!result.failed?.length) {
      ElMessage.success(result.message)
    } else {
      // ElMessageBox 的 message 按 HTML 渲染，所以文本要先转义再拼：
      // 学号/姓名是可写字段，不转义就是存储型 XSS（一个管理员植入、另一个删除时触发）。
      // 换行靠 \n + customClass 的 white-space: pre-wrap 保留
      const esc = (s) => String(s).replace(/&/g, '&amp;')
        .replace(/</g, '&lt;').replace(/>/g, '&gt;')
      const lines = result.failed.map((f) => {
        const who = f.student_no ? `${f.student_no} ${f.name}` : '（选中项不存在）'
        return `${esc(who)}：${esc(f.reason)}`
      })
      ElMessageBox.alert(
        `${esc(result.message)}\n\n${lines.join('\n')}`,
        '删除结果',
        { type: 'warning', confirmButtonText: '知道了', customClass: 'batch-delete-result' }
      )
    }
  } catch (e) {
    ElMessageBox.alert(
      e?.response?.data?.detail || '删除失败',
      '删除失败',
      { type: 'warning', confirmButtonText: '知道了' }
    )
  }
}

// ---------- 照片 ----------

/** 点「选择图片」/「拍照」：记下要换的是哪一张，再转交给对应的隐藏 input。
 *  useCamera=true 走带 capture 的那个：手机上直接开相机，桌面上退化成选文件 */
function pickPhoto(type, useCamera = false) {
  photoPicking = type
  const input = useCamera ? cameraInput : photoInput
  input.value?.click()
}

async function handlePhotoPicked(e) {
  const file = e.target.files?.[0]
  // 一定要清空：不清的话连着选同一个文件不会再触发 change
  e.target.value = ''
  if (!file || !photoPicking) return
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('照片不能超过 10MB')
    return
  }

  const type = photoPicking
  photoUploading.value = type
  photoUploadProgress.value = 0
  try {
    // 照片上限 10MB，手机上慢网络传得久，进度回填到百分比 ref
    const res = await uploadStudentPhoto(editForm.id, type, file, (loaded, total) => {
      photoUploadProgress.value = total ? Math.round((loaded / total) * 100) : 0
    })
    editForm[PHOTO_TYPE_MAP[type].field] = res.photo // 地址里的 v 参数跟着变，立刻显示新图
    ElMessage.success('照片已更新')
    fetchData()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '上传失败')
  } finally {
    photoUploading.value = ''
  }
}

async function handleDeletePhoto(type) {
  const label = PHOTO_TYPES.find((p) => p.type === type)?.label || '照片'
  try {
    await ElMessageBox.confirm(`确定删除这张${label}吗？`, '删除照片', { type: 'warning' })
  } catch (e) {
    return // 取消
  }
  try {
    await deleteStudentPhoto(editForm.id, type)
    editForm[PHOTO_TYPE_MAP[type].field] = null
    ElMessage.success('照片已删除')
    fetchData()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// 班委改备注：提交 remark + 附件（后端也只放行这两个字段）
async function handleSaveRemark() {
  saving.value = true
  try {
    // 保留的旧附件下标（remarkAttachments 里的每一项都保留，它们的原始 index 存在 index 字段里）
    const keepIndices = remarkAttachments.value.map(a => a.index)
    await updateStudent(
      remarkForm.id,
      { remark: remarkForm.remark },
      {
        remarkNewAttachments: remarkNewAttachments.value,
        remarkKeepAttachments: keepIndices,
      }
    )
    ElMessage.success('备注已保存')
    remarkVisible.value = false
    fetchData()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
    console.error(e)
  } finally {
    saving.value = false
  }
}

// 备注附件：移除已有附件
function removeRemarkAttachment(idx) {
  remarkAttachments.value.splice(idx, 1)
}

// 备注附件：移除新上传的附件
function removeNewRemarkAttachment(idx) {
  remarkNewAttachments.value.splice(idx, 1)
}

// 备注附件：上传文件变更
function handleRemarkAttachChange(file) {
  // 已保留的 + 新上传的 总数检查
  const total = remarkAttachments.value.length + remarkNewAttachments.value.length + 1
  if (total > REMARK_MAX_TOTAL_ATTACHMENTS) {
    ElMessage.warning(`备注附件总共最多 ${REMARK_MAX_TOTAL_ATTACHMENTS} 个`)
    return
  }
  // 本次新增数检查
  if (remarkNewAttachments.value.length >= REMARK_MAX_NEW_ATTACHMENTS) {
    ElMessage.warning(`每次最多上传 ${REMARK_MAX_NEW_ATTACHMENTS} 个新附件`)
    return
  }
  // 大小检查
  if (file.size > REMARK_MAX_ATTACH_SIZE) {
    ElMessage.warning(`文件「${file.name}」超过 ${REMARK_MAX_ATTACH_SIZE / 1024 / 1024}MB`)
    return
  }
  remarkNewAttachments.value.push(file.raw)
}

// 下载备注附件
async function downloadRemarkAttachment(studentId, index, name) {
  try {
    await downloadFile(`/api/students/${studentId}/remark-attachments/${index}`, name)
  } catch (e) {
    ElMessage.error('下载失败')
  }
}

// ==================== 导出 ====================

const tableRef = ref(null)
const selectedStudents = ref([])
const exportDialogVisible = ref(false)
const exportTab = ref('new') // new / history
const submitting = ref(false)
// 正在下载的那条：按钮转圈 + 显示百分比。一次只可能有一个（按钮上带了 loading，
// 下着的时候点不动）。后端的 zip 带 Content-Length，所以百分比是准的
const downloadProgress = ref(null)
const downloadPercent = computed(() => {
  const p = downloadProgress.value
  return p && p.total ? Math.round((p.loaded / p.total) * 100) : 0
})
const myRequests = ref([])
const myRequestsLoading = ref(false)

// 导出表单
const exportForm = reactive({
  export_type: 'excel_list', // excel_list / pdf_individual
  scope_type: 'all', // all / filtered / selected / id_range
  start_no: '',
  end_no: '',
  fields: [] // 选中的字段（excel 用）
})

// 字段分组（从后端拿）
const fieldGroups = ref([])
const defaultFields = ref([])

function handleSelectionChange(selection) {
  selectedStudents.value = selection
}

/** 清空勾选。「已选 N 人」标签上的 × 和批量删除成功之后都走这里 */
function clearSelection() {
  tableRef.value?.clearSelection()
  // clearSelection 会触发 selection-change，但别指望它 —— 表格还没挂载时啥也不会发生
  selectedStudents.value = []
}

async function loadFieldGroups() {
  if (fieldGroups.value.length) return
  try {
    const res = await getExportFieldGroups()
    fieldGroups.value = res.groups
    defaultFields.value = res.default_fields
    if (!exportForm.fields.length) {
      exportForm.fields = [...res.default_fields]
    }
  } catch (e) {
    console.error('加载导出字段失败', e)
  }
}

async function loadMyRequests() {
  myRequestsLoading.value = true
  try {
    const res = await getMyExportRequests({ page: 1, page_size: 20 })
    myRequests.value = res.items
  } catch (e) {
    console.error('加载我的申请失败', e)
  } finally {
    myRequestsLoading.value = false
  }
}

// 当用户切到「我的申请」tab 时加载
function handleExportTabChange(tab) {
  if (tab === 'history') {
    loadMyRequests()
  }
}

// 构造 scope_param
function buildScopeParam() {
  const t = exportForm.scope_type
  if (t === 'all') return null
  if (t === 'selected') {
    return { ids: selectedStudents.value.map(s => s.id) }
  }
  if (t === 'id_range') {
    return { start_no: exportForm.start_no, end_no: exportForm.end_no }
  }
  if (t === 'filtered') {
    // 当前筛选条件
    return {
      keyword: filterForm.keyword,
      gender: filterForm.gender,
      ethnicity: filterForm.ethnicity,
      political_status: filterForm.political_status,
      dormitory: filterForm.dormitory,
      is_poor: filterForm.is_poor,
      sort_by: sortBy.value,
      sort_order: sortOrder.value
    }
  }
  return null
}

async function handleSubmitExport() {
  // 校验
  if (exportForm.scope_type === 'selected' && !selectedStudents.value.length) {
    ElMessage.warning('请先在表格里勾选要导出的学生')
    return
  }
  if (exportForm.scope_type === 'id_range' && !exportForm.start_no && !exportForm.end_no) {
    ElMessage.warning('请输入至少一个学号边界')
    return
  }
  if (exportForm.export_type === 'excel_list' && !exportForm.fields.length) {
    ElMessage.warning('请至少选择一个导出字段')
    return
  }

  submitting.value = true
  try {
    const body = {
      export_type: exportForm.export_type,
      scope_type: exportForm.scope_type,
      scope_param: buildScopeParam(),
      fields: exportForm.export_type === 'excel_list' ? exportForm.fields : null
    }
    await createExportRequest(body)
    ElMessageBox.alert(
      '申请已提交，管理员正在审核中。\n审核通过后，请在本弹窗的「我的申请」页签下载文件。',
      '提交成功',
      {
        confirmButtonText: '查看我的申请',
        type: 'success'
      }
    ).then(() => {
      exportTab.value = 'history'
      loadMyRequests()
    })
  } catch (e) {
    ElMessage.error('提交失败：' + (e.message || '未知错误'))
  } finally {
    submitting.value = false
  }
}

async function handleDownload(req) {
  downloadProgress.value = { reqId: req.id, loaded: 0, total: 0 }
  let abortCtrl = null
  try {
    abortCtrl = new AbortController()
    const blob = await downloadExportFile(
      req.id,
      (loaded, total) => {
        downloadProgress.value = { reqId: req.id, loaded, total }
      },
      abortCtrl.signal
    )
    // 保存文件
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // 从 Content-Disposition 拿文件名太麻烦，直接用展示名 + 后缀
    const ext = req.export_type === 'excel_list' ? 'xlsx' : 'zip'
    a.download = `${req.file_original_name || ('学生信息导出.' + ext)}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    ElMessage.success('下载完成')
  } catch (e) {
    if (e?.code !== 'ERR_CANCELED' && e?.name !== 'CanceledError') {
      ElMessage.error('下载失败：' + (e.message || '未知错误'))
    }
  } finally {
    downloadProgress.value = null
  }
}

// 弹框打开时加载字段分组
function onExportDialogOpen() {
  loadFieldGroups()
  // 重置表单
  exportForm.export_type = 'excel_list'
  exportForm.scope_type = 'all'
  exportForm.start_no = ''
  exportForm.end_no = ''
  exportForm.fields = defaultFields.value.length ? [...defaultFields.value] : []
  exportTab.value = 'new'
}

// 状态 tag 颜色
function statusTagType(status) {
  return {
    pending: 'warning',
    approved: 'success',
    generated: 'success',
    rejected: 'danger',
    failed: 'info'
  }[status] || 'info'
}

function statusLabel(status) {
  return {
    pending: '待审核',
    approved: '已通过',
    generated: '已生成',
    rejected: '已驳回',
    failed: '生成失败'
  }[status] || status
}

function typeLabel(t) {
  return { excel_list: '名单 Excel', pdf_individual: '个人信息表 PDF' }[t] || t
}

/**
 * 别的页面点「查看学生」跳过来时带着 `?open=<学生 id>`，进来直接把详情弹开。
 *
 * 按 id 精确打开，**不走搜索框**：详情弹窗只用到 id，而按学号去搜会把
 * 「2026012」这种前缀相同的一串人都搜出来。
 *
 * 打开后立刻把 query 抹掉：否则在同一个页面再点一次同一个学生（组件复用、
 * onMounted 不重跑）没反应，而且刷新页面会莫名其妙又弹一次。
 */
function openFromQuery() {
  const id = Number(route.query.open)
  if (!id) return
  handleView({ id })
  router.replace({ query: {} })
}

onMounted(() => {
  fetchData()
  fetchFilterOptions()
  openFromQuery()
})

// 已经在这个页面上时，别处再点「查看」只会改 query，onMounted 不会重跑
watch(() => route.query.open, openFromQuery)
</script>

<style scoped>
.student-list {
  padding: 0;
  /* 整页水印以它为定位基准铺满 */
  position: relative;
}

.filter-card {
  padding-bottom: 0;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* 用 gap 统一间距。以前靠每个按钮自己 style="margin-left: 8px" 顶开，
   一换行行首就多出一块空白 —— 按钮多了之后这是最先难看的地方 */
.table-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}

.tools-count {
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}

.thumb-photo {
  cursor: pointer;
  display: flex;
  justify-content: center;
  align-items: center;
  width: 48px;
  height: 48px;
  margin: 0 auto;
}

.thumb-img {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}

.thumb-placeholder {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--el-fill-color-light);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-disabled);
}

.detail-photo-img {
  width: 120px;
  height: 160px;
  border-radius: 8px;
  object-fit: cover;
  display: block;
}

/* 编辑弹窗里的照片：两张并排放，各自带上传/删除 */
.edit-photos {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

.edit-photo {
  text-align: center;
}

.edit-photo-box {
  width: 100px;
  height: 130px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--el-fill-color-light);
  cursor: zoom-in;
}

.edit-photo-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.edit-photo-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-disabled);
}

.edit-photo-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin: 6px 0 4px;
}

.photo-item-img {
  /* 缩小显示，contain 保证原比例完整展示、不裁切 */
  width: 100%;
  height: 150px;
  object-fit: contain;
  display: block;
  background: var(--el-fill-color-light);
  padding: 8px;
  box-sizing: border-box;
}

.photos-tip {
  text-align: center;
  font-size: 12px;
  color: var(--el-text-color-disabled);
  margin: 8px 0 0 0;
}

.detail-header {
  display: flex;
  gap: 24px;
  padding: 16px;
  /* 走主题色浅色档：深色模式下会跟着变深，里面的字才不至于浅底白字 */
  background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-color-primary-light-8) 100%);
  border-radius: 8px;
  margin-bottom: 8px;
}

.detail-photo {
  cursor: zoom-in;
  flex-shrink: 0;
}

.no-photo {
  width: 120px;
  height: 160px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-disabled);
  font-size: 14px;
  gap: 8px;
}

.detail-info {
  flex: 1;
  padding-top: 4px;
}

.photos-section {
  margin-top: 20px;
}

.photos-row {
  display: flex;
  gap: 20px;
}

.photo-item {
  flex: 1;
  position: relative;
  cursor: zoom-in;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
}

.photo-label {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  text-align: center;
  padding: 6px 0;
  font-size: 13px;
}

:deep(.detail-dialog .el-dialog__body) {
  padding-top: 10px;
}

/* 工具栏按钮不少（人数/排序/近期生日/点名/抽签/导出/更多），手机上不换行会被顶出
   横向滚动条。收成「标题一行、工具栏一行」并左对齐 —— 右对齐换行后行首参差不齐 */
@media (max-width: 768px) {
  .table-header {
    flex-direction: column;
    align-items: flex-start;
    row-gap: 10px;
  }

  .table-tools {
    width: 100%;
    justify-content: flex-start;
  }
}

/* 导出弹框：字段分组 */
.export-field-groups {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 12px 16px;
  max-height: 360px;
  overflow-y: auto;
}
.field-group + .field-group {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.field-group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  margin-bottom: 8px;
}
.field-group .el-checkbox {
  margin-right: 16px;
  margin-bottom: 6px;
}

/* 详情里的独立 section 标题（与照片资料那一节风格一致） */
.section-title {
  margin: 20px 0 12px 0;
  color: var(--el-text-color-primary);
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 备注内容区 */
.remark-detail-content {
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  min-height: 48px;
}

/* 备注附件 */
.remark-attach-section {
  margin: 8px 0 4px;
  padding: 10px 14px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}

.attach-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.attach-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.attach-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--el-bg-color);
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
}

.attach-item:hover {
  background: var(--el-color-primary-light-9);
}

.attach-item .attach-name {
  flex: 1;
  font-size: 13px;
  color: #409eff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.attach-item .attach-size {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.attach-item .attach-download {
  font-size: 14px;
  color: #409eff;
  flex-shrink: 0;
}

/* 弹窗里的上传区 */
.upload-area {
  width: 100%;
}

.existing-attachments {
  margin-bottom: 8px;
}

.attach-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  margin-bottom: 4px;
}

.attach-row .attach-name {
  flex: 1;
  font-size: 13px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.attach-row .attach-size {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.upload-tip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>

<!-- 非 scoped：批量删除结果弹窗挂在 body 上，scoped 样式选不到 -->
<style>
.batch-delete-result .el-message-box__message p {
  white-space: pre-wrap;
}

/* Markdown 样式：v-html 渲染的内容不受 scoped 影响，必须写在这里 */
.markdown-body {
  padding: 8px 4px;
  color: var(--el-text-color-primary);
  line-height: 1.7;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3 {
  margin: 12px 0 8px;
}

.markdown-body ul,
.markdown-body ol {
  padding-left: 24px;
  margin: 8px 0;
}

.markdown-body code {
  background: var(--el-fill-color-light);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 90%;
}

.markdown-body blockquote {
  border-left: 4px solid #409EFF;
  padding: 4px 12px;
  margin: 8px 0;
  background: var(--el-color-primary-light-9);
  color: var(--el-text-color-regular);
}
</style>
