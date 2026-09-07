<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { customerChat, customerSession } from '../api'
import { useCustomerStore } from '../stores/customer'

const store = useCustomerStore()
const history = ref([])
const input = ref('')
const sending = ref(false)
const boxRef = ref(null)
let pollTimer = null
let lastCount = 0

const QUICK = ['退款进度怎么查询？', '支持哪些支付方式？', '发票怎么开具？']

const authorLabel = m => {
  if (m.is_user) return '我'
  return m.author === 'human' ? '人工客服' : '智能助手'
}

function scrollBottom() {
  nextTick(() => { if (boxRef.value) boxRef.value.scrollTop = boxRef.value.scrollHeight })
}

async function loadHistory() {
  if (!store.currentThreadId) return
  try {
    const data = await customerSession(store.currentThreadId)
    const msgs = data.conversation_history || []
    if (msgs.length !== lastCount) {
      lastCount = msgs.length
      history.value = msgs
      scrollBottom()
    }
    store.setState(data.service_state)
  } catch { /* 轮询失败静默，下一轮再试 */ }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(loadHistory, 4000) // 等待人工期间轮询人工回复
}

function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  history.value.push({ is_user: true, content: text })
  input.value = ''
  scrollBottom()
  try {
    const data = await customerChat(text, store.currentThreadId || '')
    store.currentThreadId = data.thread_id
    store.setState(data.service_state)
    history.value.push({ is_user: false, content: data.response, author: data.service_state === 'human' ? 'human' : 'ai' })
    lastCount = history.value.length
    startPolling() // 常驻轮询：转人工可能发生在任何一轮之后，人工回复必须自动到达
  } catch (e) {
    // 发送失败：保留输入并允许重试
    input.value = text
    history.value.push({ is_user: false, content: '发送失败，请重试。', system: true })
    ElMessage.error(e.response?.data?.error || '发送失败')
  } finally {
    sending.value = false
    scrollBottom()
  }
}

function onEnter(e) {
  if (e.shiftKey) return
  e.preventDefault()
  send()
}

onMounted(async () => {
  // 等待人工的会话恢复：从 localStorage 取回当前线程；线程存在即常驻轮询（人工回复自动到达）
  store.currentThreadId = localStorage.getItem('aegis_thread') || ''
  if (store.currentThreadId) {
    await loadHistory()
  }
  startPolling()
})
import { watch } from 'vue'
watch(() => store.currentThreadId, id => localStorage.setItem('aegis_thread', id || ''))
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="chat-card">
    <div ref="boxRef" class="msg-box">
      <div class="welcome">
        <p>您好，我是智能服务助手。订单、配送与售后问题都可以直接提问。</p>
        <div class="quick">
          <button v-for="q in QUICK" :key="q" class="quick-btn" @click="input = q">{{ q }}</button>
        </div>
      </div>
      <div v-for="(m, i) in history" :key="i" class="msg" :class="m.is_user ? 'user' : (m.system ? 'system' : 'ai')">
        <div v-if="m.system" class="sys-line">{{ m.content }}</div>
        <div v-else class="bubble-wrap">
          <span class="author">{{ authorLabel(m) }}</span>
          <div class="bubble" :class="{ human: m.author === 'human' }">{{ m.content }}</div>
        </div>
      </div>
      <div v-if="store.serviceState === 'waiting'" class="waiting-banner">
        您的问题已转人工处理，客服回复后将自动显示在这里，无需刷新。
      </div>
    </div>
    <form class="composer" @submit.prevent="send">
      <textarea v-model="input" rows="2" maxlength="1000"
                placeholder="请输入问题（请勿填写真实个人信息）"
                @keydown.enter="onEnter" />
      <div class="composer-footer">
        <small>Enter 发送 · Shift+Enter 换行</small>
        <el-button type="primary" native-type="submit" :loading="sending">发送</el-button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.chat-card { width: 100%; max-width: 640px; background: #fff; border: 1px solid #ebedf0; border-top: none; border-radius: 0 0 12px 12px; display: flex; flex-direction: column; min-height: 480px; flex: 1; margin-bottom: 24px; }
.msg-box { flex: 1; overflow-y: auto; padding: 14px; }
.welcome p { color: #4e5969; font-size: 14px; margin: 0 0 10px; }
.quick { display: flex; gap: 8px; flex-wrap: wrap; }
.quick-btn { border: 1px solid #d5dbe1; background: #fff; border-radius: 999px; padding: 5px 12px; font-size: 12px; color: #2f5460; cursor: pointer; }
.quick-btn:hover { background: #f0f4f7; }
.msg { display: flex; margin: 10px 0; }
.msg.user { justify-content: flex-end; }
.msg.system { justify-content: center; }
.sys-line { font-size: 12px; color: #b06a1e; background: #fdf2e9; padding: 4px 10px; border-radius: 6px; }
.bubble-wrap { max-width: 78%; display: flex; flex-direction: column; gap: 3px; }
.author { font-size: 11px; color: #86909c; }
.msg.user .bubble-wrap { align-items: flex-end; }
.bubble { padding: 9px 12px; border-radius: 10px; background: #f2f3f5; font-size: 14px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
.bubble.human { background: #e8f5ee; }
.msg.user .bubble { background: #2f5460; color: #fff; }
.waiting-banner { font-size: 13px; color: #b06a1e; background: #fdf2e9; border-radius: 8px; padding: 9px 12px; margin-top: 6px; }
.composer { border-top: 1px solid #ebedf0; padding: 10px 14px; }
.composer textarea { width: 100%; box-sizing: border-box; border: 1px solid #d5dbe1; border-radius: 8px; padding: 8px 10px; font-size: 14px; resize: none; font-family: inherit; }
.composer textarea:focus { outline: 2px solid #2f546033; border-color: #2f5460; }
.composer-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }
.composer-footer small { color: #86909c; }
</style>
