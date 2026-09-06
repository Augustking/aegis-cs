import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'

export const useTicketStore = defineStore('tickets', {
  state: () => ({ openCount: 0, connected: false, _es: null }),
  actions: {
    startSSE(onUpdate) {
      if (this._es) return
      const es = new EventSource('/api/tickets/stream')
      this._es = es
      es.onopen = () => { this.connected = true }
      es.onerror = () => { this.connected = false } // 浏览器自动重连
      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data)
          if (ev.type === 'init') this.openCount = ev.open_count
          if (ev.type === 'update') {
            this.openCount = ev.open_count
            if (ev.new_ids && ev.new_ids.length && onUpdate) {
              ElNotification({
                title: '新工单',
                message: `有 ${ev.new_ids.length} 个工单待处理`,
                type: 'warning',
              })
              onUpdate()
            }
          }
        } catch { /* 忽略解析失败 */ }
      }
    },
  },
})
