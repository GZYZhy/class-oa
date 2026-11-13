<template>
  <el-dialog
    append-to-body
    v-model="visible"
    :title="kind === 'poll' ? '投票管理授权' : '收集管理授权'"
    width="520px"
  >
    <p class="mg-tip">勾选其他班委共同管理；管理员始终可管理，不需要勾选。</p>
    <div v-loading="loading" class="mg-list">
      <el-checkbox-group v-model="selected">
        <el-checkbox
          v-for="student in committee"
          :key="student.student_no"
          :value="student.student_no"
        >
          {{ student.name }}
          <span class="mg-no">{{ student.student_no }}</span>
        </el-checkbox>
      </el-checkbox-group>
      <el-empty v-if="!loading && !committee.length" description="没有其他班委" :image-size="60" />
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getRoster } from '@/api/vote'
import { updatePollManagers } from '@/api/vote'
import { updateCollectionManagers } from '@/api/collection'
import { errText } from '@/utils/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  kind: { type: String, default: 'poll' },
  id: { type: [Number, String], default: null },
  managerNos: { type: Array, default: () => [] }
})
const emit = defineEmits(['update:modelValue', 'saved'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})
const loading = ref(false)
const saving = ref(false)
const roster = ref([])
const selected = ref([])

const committee = computed(() =>
  roster.value.filter((student) => student.committee)
)

watch(() => props.modelValue, async (open) => {
  if (!open) return
  selected.value = [...props.managerNos]
  if (roster.value.length) return
  loading.value = true
  try {
    const data = await getRoster()
    roster.value = data.items || []
  } catch (e) {
    ElMessage.error(errText(e, '读取班委名单失败'))
  } finally {
    loading.value = false
  }
})

async function save() {
  saving.value = true
  try {
    const fn = props.kind === 'poll' ? updatePollManagers : updateCollectionManagers
    const data = await fn(props.id, selected.value)
    ElMessage.success('管理授权已更新')
    visible.value = false
    emit('saved', data)
  } catch (e) {
    ElMessage.error(errText(e, '保存失败'))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.mg-tip {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.mg-list {
  max-height: 320px;
  overflow-y: auto;
}
.mg-no {
  margin-left: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
