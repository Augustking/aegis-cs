import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 180000 })

// ---------- 认证（坐席） ----------
export const login = (username, password) =>
  http.post('/auth/login', { username, password }).then(r => r.data)
export const logout = () => http.post('/auth/logout').then(r => r.data)
export const me = () => http.get('/auth/me').then(r => r.data)

// ---------- 客户 ----------
export const customerChat = (message, sessionId) =>
  http.post('/customer/chat', { message, session_id: sessionId }).then(r => r.data)
export const customerSessions = () =>
  http.get('/customer/sessions').then(r => r.data.sessions)
export const customerSession = (id) =>
  http.get(`/customer/session/${id}`).then(r => r.data)

// ---------- 坐席：会话 ----------
export const listSessions = () => http.get('/sessions').then(r => r.data.sessions)
export const getSession = (id) => http.get(`/sessions/${id}`).then(r => r.data.session)
export const deleteSession = (id) => http.delete(`/sessions/${id}`).then(r => r.data)

// ---------- 坐席：工单 ----------
export const listTickets = (status, q = '', limit = 200, offset = 0) =>
  http.get('/tickets', { params: { status, q, limit, offset } }).then(r => r.data)
export const getTicket = (id) => http.get(`/tickets/${id}`).then(r => r.data.ticket)
export const resolveTicket = (id, human_reply) =>
  http.post(`/tickets/${id}/resolve`, { human_reply }).then(r => r.data)
