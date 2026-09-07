import { defineStore } from 'pinia'

// 客户服务状态与工单状态分离（3.1 设计 §5）
export const useCustomerStore = defineStore('customer', {
  state: () => ({
    serviceState: 'normal', // normal | waiting | human
    currentThreadId: '',
    sessions: [],
  }),
  actions: {
    setState(s) {
      if (['normal', 'waiting', 'human'].includes(s)) this.serviceState = s
    },
  },
})
