<script setup>
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useTicketStore } from './stores/tickets'

const store = useTicketStore()
const route = useRoute()
onMounted(() => store.startSSE())
</script>

<template>
  <el-container class="layout">
    <el-header class="header">
      <span class="title">智能客服工作台</span>
      <el-menu mode="horizontal" :default-active="route.path" router class="menu" :ellipsis="false">
        <el-menu-item index="/">客户聊天</el-menu-item>
        <el-menu-item index="/tickets">
          <el-badge :value="store.openCount" :hidden="!store.openCount">工单台</el-badge>
        </el-menu-item>
        <el-menu-item index="/sessions">会话回放</el-menu-item>
      </el-menu>
      <el-tag :type="store.connected ? 'success' : 'info'" size="small">
        {{ store.connected ? '实时已连接' : '实时未连接' }}
      </el-tag>
    </el-header>
    <el-main class="main"><router-view /></el-main>
  </el-container>
</template>

<style>
html, body, #app, .layout { height: 100%; margin: 0; }
.header { display: flex; align-items: center; gap: 16px; border-bottom: 1px solid #eee; }
.title { font-weight: 600; white-space: nowrap; }
.menu { flex: 1; border-bottom: none !important; }
.main { padding: 0; }
</style>
