<template>
  <div class="agent-shell">
    <header class="a-header">
      <span class="brand-mark">知</span>
      <strong>知序 · 坐席工作空间</strong>
      <nav>
        <router-link to="/agent/inbox">处理台</router-link>
        <router-link to="/agent/review">会话复盘</router-link>
      </nav>
      <span class="conn" :class="ticketStore.connected ? 'ok' : ''">
        {{ ticketStore.connected ? '实时已连接' : '实时未连接' }}
      </span>
      <button class="exit" @click="exit">退出（{{ auth.username }}）</button>
    </header>
    <main class="a-main"><router-view /></main>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useTicketStore } from '../stores/tickets'

const auth = useAuthStore()
const ticketStore = useTicketStore()
const router = useRouter()

onMounted(() => ticketStore.startSSE())

async function exit() {
  ticketStore.stopSSE?.()
  await auth.logout()
  router.push({ name: 'agent-login' })
}
</script>

<style scoped>
.agent-shell { min-height: 100%; background: #f5f6f8; display: flex; flex-direction: column; }
.a-header { display: flex; align-items: center; gap: 14px; padding: 10px 18px; background: #2f5460; color: #fff; }
.brand-mark { width: 30px; height: 30px; border-radius: 8px; background: #fff; color: #2f5460; display: flex; align-items: center; justify-content: center; font-weight: 600; }
.a-header nav { display: flex; gap: 4px; flex: 1; }
.a-header nav a { color: #cfdae0; text-decoration: none; padding: 5px 12px; border-radius: 6px; font-size: 14px; }
.a-header nav a.router-link-active { background: #ffffff22; color: #fff; }
.conn { font-size: 12px; color: #cfdae0; }
.conn.ok { color: #9fe0b9; }
.exit { background: transparent; border: 1px solid #ffffff55; color: #fff; border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12px; }
.a-main { flex: 1; }
</style>
