import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'
import TicketsView from '../views/TicketsView.vue'
import SessionsView from '../views/SessionsView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: ChatView },
    { path: '/tickets', component: TicketsView },
    { path: '/sessions', component: SessionsView },
  ],
})
