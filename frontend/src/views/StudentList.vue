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
          <span style="color: #909399; font-size: 14px; margin-right: 12px;">
            共 {{ total }} 人
          </span>
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
              <p style="margin: 0 0 10px 0; font-size: 13px; color: #606266;">
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
          <el-button style="margin-left: 8px;" @click="rollCallRef?.open()">
            <el-icon><Pointer /></el-icon>
            点名
          </el-button>

          <!-- 新增/删除学生都会连带处理登录账号，只给管理员 -->
          <el-button
            v-if="userStore.isAdmin"
            type="primary"
            style="margin-left: 8px;"
            @click="handleCreate"
          >
            <el-icon><Plus /></el-icon>
            添加学生
          </el-button>

          <!-- 生日筛选生效时显示的标签 -->
          <el-tag
            v-if="birthdayFilter"
            type="warning"
            closable
            @close="clearBirthday"
            style="margin-left: 8px;"
          >
            未来 {{ birthdayDays }} 天生日 · {{ total }} 人
          </el-tag>
        </div>
      </div>

      <el-table
        :data="tableData"
        v-loading="loading"
        stripe
        border
        style="width: 100%; margin-top: 16px;"
        @row-click="handleView"
        :row-style="{ cursor: 'pointer' }"
      >
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
                @error="handleImgError($event)"
              />
              <div v-else class="thumb-placeholder">
                <el-icon style="font-size: 22px;"><Avatar /></el-icon>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="姓名" width="90" align="center" />
        <el-table-column prop="student_no" label="学号" width="130" align="center" />
        <el-table-column prop="gender" label="性别" width="60" align="center">
          <template #default="{ row }">
            <el-tag :type="row.gender === '男' ? 'primary' : 'danger'" size="small">
              {{ row.gender }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ethnicity" label="民族" width="90" align="center" />
        <el-table-column prop="political_status" label="政治面貌" width="100" align="center" />
        <!-- 生源地不再平铺展示，让位给备注：备注是班委内部记录，需要一眼看到 -->
        <el-table-column prop="remark" label="备注" min-width="180" align="center" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.remark">{{ row.remark }}</span>
            <span v-else style="color: #c0c4cc;">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="dormitory" label="宿舍" width="90" align="center" />
        <el-table-column prop="gaokao_score" label="高考分数" width="90" align="center" sortable />
        <el-table-column prop="class_position" label="班委" width="120" align="center" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="row.class_position && row.class_position !== '无'" type="warning" size="small">
              {{ row.class_position }}
            </el-tag>
            <span v-else style="color: #c0c4cc;">-</span>
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
            <p style="margin: 4px 0; color: #606266;">
              学号：{{ currentStudent.student_no }}
              <el-button link type="primary" @click="copyText(currentStudent.student_no)">
                <el-icon><CopyDocument /></el-icon>
              </el-button>
            </p>
            <p style="margin: 4px 0; color: #606266;">
              {{ currentStudent.class_name }}班 · {{ currentStudent.major }}专业
            </p>
            <p style="margin: 4px 0; color: #606266;">
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
          <el-descriptions-item label="备注" :span="detailColumns">{{ currentStudent.remark || '无' }}</el-descriptions-item>
        </el-descriptions>

        <!-- 照片展示区 -->
        <div class="photos-section" v-if="currentStudent.gaokao_photo || currentStudent.on_site_photo">
          <h4 style="margin: 20px 0 12px 0; color: #303133; font-size: 15px;">
            <el-icon><Picture /></el-icon> 照片资料
          </h4>
          <div class="photos-row">
            <div class="photo-item" v-if="currentStudent.gaokao_photo" @click="openStudentPhotos(currentStudent, 'gaokao')">
              <img :src="getPhotoUrl(currentStudent, 'gaokao')" class="photo-item-img" @error="handleImgError($event)" />
              <span class="photo-label">高考照片</span>
            </div>
            <div class="photo-item" v-if="currentStudent.on_site_photo" @click="openStudentPhotos(currentStudent, 'on_site')">
              <img :src="getPhotoUrl(currentStudent, 'on_site')" class="photo-item-img" @error="handleImgError($event)" />
              <span class="photo-label">实地采集</span>
            </div>
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
              <el-col :xs="24" :sm="12">
                <el-form-item label="在校状态">
                  <el-input v-model="editForm.school_status" />
                </el-form-item>
              </el-col>

              <el-col :span="24">
                <el-form-item label="照片">
                  <div v-if="!editForm.id" style="color: #909399; font-size: 13px;">
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
                          选择图片
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
                  <!-- 隐藏的原生文件选择框：选完即传，不需要额外的「上传」按钮 -->
                  <input
                    ref="photoInput"
                    type="file"
                    accept="image/*"
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

          <el-tab-pane label="学习信息" name="study">
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
                <el-form-item label="是否贫困生">
                  <el-select v-model="editForm.is_poor" style="width: 100%">
                    <el-option label="是" value="是" />
                    <el-option label="否" value="否" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
          </el-tab-pane>

          <el-tab-pane label="宿舍职务" name="dorm">
            <el-row :gutter="20">
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
              <el-col :span="24">
                <el-form-item label="备注">
                  <el-input v-model="editForm.remark" type="textarea" :rows="3" />
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
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form :model="remarkForm" label-width="70px">
        <el-form-item label="备注">
          <el-input
            v-model="remarkForm.remark"
            type="textarea"
            :rows="4"
            maxlength="200"
            show-word-limit
            placeholder="班委内部记录，普通学生看不到"
          />
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

    <!-- 点名弹窗 -->
    <RollCallDialog ref="rollCallRef" />

    <!-- 整页水印：记录「谁在什么时候看的」，防止名单被截图外传 -->
    <Watermark :text="watermarkText" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getStudentList,
  getStudent,
  getFilterOptions,
  createStudent,
  updateStudent,
  deleteStudent,
  uploadStudentPhoto,
  deleteStudentPhoto
} from '@/api/student'
import { useUserStore } from '@/store/user'
import Watermark from '@/components/Watermark.vue'
import RollCallDialog from '@/components/RollCallDialog.vue'
import { useWatermark } from '@/composables/useWatermark'
import { useIsMobile } from '@/composables/useIsMobile'

const userStore = useUserStore()

// 点名弹窗（独立组件，靠 ref 调它的 open()）
const rollCallRef = ref(null)

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

// 弹窗里的两张照片。type 与后端 ?type= 的取值一致，field 是 students 表里对应的列
const PHOTO_TYPES = [
  { type: 'gaokao', field: 'gaokao_photo', label: '高考照片' },
  { type: 'on_site', field: 'on_site_photo', label: '实地采集' }
]
const photoInput = ref(null)
const photoUploading = ref('') // 正在上传的那张照片的 type，用来显示按钮 loading
let photoPicking = '' // 这次点「选择图片」是想换哪一张

// 备注单独一个弹窗：班委只能改备注，没必要给他们开全字段的表单
const remarkVisible = ref(false)
const remarkForm = reactive({ id: null, name: '', remark: '' })

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
 * @param {string} type gaokao=高考照片，on_site=实地采集
 */
function getPhotoUrl(student, type) {
  if (!student?.id) return ''
  const fileName = type === 'on_site' ? student.on_site_photo : student.gaokao_photo
  return `/api/students/${student.id}/photo?type=${type}&v=${encodeURIComponent(fileName || '')}`
}

/** 组装某学生可用的照片列表 [{ type, url }] */
function studentPhotos(student) {
  const photos = []
  if (student?.gaokao_photo) photos.push({ type: 'gaokao', url: getPhotoUrl(student, 'gaokao') })
  if (student?.on_site_photo) photos.push({ type: 'on_site', url: getPhotoUrl(student, 'on_site') })
  return photos
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

function copyText(text) {
  if (!text) return
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    // 降级方案
    const textarea = document.createElement('textarea')
    textarea.value = text
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    ElMessage.success('已复制到剪贴板')
  })
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
  try {
    currentStudent.value = await getStudent(row.id)
    detailVisible.value = true
  } catch (e) {
    ElMessage.error('获取详情失败')
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
    editVisible.value = true
    activeTab.value = 'basic'
  } else {
    remarkForm.id = row.id
    remarkForm.name = row.name
    remarkForm.remark = row.remark || ''
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
      await updateStudent(editForm.id, editForm)
      ElMessage.success('保存成功')
    } else {
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

// ---------- 照片 ----------

/** 点「选择图片」：记下要换的是哪一张，再转交给隐藏的 input */
function pickPhoto(type) {
  photoPicking = type
  photoInput.value?.click()
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
  try {
    const res = await uploadStudentPhoto(editForm.id, type, file)
    const field = type === 'on_site' ? 'on_site_photo' : 'gaokao_photo'
    editForm[field] = res.photo // 地址里的 v 参数跟着变，立刻显示新图
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
    const field = type === 'on_site' ? 'on_site_photo' : 'gaokao_photo'
    editForm[field] = null
    ElMessage.success('照片已删除')
    fetchData()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// 班委改备注：只提交 remark 一个字段（后端也只放行这一个字段）
async function handleSaveRemark() {
  saving.value = true
  try {
    await updateStudent(remarkForm.id, { remark: remarkForm.remark })
    ElMessage.success('备注已保存')
    remarkVisible.value = false
    fetchData()
  } catch (e) {
    ElMessage.error('保存失败')
    console.error(e)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  fetchData()
  fetchFilterOptions()
})
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

.table-tools {
  display: flex;
  align-items: center;
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
  background: #f5f7fa;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
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
  background: #f5f7fa;
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
  color: #c0c4cc;
}

.edit-photo-label {
  font-size: 13px;
  color: #606266;
  margin: 6px 0 4px;
}

.photo-item-img {
  /* 缩小显示，contain 保证原比例完整展示、不裁切 */
  width: 100%;
  height: 150px;
  object-fit: contain;
  display: block;
  background: #f5f7fa;
  padding: 8px;
  box-sizing: border-box;
}

.photos-tip {
  text-align: center;
  font-size: 12px;
  color: #c0c4cc;
  margin: 8px 0 0 0;
}

.detail-header {
  display: flex;
  gap: 24px;
  padding: 16px;
  background: linear-gradient(135deg, #f0f7ff 0%, #e8f4ff 100%);
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
  background: #f5f7fa;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
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
  border: 1px solid #ebeef5;
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

/* 工具栏有 4 个元素（人数/排序/近期生日/点名），手机上不换行会被顶出横向滚动条 */
@media (max-width: 768px) {
  .table-header {
    flex-wrap: wrap;
    row-gap: 10px;
  }

  .table-tools {
    flex-wrap: wrap;
    justify-content: flex-end;
    row-gap: 8px;
  }
}
</style>
