<template>
  <div class="customer-page">
    <header class="c-header">
      <span class="brand-mark">知</span>
      <div class="brand-text">
        <strong>知序在线客服</strong>
        <small>{{ stateLabel }}</small>
      </div>
      <span class="state-badge" :class="badgeClass">{{ stateLabel }}</span>
    </header>
    <p class="c-notice">设计演示 · 不连接真实服务 · 请勿填写真实个人信息</p>
    <router-view />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useCustomerStore } from '../stores/customer'

const store = useCustomerStore()
const LABELS = { normal: '智能助手为您服务', waiting: '等待人工处理', human: '人工客服已回复' }
const stateLabel = computed(() => LABELS[store.serviceState] || LABELS.normal)
const badgeClass = computed(() => (store.serviceState === 'waiting' ? 'warn' : store.serviceState === 'human' ? 'ok' : ''))
</script>

<style scoped>
.customer-page { min-height: 100%; background: #f5f6f8; display: flex; flex-direction: column; }
.c-header { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: #fff; border-bottom: 1px solid #ebedf0; }
.brand-mark { width: 34px; height: 34px; border-radius: 8px; background: #2f5460; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 600; }
.brand-text { display: flex; flex-direction: column; flex: 1; }
.brand-text small { color: #86909c; }
.state-badge { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: #eef2f5; color: #4e5969; }
.state-badge.warn { background: #fdf2e9; color: #b06a1e; }
.state-badge.ok { background: #e8f5ee; color: #2e7d4f; }
.c-notice { text-align: center; color: #86909c; font-size: 12px; margin: 8px 0 0; }
@media (min-width: 761px) {
  .customer-page { align-items: center; }
  .c-header { width: 640px; margin-top: 24px; border-radius: 12px 12px 0 0; border: 1px solid #ebedf0; }
  .c-notice { width: 640px; }
}
</style>
