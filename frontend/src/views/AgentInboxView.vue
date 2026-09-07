<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSession, getTicket, listTickets, resolveTicket } from '../api'
import { useTicketStore } from '../stores/tickets'

const ticketStore = useTicketStore()

const queue = reactive({ items: [], total: 0, limit: 50, offset: 0, status: '', q: '' })
const selected = ref(null)          // 当前工单
const conversation = ref([])        // 当前线程对话
const editor = ref('')
const submitting = ref(false)
const unread = reactive(new Set())
let pollTimer = null

const isDirty = computed(() => !!(selected.value?.status === 'open' && editor.value.trim()))

function fmtDims(t) {
  if (!t?.quality_dims) return null
  try { return JSON.parse(t.quality_dims) } catch { return null }
}

async function refreshQueue(keepSelection = true) {
  const data = await listTickets(queue.status || undefined, queue.q, queue.limit, queue.offset)
  queue.items = data.items
  queue.total = data.total
  if (!keepSelection && data.items.length) await openTicket(data.items[0])
}

async function openTicket(t, force = false) {
  if (force !== true && isDirty.value && t.id !== selected.value?.id) {
    try {
      await ElMessageBox.confirm('离开将丢弃当前输入，草稿采纳并不代表已发送。', '有尚未提交的内容', {
        confirmButtonText: '放弃并离开',
        cancelButtonText: '取消，继续编辑',
        type: 'warning',
      })
    } catch { return } // 取消 → 留在原处
  }
  selected.value = t
  editor.value = ''
  unread.delete(t.id)
  await loadConversation(t.thread_id)
}

async function loadConversation(threadId) {
  try {
    const s = await getSession(threadId)
    conversation.value = s.conversation_history || []
  } catch {
    conversation.value = []
    ElMessage.warning('会话加载失败，请稍后重试')
  }
}

function adopt() {
  if (!selected.value) return
  editor.value = selected.value.draft_reply || ''
  ElMessage.success('草稿已填入编辑器，尚未发送')
}

async function submitReply() {
  const reply = editor.value.trim()
  if (!reply || !selected.value || submitting.value) return
  submitting.value = true
  try {
    await ElMessageBox.confirm(
      `将向 ${selected.value.user_query.slice(0, 20)}…（${selected.value.id.slice(0, 8)}…）记录以下回复并关闭工单：\n${reply}`,
      '确认提交人工回复', { confirmButtonText: '确认提交', cancelButtonText: '取消，继续编辑', type: 'warning' })
    const data = await resolveTicket(selected.value.id, reply)
    if (data.degraded) ElMessage.warning(data.message)
    else ElMessage.success(data.message)
    const detail = await getTicket(selected.value.id).catch(() => null)
    if (detail) selected.value = detail
    editor.value = ''
    await refreshQueue()
  } catch (e) {
    if (e !== 'cancel' && e?.message !== 'cancel') {
      ElMessage.error(e.response?.data?.error || '提交失败，请稍后重试')
    }
  } finally {
    submitting.value = false
  }
}

async function switchStatus() {
  queue.offset = 0
  await refreshQueue(false)
}

function onPage(delta) {
  queue.offset = Math.max(0, queue.offset + delta * queue.limit)
  refreshQueue()
}

function startPollDetail() {
  pollTimer = setInterval(async () => {
    if (selected.value?.status === 'open') return
    // 已处理工单：轮询会话更新（人工写回后客户/坐席同步可见）
    if (selected.value) await loadConversation(selected.value.thread_id)
  }, 5000)
}

function onSseUpdate() { refreshQueue(true) }

onMounted(async () => {
  await refreshQueue(false)
  ticketStore.startSSE(onSseUpdate)
  startPollDetail()
  window.addEventListener('beforeunload', beforeUnload)
})
function beforeUnload(e) { if (isDirty.value) { e.preventDefault(); e.returnValue = '' } }
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="inbox">
    <!-- 左：队列 -->
    <aside class="pane queue">
      <div class="q-head">
        <input v-model="queue.q" class="search" placeholder="搜索问题 / 工单编号" @input="refreshQueue" />
        <select v-model="queue.status" class="filter" @change="switchStatus">
          <option value="">全部工单</option>
          <option value="open">待处理</option>
          <option value="resolved">已处理</option>
        </select>
      </div>
      <div class="q-list">
        <button v-for="t in queue.items" :key="t.id" class="ticket"
                :class="{ active: selected?.id === t.id }" @click="openTicket(t)">
          <div class="row">
            <span class="tid">{{ t.id.slice(0, 8) }}…</span>
            <span class="badge" :class="t.status === 'open' ? 'warn' : 'ok'">
              {{ t.status === 'open' ? '待处理' : '已处理' }}
            </span>
            <span v-if="unread.has(t.id)" class="dot" title="新工单" />
          </div>
          <div class="q-text">{{ t.user_query }}</div>
          <div class="meta">质检 {{ t.quality_score }} 分 · {{ t.created_at }}</div>
        </button>
        <p v-if="!queue.items.length" class="empty">没有匹配的工单</p>
      </div>
      <div class="q-foot">
        <small>{{ queue.offset + 1 }}-{{ Math.min(queue.offset + queue.limit, queue.total) }} / {{ queue.total }}</small>
        <button :disabled="queue.offset === 0" @click="onPage(-1)">上一页</button>
        <button :disabled="queue.offset + queue.limit >= queue.total" @click="onPage(1)">下一页</button>
      </div>
    </aside>

    <!-- 中：对话 + 回复编辑 -->
    <section v-if="selected" class="pane conv">
      <header class="c-head">
        <strong>工单 {{ selected.id.slice(0, 8) }}…</strong>
        <span class="badge" :class="selected.status === 'open' ? 'warn' : 'ok'">
          {{ selected.status === 'open' ? '待处理' : '已处理' }}
        </span>
      </header>
      <div class="conversation">
        <div v-for="(m, i) in conversation" :key="i" class="msg" :class="m.is_user ? 'user' : 'ai'">
          <span class="author">{{ m.is_user ? '客户' : (m.author === 'human' ? '人工坐席' : 'AI') }}</span>
          <div class="bubble">{{ m.content }}</div>
        </div>
        <p v-if="!conversation.length" class="empty">暂无对话记录</p>
      </div>
      <template v-if="selected.status === 'open'">
        <div class="draft-box">
          <div class="row"><strong>AI 建议草稿</strong><span class="badge">内部可见 · 未发送</span></div>
          <p>{{ selected.draft_reply }}</p>
          <button class="ghost" @click="adopt">采纳到编辑器</button>
        </div>
        <div class="editor">
          <textarea v-model="editor" rows="5" maxlength="2000"
                    placeholder="核实信息后编辑回复，确认后才会提交" />
          <div class="row">
            <small>提交后关闭该虚构工单并写回会话</small>
            <button class="primary" :disabled="!editor.trim() || submitting" @click="submitReply">
              {{ submitting ? '提交中…' : '预览并确认提交' }}
            </button>
          </div>
        </div>
      </template>
      <div v-else class="resolved-note">
        人工回复：{{ selected.human_reply }}
      </div>
    </section>

    <!-- 右：工单与质检 -->
    <aside v-if="selected" class="pane insights">
      <h3>质检信息</h3>
      <div class="score">{{ selected.quality_score }}<small> / 10</small></div>
      <p class="reason">{{ selected.quality_reason }}</p>
      <div v-if="fmtDims(selected)" class="dims">
        <span>相关性 {{ fmtDims(selected).relevance }}/4</span>
        <span>解答度 {{ fmtDims(selected).completeness }}/3</span>
        <span>可信度 {{ fmtDims(selected).faithfulness }}/3</span>
      </div>
      <h3>工单信息</h3>
      <p class="kv"><span>创建时间</span>{{ selected.created_at }}</p>
      <p class="kv"><span>客户问题</span>{{ selected.user_query }}</p>
      <p class="notice">质检评分仅辅助判断；回复前请核实事实。</p>
    </aside>
  </div>
</template>

<style scoped>
.inbox { display: grid; grid-template-columns: 300px 1fr 280px; gap: 12px; padding: 12px; height: calc(100vh - 52px); box-sizing: border-box; }
.pane { background: #fff; border: 1px solid #ebedf0; border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; min-height: 0; }
/* 队列 */
.q-head { display: flex; gap: 6px; padding: 10px; border-bottom: 1px solid #ebedf0; }
.search { flex: 1; border: 1px solid #d5dbe1; border-radius: 6px; padding: 6px 8px; font-size: 13px; }
.filter { border: 1px solid #d5dbe1; border-radius: 6px; padding: 6px; font-size: 13px; }
.q-list { flex: 1; overflow-y: auto; padding: 8px; }
.ticket { display: block; width: 100%; text-align: left; border: 1px solid #ebedf0; border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; background: #fff; cursor: pointer; }
.ticket:hover { background: #f7f9fa; }
.ticket.active { border-color: #2f5460; background: #f0f5f7; }
.row { display: flex; align-items: center; gap: 6px; }
.tid { font-size: 12px; color: #86909c; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #eef2f5; color: #4e5969; }
.badge.warn { background: #fdf2e9; color: #b06a1e; }
.badge.ok { background: #e8f5ee; color: #2e7d4f; }
.dot { width: 7px; height: 7px; background: #e0564f; border-radius: 50%; }
.q-text { font-size: 13px; margin: 5px 0 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { font-size: 11px; color: #86909c; }
.q-foot { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-top: 1px solid #ebedf0; }
.q-foot small { flex: 1; color: #86909c; }
.q-foot button { border: 1px solid #d5dbe1; background: #fff; border-radius: 6px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
.q-foot button:disabled { opacity: .4; cursor: default; }
.empty { text-align: center; color: #86909c; font-size: 13px; padding: 20px 0; }
/* 对话 */
.conv { padding: 0; }
.c-head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid #ebedf0; }
.conversation { flex: 1; overflow-y: auto; padding: 12px 14px; min-height: 120px; }
.msg { display: flex; flex-direction: column; gap: 2px; margin: 8px 0; }
.msg.user { align-items: flex-end; }
.author { font-size: 11px; color: #86909c; }
.bubble { max-width: 75%; padding: 8px 12px; border-radius: 10px; background: #f2f3f5; font-size: 13px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
.msg.user .bubble { background: #2f5460; color: #fff; }
/* 草稿与编辑 */
.draft-box { margin: 0 14px 10px; border: 1px dashed #d5dbe1; border-radius: 8px; padding: 10px; }
.draft-box p { font-size: 13px; color: #4e5969; margin: 6px 0; }
.ghost { border: 1px solid #2f5460; color: #2f5460; background: #fff; border-radius: 6px; padding: 4px 12px; font-size: 12px; cursor: pointer; }
.editor { padding: 0 14px 12px; }
.editor textarea { width: 100%; box-sizing: border-box; border: 1px solid #d5dbe1; border-radius: 8px; padding: 8px 10px; font-size: 13px; resize: vertical; font-family: inherit; }
.editor .row { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }
.editor small { color: #86909c; }
.primary { background: #2f5460; color: #fff; border: none; border-radius: 8px; padding: 7px 16px; font-size: 13px; cursor: pointer; }
.primary:disabled { opacity: .5; cursor: default; }
.resolved-note { padding: 14px; font-size: 13px; color: #2e7d4f; background: #e8f5ee; border-radius: 8px; margin: 14px; }
/* 右栏 */
.insights { padding: 14px; overflow-y: auto; }
.insights h3 { font-size: 13px; margin: 10px 0 6px; }
.score { font-size: 30px; font-weight: 600; color: #2f5460; }
.reason { font-size: 12px; color: #4e5969; background: #f7f9fa; border-radius: 6px; padding: 8px; }
.dims { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #4e5969; margin: 8px 0; }
.kv { font-size: 12px; color: #1f2329; display: flex; flex-direction: column; }
.kv span { color: #86909c; }
.notice { font-size: 11px; color: #86909c; border-top: 1px solid #ebedf0; padding-top: 8px; }
/* 窄屏：右栏折叠，队列变窄 */
@media (max-width: 1024px) {
  .inbox { grid-template-columns: 240px 1fr; }
  .insights { display: none; }
}
@media (max-width: 760px) {
  .inbox { grid-template-columns: 1fr; grid-auto-rows: minmax(0, auto); height: auto; }
  .q-list { max-height: 200px; }
}
</style>
