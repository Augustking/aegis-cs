<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { clearSession, deleteSession, getSession, listSessions, sendMessage } from '../api'

const sessions = ref([])
const currentId = ref('')
const history = ref([])
const input = ref('')
const sending = ref(false)
const boxRef = ref(null)

async function refreshSessions() {
  sessions.value = await listSessions()
}

function scrollBottom() {
  nextTick(() => {
    if (boxRef.value) boxRef.value.scrollTop = boxRef.value.scrollHeight
  })
}

async function selectSession(id) {
  currentId.value = id
  const s = await getSession(id)
  history.value = s.conversation_history || []
  scrollBottom()
}

function newSession() {
  currentId.value = ''
  history.value = []
}

async function removeSession(id) {
  await deleteSession(id)
  if (currentId.value === id) newSession()
  refreshSessions()
}

async function clearCurrent() {
  if (!currentId.value) return
  const data = await clearSession(currentId.value)
  await selectSession(data.new_thread_id)
  refreshSessions()
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  history.value.push({ is_user: true, content: text })
  input.value = ''
  scrollBottom()
  try {
    const data = await sendMessage(text, currentId.value || 'default')
    currentId.value = data.thread_id
    history.value.push({ is_user: false, content: data.response })
    refreshSessions()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '发送失败')
  } finally {
    sending.value = false
    scrollBottom()
  }
}

onMounted(refreshSessions)
</script>

<template>
  <el-container class="page">
    <el-aside width="280px" class="aside">
      <el-button type="primary" plain style="width: 100%" @click="newSession">新建会话</el-button>
      <div v-for="s in sessions" :key="s.session_id" class="session-item"
           :class="{ active: s.session_id === currentId }" @click="selectSession(s.session_id)">
        <div class="q">{{ s.last_user_question || '（无消息）' }}</div>
        <div class="meta">
          <span>{{ new Date(s.created_at * 1000).toLocaleString() }}</span>
          <el-button link type="danger" size="small" @click.stop="removeSession(s.session_id)">删除</el-button>
        </div>
      </div>
    </el-aside>
    <el-main class="chat-main">
      <div class="toolbar">
        <el-button size="small" :disabled="!currentId" @click="clearCurrent">清空当前会话</el-button>
      </div>
      <div ref="boxRef" class="msg-box">
        <el-empty v-if="!history.length" description="开始你的咨询吧" />
        <div v-for="(m, i) in history" :key="i" class="msg" :class="m.is_user ? 'user' : 'ai'">
          <div class="bubble">{{ m.content }}</div>
        </div>
      </div>
      <div class="input-row">
        <el-input v-model="input" type="textarea" :rows="2" placeholder="输入消息，Enter 发送"
                  @keydown.enter.exact.prevent="send" />
        <el-button type="primary" :loading="sending" @click="send">发送</el-button>
      </div>
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
.session-item .meta { font-size: 12px; color: #999; display: flex; justify-content: space-between; }
.chat-main { display: flex; flex-direction: column; }
.toolbar { padding: 6px 0; }
.msg-box { flex: 1; overflow-y: auto; padding: 10px; }
.msg { display: flex; margin: 8px 0; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 70%; padding: 10px 12px; border-radius: 8px; white-space: pre-wrap; font-size: 14px; line-height: 1.5; }
.msg.user .bubble { background: #409eff; color: #fff; }
.msg.ai .bubble { background: #f4f4f5; }
.input-row { display: flex; gap: 10px; padding-top: 10px; border-top: 1px solid #eee; }
</style>
