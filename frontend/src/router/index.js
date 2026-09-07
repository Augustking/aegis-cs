import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import CustomerLayout from '../layouts/CustomerLayout.vue'
import AgentLayout from '../layouts/AgentLayout.vue'
import ChatView from '../views/ChatView.vue'
import AgentLoginView from '../views/AgentLoginView.vue'
import AgentInboxView from '../views/AgentInboxView.vue'
import AgentReviewView from '../views/AgentReviewView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: CustomerLayout, children: [
      { path: '', name: 'chat', component: ChatView },
    ]},
    { path: '/agent/login', name: 'agent-login', component: AgentLoginView },
    { path: '/agent', component: AgentLayout, children: [
      { path: '', redirect: '/agent/inbox' },
      { path: 'inbox', name: 'agent-inbox', component: AgentInboxView },
      { path: 'review', name: 'agent-review', component: AgentReviewView },
    ]},
  ],
})

// 坐席路由守卫：真实校验在后端（401 时接口会失败），这里只做体验层跳转
router.beforeEach(async to => {
  if (!to.path.startsWith('/agent') || to.name === 'agent-login') return true
  const auth = useAuthStore()
  const ok = await auth.check()
  return ok ? true : { name: 'agent-login', query: { next: to.fullPath } }
})

export default router
