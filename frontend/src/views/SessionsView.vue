<script setup>
import { onMounted, ref } from 'vue'
import { getSession, listSessions } from '../api'

const sessions = ref([])
const currentId = ref('')
const history = ref([])
const trace = ref([])

const STEP_META = {
  classify: { label: '意图分类', type: 'primary' },
  quality_check: { label: '回复质检', type: 'warning' },
  handoff: { label: '转人工', type: 'danger' },
  suspended: { label: '挂起等待人工', type: 'info' },
  final_response: { label: '生成回复', type: 'success' },
}

function stepText(s) {
  if (s.step === 'classify') return `分类为 ${s.query_type}`
  if (s.step === 'quality_check') return `质检 ${s.score} 分（阈值 ${s.threshold}）：${s.reason}`
  if (s.step === 'handoff') return `已创建工单 ${(s.ticket_id || '').slice(0, 8)}…`
  if (s.step === 'suspended') return '会话挂起中'
  if (s.step === 'final_response') return `由【${s.agent}】输出`
  return JSON.stringify(s)
}

async function refresh() {
  sessions.value = await listSessions()
}

async function select(id) {
  currentId.value = id
  const s = await getSession(id)
  history.value = s.conversation_history || []
  trace.value = s.decision_trace || []
}

onMounted(refresh)
</script>

<template>
  <el-container class="page">
    <el-aside width="280px" class="aside">
      <div v-for="s in sessions" :key="s.session_id" class="session-item"
           :class="{ active: s.session_id === currentId }" @click="select(s.session_id)">
        <div class="q">{{ s.last_user_question || '（无消息）' }}</div>
        <div class="meta">{{ s.message_count }} 条消息</div>
      </div>
    </el-aside>
    <el-main class="detail">
      <el-empty v-if="!currentId" description="选择左侧会话查看回放" />
      <template v-else>
        <div class="msg-box">
          <div v-for="(m, i) in history" :key="i" class="msg" :class="m.is_user ? 'user' : 'ai'">
            <div class="bubble">{{ m.content }}</div>
          </div>
        </div>
        <div class="trace">
          <h4>决策轨迹</h4>
          <el-timeline>
            <el-timeline-item v-for="(s, i) in trace" :key="i"
                              :timestamp="s.timestamp" :type="STEP_META[s.step]?.type || 'info'">
              <b>{{ STEP_META[s.step]?.label || s.step }}</b>：{{ stepText(s) }}
            </el-timeline-item>
          </el-timeline>
        </div>
      </template>
    </el-main>
  </el-container>
</template>

<style scoped>
.page { height: calc(100vh - 60px); }
.aside { border-right: 1px solid #eee; padding: 10px; overflow-y: auto; }
.session-item { padding: 8px; border-radius: 6px; cursor: pointer; margin-top: 8px; }
.session-item:hover { background: #f5f7fa; }
.session-item.active { background: #ecf5ff; }
.session-item .q { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-item .meta { font-size: 12px; color: #999; }
.detail { display: flex; flex-direction: column; overflow-y: auto; }
.msg-box { flex: 1; }
.msg { display: flex; margin: 8px 0; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 70%; padding: 10px 12px; border-radius: 8px; white-space: pre-wrap; font-size: 14px; line-height: 1.5; }
.msg.user .bubble { background: #409eff; color: #fff; }
.msg.ai .bubble { background: #f4f4f5; }
.trace { border-top: 1px solid #eee; padding-top: 12px; }
</style>
