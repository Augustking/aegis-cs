<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listTickets, resolveTicket } from '../api'

const tab = ref('open')
const rows = ref([])
const drawer = ref(false)
const current = ref(null)
const reply = ref('')
const submitting = ref(false)

async function refresh() {
  rows.value = await listTickets(tab.value)
}

function openTicket(row) {
  current.value = row
  reply.value = row.status === 'open' ? (row.draft_reply || '') : (row.human_reply || '')
  drawer.value = true
}

async function submit() {
  if (!reply.value.trim()) {
    ElMessage.warning('回复内容不能为空')
    return
  }
  submitting.value = true
  try {
    const data = await resolveTicket(current.value.id, reply.value.trim())
    if (data.degraded) ElMessage.warning(data.message)
    else ElMessage.success(data.message)
    drawer.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '处理失败')
  } finally {
    submitting.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <el-tabs v-model="tab" @tab-change="refresh">
      <el-tab-pane label="待处理" name="open" />
      <el-tab-pane label="已处理" name="resolved" />
    </el-tabs>
    <el-table :data="rows" style="cursor: pointer" @row-click="openTicket">
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column prop="user_query" label="客户问题" min-width="220" show-overflow-tooltip />
      <el-table-column prop="quality_score" label="质检分" width="90" />
      <el-table-column prop="quality_reason" label="质检理由" min-width="160" show-overflow-tooltip />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'open' ? 'warning' : 'success'">
            {{ row.status === 'open' ? '待处理' : '已处理' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawer" title="工单详情" size="45%">
      <el-descriptions v-if="current" :column="1" border>
        <el-descriptions-item label="客户问题">{{ current.user_query }}</el-descriptions-item>
        <el-descriptions-item label="质检得分">{{ current.quality_score }}</el-descriptions-item>
        <el-descriptions-item label="质检理由">{{ current.quality_reason }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ current.created_at }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="current && current.status === 'open'" style="margin-top: 16px">
        <div style="margin-bottom: 8px">草稿回复（AI 原始回答，可修改后提交）：</div>
        <el-input v-model="reply" type="textarea" :rows="6" />
        <el-button type="primary" style="margin-top: 12px" :loading="submitting" @click="submit">
          提交人工回复
        </el-button>
      </div>
      <div v-else-if="current" style="margin-top: 16px">
        <div style="margin-bottom: 8px">人工回复：</div>
        <el-input :model-value="reply" type="textarea" :rows="6" disabled />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page { padding: 0 16px; }
</style>
