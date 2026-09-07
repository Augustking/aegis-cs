import { defineStore } from 'pinia'
import { me, login as apiLogin, logout as apiLogout } from '../api'

export const useAuthStore = defineStore('auth', {
  state: () => ({ username: '', role: '', checked: false, checking: false }),
  getters: {
    loggedIn: s => !!s.username,
  },
  actions: {
    async check() {
      if (this.checking) return this.loggedIn
      this.checking = true
      try {
        const u = await me()
        this.username = u.username
        this.role = u.role
      } catch {
        this.username = ''
        this.role = ''
      } finally {
        this.checked = true
        this.checking = false
      }
      return this.loggedIn
    },
    async login(username, password) {
      const u = await apiLogin(username, password)
      this.username = u.username
      this.role = u.role
      this.checked = true
    },
    async logout() {
      try { await apiLogout() } catch { /* 忽略 */ }
      this.username = ''
      this.role = ''
    },
  },
})
