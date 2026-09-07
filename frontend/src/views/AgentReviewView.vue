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

async function refresh() { sessions.value = await listSessions() }

async function select(id) {
  currentId.value = id
  const s = await getSession(id)
  history.value = s.conversation_history || []
  trace.value = s.decision_trace || []
}

onMounted(refresh)
</script>

<template>
  <div class="review">
    <aside class="r-list">
      <div v-for="s in sessions" :key="s.session_id" class="item"
           :class="{ active: s.session_id === currentId }" @click="select(s.session_id)">
        <div class="q">{{ s.last_user_question || '（无消息）' }}</div>
        <div class="meta">{{ s.message_count }} 条消息</div>
      </div>
      <p v-if="!sessions.length" class="empty">暂无会话</p>
    </aside>
    <section class="r-detail">
      <p v-if="!currentId" class="empty">选择左侧会话查看复盘</p>
      <template v-else>
        <div class="conversation">
          <div v-for="(m, i) in history" :key="i" class="msg" :class="m.is_user ? 'user' : 'ai'">
            <span class="author">{{ m.is_user ? '客户' : (m.author === 'human' ? '人工坐席' : 'AI') }}</span>
            <div class="bubble">{{ m.content }}</div>
          </div>
        </div>
        <div class="trace">
          <h3>决策轨迹</h3>
          <p v-if="!trace.length" class="empty">该会话早于轨迹功能，暂无决策记录</p>
          <ol v-else class="tl">
            <li v-for="(s, i) in trace" :key="i" class="tl-item">
              <div class="tl-head">
                <strong>{{ STEP_META[s.step]?.label || s.step }}</strong>
                <small>{{ s.timestamp }}</small>
              </div>
              <div class="tl-body">{{ stepText(s) }}</div>
            </li>
          </ol>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.review { display: grid; grid-template-columns: 300px 1fr; gap: 12px; padding: 12px; height: calc(100vh - 52px); box-sizing: border-box; }
.r-list { background: #fff; border: 1px solid #ebedf0; border-radius: 10px; overflow-y: auto; padding: 8px; }
.item { padding: 8px 10px; border-radius: 8px; cursor: pointer; margin-bottom: 6px; }
.item:hover { background: #f7f9fa; }
.item.active { background: #f0f5f7; border: 1px solid #2f5460; }
.q { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { font-size: 11px; color: #86909c; }
.r-detail { background: #fff; border: 1px solid #ebedf0; border-radius: 10px; overflow-y: auto; padding: 14px; }
.conversation { margin-bottom: 14px; }
.msg { display: flex; flex-direction: column; gap: 2px; margin: 8px 0; }
.msg.user { align-items: flex-end; }
.author { font-size: 11px; color: #86909c; }
.bubble { max-width: 70%; padding: 8px 12px; border-radius: 10px; background: #f2f3f5; font-size: 13px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
.msg.user .bubble { background: #2f5460; color: #fff; }
.trace { border-top: 1px solid #ebedf0; padding-top: 10px; }
.tl { list-style: none; padding: 0; margin: 8px 0 0; }
.tl-item { border-left: 2px solid #d5dbe1; padding: 0 0 12px 14px; position: relative; }
.tl-item::before { content: ""; position: absolute; left: -5px; top: 4px; width: 8px; height: 8px; border-radius: 50%; background: #2f5460; }
.tl-head { display: flex; gap: 8px; align-items: baseline; }
.tl-head small { color: #86909c; font-size: 11px; }
.tl-body { font-size: 13px; color: #4e5969; margin-top: 2px; }
.empty { text-align: center; color: #86909c; font-size: 13px; padding: 24px 0; }
@media (max-width: 760px) { .review { grid-template-columns: 1fr; height: auto; } .r-list { max-height: 180px; } }
</style>
