<template>
  <!-- 单科统计表（班委及以上）。**只有单科，没有总分** —— 模块里不存在这个概念 -->
  <el-dialog
    v-model="visible"
    :title="`${stats?.name || '成绩统计'} · 统计`"
    width="92%"
    top="6vh"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <div v-loading="loading" class="gs-body">
      <div class="gs-meta">
        <span>{{ formatDate(stats?.tested_at) }}</span>
        <span class="gs-count">名单 {{ stats?.roster_count || 0 }} 人</span>
      </div>

      <el-table :data="stats?.subjects || []" size="small" border max-height="60vh">
        <el-table-column prop="name" label="科目" min-width="110" fixed />
        <el-table-column label="形态" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.mode === 'pass_fail'" size="small" type="success" effect="plain">
              通过制
            </el-tag>
            <span v-else>计分</span>
          </template>
        </el-table-column>
        <el-table-column label="满分" width="80">
          <template #default="{ row }">
            {{ row.mode === 'pass_fail' ? '—' : row.full_score }}
          </template>
        </el-table-column>
        <el-table-column label="有成绩" width="90">
          <template #default="{ row }">
            <div>{{ row.scored_count }}</div>
            <!-- 缺考 / 未录的人数不参与平均和及格率，但得让人看见它们去哪了 -->
            <div v-if="row.marked_count || row.blank_count" class="gs-sub">
              标记 {{ row.marked_count }} · 未录 {{ row.blank_count }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="平均" width="80">
          <template #default="{ row }">{{ statScore(row, 'avg') }}</template>
        </el-table-column>
        <el-table-column label="最高" width="80">
          <template #default="{ row }">{{ statScore(row, 'max') }}</template>
        </el-table-column>
        <el-table-column label="最低" width="80">
          <template #default="{ row }">{{ statScore(row, 'min') }}</template>
        </el-table-column>
        <el-table-column label="及格率 / 通过率" width="120">
          <template #default="{ row }">
            <template v-if="row.pass_rate === null || row.pass_rate === undefined">—</template>
            <template v-else>
              {{ fmtNum(row.pass_rate) }}%
              <span class="gs-sub">
                {{ row.mode === 'pass_fail'
                  ? `${row.passed_count} 通过 / ${row.failed_count} 不通过`
                  : `${row.pass_count} 人及格` }}
              </span>
            </template>
          </template>
        </el-table-column>
        <el-table-column label="分数段" min-width="240">
          <template #default="{ row }">
            <div v-if="row.mode === 'pass_fail'" class="gs-sub">通过制不分分数段</div>
            <div v-else class="gs-ranges">
              <span v-for="b in row.ranges" :key="b.label" class="gs-range">
                {{ b.label }} <b>{{ b.count }}</b>
              </span>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="gs-hint">
        分数段按<strong>满分的百分比</strong>划，及格线是满分的 60%。
        缺考 / 免修 / 缓考 / 违纪和没录的空格不计入平均、及格率和分数段。
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getGradeStats } from '@/api/grade'
import { formatDate } from '@/utils/format'
import { errText } from '@/utils/request'

const visible = ref(false)
const loading = ref(false)
const stats = ref(null)

async function open(row) {
  // 先把列表里已有的名字填上，统计回来前标题就不空着
  stats.value = { id: row.id, name: row.name, tested_at: row.tested_at, subjects: [] }
  visible.value = true
  loading.value = true
  try {
    stats.value = await getGradeStats(row.id)
  } catch (e) {
    ElMessage.error(errText(e, '读取统计失败'))
  } finally {
    loading.value = false
  }
}

function reset() {
  stats.value = null
}

/** 数字去掉多余的小数位：12.0 → 12，12.34 → 12.3 */
function fmtNum(v) {
  return v === null || v === undefined ? '—' : String(Math.round(v * 10) / 10)
}

/** 通过制科目没有平均 / 最高 / 最低，一律显示横杠而不是 0 */
function statScore(row, key) {
  return row.mode === 'pass_fail' ? '—' : fmtNum(row[key])
}

defineExpose({ open })
</script>

<style scoped>
.gs-body {
  min-height: 200px;
}

.gs-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 10px;
}

.gs-count {
  margin-left: auto;
}

.gs-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.gs-ranges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-size: 12px;
}

.gs-range {
  color: var(--el-text-color-regular);
}

.gs-hint {
  margin-top: 12px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
</style>
